#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UNIT = "zel-q4r3-telegram-pos-adapter-v2.service"
ENV_FILE = Path("/etc/zel/telegram-pos-adapter.env")
DROPIN = Path("/etc/systemd/system/zel-q4r3-telegram-pos-adapter-v2.service.d/20-canonical-environment.conf")
REQUIRED_KEYS = ("ZEL_TELEGRAM_BOT_TOKEN", "ZEL_TELEGRAM_ALLOWED_CHAT_ID")
TOKEN_KEYS = ("ZEL_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
CHAT_KEYS = ("ZEL_TELEGRAM_ALLOWED_CHAT_ID", "TELEGRAM_ALLOWED_CHAT_ID", "TELEGRAM_CHAT_ID")
TOKEN_RE = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")
CHAT_ASSIGN_RE = re.compile(
    r"(?im)^\s*(?:export\s+)?(?:ZEL_TELEGRAM_ALLOWED_CHAT_ID|TELEGRAM_ALLOWED_CHAT_ID|TELEGRAM_CHAT_ID)\s*=\s*[\"']?(-?\d{4,20})"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes()) if path.is_file() else None
    except Exception:
        return None


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o644)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def protected_snapshot(root: Path) -> dict[str, str | None]:
    paths = {
        "formal_ledger": root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
        "shadow_snapshot": root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json",
        "view_contract": Path("/var/www/z-os-alimi/api/view_contract_latest.json"),
        "deployed_source": Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py"),
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("Environment="):
            line = line.split("=", 1)[1].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().strip('"').strip("'")
        value = value.strip().strip('"').strip("'")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


def read_process_environment(unit: str) -> dict[str, str]:
    proc = run(["systemctl", "show", unit, "-p", "MainPID", "--value"])
    try:
        pid = int(proc.stdout.strip())
    except Exception:
        return {}
    if pid <= 0:
        return {}
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except Exception:
        return {}
    result: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        result[key.decode("utf-8", errors="ignore")] = value.decode("utf-8", errors="ignore")
    return result


def systemd_environment(unit: str) -> tuple[dict[str, str], list[str]]:
    values = read_process_environment(unit)
    cat = run(["systemctl", "cat", unit])
    text = cat.stdout if cat.returncode == 0 else ""
    values.update(parse_env_text(text))
    files: list[str] = []
    for raw in re.findall(r"(?m)^\s*EnvironmentFile\s*=\s*([^\n]+)$", text):
        candidate = raw.strip().strip('"').strip("'")
        if candidate.startswith("-"):
            candidate = candidate[1:]
        files.append(candidate)
        path = Path(candidate)
        try:
            if path.is_file():
                values.update(parse_env_text(path.read_text(encoding="utf-8", errors="replace")))
        except Exception:
            continue
    return values, sorted(set(files))


def candidate_files(root: Path) -> list[Path]:
    roots = [Path("/etc/zel"), Path("/etc/systemd/system"), Path("/var/www/z-os-alimi"), root, Path("/usr/local/bin")]
    excluded = ("/.git/", "/backup/", "/backups/", "/rollback/", "/graveyard/", "/archive/", "/node_modules/", "/__pycache__/")
    files: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        try:
            iterator = base.rglob("*") if base.is_dir() else [base]
            for path in iterator:
                try:
                    marker = "/" + str(path).strip("/") + "/"
                    if any(part in marker.lower() for part in excluded):
                        continue
                    if not path.is_file() or path.stat().st_size > 2_000_000:
                        continue
                    files.append(path)
                except Exception:
                    continue
        except Exception:
            continue
    unique: dict[str, Path] = {str(path): path for path in files}
    return list(unique.values())


def discover_candidates(root: Path) -> tuple[dict[str, str], dict[str, str], list[str]]:
    token_candidates: dict[str, str] = {}
    chat_candidates: dict[str, str] = {}
    env_values, env_files = systemd_environment(UNIT)
    for key in TOKEN_KEYS:
        value = env_values.get(key, "").strip()
        if TOKEN_RE.fullmatch(value):
            token_candidates[value] = "systemd_or_process_environment"
    for key in CHAT_KEYS:
        value = env_values.get(key, "").strip()
        if re.fullmatch(r"-?\d{4,20}", value):
            chat_candidates[value] = "systemd_or_process_environment"

    for path in candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for match in TOKEN_RE.finditer(text):
            token_candidates.setdefault(match.group(0), "existing_local_source")
        for match in CHAT_ASSIGN_RE.finditer(text):
            chat_candidates.setdefault(match.group(1), "existing_named_assignment")
    return token_candidates, chat_candidates, env_files


def telegram_call(token: str, method: str, params: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"User-Agent": "ZEL-R7A1A4C/1.0"})
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read().decode("utf-8", errors="ignore")
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"ok": False, "error": "NON_OBJECT_RESPONSE"}
    except Exception as exc:
        safe = str(exc).replace(token, "<redacted>")[:240]
        return {"ok": False, "error": safe}


