#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
VIEW_FILE = Path("/var/www/z-os-alimi/api/view_contract_latest.json")
TELEGRAM_STATUS = Path("/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json")
REQUIRED_ENV_KEYS = ("ZEL_TELEGRAM_BOT_TOKEN", "ZEL_TELEGRAM_ALLOWED_CHAT_ID")
REQUIRED_COMMANDS = ("/pos", "/pnl", "/view")
TOKEN_LITERAL = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def json_from_bytes(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


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


def file_mode_owner(path: Path) -> tuple[str | None, str | None]:
    try:
        meta = path.stat()
        return f"{stat.S_IMODE(meta.st_mode):04o}", f"{meta.st_uid}:{meta.st_gid}"
    except Exception:
        return None, None


def parse_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return result
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            result[key.strip()] = value.strip()
    return result


def main_pid() -> int:
    proc = run(["systemctl", "show", UNIT, "-p", "MainPID", "--value"], timeout=15)
    try:
        return int(proc.stdout.strip())
    except Exception:
        return 0


def unit_active() -> bool:
    proc = run(["systemctl", "is-active", UNIT], timeout=15)
    return proc.returncode == 0 and proc.stdout.strip() == "active"


def process_cmdline() -> list[str]:
    pid = main_pid()
    if pid <= 0:
        return []
    try:
        return [part.decode("utf-8", errors="replace") for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part]
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


def collect_key_values(value: Any, key_names: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in key_names:
                found.append(child)
            found.extend(collect_key_values(child, key_names))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_key_values(child, key_names))
    return found


def writer_counts(view: dict[str, Any]) -> tuple[int | None, int | None]:
    configured_values = collect_key_values(view, {"configured_writer_count", "writer_registry_count", "configured_count"})
    active_values = collect_key_values(view, {"active_writer_count", "writer_count", "active_count"})

    def first_int(values: list[Any]) -> int | None:
        for value in values:
            try:
                return int(value)
            except Exception:
                continue
        return None

    return first_int(configured_values), first_int(active_values)


def fetch_view_endpoint() -> tuple[int, dict[str, Any], str]:
    attempts = [
        ["curl", "-kfsS", "--max-time", "10", "--resolve", "alimi.z-os.vip:443:127.0.0.1", "-w", "\n%{http_code}", "https://alimi.z-os.vip/api/view_contract_latest.json"],
        ["curl", "-fsS", "--max-time", "10", "-H", "Host: alimi.z-os.vip", "-w", "\n%{http_code}", "http://127.0.0.1/api/view_contract_latest.json"],
    ]
    for index, cmd in enumerate(attempts, start=1):
        proc = run(cmd, timeout=15)
        if proc.returncode != 0:
            continue
        body, _, tail = proc.stdout.rpartition("\n")
        try:
            status = int(tail.strip())
        except Exception:
            status = 0
        payload = json_from_bytes(body.encode("utf-8"))
        if status > 0 and payload:
            return status, payload, f"attempt_{index}"
    return 0, {}, "none"


def wait_command(command: str, timeout_seconds: int) -> tuple[bool, dict[str, Any], str | None, int | None]:
    try:
        baseline = REPORT.stat().st_mtime_ns if REPORT.is_file() else 0
    except Exception:
        baseline = 0
    print(f"ACTION_REQUIRED=SEND_{command}_TO_ZEL_BOT_WITHIN_{timeout_seconds}_SECONDS")
    started = time.monotonic()
    deadline = started + timeout_seconds
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if not unit_active():
            return False, latest, "TARGET_UNIT_STOPPED_DURING_COMMAND_SMOKE", None
        try:
            changed = REPORT.is_file() and REPORT.stat().st_mtime_ns > baseline
        except Exception:
            changed = False
        if changed:
            latest = load_json(REPORT)
            if str(latest.get("status") or "").startswith("HOLD_"):
                return False, latest, "RUNTIME_REPORT_HOLD", int((time.monotonic() - started) * 1000)
            ok, semantic_blockers = report_semantics(latest)
            if not ok:
                return False, latest, semantic_blockers[0], int((time.monotonic() - started) * 1000)
            try:
                sent_count = int(latest.get("sent_count", 0) or 0)
            except Exception:
                sent_count = 0
            if sent_count >= 1:
                return True, latest, None, int((time.monotonic() - started) * 1000)
        time.sleep(0.25)
    return False, latest, "COMMAND_SMOKE_TIMEOUT", None


def protected_snapshot(root: Path, release_path: Path) -> dict[str, str | None]:
    paths = {
        "formal_ledger": root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
        "shadow_snapshot": root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json",
        "legacy_source": LEGACY_SOURCE,
        "environment_file": ENV_FILE,
        "environment_dropin": ENV_DROPIN,
        "source_dropin": SOURCE_DROPIN,
        "release_file": release_path,
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--command-timeout", type=int, default=90)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = root / "runtime/exact25_edge_v1/r7a1a6_deployment_parity_command_smoke"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    blockers: list[str] = []
    command_results: list[dict[str, Any]] = []

    contract = load_json(Path(args.contract))
    parent = load_json(root / "runtime/exact25_edge_v1/r7a1a5_systemd_source_cutover_canary/status_latest.json")
    classifier = load_json(root / "runtime/exact25_edge_v1/r7a1a5a_runtime_error_classification/status_latest.json")
    release_path = Path(str(parent.get("release_path") or ""))
    canonical = git_bytes(root, args.sha, CANONICAL_PATH)
    before = protected_snapshot(root, release_path)

    if contract.get("official_stage") != "R7.A1A6":
        blockers.append("CONTRACT_INVALID")
    if parent.get("state") != "PASS":
        blockers.append("R7A1A5_NOT_PASS")
    if classifier.get("state") != "PASS" or classifier.get("runtime_error_class") != "NONE":
        blockers.append("R7A1A5A_NOT_CLEAN_PASS")
    if not unit_active():
        blockers.append("TARGET_UNIT_NOT_ACTIVE")
    if not release_path.is_file():
        blockers.append("RELEASE_FILE_MISSING")
    if canonical is None:
        blockers.append("CANONICAL_SOURCE_MISSING")
    release_sha_matches_git = canonical is not None and sha256_file(release_path) == sha256_bytes(canonical)
    if not release_sha_matches_git:
        blockers.append("RELEASE_FILE_SHA_MISMATCH")

    argv = process_cmdline()
    process_release_bound = argv.count(str(release_path)) == 1 and str(LEGACY_SOURCE) not in argv
    if not process_release_bound:
        blockers.append("TARGET_PROCESS_RELEASE_PATH_NOT_BOUND")

    env_mode, env_owner = file_mode_owner(ENV_FILE)
    env_values = parse_env_file(ENV_FILE)
    proc_env = process_environment()
    process_env_key_count = sum(1 for key in REQUIRED_ENV_KEYS if proc_env.get(key) == env_values.get(key) and bool(env_values.get(key)))
    if env_mode != "0600" or env_owner != "0:0":
        blockers.append(f"ENVIRONMENT_FILE_METADATA_{env_mode}_{env_owner}")
    if not ENV_DROPIN.is_file():
        blockers.append("ENVIRONMENT_DROPIN_MISSING")
    if not SOURCE_DROPIN.is_file():
        blockers.append("SOURCE_DROPIN_MISSING")
    if process_env_key_count != 2:
        blockers.append(f"TARGET_PROCESS_ENVIRONMENT_KEY_COUNT_{process_env_key_count}")

    runtime = load_json(REPORT)
    runtime_ok, runtime_blockers = report_semantics(runtime)
    if not runtime_ok:
        blockers.extend(runtime_blockers)

    http_status, view_http, endpoint_mode = fetch_view_endpoint()
    view_file = load_json(VIEW_FILE)
    view_parity = bool(view_http) and bool(view_file) and view_http == view_file
    if http_status != 200:
        blockers.append(f"ALIMI_VIEW_HTTP_STATUS_{http_status}")
    if not view_parity:
        blockers.append("ALIMI_VIEW_FILE_HTTP_JSON_PARITY_FAILED")

    order_values = collect_key_values(view_http, {"order_authority"})
    execution_values = collect_key_values(view_http, {"execution_authority"})
    real_order_values = collect_key_values(view_http, {"real_order_enabled"})
    if not order_values or any(value != "blocked" for value in order_values):
        blockers.append("VIEW_ORDER_AUTHORITY_NOT_BLOCKED")
    if not execution_values or any(value != "none" for value in execution_values):
        blockers.append("VIEW_EXECUTION_AUTHORITY_NOT_NONE")
    if not real_order_values or any(value is not False for value in real_order_values):
        blockers.append("VIEW_REAL_ORDER_ENABLED_NOT_FALSE")

    configured_writer_count, active_writer_count = writer_counts(view_http)
    if configured_writer_count != 7:
        blockers.append(f"VIEW_CONFIGURED_WRITER_COUNT_{configured_writer_count}")

    if not TELEGRAM_STATUS.is_file() or not load_json(TELEGRAM_STATUS):
        blockers.append("TELEGRAM_CANONICAL_STATUS_MISSING")

    if not blockers:
        for command in REQUIRED_COMMANDS:
            ok, latest, error, latency_ms = wait_command(command, max(30, args.command_timeout))
            command_results.append({
                "command": command,
                "pass": ok,
                "error": error,
                "latency_ms": latency_ms,
                "runtime_status": latest.get("status"),
                "sent_count": latest.get("sent_count"),
            })
            if not ok:
                blockers.append(f"COMMAND_SMOKE_{command[1:].upper()}_{error}")
                break

    after = protected_snapshot(root, release_path)
    protected_changes = [name for name in before if before.get(name) != after.get(name)]
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_" + ",".join(protected_changes))

    command_pass_count = sum(1 for item in command_results if item.get("pass") is True)
    state = "PASS" if not blockers else "HOLD"
    next_stage = "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE" if state == "PASS" else "R7.A1A6_DIAGNOSE"
    payload = {
        "schema": "r7a1a6_deployment_parity_command_smoke_status_v1",
        "official_stage": "R7.A1A6",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "mutation_count": 0,
        "target_unit_active": unit_active(),
        "release_path": str(release_path),
        "release_file_sha_matches_git": release_sha_matches_git,
        "target_process_release_path_bound": process_release_bound,
        "environment_file_mode": env_mode,
        "environment_file_owner": env_owner,
        "target_process_environment_key_count": process_env_key_count,
        "runtime_report_status": runtime.get("status"),
        "alimi_view_http_status": http_status,
        "alimi_view_endpoint_mode": endpoint_mode,
        "alimi_view_file_http_json_parity": view_parity,
        "configured_writer_count": configured_writer_count,
        "active_writer_count": active_writer_count,
        "command_smoke_pass_count": command_pass_count,
        "command_results": command_results,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "paper_mutation_count": 0,
        "live_mutation_count": 0,
        "order_mutation_count": 0,
        "value_exposure_count": 0,
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A6 Deployment Parity and Command Smoke",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- release SHA parity: `{release_sha_matches_git}`",
            f"- process release bound: `{process_release_bound}`",
            f"- environment key count: `{process_env_key_count}`",
            f"- ALIMI view HTTP status: `{http_status}`",
            f"- ALIMI file/HTTP JSON parity: `{view_parity}`",
            f"- Writers configured/active: `{configured_writer_count}/{active_writer_count}`",
            f"- command smoke pass count: `{command_pass_count}`",
            f"- protected changes: `{protected_changes}`",
            f"- next: `{next_stage}`",
            "",
            "No credential or chat identifier is recorded or printed.",
        ]) + "\n",
        encoding="utf-8",
    )
    os.chmod(report_path, 0o600)

    print("R7A1A6_DEPLOYMENT_PARITY_COMMAND_SMOKE_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print("MUTATION_COUNT=0")
    print(f"TARGET_UNIT_ACTIVE={str(unit_active()).lower()}")
    print(f"RELEASE_FILE_SHA_MATCHES_GIT={str(release_sha_matches_git).lower()}")
    print(f"TARGET_PROCESS_RELEASE_PATH_BOUND={str(process_release_bound).lower()}")
    print(f"ENVIRONMENT_FILE_MODE={env_mode}")
    print(f"ENVIRONMENT_FILE_OWNER={env_owner}")
    print(f"TARGET_PROCESS_ENVIRONMENT_KEY_COUNT={process_env_key_count}")
    print(f"RUNTIME_REPORT_STATUS={runtime.get('status')}")
    print(f"ALIMI_VIEW_HTTP_STATUS={http_status}")
    print(f"ALIMI_VIEW_FILE_HTTP_JSON_PARITY={str(view_parity).lower()}")
    print(f"CONFIGURED_WRITER_COUNT={configured_writer_count}")
    print(f"ACTIVE_WRITER_COUNT={active_writer_count}")
    print(f"COMMAND_SMOKE_PASS_COUNT={command_pass_count}")
    print(f"PROTECTED_CHANGE_COUNT={len(protected_changes)}")
    print("PAPER_MUTATION_COUNT=0")
    print("LIVE_MUTATION_COUNT=0")
    print("ORDER_MUTATION_COUNT=0")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
