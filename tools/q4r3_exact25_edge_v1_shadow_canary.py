from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

ROOT = Path(os.environ.get("Q4R3_ROOT", "/home/z/z"))
BINDING = ROOT / "backend/config/q4r3_exact25_shadow_binding_v1.json"
MANIFEST = ROOT / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
LOADER_DIR = ROOT / "backend/engine"
EPOCH = ROOT / "runtime/exact25_edge_v1/epoch_latest.json"
CANARY_DIR = ROOT / "runtime/exact25_edge_v1/canary"
LEDGER = CANARY_DIR / "canary_ledger.jsonl"
REPORT = CANARY_DIR / "canary_latest.json"
LOCK = CANARY_DIR / ".canary.lock"
EXPECTED_WRITER = "tools/q4r3_vwap_mfe_mae_capture_sidecar.py"
TOKEN = "EXACT25_EDGE_V1_CANARY"


def load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_components():
    sys.path.insert(0, str(LOADER_DIR))
    try:
        from q4r3_exact25_shadow_manifest_loader import (  # type: ignore
            load_shadow_registry,
            validate_binding_config,
            validate_closed_measurement_row,
        )
    finally:
        if sys.path and sys.path[0] == str(LOADER_DIR):
            sys.path.pop(0)
    binding = load_json(BINDING)
    validate_binding_config(binding)
    registry = load_shadow_registry(ROOT, MANIFEST, BINDING)
    return binding, registry, validate_closed_measurement_row


def assert_safe_binding(binding: Mapping[str, Any]) -> None:
    if binding.get("epoch_id") != "EXACT25_EDGE_V1":
        raise ValueError("EPOCH_ID_MISMATCH")
    if binding.get("shadow_enabled") is not True:
        raise ValueError("SHADOW_NOT_ENABLED")
    for key in ("paper_enabled", "live_enabled", "order_enabled", "write_enabled", "canary_enabled"):
        if binding.get(key) is not False:
            raise ValueError(f"UNSAFE_BINDING_FLAG:{key}")
    if binding.get("authoritative_lifecycle_writer") != EXPECTED_WRITER:
        raise ValueError("AUTHORITATIVE_WRITER_PATH_MISMATCH")
    writer = ROOT / EXPECTED_WRITER
    if not writer.is_file():
        raise FileNotFoundError(f"AUTHORITATIVE_WRITER_MISSING:{writer}")
    expected_sha = str(binding.get("authoritative_lifecycle_writer_sha256") or "")
    if not expected_sha or file_sha256(writer) != expected_sha:
        raise ValueError("AUTHORITATIVE_WRITER_SHA_MISMATCH")


def deterministic_row(strategy_id: str, owner_sha: str, index: int) -> Dict[str, Any]:
    side = "long" if index % 2 == 0 else "short"
    entry = 100.0 + index
    stop = entry - 1.0 if side == "long" else entry + 1.0
    initial_risk = 10.0
    realized_r = ((index % 5) - 2) * 0.25
    realized_pnl = initial_risk * realized_r
    event_id = f"EXACT25_EDGE_V1_CANARY::{strategy_id}::v1"
    return {
        "event_id": event_id,
        "event_type": "closed_measurement_canary",
        "measurement_namespace": "canary_isolated",
        "strategy_id": strategy_id,
        "owner_sha256": owner_sha,
        "symbol": "BTCUSDT",
        "side": side,
        "regime": "deterministic_canary",
        "entry_ts": "2026-01-01T00:00:00+00:00",
        "exit_ts": "2026-01-01T00:05:00+00:00",
        "entry_price": entry,
        "stop_price": stop,
        "initial_risk_usdt": initial_risk,
        "realized_pnl_usdt": realized_pnl,
        "realized_R": realized_r,
        "fee": 0.01,
        "slippage": 0.001,
        "latency_ms": 25.0,
        "MFE_R": max(realized_r, 0.5),
        "MAE_R": min(realized_r, -0.25),
        "time_exposure_min": 5.0,
        "epoch_id": "EXACT25_EDGE_V1",
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "canary": True,
    }


def existing_event_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.is_file():
        return ids
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        event_id = str(payload.get("event_id") or "")
        if event_id:
            ids.add(event_id)
    return ids


def append_unique_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    accepted = 0
    rejected_duplicate = 0
    with LOCK.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        known = existing_event_ids(path)
        with path.open("a", encoding="utf-8") as output:
            for row in rows:
                event_id = str(row.get("event_id") or "")
                if not event_id:
                    raise ValueError("EVENT_ID_REQUIRED")
                if event_id in known:
                    rejected_duplicate += 1
                    continue
                output.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
                known.add(event_id)
                accepted += 1
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return {"accepted": accepted, "rejected_duplicate": rejected_duplicate}