def current_offset() -> int:
    state = load_json(Path("/var/www/z-os-alimi/api/q4r3_telegram_pos_adapter_v2_state.json"))
    try:
        return max(0, int(state.get("offset", 0) or 0))
    except Exception:
        return 0


def capture_private_chat_id(token: str, timeout_seconds: int = 120) -> tuple[str | None, int, str | None]:
    deadline = time.monotonic() + timeout_seconds
    offset = current_offset()
    seen = 0
    print(f"ACTION_REQUIRED=SEND_/bind_TO_ZEL_BOT_WITHIN_{timeout_seconds}_SECONDS")
    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        payload = telegram_call(
            token,
            "getUpdates",
            {
                "timeout": str(min(20, remaining)),
                "offset": str(offset),
                "allowed_updates": json.dumps(["message"]),
            },
            timeout=min(25, remaining + 5),
        )
        if not payload.get("ok"):
            return None, seen, str(payload.get("error") or "GETUPDATES_FAILED")
        for update in payload.get("result", []):
            if not isinstance(update, dict):
                continue
            try:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
            except Exception:
                pass
            seen += 1
            message = update.get("message") or {}
            text = str(message.get("text") or "").strip()
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            chat_type = str(chat.get("type") or "")
            if not (text == "/bind" or text.startswith("/bind@")):
                continue
            if chat_type != "private":
                continue
            chat_id = str(chat.get("id") or "")
            sender_id = str(sender.get("id") or "")
            if not re.fullmatch(r"-?\d{4,20}", chat_id):
                continue
            if sender_id and sender_id != chat_id:
                continue
            telegram_call(token, "getUpdates", {"timeout": "0", "offset": str(offset)}, timeout=10)
            return chat_id, seen, None
    return None, seen, "BIND_TIMEOUT"


