#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = ROOT / "backend/research/rebuild/a1_top5_structure_authority_lock_v1.json"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def trade_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return (str(row.get("symbol") or ""), int(row.get("signal_ts") or 0), str(row.get("side") or ""))


def load_lock() -> dict[str, Any]:
    lock = read(LOCK_PATH)
    if lock.get("state") != "LOCKED_CURRENT_TOP5_PARENT_STRUCTURE":
        raise RuntimeError("TOP5_STRUCTURE_LOCK_NOT_ACTIVE")
    policy = lock.get("historical_record_policy") or {}
    if policy.get("automatic_historical_union") is not False:
        raise RuntimeError("AUTO_HISTORICAL_UNION_MUST_BE_FALSE")
    if policy.get("unlisted_prelock_history") != "QUARANTINE_DO_NOT_UNION":
        raise RuntimeError("PRELOCK_QUARANTINE_POLICY_MISMATCH")
    return lock


def _assert_close(name: str, observed: Any, expected: Any, tol: float = 1e-9) -> None:
    if abs(float(observed) - float(expected)) > tol:
        raise RuntimeError(f"{name}_MISMATCH:{observed}!={expected}")


def assert_structure_lock() -> dict[str, Any]:
    lock = load_lock()
    lanes = lock["lanes"]

    primary = lanes["trend_rider_primary_wr8125"]
    primary_path = ROOT / primary["parent_path"]
    primary_doc = read(primary_path)
    if git_blob_sha(primary_path) != primary["parent_blob_sha"]:
        raise RuntimeError("TREND_PRIMARY_PARENT_BLOB_DRIFT")
    if primary_doc.get("receipt_sha256") != primary["parent_receipt_sha256"]:
        raise RuntimeError("TREND_PRIMARY_PARENT_RECEIPT_DRIFT")
    pm = primary_doc.get("metrics") or {}
    if int(pm.get("trades") or 0) != int(primary["parent_T"]):
        raise RuntimeError("TREND_PRIMARY_T_DRIFT")
    _assert_close("TREND_PRIMARY_WR", pm.get("win_rate"), primary["parent_win_rate"], 1e-12)
    _assert_close("TREND_PRIMARY_PAYOFF", pm.get("payoff"), primary["parent_payoff"], 1e-9)

    fresh_path = ROOT / primary["fresh2_path"]
    fresh_doc = read(fresh_path)
    if git_blob_sha(fresh_path) != primary["fresh2_blob_sha"]:
        raise RuntimeError("TREND_PRIMARY_FRESH2_BLOB_DRIFT")
    if fresh_doc.get("receipt_sha256") != primary["fresh2_receipt_sha256"]:
        raise RuntimeError("TREND_PRIMARY_FRESH2_RECEIPT_DRIFT")
    if len(fresh_doc.get("trades") or []) != int(primary["fresh2_T"]):
        raise RuntimeError("TREND_PRIMARY_FRESH2_T_DRIFT")

    broad = lanes["trend_rider_broad_wr7000"]
    ledger_path = ROOT / broad["canonical_ledger_path"]
    ledger = read(ledger_path)
    if git_blob_sha(ledger_path) != broad["canonical_ledger_blob_sha_at_lock"]:
        raise RuntimeError("TREND_BROAD_CANONICAL_LEDGER_DRIFT_REQUIRES_EXPLICIT_LOCK_ROTATION")
    row = (ledger.get("strategies") or {}).get("trend_rider") or {}
    if int(row.get("completed_trades") or 0) != int(broad["parent_T"]):
        raise RuntimeError("TREND_BROAD_T_DRIFT")
    _assert_close("TREND_BROAD_WR", row.get("win_rate"), broad["parent_win_rate"], 1e-12)
    _assert_close("TREND_BROAD_PAYOFF", row.get("payoff"), broad["parent_payoff"], 1e-9)
    _assert_close("TREND_BROAD_EXPECTANCY", row.get("net_expectancy_bps"), broad["parent_net_expectancy_bps"], 1e-6)
    if row.get("status") != broad["canonical_status_at_lock"]:
        raise RuntimeError("TREND_BROAD_STATUS_DRIFT_REQUIRES_EXPLICIT_LOCK_ROTATION")
    if bool(broad["survivor_at_lock"]):
        raise RuntimeError("LOCK_SEMANTICS_INVALID_BROAD_MARKED_SURVIVOR")

    return lock


def quarantine_unlisted_prelock(
    rows: Iterable[dict[str, Any]],
    *,
    allowed_locked_rows: Iterable[dict[str, Any]],
    boundary_ms: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed = {trade_key(dict(x)) for x in allowed_locked_rows}
    postlock: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        ts = int(row.get("signal_ts") or 0)
        if ts > boundary_ms:
            postlock.append(row)
        elif trade_key(row) not in allowed:
            quarantined.append(row)
    return postlock, quarantined


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    lock = assert_structure_lock()
    if args.check:
        print(json.dumps({
            "state": "PASS_TOP5_STRUCTURE_AUTHORITY_LOCK",
            "lock_id": lock["lock_id"],
            "lock_boundary_ms": lock["lock_boundary_ms"],
            "trend_primary_T": lock["lanes"]["trend_rider_primary_wr8125"]["parent_T"],
            "trend_broad_T": lock["lanes"]["trend_rider_broad_wr7000"]["parent_T"],
            "trend_broad_survivor": lock["lanes"]["trend_rider_broad_wr7000"]["survivor_at_lock"],
            "historical_union": lock["historical_record_policy"]["automatic_historical_union"],
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
