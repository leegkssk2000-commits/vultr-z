#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HISTORY = ROOT / "backend/research/architecture_factory/a1_trendrider_lane_aware_history_latest.json"
SCHEMA = "zel.a1_trendrider_lane_aware_history.v1"
WRITER_CONTRACT = "backend/research/architecture_factory/a1_trendrider_lane_aware_history_writer_v1.py"
LANES = (
    "trend_rider_primary_wr8125",
    "trend_rider_broad_wr7000",
)
BLOCKED_AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("HISTORY_OBJECT_REQUIRED")
    return value


def _assert_contract(history: Mapping[str, Any]) -> None:
    if str(history.get("schema_version") or "") != SCHEMA:
        raise RuntimeError("HISTORY_SCHEMA_DRIFT")
    if str(history.get("selection_unit") or "") != "lane_id":
        raise RuntimeError("HISTORY_SELECTION_UNIT_DRIFT")
    if str(history.get("writer_contract") or "") != WRITER_CONTRACT:
        raise RuntimeError("HISTORY_WRITER_CONTRACT_DRIFT")
    for key, expected in BLOCKED_AUTH.items():
        if history.get(key) != expected:
            raise RuntimeError(f"HISTORY_AUTHORITY_DRIFT:{key}")
    lanes = history.get("lanes")
    if not isinstance(lanes, Mapping) or set(lanes.keys()) != set(LANES):
        raise RuntimeError("HISTORY_LANE_ID_DRIFT")
    for lane_id in LANES:
        row = lanes.get(lane_id)
        if not isinstance(row, Mapping):
            raise RuntimeError(f"HISTORY_LANE_MISSING:{lane_id}")
        if not isinstance(row.get("attempted_axes"), list):
            raise RuntimeError(f"HISTORY_ATTEMPTED_AXES_REQUIRED:{lane_id}")
        if not isinstance(row.get("attempts"), list):
            raise RuntimeError(f"HISTORY_ATTEMPTS_REQUIRED:{lane_id}")
        axes = [str(x) for x in row.get("attempted_axes") or []]
        if len(axes) != len(set(axes)):
            raise RuntimeError(f"HISTORY_DUPLICATE_AXIS:{lane_id}")
        attempt_axes = [str(x.get("axis") or "") for x in row.get("attempts") or [] if isinstance(x, Mapping)]
        if attempt_axes != axes:
            raise RuntimeError(f"HISTORY_ATTEMPT_AXIS_PARITY:{lane_id}")


def _attempt_id(lane_id: str, axis: str, result: str, receipt_sha256: str | None) -> str:
    raw = json.dumps(
        {
            "lane_id": lane_id,
            "axis": axis,
            "result": result,
            "receipt_sha256": receipt_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def append_attempt(
    history_path: Path,
    lane_id: str,
    axis: str,
    result: str,
    receipt_sha256: str | None = None,
) -> dict[str, Any]:
    if lane_id not in LANES:
        raise RuntimeError(f"LANE_ID_NOT_ALLOWED:{lane_id}")
    axis = str(axis or "").strip()
    if not axis.startswith("LANE_DONOR__") or not axis.endswith("__ONLY"):
        raise RuntimeError("LANE_AXIS_FORMAT_REQUIRED")
    result = str(result or "").strip().upper()
    if result not in {"PASS", "FAIL", "HOLD"}:
        raise RuntimeError(f"ATTEMPT_RESULT_NOT_ALLOWED:{result}")
    if receipt_sha256 is not None:
        receipt_sha256 = str(receipt_sha256).strip().lower()
        if len(receipt_sha256) != 64 or any(c not in "0123456789abcdef" for c in receipt_sha256):
            raise RuntimeError("ATTEMPT_RECEIPT_SHA256_REQUIRED")

    history = _read(history_path)
    _assert_contract(history)
    lane = history["lanes"][lane_id]
    attempted = [str(x) for x in lane["attempted_axes"]]
    if axis in attempted:
        raise RuntimeError(f"LANE_AXIS_RETRY_FORBIDDEN:{lane_id}:{axis}")

    entry = {
        "attempt_id": _attempt_id(lane_id, axis, result, receipt_sha256),
        "lane_id": lane_id,
        "axis": axis,
        "result": result,
        "receipt_sha256": receipt_sha256,
    }
    lane["attempted_axes"].append(axis)
    lane["attempts"].append(entry)
    history["state"] = "ACTIVE_LANE_ATTEMPT_HISTORY"
    history["failed_lane_gene_pair_retry_forbidden"] = True
    _assert_contract(history)
    _atomic_write(history_path, history)
    return entry


def self_test() -> int:
    initial = {
        "schema_version": SCHEMA,
        "state": "READY_EMPTY_LANE_ATTEMPT_HISTORY",
        "selection_unit": "lane_id",
        "writer_contract": WRITER_CONTRACT,
        "lanes": {
            LANES[0]: {"attempted_axes": [], "attempts": []},
            LANES[1]: {"attempted_axes": [], "attempts": []},
        },
        "failed_lane_gene_pair_retry_forbidden": True,
        **BLOCKED_AUTH,
    }
    axis = "LANE_DONOR__TEST__GENE__ONLY"
    with tempfile.TemporaryDirectory(prefix="a1_lane_history_writer_") as td:
        path = Path(td) / "history.json"
        _atomic_write(path, initial)
        first = append_attempt(path, LANES[0], axis, "FAIL")
        assert first["lane_id"] == LANES[0] and first["axis"] == axis
        try:
            append_attempt(path, LANES[0], axis, "FAIL")
        except RuntimeError as exc:
            assert str(exc).startswith("LANE_AXIS_RETRY_FORBIDDEN:")
        else:
            raise AssertionError("same lane/axis retry must fail")
        second = append_attempt(path, LANES[1], axis, "HOLD")
        assert second["lane_id"] == LANES[1]
        persisted = _read(path)
        _assert_contract(persisted)
        assert persisted["lanes"][LANES[0]]["attempted_axes"] == [axis]
        assert persisted["lanes"][LANES[1]]["attempted_axes"] == [axis]
        assert len(persisted["lanes"][LANES[0]]["attempts"]) == 1
        assert len(persisted["lanes"][LANES[1]]["attempts"]) == 1
    print("PASS_A1_TRENDRIDER_LANE_HISTORY_WRITER_V1_SELF_TEST")
    print("PASS_SAME_LANE_AXIS_RETRY_FORBIDDEN")
    print("PASS_OTHER_LANE_SAME_AXIS_ALLOWED")
    print("PASS_APPEND_ONLY_PERSISTENCE_RELOAD")
    print("PASS_AUTHORITY_BLOCKS_INTACT")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    ap.add_argument("--lane-id")
    ap.add_argument("--axis")
    ap.add_argument("--result")
    ap.add_argument("--receipt-sha256")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.lane_id or not args.axis or not args.result:
        raise SystemExit("LANE_ID_AXIS_RESULT_REQUIRED")
    entry = append_attempt(args.history, args.lane_id, args.axis, args.result, args.receipt_sha256)
    print(json.dumps(entry, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())