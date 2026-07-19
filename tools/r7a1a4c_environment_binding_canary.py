#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import importlib.util
import io
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
CANONICAL_PATH = "services/telegram/zel_q4r3_telegram_pos_adapter_v2.py"
DEPLOYED_SOURCE = Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py")
ENV_FILE = Path("/etc/zel/telegram-pos-adapter.env")
DROPIN = Path("/etc/systemd/system/zel-q4r3-telegram-pos-adapter-v2.service.d/20-canonical-environment.conf")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes()) if path.is_file() else None
    except Exception:
        return None


def run(cmd: list[str], timeout: int = 45) -> subprocess.CompletedProcess[str]:
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
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
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
        "deployed_source": DEPLOYED_SOURCE,
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def git_bytes(root: Path, ref: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def assignment_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        result: list[str] = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                result.append(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                result.extend(item.id for item in target.elts if isinstance(item, ast.Name))
        return result
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def assignment_value(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Assign):
        return node.value
    if isinstance(node, ast.AnnAssign):
        return node.value
    return None


def env_key_from_call(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    key = node.args[0]
    if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        return key.value
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
        and func.value.attr == "environ"
    ):
        return key.value
    return None


def direct_environment_keys(canonical: bytes | None) -> dict[str, str]:
    if canonical is None:
        return {}
    tree = ast.parse(canonical.decode("utf-8"))
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        value = assignment_value(node)
        if value is None:
            continue
        key = env_key_from_call(value)
        if key is None:
            continue
        for target in assignment_targets(node):
            if target in {"token", "chat_id"}:
                result[target] = key
    return result


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


def load_token_from_deployed() -> str:
    spec = importlib.util.spec_from_file_location("r7a1a4c_deployed_probe", DEPLOYED_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("DEPLOYED_MODULE_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(module)
        finder = getattr(module, "find_token", None)
        if not callable(finder):
            raise RuntimeError("DEPLOYED_TOKEN_RESOLVER_MISSING")
        resolved = finder()
    token = resolved[0] if isinstance(resolved, tuple) else resolved
    token = token.strip() if isinstance(token, str) else ""
    if not re.fullmatch(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}", token):
        raise RuntimeError("TOKEN_RESOLUTION_INVALID")
    return token


def telegram_call(token: str, method: str, params: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=urllib.parse.urlencode(params or {}).encode("utf-8"),
        headers={"User-Agent": "ZEL-R7A1A4C/1.1"},
    )
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read().decode("utf-8", errors="ignore")
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"ok": False, "error": "NON_OBJECT_RESPONSE"}
    except Exception as exc:
        return {"ok": False, "error": str(exc).replace(token, "<redacted>")[:240]}


def extract_bind_chat_id(payload: dict[str, Any]) -> tuple[str | None, int | None, int]:
    selected: str | None = None
    next_offset: int | None = None
    seen = 0
    result = payload.get("result") if isinstance(payload.get("result"), list) else []
    for update in result:
        if not isinstance(update, dict):
            continue
        seen += 1
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = max(next_offset or update_id + 1, update_id + 1)
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "").strip()
        command = text.split(maxsplit=1)[0].split("@", 1)[0] if text else ""
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat_id = str(chat.get("id") or "")
        sender_id = str(sender.get("id") or "")
        if command == "/bind" and chat.get("type") == "private" and re.fullmatch(r"-?[0-9]{4,20}", chat_id):
            if not sender_id or sender_id == chat_id:
                selected = chat_id
    return selected, next_offset, seen


def capture_private_chat_id(token: str, timeout_seconds: int) -> tuple[str | None, int, str | None]:
    deadline = time.monotonic() + timeout_seconds
    offset: int | None = None
    seen = 0
    print(f"ACTION_REQUIRED=SEND_/bind_TO_ZEL_BOT_WITHIN_{timeout_seconds}_SECONDS")
    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        params = {"timeout": str(min(12, remaining)), "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            params["offset"] = str(offset)
        payload = telegram_call(token, "getUpdates", params, timeout=min(18, remaining + 5))
        if not payload.get("ok"):
            return None, seen, str(payload.get("error") or "GETUPDATES_FAILED")
        selected, next_offset, row_count = extract_bind_chat_id(payload)
        seen += row_count
        if next_offset is not None:
            offset = next_offset
        if selected:
            if offset is not None:
                telegram_call(token, "getUpdates", {"timeout": "0", "offset": str(offset)}, timeout=10)
            return selected, seen, None
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
        path.unlink(missing_ok=True)


def write_environment(path: Path, token_key: str, token: str, chat_key: str, chat_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{token_key}={token}\n{chat_key}={chat_id}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.chown(temp_name, 0, 0)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def write_dropin(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"[Service]\nEnvironmentFile=-{ENV_FILE}\n")
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


def process_environment() -> dict[str, str]:
    proc = run(["systemctl", "show", UNIT, "-p", "MainPID", "--value"])
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


def environment_file_metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        metadata = path.stat()
        return f"{stat.S_IMODE(metadata.st_mode):04o}", f"{metadata.st_uid}:{metadata.st_gid}"
    except Exception:
        return None, None


def rollback(entries: list[dict[str, Any]], initially_active: bool) -> list[str]:
    errors: list[str] = []
    for entry in reversed(entries):
        try:
            restore_entry(entry)
        except Exception as exc:
            errors.append(type(exc).__name__)
    if run(["systemctl", "daemon-reload"]).returncode != 0:
        errors.append("DAEMON_RELOAD")
    action = "restart" if initially_active else "stop"
    if run(["systemctl", action, UNIT], timeout=45).returncode != 0:
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
    mutation_count = 0
    bind_updates_seen = 0
    canary_message_sent = False
    api_probe = False
    initial_active = unit_is_active()
    before = protected_snapshot(root)
    backups: list[dict[str, Any]] = []

    canonical = git_bytes(root, args.sha, CANONICAL_PATH)
    direct_keys = direct_environment_keys(canonical)
    token_key = direct_keys.get("token")
    chat_key = direct_keys.get("chat_id")
    token = ""
    chat_id = ""
    token_source_class: str | None = None
    chat_source_class: str | None = None

    preflight = load_json(root / "runtime/exact25_edge_v1/r7a1a4b2_telegram_src_provenance_fix/status_latest.json")
    if os.geteuid() != 0:
        blockers.append("ROOT_REQUIRED")
    if preflight.get("state") != "PASS":
        blockers.append("R7A1A4B2_NOT_PASS")
    if not initial_active:
        blockers.append("TARGET_UNIT_NOT_ACTIVE")
    if set(direct_keys) != {"token", "chat_id"} or len(set(direct_keys.values())) != 2:
        blockers.append("CANONICAL_DIRECT_KEY_MAP_INVALID")

    try:
        if not blockers:
            token = load_token_from_deployed()
            token_source_class = "deployed_find_token_resolver"
            probe = telegram_call(token, "getMe", timeout=15)
            api_probe = bool(probe.get("ok"))
            if not api_probe:
                blockers.append("TELEGRAM_API_PROBE_FAILED")

        existing = parse_env_text(ENV_FILE.read_text(encoding="utf-8", errors="replace")) if ENV_FILE.is_file() else {}
        if not blockers and chat_key and re.fullmatch(r"-?[0-9]{4,20}", existing.get(chat_key, "")):
            chat_id = existing[chat_key]
            chat_source_class = "existing_canonical_environment"

        if not blockers:
            backups = [backup_path(ENV_FILE, rollback_dir), backup_path(DROPIN, rollback_dir)]
            if not chat_id:
                stop_proc = run(["systemctl", "stop", UNIT], timeout=45)
                if stop_proc.returncode != 0:
                    blockers.append("TARGET_UNIT_STOP_FAILED")
                else:
                    mutation_count += 1
                    captured, bind_updates_seen, capture_error = capture_private_chat_id(token, max(30, args.bind_timeout))
                    if captured:
                        chat_id = captured
                        chat_source_class = "interactive_private_bind"
                    else:
                        blockers.append("CHAT_ID_CAPTURE_" + str(capture_error or "FAILED"))

        if not blockers and token_key and chat_key:
            write_environment(ENV_FILE, token_key, token, chat_key, chat_id)
            mutation_count += 1
            write_dropin(DROPIN)
            mutation_count += 1
            if run(["systemctl", "daemon-reload"]).returncode != 0:
                blockers.append("DAEMON_RELOAD_FAILED")
            else:
                mutation_count += 1
            if not blockers:
                restart_proc = run(["systemctl", "restart", UNIT], timeout=45)
                mutation_count += 1
                if restart_proc.returncode != 0:
                    blockers.append("TARGET_UNIT_RESTART_FAILED")
            if not blockers:
                time.sleep(3)
                if not unit_is_active():
                    blockers.append("TARGET_UNIT_NOT_ACTIVE_AFTER_RESTART")
            if not blockers:
                process_env = process_environment()
                if process_env.get(token_key) != token or process_env.get(chat_key) != chat_id:
                    blockers.append("PROCESS_ENVIRONMENT_PARITY_FAILED")
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

    token = ""
    chat_id = ""
    mode, owner = environment_file_metadata(ENV_FILE)
    final_env = process_environment() if unit_is_active() else {}
    process_key_count = sum(1 for key in direct_keys.values() if final_env.get(key))
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
        "mutation_count": mutation_count,
        "token_candidate_count": 1 if token_source_class else 0,
        "chat_id_candidate_count": 1 if chat_source_class else 0,
        "token_source_class": token_source_class,
        "chat_id_source_class": chat_source_class,
        "value_exposure_count": 0,
        "api_probe": api_probe,
        "bind_updates_seen": bind_updates_seen,
        "canary_message_sent": canary_message_sent,
        "environment_file": {"path": str(ENV_FILE), "mode": mode, "owner": owner},
        "dropin": {"path": str(DROPIN), "exists": DROPIN.is_file()},
        "target_unit_active": unit_is_active(),
        "target_process_environment_key_count": process_key_count,
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
            "No credential value or chat identifier is recorded or printed.",
        ]) + "\n",
        encoding="utf-8",
    )
    os.chmod(report_path, 0o600)

    print("R7A1A4C_ENVIRONMENT_BINDING_CANARY_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"MUTATION_COUNT={mutation_count}")
    print(f"TOKEN_CANDIDATE_COUNT={1 if token_source_class else 0}")
    print(f"CHAT_ID_CANDIDATE_COUNT={1 if chat_source_class else 0}")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"TELEGRAM_API_PROBE={str(api_probe).lower()}")
    print(f"ENVIRONMENT_FILE_MODE={mode}")
    print(f"ENVIRONMENT_FILE_OWNER={owner}")
    print(f"TARGET_PROCESS_ENVIRONMENT_KEY_COUNT={process_key_count}")
    print(f"TARGET_UNIT_ACTIVE={str(unit_is_active()).lower()}")
    print(f"CANARY_MESSAGE_SENT={str(canary_message_sent).lower()}")
    print(f"ROLLBACK_PERFORMED={str(rollback_performed).lower()}")
    print(f"PROTECTED_CHANGE_COUNT={len(protected_changes)}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
