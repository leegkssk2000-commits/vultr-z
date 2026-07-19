#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DISPLAY = Path("/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json")
LEDGER = Path("/var/www/z-os-alimi/api/q4r3_shadow_closed_ledger_latest.json")
TRACE = Path("/var/www/z-os-alimi/api/q4r3_recent_ledger_trace_latest.json")
VIEW = Path("/var/www/z-os-alimi/api/view_contract_latest.json")
FORMAL_LEDGER = Path("/home/z/z/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl")
SHADOW = Path("/home/z/z/runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json")
PROTECTED = (DISPLAY, LEDGER, TRACE, VIEW, FORMAL_LEDGER, SHADOW)


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


def snapshot() -> dict[str, str | None]:
    return {str(path): sha256(path) for path in PROTECTED}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def normalized(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text.rstrip("Rr%"))
        except Exception:
            return text
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


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


def all_nested(value: Any, keys: set[str]) -> tuple[Any, ...]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys:
                found.append(normalized(child))
            found.extend(all_nested(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(all_nested(child, keys))
    return tuple(sorted(found, key=lambda item: str(item)))


def row_count(payload: dict[str, Any]) -> int | None:
    value = first_nested(payload, {"recent_rows", "row_count", "rows"})
    if isinstance(value, list):
        return len(value)
    try:
        return int(float(value))
    except Exception:
        return None


def writer_count(payload: dict[str, Any], configured: bool) -> int | None:
    keys = {"configured_writer_count", "writer_registry_count", "configured_count"} if configured else {"active_writer_count", "writer_count", "active_count"}
    value = first_nested(payload, keys)
    try:
        return int(float(value))
    except Exception:
        return None


def critical_subset(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_authority": all_nested(payload, {"order_authority"}),
        "execution_authority": all_nested(payload, {"execution_authority"}),
        "real_order_enabled": all_nested(payload, {"real_order_enabled"}),
        "configured_writer_count": writer_count(payload, True),
        "active_writer_count": writer_count(payload, False),
        "closed": normalized(first_nested(payload, {"closed", "closed_count", "shadow_closed"})),
        "pnl_r": normalized(first_nested(payload, {"pnl_r", "net_r", "shadow_pnl_r"})),
        "recent_rows": row_count(payload),
    }


def critical_diff(left: dict[str, Any], right: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keys = sorted(set(left) | set(right))
    return {key: {"http": left.get(key), "file": right.get(key)} for key in keys if left.get(key) != right.get(key)}


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    blockers: list[str] = []
    before = snapshot()

    if contract.get("official_stage") != "R7.A1A6B":
        blockers.append("CONTRACT_INVALID")

    http_status, http_payload, endpoint_mode = fetch_http()
    file_payload = load_json(VIEW)
    if http_status != 200:
        blockers.append(f"ALIMI_HTTP_STATUS_{http_status}")
    if not file_payload:
        blockers.append("VIEW_FILE_EMPTY_OR_INVALID")

    http_subset = critical_subset(http_payload)
    file_subset = critical_subset(file_payload)
    diff = critical_diff(http_subset, file_subset)

    display = load_json(DISPLAY)
    ledger = load_json(LEDGER)
    trace = load_json(TRACE)
    view = file_payload
    row_sources = {
        "display": row_count(display),
        "ledger": row_count(ledger),
        "trace": row_count(trace),
        "view": row_count(view),
    }
    zero_epoch_expected = (
        normalized(first_nested(view, {"closed", "closed_count", "shadow_closed"})) in (0, 0.0, None)
        and normalized(first_nested(view, {"pnl_r", "net_r", "shadow_pnl_r"})) in (0, 0.0, None)
    )
    nonzero_row_sources = {key: value for key, value in row_sources.items() if value not in (0, None)}
    zero_epoch_row_parity = not zero_epoch_expected or not nonzero_row_sources

    after = snapshot()
    protected_changes = [path for path in before if before[path] != after[path]]
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_DETECTED")

    mismatch_axes: list[str] = []
    if diff:
        mismatch_axes.append("ALIMI_HTTP_FILE")
    if not zero_epoch_row_parity:
        mismatch_axes.append("TELEGRAM_RECENT_ROWS")

    next_stage = "R7.A1A6C_SINGLE_SOURCE_SURFACE_REPAIR_PLAN" if mismatch_axes else "R7.A1A6A_RETRY"
    diagnosis_complete = http_status == 200 and bool(file_payload)
    state = "PASS" if not blockers and diagnosis_complete else "HOLD"

    out_dir = root / "runtime/exact25_edge_v1/r7a1a6b_surface_semantic_parity_diagnose"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    payload = {
        "schema": "r7a1a6b_surface_semantic_parity_diagnose_status_v1",
        "official_stage": "R7.A1A6B",
        "generated_at": now_iso(),
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "diagnosis_complete": diagnosis_complete,
        "alimi_http_status": http_status,
        "alimi_endpoint_mode": endpoint_mode,
        "alimi_http_subset": http_subset,
        "alimi_file_subset": file_subset,
        "alimi_mismatch_count": len(diff),
        "alimi_mismatch_fields": sorted(diff),
        "alimi_mismatch_values": diff,
        "telegram_recent_rows_sources": row_sources,
        "telegram_nonzero_recent_rows_sources": nonzero_row_sources,
        "zero_epoch_expected": zero_epoch_expected,
        "zero_epoch_recent_rows_parity": zero_epoch_row_parity,
        "mismatch_axes": mismatch_axes,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "systemd_mutation_count": 0,
        "telegram_send_count": 0,
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
            "# R7.A1A6B Surface Semantic Parity Diagnosis",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- ALIMI HTTP status: `{http_status}`",
            f"- ALIMI mismatch fields: `{sorted(diff)}`",
            f"- Telegram recent_rows sources: `{row_sources}`",
            f"- zero-epoch recent_rows parity: `{zero_epoch_row_parity}`",
            f"- mismatch axes: `{mismatch_axes}`",
            f"- protected changes: `{protected_changes}`",
            f"- next: `{next_stage}`",
        ]) + "\n",
        encoding="utf-8",
    )
    os.chmod(report_path, 0o600)

    print("R7A1A6B_SURFACE_SEMANTIC_PARITY_DIAGNOSE_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"DIAGNOSIS_COMPLETE={str(diagnosis_complete).lower()}")
    print(f"ALIMI_HTTP_STATUS={http_status}")
    print(f"ALIMI_ENDPOINT_MODE={endpoint_mode}")
    print(f"ALIMI_MISMATCH_COUNT={len(diff)}")
    print(f"ALIMI_MISMATCH_FIELDS={json.dumps(sorted(diff), ensure_ascii=False)}")
    for field in sorted(diff):
        print(f"ALIMI_DIFF_{field.upper()}={json.dumps(diff[field], ensure_ascii=False)}")
    print(f"TELEGRAM_RECENT_ROWS_SOURCES={json.dumps(row_sources, ensure_ascii=False, sort_keys=True)}")
    print(f"TELEGRAM_NONZERO_RECENT_ROWS_SOURCES={json.dumps(nonzero_row_sources, ensure_ascii=False, sort_keys=True)}")
    print(f"ZERO_EPOCH_EXPECTED={str(zero_epoch_expected).lower()}")
    print(f"ZERO_EPOCH_RECENT_ROWS_PARITY={str(zero_epoch_row_parity).lower()}")
    print(f"MISMATCH_AXES={json.dumps(mismatch_axes, ensure_ascii=False)}")
    print(f"PROTECTED_CHANGE_COUNT={len(protected_changes)}")
    print("SYSTEMD_MUTATION_COUNT=0")
    print("TELEGRAM_SEND_COUNT=0")
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