def backup_path(source: Path, rollback_dir: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": str(source), "existed": source.exists(), "backup": None}
    if source.exists():
        rollback_dir.mkdir(parents=True, exist_ok=True)
        destination = rollback_dir / (source.name + ".bak")
        shutil.copy2(source, destination)
        os.chmod(destination, 0o600)
        entry["backup"] = str(destination)
    return entry


def restore_entry(entry: dict[str, Any]) -> None:
    path = Path(str(entry["path"]))
    backup = entry.get("backup")
    if entry.get("existed") and backup:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(str(backup)), path)
    elif not entry.get("existed"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def write_secret_environment(path: Path, token: str, chat_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("ZEL_TELEGRAM_BOT_TOKEN=" + token + "\n")
            handle.write("ZEL_TELEGRAM_ALLOWED_CHAT_ID=" + chat_id + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.chown(temp_name, 0, 0)
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
        os.chown(path, 0, 0)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def write_dropin(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "[Service]\nEnvironmentFile=-/etc/zel/telegram-pos-adapter.env\n"
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o644)
        os.chown(temp_name, 0, 0)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def unit_is_active() -> bool:
    proc = run(["systemctl", "is-active", UNIT])
    return proc.returncode == 0 and proc.stdout.strip() == "active"


def bound_process_key_count() -> int:
    env = read_process_environment(UNIT)
    return sum(1 for key in REQUIRED_KEYS if env.get(key))


def environment_file_metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        metadata = path.stat()
        mode = stat.S_IMODE(metadata.st_mode)
        owner = f"{metadata.st_uid}:{metadata.st_gid}"
        return f"{mode:04o}", owner
    except Exception:
        return None, None


def rollback(entries: list[dict[str, Any]], initially_active: bool) -> list[str]:
    errors: list[str] = []
    for entry in reversed(entries):
        try:
            restore_entry(entry)
        except Exception as exc:
            errors.append(type(exc).__name__)
    reload_proc = run(["systemctl", "daemon-reload"])
    if reload_proc.returncode != 0:
        errors.append("DAEMON_RELOAD")
    action = "restart" if initially_active else "stop"
    proc = run(["systemctl", action, UNIT], timeout=45)
    if proc.returncode != 0:
        errors.append("SERVICE_RESTORE")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--bind-timeout", type=int, default=120)
    args = parser.parse_args()

    root = Path(args.root)
    out_dir = root / "runtime/exact25_edge_v1/r7a1a4c_environment_binding_canary"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    rollback_dir = out_dir / "rollback"
    blockers: list[str] = []
    rollback_errors: list[str] = []
    rollback_performed = False
    service_restart_count = 0
    api_probe = False
    canary_message_sent = False
    bind_updates_seen = 0
    token_source_class: str | None = None
    chat_source_class: str | None = None
    initial_active = unit_is_active()
    before = protected_snapshot(root)
    backups: list[dict[str, Any]] = []

    preflight = load_json(root / "runtime/exact25_edge_v1/r7a1a4b2_telegram_src_provenance_fix/status_latest.json")
    if os.geteuid() != 0:
        blockers.append("ROOT_REQUIRED")
    if preflight.get("state") != "PASS":
        blockers.append("R7A1A4B2_NOT_PASS")
    if not initial_active:
        blockers.append("TARGET_UNIT_NOT_ACTIVE")

    token_candidates: dict[str, str] = {}
    chat_candidates: dict[str, str] = {}
    environment_files: list[str] = []
    if not blockers:
        token_candidates, chat_candidates, environment_files = discover_candidates(root)
        if len(token_candidates) != 1:
            blockers.append(f"TOKEN_CANDIDATE_COUNT_{len(token_candidates)}")

    token = next(iter(token_candidates), "") if len(token_candidates) == 1 else ""
    if token:
        token_source_class = token_candidates[token]
        probe = telegram_call(token, "getMe", timeout=15)
        api_probe = bool(probe.get("ok"))
        if not api_probe:
            blockers.append("TELEGRAM_API_PROBE_FAILED")

    if not blockers:
        backups = [backup_path(ENV_FILE, rollback_dir), backup_path(DROPIN, rollback_dir)]
        if len(chat_candidates) == 0:
            stop_proc = run(["systemctl", "stop", UNIT], timeout=45)
            if stop_proc.returncode != 0:
                blockers.append("TARGET_UNIT_STOP_FAILED")
            else:
                chat_id, bind_updates_seen, capture_error = capture_private_chat_id(token, max(30, args.bind_timeout))
                if chat_id:
                    chat_candidates[chat_id] = "interactive_private_bind"
                else:
                    blockers.append("CHAT_ID_CAPTURE_" + str(capture_error or "FAILED"))
        if len(chat_candidates) != 1:
            blockers.append(f"CHAT_ID_CANDIDATE_COUNT_{len(chat_candidates)}")

    chat_id = next(iter(chat_candidates), "") if len(chat_candidates) == 1 else ""
    if chat_id:
        chat_source_class = chat_candidates[chat_id]

    try:
        if not blockers:
            write_secret_environment(ENV_FILE, token, chat_id)
            write_dropin(DROPIN)
            if run(["systemctl", "daemon-reload"]).returncode != 0:
                blockers.append("DAEMON_RELOAD_FAILED")
            if not blockers:
                action = "restart" if initial_active else "start"
                restart_proc = run(["systemctl", action, UNIT], timeout=45)
                service_restart_count += 1
                if restart_proc.returncode != 0:
                    blockers.append("TARGET_UNIT_RESTART_FAILED")
            if not blockers:
                time.sleep(3)
                if not unit_is_active():
                    blockers.append("TARGET_UNIT_NOT_ACTIVE_AFTER_RESTART")
            process_key_count = bound_process_key_count() if not blockers else 0
            if not blockers and process_key_count != 2:
                blockers.append(f"PROCESS_ENVIRONMENT_KEY_COUNT_{process_key_count}")
            mode, owner = environment_file_metadata(ENV_FILE)
            if not blockers and mode != "0600":
                blockers.append(f"ENVIRONMENT_FILE_MODE_{mode}")
            if not blockers and owner != "0:0":
                blockers.append(f"ENVIRONMENT_FILE_OWNER_{owner}")
            if not blockers:
                sent = telegram_call(
                    token,
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": "R7.A1A4C PASS · environment binding active · order=blocked · exec=none",
                        "disable_web_page_preview": "true",
                    },
                    timeout=15,
                )
                canary_message_sent = bool(sent.get("ok"))
                if not canary_message_sent:
                    blockers.append("TELEGRAM_CANARY_MESSAGE_FAILED")
    except Exception as exc:
        blockers.append("CANARY_EXCEPTION_" + type(exc).__name__)

    after = protected_snapshot(root)
    protected_changes = [name for name in before if before.get(name) != after.get(name)]
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_" + ",".join(protected_changes))

    if blockers and backups:
        rollback_performed = True
        rollback_errors = rollback(backups, initial_active)
        if rollback_errors:
            blockers.append("ROLLBACK_ERRORS_" + ",".join(rollback_errors))

    mode, owner = environment_file_metadata(ENV_FILE)
    process_key_count = bound_process_key_count() if unit_is_active() else 0
    state = "PASS" if not blockers else "HOLD"
    next_stage = "R7.A1A5_SYSTEMD_SOURCE_CUTOVER_CANARY" if state == "PASS" else "R7.A1A4C_DIAGNOSE"

    payload: dict[str, Any] = {
        "schema": "r7a1a4c_environment_binding_canary_status_v1",
        "official_stage": "R7.A1A4C",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "token_candidate_count": len(token_candidates),
        "chat_id_candidate_count": len(chat_candidates),
        "token_source_class": token_source_class,
        "chat_id_source_class": chat_source_class,
        "environment_files_seen_count": len(environment_files),
        "value_exposure_count": 0,
        "api_probe": api_probe,
        "bind_updates_seen": bind_updates_seen,
        "canary_message_sent": canary_message_sent,
        "environment_file": {"path": str(ENV_FILE), "mode": mode, "owner": owner},
        "dropin": {"path": str(DROPIN), "exists": DROPIN.is_file()},
        "target_unit_active": unit_is_active(),
        "target_process_environment_key_count": process_key_count,
        "service_restart_count": service_restart_count,
        "rollback_performed": rollback_performed,
        "rollback_error_count": len(rollback_errors),
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A4C Environment Binding Canary",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- token candidates: `{len(token_candidates)}`",
            f"- chat-id candidates: `{len(chat_candidates)}`",
            f"- token source class: `{token_source_class}`",
            f"- chat-id source class: `{chat_source_class}`",
            f"- environment file mode/owner: `{mode}` / `{owner}`",
            f"- target process bound keys: `{process_key_count}`",
            f"- Telegram API probe: `{api_probe}`",
            f"- canary message sent: `{canary_message_sent}`",
            f"- rollback performed: `{rollback_performed}`",
            f"- protected changes: `{protected_changes}`",
            f"- next: `{next_stage}`",
            "",
            "No credential value is recorded or printed.",
        ]) + "\n",
        encoding="utf-8",
    )

    print("R7A1A4C_ENVIRONMENT_BINDING_CANARY_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"TOKEN_CANDIDATE_COUNT={len(token_candidates)}")
    print(f"CHAT_ID_CANDIDATE_COUNT={len(chat_candidates)}")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"TELEGRAM_API_PROBE={str(api_probe).lower()}")
    print(f"ENVIRONMENT_FILE_MODE={mode}")
    print(f"ENVIRONMENT_FILE_OWNER={owner}")
    print(f"TARGET_PROCESS_ENVIRONMENT_KEY_COUNT={process_key_count}")
    print(f"TARGET_UNIT_ACTIVE={str(unit_is_active()).lower()}")
    print(f"CANARY_MESSAGE_SENT={str(canary_message_sent).lower()}")
    print(f"SERVICE_RESTART_COUNT={service_restart_count}")
    print(f"ROLLBACK_PERFORMED={str(rollback_performed).lower()}")
    print(f"PROTECTED_CHANGE_COUNT={len(protected_changes)}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
