#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VIEW = Path("/var/www/z-os-alimi/api/view_contract_latest.json")
LEDGER = Path("/var/www/z-os-alimi/api/q4r3_shadow_closed_ledger_latest.json")
TRACE = Path("/var/www/z-os-alimi/api/q4r3_recent_ledger_trace_latest.json")
DISPLAY = Path("/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json")
FORMAL = Path("/home/z/z/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl")
SHADOW = Path("/home/z/z/runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json")
REPAIRABLE = (VIEW, LEDGER, TRACE)
PROTECTED = (FORMAL, SHADOW, DISPLAY)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def json_from_text(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except Exception:
        return None


def snapshot(paths: tuple[Path, ...]) -> dict[str, str | None]:
    return {str(path): sha256(path) for path in paths}


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o644) -> None:
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


def atomic_bytes(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def normalized_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("Rr%"))
        except Exception:
            return None
    return None


def first_nested(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys and child is not None:
                return child
        for child in value.values():
            found = first_nested(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = first_nested(child, keys)
            if found is not None:
                return found
    return None


def all_nested(value: Any, keys: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys:
                found.append(child)
            found.extend(all_nested(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(all_nested(child, keys))
    return found


def first_int(value: Any, keys: set[str]) -> int | None:
    candidate = first_nested(value, keys)
    try:
        return int(float(candidate))
    except Exception:
        return None


def row_count(value: dict[str, Any]) -> int | None:
    candidate = first_nested(value, {"recent_rows", "row_count", "rows"})
    if isinstance(candidate, list):
        return len(candidate)
    try:
        return int(float(candidate))
    except Exception:
        return None


def fetch_http() -> tuple[int, dict[str, Any], str]:
    attempts = [
        ["curl", "-kfsS", "--max-time", "10", "--resolve", "alimi.z-os.vip:443:127.0.0.1", "-w", "\n%{http_code}", "https://alimi.z-os.vip/api/view_contract_latest.json"],
        ["curl", "-fsS", "--max-time", "10", "-H", "Host: alimi.z-os.vip", "-w", "\n%{http_code}", "http://127.0.0.1/api/view_contract_latest.json"],
    ]
    for index, cmd in enumerate(attempts, start=1):
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=15)
        if proc.returncode != 0:
            continue
        body, _, tail = proc.stdout.rpartition("\n")
        try:
            status = int(tail.strip())
        except Exception:
            status = 0
        payload = json_from_text(body)
        if status and payload:
            return status, payload, f"attempt_{index}"
    return 0, {}, "none"


def safety_ok(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    order_values = all_nested(payload, {"order_authority"})
    execution_values = all_nested(payload, {"execution_authority"})
    real_values = all_nested(payload, {"real_order_enabled"})
    configured = first_int(payload, {"configured_writer_count", "writer_registry_count", "configured_count"})
    if configured != 7:
        blockers.append(f"CONFIGURED_WRITER_COUNT_{configured}")
    if not order_values or any(value != "blocked" for value in order_values):
        blockers.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if not execution_values or any(value != "none" for value in execution_values):
        blockers.append("EXECUTION_AUTHORITY_NOT_NONE")
    if not real_values or any(value is not False for value in real_values):
        blockers.append("REAL_ORDER_ENABLED_NOT_FALSE")
    return not blockers, blockers


def zero_epoch_ok(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    closed = normalized_number(first_nested(payload, {"closed", "closed_count", "shadow_closed"}))
    pnl = normalized_number(first_nested(payload, {"pnl_r", "net_r", "shadow_pnl_r"}))
    rows = row_count(payload)
    if closed not in (0.0, None):
        blockers.append(f"HTTP_CLOSED_NOT_ZERO_{closed}")
    if pnl not in (0.0, None):
        blockers.append(f"HTTP_PNL_NOT_ZERO_{pnl}")
    if rows not in (0, None):
        blockers.append(f"HTTP_RECENT_ROWS_NOT_ZERO_{rows}")
    return not blockers, blockers


def clean_ledger(epoch: str) -> dict[str, Any]:
    return {
        "schema": "q4r3_shadow_closed_ledger_zero_epoch_v1",
        "epoch": epoch,
        "mode": "shadow",
        "closed": 0,
        "closed_count": 0,
        "pnl_r": 0.0,
        "net_r": 0.0,
        "recent_rows": 0,
        "rows": [],
        "last_close": "none",
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "generated_at": now_iso(),
    }


def clean_trace(epoch: str) -> dict[str, Any]:
    return {
        "schema": "q4r3_recent_ledger_trace_zero_epoch_v1",
        "epoch": epoch,
        "mode": "shadow",
        "recent_rows": 0,
        "row_count": 0,
        "rows": [],
        "last12_r": 0.0,
        "last12_pnl_r": 0.0,
        "wr_pct": 0.0,
        "winrate_pct": 0.0,
        "ev_r": 0.0,
        "last_close": "none",
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "generated_at": now_iso(),
    }


def backup_files(backup_dir: Path) -> dict[str, Any]:
    backup_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(backup_dir, 0o700)
    entries: dict[str, Any] = {}
    for index, path in enumerate(REPAIRABLE, start=1):
        key = f"file_{index}"
        entry: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
        if path.is_file():
            data = path.read_bytes()
            mode = stat.S_IMODE(path.stat().st_mode)
            backup_path = backup_dir / f"{index}_{path.name}"
            backup_path.write_bytes(data)
            os.chmod(backup_path, 0o600)
            entry.update({"backup_path": str(backup_path), "mode": mode, "sha256": hashlib.sha256(data).hexdigest()})
        entries[key] = entry
    manifest = {"created_at": now_iso(), "entries": entries}
    atomic_json(backup_dir / "manifest.json", manifest, 0o600)
    return manifest


def restore_manifest(manifest_path: Path) -> list[str]:
    manifest = load_json(manifest_path)
    errors: list[str] = []
    for entry in (manifest.get("entries") or {}).values():
        if not isinstance(entry, dict):
            continue
        path = Path(str(entry.get("path") or ""))
        try:
            if entry.get("exists") is True:
                backup_path = Path(str(entry.get("backup_path") or ""))
                data = backup_path.read_bytes()
                atomic_bytes(path, data, int(entry.get("mode") or 0o644))
            elif path.exists():
                path.unlink()
        except Exception as exc:
            errors.append(f"{path}:{type(exc).__name__}")
    return errors


def apply(root: Path, contract_path: Path) -> int:
    contract = load_json(contract_path)
    blockers: list[str] = []
    protected_before = snapshot(PROTECTED)
    display = load_json(DISPLAY)
    if contract.get("official_stage") != "R7.A1A6C":
        blockers.append("CONTRACT_INVALID")
    http_status, http_payload, endpoint_mode = fetch_http()
    if http_status != 200:
        blockers.append(f"ALIMI_HTTP_STATUS_{http_status}")
    ok, reasons = safety_ok(http_payload)
    if not ok:
        blockers.extend(reasons)
    ok, reasons = zero_epoch_ok(http_payload)
    if not ok:
        blockers.extend(reasons)
    display_closed = normalized_number(first_nested(display, {"closed", "closed_count"}))
    display_pnl = normalized_number(first_nested(display, {"pnl_r", "net_r", "pnl"}))
    if display_closed not in (0.0, None) or display_pnl not in (0.0, None):
        blockers.append("DISPLAY_STATUS_NOT_ZERO_EPOCH")

    out_dir = root / "runtime/exact25_edge_v1/r7a1a6c_zero_epoch_surface_repair"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    backup_dir: Path | None = None
    rollback_errors: list[str] = []
    repair_applied = False
    epoch = str(first_nested(display, {"epoch"}) or "q4r3.exact25.shadow.pending")

    if not blockers:
        try:
            backup_dir = out_dir / ("backup_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            backup_files(backup_dir)
            atomic_json(VIEW, http_payload, 0o644)
            atomic_json(LEDGER, clean_ledger(epoch), 0o644)
            atomic_json(TRACE, clean_trace(epoch), 0o644)
            repair_applied = True
        except Exception as exc:
            blockers.append(f"SURFACE_WRITE_FAILED_{type(exc).__name__}")

    http_status_after, http_payload_after, _ = fetch_http()
    view_after = load_json(VIEW)
    ledger_after = load_json(LEDGER)
    trace_after = load_json(TRACE)
    view_parity = http_status_after == 200 and bool(http_payload_after) and http_payload_after == view_after
    ledger_zero = (
        normalized_number(ledger_after.get("closed")) == 0.0
        and normalized_number(ledger_after.get("pnl_r")) == 0.0
        and ledger_after.get("rows") == []
        and row_count(ledger_after) == 0
    )
    trace_zero = (
        trace_after.get("rows") == []
        and row_count(trace_after) == 0
        and normalized_number(trace_after.get("last12_r")) == 0.0
        and normalized_number(trace_after.get("wr_pct")) == 0.0
        and normalized_number(trace_after.get("ev_r")) == 0.0
    )
    protected_after = snapshot(PROTECTED)
    protected_changes = [path for path in protected_before if protected_before[path] != protected_after[path]]
    if repair_applied and not view_parity:
        blockers.append("ALIMI_HTTP_FILE_JSON_PARITY_FALSE")
    if repair_applied and not ledger_zero:
        blockers.append("LEDGER_ZERO_EPOCH_FALSE")
    if repair_applied and not trace_zero:
        blockers.append("TRACE_ZERO_EPOCH_FALSE")
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_DETECTED")

    if blockers and backup_dir is not None and (backup_dir / "manifest.json").is_file():
        rollback_errors = restore_manifest(backup_dir / "manifest.json")
        repair_applied = False

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "r7a1a6c_zero_epoch_surface_repair_status_v1",
        "official_stage": "R7.A1A6C",
        "generated_at": now_iso(),
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "alimi_http_status": http_status_after,
        "alimi_endpoint_mode": endpoint_mode,
        "alimi_http_file_json_parity": view_parity,
        "ledger_zero_epoch": ledger_zero,
        "trace_zero_epoch": trace_zero,
        "surface_repair_applied": repair_applied,
        "backup_dir": str(backup_dir) if backup_dir else None,
        "backup_manifest": str(backup_dir / "manifest.json") if backup_dir else None,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "rollback_error_count": len(rollback_errors),
        "rollback_errors": rollback_errors,
        "paper_mutation_count": 0,
        "live_mutation_count": 0,
        "order_mutation_count": 0,
        "value_exposure_count": 0,
        "next_stage": "R7.A1A6C_ROUTER_CUTOVER" if state == "PASS" else "R7.A1A6C_DIAGNOSE",
    }
    atomic_json(status_path, payload, 0o600)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A6C Zero-Epoch Surface Repair",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- HTTP/file parity: `{view_parity}`",
            f"- ledger zero epoch: `{ledger_zero}`",
            f"- trace zero epoch: `{trace_zero}`",
            f"- protected changes: `{protected_changes}`",
            f"- backup: `{backup_dir}`",
        ]) + "\n",
        encoding="utf-8",
    )
    os.chmod(report_path, 0o600)

    print("R7A1A6C_ZERO_EPOCH_SURFACE_REPAIR_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"ALIMI_HTTP_STATUS={http_status_after}")
    print(f"ALIMI_HTTP_FILE_JSON_PARITY={str(view_parity).lower()}")
    print(f"LEDGER_ZERO_EPOCH={str(ledger_zero).lower()}")
    print(f"TRACE_ZERO_EPOCH={str(trace_zero).lower()}")
    print(f"SURFACE_REPAIR_APPLIED={str(repair_applied).lower()}")
    print(f"BACKUP_MANIFEST={payload['backup_manifest']}")
    print(f"PROTECTED_CHANGE_COUNT={len(protected_changes)}")
    print("PAPER_MUTATION_COUNT=0")
    print("LIVE_MUTATION_COUNT=0")
    print("ORDER_MUTATION_COUNT=0")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"EVIDENCE_JSON={status_path}")
    return 0 if state == "PASS" else 2


def rollback(root: Path) -> int:
    status_path = root / "runtime/exact25_edge_v1/r7a1a6c_zero_epoch_surface_repair/status_latest.json"
    status = load_json(status_path)
    manifest = Path(str(status.get("backup_manifest") or ""))
    errors = restore_manifest(manifest) if manifest.is_file() else ["BACKUP_MANIFEST_MISSING"]
    status.update({
        "state": "ROLLED_BACK" if not errors else "ROLLBACK_FAILED",
        "surface_repair_applied": False,
        "rollback_requested_at": now_iso(),
        "rollback_error_count": len(errors),
        "rollback_errors": errors,
    })
    atomic_json(status_path, status, 0o600)
    print("R7A1A6C_ZERO_EPOCH_SURFACE_ROLLBACK_COMPLETE")
    print(f"STATE={status['state']}")
    print(f"ROLLBACK_ERROR_COUNT={len(errors)}")
    return 0 if not errors else 2


def verify(root: Path) -> int:
    status_path = root / "runtime/exact25_edge_v1/r7a1a6c_zero_epoch_surface_repair/status_latest.json"
    status = load_json(status_path)
    http_status, http_payload, _ = fetch_http()
    view_parity = http_status == 200 and bool(http_payload) and http_payload == load_json(VIEW)
    ledger_zero = load_json(LEDGER).get("rows") == [] and row_count(load_json(LEDGER)) == 0
    trace_zero = load_json(TRACE).get("rows") == [] and row_count(load_json(TRACE)) == 0
    ok = status.get("state") == "PASS" and view_parity and ledger_zero and trace_zero
    print("R7A1A6C_ZERO_EPOCH_SURFACE_VERIFY_COMPLETE")
    print(f"STATE={'PASS' if ok else 'HOLD'}")
    print(f"ALIMI_HTTP_FILE_JSON_PARITY={str(view_parity).lower()}")
    print(f"LEDGER_ZERO_EPOCH={str(ledger_zero).lower()}")
    print(f"TRACE_ZERO_EPOCH={str(trace_zero).lower()}")
    return 0 if ok else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("apply", "rollback", "verify"))
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.mode == "apply":
        if not args.contract:
            print('BLOCKERS=["MISSING_CONTRACT"]')
            return 2
        return apply(root, Path(args.contract))
    if args.mode == "rollback":
        return rollback(root)
    return verify(root)


if __name__ == "__main__":
    raise SystemExit(main())