def verify_ledger(path: Path, expected_rows: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    ids = [str(row.get("event_id") or "") for row in rows]
    duplicate_count = len(ids) - len(set(ids))
    owner_mismatches = []
    formula_mismatches = []
    unsafe_flags = []
    for row in rows:
        expected = expected_rows.get(str(row.get("strategy_id") or ""))
        if expected and row.get("owner_sha256") != expected.get("owner_sha256"):
            owner_mismatches.append(row.get("strategy_id"))
        risk = float(row.get("initial_risk_usdt") or 0.0)
        pnl = float(row.get("realized_pnl_usdt") or 0.0)
        realized_r = float(row.get("realized_R") or 0.0)
        if risk <= 0 or abs(realized_r - pnl / risk) > 1e-12:
            formula_mismatches.append(row.get("strategy_id"))
        if any(row.get(key) is not False for key in ("paper_enabled", "live_enabled", "order_enabled")):
            unsafe_flags.append(row.get("strategy_id"))
    return {
        "row_count": len(rows),
        "unique_event_count": len(set(ids)),
        "duplicate_count": duplicate_count,
        "owner_mismatches": owner_mismatches,
        "formula_mismatches": formula_mismatches,
        "unsafe_flags": unsafe_flags,
        "ledger_sha256": file_sha256(path),
    }


def run() -> Dict[str, Any]:
    if os.environ.get("Q4R3_ALLOW_CANARY_WRITE") != TOKEN:
        raise PermissionError("CANARY_WRITE_TOKEN_REQUIRED")
    binding, registry, validate_closed = load_components()
    assert_safe_binding(binding)
    if len(registry) != 25:
        raise ValueError("REGISTRY_NOT_EXACT25")

    rows = []
    expected_by_strategy: Dict[str, Mapping[str, Any]] = {}
    for index, (strategy_id, owner) in enumerate(sorted(registry.items())):
        row = deterministic_row(strategy_id, owner.owner_sha256, index)
        validate_closed(row)
        rows.append(row)
        expected_by_strategy[strategy_id] = row

    before = existing_event_ids(LEDGER)
    if before:
        shutil.rmtree(CANARY_DIR)
    first = append_unique_rows(LEDGER, rows)
    second = append_unique_rows(LEDGER, rows)
    verification = verify_ledger(LEDGER, expected_by_strategy)

    pass_gate = (
        first == {"accepted": 25, "rejected_duplicate": 0}
        and second == {"accepted": 0, "rejected_duplicate": 25}
        and verification["row_count"] == 25
        and verification["unique_event_count"] == 25
        and verification["duplicate_count"] == 0
        and not verification["owner_mismatches"]
        and not verification["formula_mismatches"]
        and not verification["unsafe_flags"]
    )

    result = {
        "schema": "q4r3_exact25_edge_v1_shadow_canary_v1",
        "status": "PASS_Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY" if pass_gate else "HOLD_Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY",
        "verdict": "CANARY_PASS_WRITE_PATH_DUPLICATE_LINEAGE_R_FORMULA" if pass_gate else "CANARY_GAPS_REMAIN",
        "action": "HOLD",
        "next_action": "ENABLE_FORWARD_MEASUREMENT_WRITER_SHADOW_ONLY" if pass_gate else "PATCH_ONLY_CANARY_GAPS_AND_RERUN",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "epoch_id": "EXACT25_EDGE_V1",
        "strategy_count": len(registry),
        "first_write": first,
        "replay_write": second,
        "verification": verification,
        "authoritative_writer": EXPECTED_WRITER,
        "authoritative_writer_sha256": binding["authoritative_lifecycle_writer_sha256"],
        "canary_ledger_path": str(LEDGER),
        "isolated_canary_namespace": True,
        "production_measurement_write_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }
    atomic_json(REPORT, result)

    epoch = load_json(EPOCH)
    epoch["canary_state"] = "PASS_ISOLATED_WRITE_DISABLED_AFTER_CANARY" if pass_gate else "HOLD_CANARY_GAPS"
    epoch["canary_completed_at"] = result["created_at"]
    epoch["canary_accepted_row_count"] = first["accepted"]
    epoch["canary_duplicate_reject_count"] = second["rejected_duplicate"]
    epoch["canary_ledger_sha256"] = verification["ledger_sha256"]
    epoch["write_enabled"] = False
    epoch["canary_enabled"] = False
    epoch["state"] = "CANARY_PASS_FORWARD_WRITE_NOT_STARTED" if pass_gate else "CANARY_HOLD"
    atomic_json(EPOCH, epoch)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    if args.output:
        atomic_json(args.output, result)
    print(json.dumps({key: result[key] for key in ("status", "verdict", "strategy_count", "first_write", "replay_write", "next_action")}, ensure_ascii=False))
    raise SystemExit(0 if result["status"].startswith("PASS_") else 2)


if __name__ == "__main__":
    main()
