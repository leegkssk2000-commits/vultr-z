#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UNIT = "zel-q4r3-telegram-pos-adapter-v2.service"
CANONICAL_PATH = "services/telegram/zel_q4r3_telegram_pos_adapter_v2.py"
LEGACY_SOURCE = Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py")
ENV_FILE = Path("/etc/zel/telegram-pos-adapter.env")
ENV_DROPIN = Path("/etc/systemd/system/zel-q4r3-telegram-pos-adapter-v2.service.d/20-canonical-environment.conf")
SOURCE_DROPIN = Path("/etc/systemd/system/zel-q4r3-telegram-pos-adapter-v2.service.d/30-canonical-source.conf")
REPORT = Path("/var/www/z-os-alimi/api/q4r3_telegram_pos_adapter_v2_latest.json")
TOKEN_LITERAL = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
REQUIRED_COMMANDS = ("/pos", "/pnl", "/view")
REQUIRED_ENV_KEYS = ("ZEL_TELEGRAM_BOT_TOKEN", "ZEL_TELEGRAM_ALLOWED_CHAT_ID")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes()) if path.is_file() else None
    except Exception:
        return None


def git_bytes(root: Path, ref: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value.strip()
    return values


def file_mode_owner(path: Path) -> tuple[str | None, str | None]:
    try:
        meta = path.stat()
        return f"{stat.S_IMODE(meta.st_mode):04o}", f"{meta.st_uid}:{meta.st_gid}"
    except Exception:
        return None, None


def unit_active() -> bool:
    proc = run(["systemctl", "is-active", UNIT], timeout=15)
    return proc.returncode == 0 and proc.stdout.strip() == "active"


def main_pid() -> int:
    proc = run(["systemctl", "show", UNIT, "-p", "MainPID", "--value"], timeout=15)
    try:
        return int(proc.stdout.strip())
    except Exception:
        return 0


def process_cmdline() -> list[str]:
    pid = main_pid()
    if pid <= 0:
        return []
    try:
        return [item.decode("utf-8", errors="replace") for item in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if item]
    except Exception:
        return []


def process_environment() -> dict[str, str]:
    pid = main_pid()
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


def canonical_analysis(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {"compile_ok": False, "secret_literal_count": 0, "command_counts": {}, "environment_keys": []}
    text = data.decode("utf-8", errors="replace")
    try:
        compile(text, CANONICAL_PATH, "exec")
        compile_ok = True
    except Exception:
        compile_ok = False
    keys: set[str] = set()
    try:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
                keys.add(first.value)
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
                and func.value.attr == "environ"
            ):
                keys.add(first.value)
    except Exception:
        pass
    return {
        "compile_ok": compile_ok,
        "secret_literal_count": len(TOKEN_LITERAL.findall(text)),
        "command_counts": {command: text.count(command) for command in REQUIRED_COMMANDS},
        "environment_keys": sorted(keys),
    }


def replace_source_arg(argv: list[str], old_source: Path, new_source: Path) -> list[str]:
    indexes = [index for index, value in enumerate(argv) if value == str(old_source)]
    if len(indexes) != 1:
        raise ValueError(f"LEGACY_EXEC_SOURCE_COUNT_{len(indexes)}")
    result = list(argv)
    result[indexes[0]] = str(new_source)
    return result


def systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def source_dropin_text(argv: list[str]) -> str:
    if not argv or any("\x00" in value or "\n" in value for value in argv):
        raise ValueError("UNSAFE_EXEC_ARGV")
    return "[Service]\nExecStart=\nExecStart=" + " ".join(systemd_quote(value) for value in argv) + "\n"


def install_release(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent.parent, 0o755)
    os.chmod(path.parent, 0o755)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o755)
        os.chown(temp_name, 0, 0)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def write_text_root(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.chown(temp_name, 0, 0)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def backup_path(path: Path, rollback_dir: Path, name: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": str(path), "existed": path.exists(), "backup": None}
    if path.exists():
        rollback_dir.mkdir(parents=True, exist_ok=True)
        backup = rollback_dir / name
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
        entry["backup"] = str(backup)
    return entry


def restore_entry(entry: dict[str, Any]) -> None:
    path = Path(str(entry["path"]))
    backup = entry.get("backup")
    if entry.get("existed") and backup:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(str(backup)), path)
    elif not entry.get("existed"):
        path.unlink(missing_ok=True)


def stable_snapshot(root: Path) -> dict[str, str | None]:
    paths = {
        "formal_ledger": root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
        "shadow_snapshot": root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json",
        "legacy_source": LEGACY_SOURCE,
        "environment_file": ENV_FILE,
        "environment_dropin": ENV_DROPIN,
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def report_semantics(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if payload.get("status") != "PASS_TELEGRAM_POS_ADAPTER_V2_RUNNING":
        blockers.append("RUNTIME_REPORT_NOT_PASS")
    if payload.get("order_authority") != "blocked":
        blockers.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if payload.get("execution_authority") != "none":
        blockers.append("EXECUTION_AUTHORITY_NOT_NONE")
    if payload.get("real_order_enabled") is not False:
        blockers.append("REAL_ORDER_ENABLED_NOT_FALSE")
    return not blockers, blockers


def wait_for_visible_pos_reply(baseline_mtime_ns: int, timeout_seconds: int) -> tuple[bool, dict[str, Any], str | None]:
    print(f"ACTION_REQUIRED=SEND_/pos_TO_ZEL_BOT_WITHIN_{timeout_seconds}_SECONDS")
    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if not unit_active():
            return False, latest, "TARGET_UNIT_STOPPED_DURING_SMOKE"
        try:
            changed = REPORT.is_file() and REPORT.stat().st_mtime_ns > baseline_mtime_ns
        except Exception:
            changed = False
        if changed:
            latest = load_json(REPORT)
            if str(latest.get("status") or "").startswith("HOLD_"):
                return False, latest, "RUNTIME_REPORT_HOLD"
            ok, semantic_blockers = report_semantics(latest)
            if not ok:
                return False, latest, semantic_blockers[0]
            try:
                sent_count = int(latest.get("sent_count", 0) or 0)
            except Exception:
                sent_count = 0
            if sent_count >= 1:
                return True, latest, None
        time.sleep(0.25)
    return False, latest, "VISIBLE_POS_REPLY_TIMEOUT"


def rollback(entries: list[dict[str, Any]], initially_active: bool) -> list[str]:
    errors: list[str] = []
    for entry in reversed(entries):
        try:
            restore_entry(entry)
        except Exception as exc:
            errors.append("RESTORE_" + type(exc).__name__)
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
    parser.add_argument("--contract", required=True)
    parser.add_argument("--smoke-timeout", type=int, default=120)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = root / "runtime/exact25_edge_v1/r7a1a5_systemd_source_cutover_canary"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    rollback_dir = out_dir / "rollback"
    blockers: list[str] = []
    rollback_errors: list[str] = []
    rollback_performed = False
    mutation_count = 0
    service_restart_count = 0
    visible_reply = False
    runtime_report: dict[str, Any] = {}
    backups: list[dict[str, Any]] = []
    initial_active = unit_active()
    initial_argv = process_cmdline()
    before = stable_snapshot(root)
    release_path = Path(f"/opt/zel/releases/{args.sha}/telegram/zel_q4r3_telegram_pos_adapter_v2.py")
    canonical = git_bytes(root, args.sha, CANONICAL_PATH)
    analysis = canonical_analysis(canonical)
    env_values = parse_env_file(ENV_FILE)
    env_mode, env_owner = file_mode_owner(ENV_FILE)
    source_dropin_bound = False
    process_release_bound = False
    process_env_key_count = 0
    release_sha_matches = False
    legacy_exec_source_count = initial_argv.count(str(LEGACY_SOURCE))

    parent = load_json(root / "runtime/exact25_edge_v1/r7a1a4c_environment_binding_canary/status_latest.json")
    try:
        contract = load_json(Path(args.contract))
    except Exception:
        contract = {}

    if os.geteuid() != 0:
        blockers.append("ROOT_REQUIRED")
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        blockers.append("TARGET_SHA_INVALID")
    if contract.get("official_stage") != "R7.A1A5":
        blockers.append("CONTRACT_INVALID")
    if parent.get("state") != "PASS" or parent.get("scope_patch_stage") != "R7.A1A4C3":
        blockers.append("R7A1A4C3_NOT_PASS")
    if not initial_active:
        blockers.append("TARGET_UNIT_NOT_ACTIVE")
    if legacy_exec_source_count != 1:
        blockers.append(f"LEGACY_EXEC_SOURCE_COUNT_{legacy_exec_source_count}")
    if canonical is None:
        blockers.append("CANONICAL_SOURCE_MISSING")
    if analysis.get("compile_ok") is not True:
        blockers.append("CANONICAL_COMPILE_FAILED")
    if analysis.get("secret_literal_count") != 0:
        blockers.append(f"CANONICAL_SECRET_LITERAL_COUNT_{analysis.get('secret_literal_count')}")
    command_counts = analysis.get("command_counts") if isinstance(analysis.get("command_counts"), dict) else {}
    if any(int(command_counts.get(command, 0) or 0) < 1 for command in REQUIRED_COMMANDS):
        blockers.append("COMMAND_SURFACE_INCOMPLETE")
    if not set(REQUIRED_ENV_KEYS).issubset(set(analysis.get("environment_keys") or [])):
        blockers.append("CANONICAL_ENVIRONMENT_KEYS_INCOMPLETE")
    if env_mode != "0600" or env_owner != "0:0":
        blockers.append(f"ENVIRONMENT_FILE_METADATA_{env_mode}_{env_owner}")
    if not ENV_DROPIN.is_file():
        blockers.append("ENVIRONMENT_DROPIN_MISSING")
    if any(not env_values.get(key) for key in REQUIRED_ENV_KEYS):
        blockers.append("ENVIRONMENT_VALUE_SHAPE_INCOMPLETE")

    try:
        target_argv = replace_source_arg(initial_argv, LEGACY_SOURCE, release_path) if not blockers else []
        dropin_text = source_dropin_text(target_argv) if target_argv else ""
        if not blockers and canonical is not None:
            backups = [
                backup_path(SOURCE_DROPIN, rollback_dir, "30-canonical-source.conf.bak"),
                backup_path(release_path, rollback_dir, "canonical-source.py.bak"),
            ]
            install_release(release_path, canonical)
            mutation_count += 1
            release_sha_matches = sha256_file(release_path) == sha256_bytes(canonical)
            if not release_sha_matches:
                blockers.append("RELEASE_FILE_SHA_MISMATCH")
            if not blockers:
                write_text_root(SOURCE_DROPIN, dropin_text, 0o644)
                mutation_count += 1
                source_dropin_bound = SOURCE_DROPIN.is_file() and SOURCE_DROPIN.read_text(encoding="utf-8", errors="replace") == dropin_text
                if not source_dropin_bound:
                    blockers.append("SOURCE_DROPIN_PARITY_FAILED")
            if not blockers:
                reload_proc = run(["systemctl", "daemon-reload"])
                mutation_count += 1
                if reload_proc.returncode != 0:
                    blockers.append("DAEMON_RELOAD_FAILED")
            baseline_mtime_ns = REPORT.stat().st_mtime_ns if REPORT.is_file() else 0
            if not blockers:
                restart_proc = run(["systemctl", "restart", UNIT], timeout=45)
                mutation_count += 1
                service_restart_count += 1
                if restart_proc.returncode != 0:
                    blockers.append("TARGET_UNIT_RESTART_FAILED")
            if not blockers:
                time.sleep(3)
                if not unit_active():
                    blockers.append("TARGET_UNIT_NOT_ACTIVE_AFTER_RESTART")
            if not blockers:
                current_argv = process_cmdline()
                process_release_bound = current_argv.count(str(release_path)) == 1 and str(LEGACY_SOURCE) not in current_argv
                if not process_release_bound:
                    blockers.append("TARGET_PROCESS_RELEASE_PATH_NOT_BOUND")
            if not blockers:
                current_env = process_environment()
                process_env_key_count = sum(1 for key in REQUIRED_ENV_KEYS if current_env.get(key) == env_values.get(key))
                if process_env_key_count != 2:
                    blockers.append(f"TARGET_PROCESS_ENVIRONMENT_KEY_COUNT_{process_env_key_count}")
            if not blockers:
                visible_reply, runtime_report, smoke_error = wait_for_visible_pos_reply(baseline_mtime_ns, max(30, args.smoke_timeout))
                if not visible_reply:
                    blockers.append(str(smoke_error or "VISIBLE_POS_REPLY_NOT_OBSERVED"))
    except KeyboardInterrupt:
        blockers.append("CANARY_INTERRUPTED")
    except Exception as exc:
        blockers.append("CANARY_EXCEPTION_" + type(exc).__name__)

    after = stable_snapshot(root)
    protected_changes = [name for name in before if before.get(name) != after.get(name)]
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_" + ",".join(protected_changes))

    if blockers and backups:
        rollback_performed = True
        rollback_errors = rollback(backups, initial_active)
        if rollback_errors:
            blockers.append("ROLLBACK_ERRORS_" + ",".join(rollback_errors))

    final_active = unit_active()
    final_argv = process_cmdline()
    if rollback_performed:
        process_release_bound = False
        source_dropin_bound = SOURCE_DROPIN.is_file()
        if initial_active and not final_active:
            blockers.append("ROLLBACK_TARGET_UNIT_NOT_ACTIVE")
        if initial_argv and final_argv != initial_argv:
            blockers.append("ROLLBACK_EXEC_ARGV_MISMATCH")

    state = "PASS" if not blockers else "HOLD"
    next_stage = "R7.A1A6_DEPLOYMENT_PARITY_AND_COMMAND_SMOKE" if state == "PASS" else "R7.A1A5_DIAGNOSE"
    payload = {
        "schema": "r7a1a5_systemd_source_cutover_canary_status_v1",
        "official_stage": "R7.A1A5",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "mutation_count": mutation_count,
        "service_restart_count": service_restart_count,
        "legacy_exec_source_count": legacy_exec_source_count,
        "canonical_compile_ok": analysis.get("compile_ok"),
        "canonical_secret_literal_count": analysis.get("secret_literal_count"),
        "canonical_command_counts": command_counts,
        "release_path": str(release_path),
        "release_file_sha_matches_git": release_sha_matches,
        "source_dropin": {"path": str(SOURCE_DROPIN), "bound": source_dropin_bound},
        "target_unit_active": final_active,
        "target_process_release_path_bound": process_release_bound,
        "target_process_environment_key_count": process_env_key_count,
        "runtime_report_status": runtime_report.get("status"),
        "visible_pos_reply_observed": visible_reply,
        "value_exposure_count": 0,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "rollback_performed": rollback_performed,
        "rollback_error_count": len(rollback_errors),
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A5 Systemd Source Cutover Canary",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- release path: `{release_path}`",
            f"- release SHA parity: `{release_sha_matches}`",
            f"- source drop-in bound: `{source_dropin_bound}`",
            f"- process release path bound: `{process_release_bound}`",
            f"- process environment key count: `{process_env_key_count}`",
            f"- visible /pos reply observed: `{visible_reply}`",
            f"- runtime report status: `{runtime_report.get('status')}`",
            f"- protected changes: `{protected_changes}`",
            f"- rollback performed: `{rollback_performed}`",
            f"- next: `{next_stage}`",
            "",
            "No credential or chat identifier is recorded or printed.",
        ]) + "\n",
        encoding="utf-8",
    )
    os.chmod(report_path, 0o600)

    print("R7A1A5_SYSTEMD_SOURCE_CUTOVER_CANARY_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"MUTATION_COUNT={mutation_count}")
    print(f"SERVICE_RESTART_COUNT={service_restart_count}")
    print(f"LEGACY_EXEC_SOURCE_COUNT={legacy_exec_source_count}")
    print(f"CANONICAL_COMPILE_OK={str(analysis.get('compile_ok')).lower()}")
    print(f"CANONICAL_SECRET_LITERAL_COUNT={analysis.get('secret_literal_count')}")
    print(f"RELEASE_FILE_SHA_MATCHES_GIT={str(release_sha_matches).lower()}")
    print(f"SOURCE_DROPIN_BOUND={str(source_dropin_bound).lower()}")
    print(f"TARGET_UNIT_ACTIVE={str(final_active).lower()}")
    print(f"TARGET_PROCESS_RELEASE_PATH_BOUND={str(process_release_bound).lower()}")
    print(f"TARGET_PROCESS_ENVIRONMENT_KEY_COUNT={process_env_key_count}")
    print(f"RUNTIME_REPORT_STATUS={runtime_report.get('status')}")
    print(f"VISIBLE_POS_REPLY_OBSERVED={str(visible_reply).lower()}")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"PROTECTED_CHANGE_COUNT={len(protected_changes)}")
    print(f"ROLLBACK_PERFORMED={str(rollback_performed).lower()}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
