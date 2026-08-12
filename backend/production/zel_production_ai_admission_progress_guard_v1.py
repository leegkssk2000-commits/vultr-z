from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production import zel_production_ai_admission_executor_v1 as v1
from backend.production import zel_production_ai_admission_executor_v2 as v2
from backend.production import zel_production_ai_admission_executor_v3 as v3
from backend.production.zel_production_improvement_controller_v1 import read_json, stable_sha

SCHEMA = "zel.production_ai_admission_progress_guard.v1"
TARGET_TEMPLATE = "funding_volume_elasticity_v1"


def _key(row: Mapping[str, Any]) -> tuple[str, str, int]:
    return (
        str(row.get("contract_id") or ""),
        str(row.get("symbol") or ""),
        int(row.get("outcome_candle_ts_ms") or 0),
    )


def _base(state: str, next_step: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": state,
        "next": next_step,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
    }


def progress_guard_tick(
    policy: Mapping[str, Any],
    *,
    contract_state: Mapping[str, Any] | None,
    carry_snapshot: Mapping[str, Any] | None,
    history: Sequence[Mapping[str, Any]],
    executor_summary: Mapping[str, Any],
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    cfg = v2.validate_policy(policy)
    if executor_summary.get("executor_version") != "V3":
        raise RuntimeError("AI_ADMISSION_PROGRESS_GUARD_EXECUTOR_VERSION_DRIFT")
    try:
        appended = int(executor_summary.get("observation_history_appended") or 0)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("AI_ADMISSION_PROGRESS_GUARD_APPENDED_INVALID") from exc
    if appended < 0:
        raise RuntimeError("AI_ADMISSION_PROGRESS_GUARD_APPENDED_NEGATIVE")

    contracts = []
    if isinstance(contract_state, Mapping) and isinstance(contract_state.get("contracts"), list):
        contracts = [
            dict(x)
            for x in contract_state.get("contracts") or []
            if isinstance(x, Mapping) and str(x.get("template_id") or "") == TARGET_TEMPLATE
        ]
    if not contracts:
        out = _base("HOLD_PROSPECTIVE_NO_TARGET_CONTRACT", "WAIT_FOR_FROZEN_TARGET_CONTRACT")
        out.update({"observation_history_appended": appended, "expected_key_count": 0, "history_key_count": len(history), "integrity_ok": True})
        out["receipt_sha256"] = stable_sha(out)
        return out

    if not isinstance(carry_snapshot, Mapping):
        out = _base("HOLD_PROSPECTIVE_SOURCE_CANDLE_UNAVAILABLE", "WAIT_FOR_VERIFIED_CARRY_AND_CLOSED_CANDLE")
        out.update({"observation_history_appended": appended, "expected_key_count": 0, "history_key_count": len(history), "integrity_ok": True})
        out["receipt_sha256"] = stable_sha(out)
        return out
    observed_at_ms = int(carry_snapshot.get("observed_at_ms") or 0)
    if observed_at_ms <= 0:
        raise RuntimeError("AI_ADMISSION_PROGRESS_GUARD_CARRY_OBSERVED_AT_INVALID")

    history_keys: set[tuple[str, str, int]] = set()
    duplicate_keys: list[tuple[str, str, int]] = []
    for raw in history:
        if not isinstance(raw, Mapping):
            continue
        key = _key(raw)
        if key in history_keys:
            duplicate_keys.append(key)
        history_keys.add(key)
    if duplicate_keys:
        out = _base("HOLD_PROSPECTIVE_HISTORY_DUPLICATE_KEY", "INVESTIGATE_APPEND_SERIALIZATION")
        out.update(
            {
                "observation_history_appended": appended,
                "expected_key_count": 0,
                "history_key_count": len(history_keys),
                "duplicate_key_count": len(duplicate_keys),
                "duplicate_keys": [list(x) for x in sorted(set(duplicate_keys))],
                "integrity_ok": False,
            }
        )
        out["receipt_sha256"] = stable_sha(out)
        return out

    expected: set[tuple[str, str, int]] = set()
    latest_candle_ts_by_symbol: dict[str, int] = {}
    for symbol in cfg["symbols"]:
        candle = v3._latest_closed_ohlcv(candles_by_symbol.get(symbol) or [], observed_at_ms)
        if candle is None:
            continue
        candle_ts = int(candle["candle_ts_ms"])
        latest_candle_ts_by_symbol[symbol] = candle_ts
        for contract in contracts:
            expected.add((str(contract.get("contract_id") or ""), symbol, candle_ts))

    if not expected:
        out = _base("HOLD_PROSPECTIVE_SOURCE_CANDLE_UNAVAILABLE", "WAIT_FOR_VERIFIED_CARRY_AND_CLOSED_CANDLE")
        out.update(
            {
                "observation_history_appended": appended,
                "expected_key_count": 0,
                "history_key_count": len(history_keys),
                "latest_candle_ts_by_symbol": latest_candle_ts_by_symbol,
                "integrity_ok": True,
            }
        )
        out["receipt_sha256"] = stable_sha(out)
        return out

    missing = sorted(expected - history_keys)
    if missing:
        out = _base("HOLD_PROSPECTIVE_APPEND_MISSING", "INVESTIGATE_SOURCE_TO_HISTORY_APPEND")
        out.update(
            {
                "observation_history_appended": appended,
                "expected_key_count": len(expected),
                "history_key_count": len(history_keys),
                "missing_key_count": len(missing),
                "missing_keys": [list(x) for x in missing],
                "latest_candle_ts_by_symbol": latest_candle_ts_by_symbol,
                "integrity_ok": False,
            }
        )
        out["receipt_sha256"] = stable_sha(out)
        return out

    state = "PASS_PROSPECTIVE_HISTORY_ADVANCED" if appended > 0 else "HOLD_PROSPECTIVE_DUPLICATE_CANDLE"
    next_step = "CONTINUE_PROSPECTIVE_SOURCE_HISTORY" if appended > 0 else "WAIT_NEXT_CLOSED_CANDLE"
    out = _base(state, next_step)
    out.update(
        {
            "observation_history_appended": appended,
            "expected_key_count": len(expected),
            "history_key_count": len(history_keys),
            "missing_key_count": 0,
            "latest_candle_ts_by_symbol": latest_candle_ts_by_symbol,
            "dedup_valid": appended == 0,
            "integrity_ok": True,
        }
    )
    out["receipt_sha256"] = stable_sha(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify V3 prospective history advanced or deduplicated against the actual latest closed candle")
    ap.add_argument("--policy", type=Path, default=Path("config/zel_production_ai_admission_executor_v1.json"))
    ap.add_argument("--executor-summary", type=Path, required=True)
    ns = ap.parse_args(argv)
    policy = json.loads(ns.policy.read_text(encoding="utf-8"))
    cfg = v2.validate_policy(policy)
    contract_state = read_json(Path(str(cfg["contract_state_path"])))
    carry_snapshot = read_json(Path(str(cfg["carry_snapshot_path"])))
    history = v1.read_history(Path(str(cfg["observation_history_path"])))
    executor_summary = json.loads(ns.executor_summary.read_text(encoding="utf-8"))
    candles = asyncio.run(v2._fetch_candles(cfg["symbols"]))
    out = progress_guard_tick(
        cfg,
        contract_state=contract_state,
        carry_snapshot=carry_snapshot,
        history=history,
        executor_summary=executor_summary,
        candles_by_symbol=candles,
    )
    print(json.dumps(out, sort_keys=True))
    return 0 if out.get("integrity_ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
