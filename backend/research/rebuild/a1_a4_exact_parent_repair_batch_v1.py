#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import (
    concentration,
    economic_gate,
    metrics,
)
from backend.research.rebuild.policy_kernel_v1 import atr, ema

ROOT = Path(__file__).resolve().parents[3]
A5_CONTRACT = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
HARDENING_POLICY = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
PARENT_EVALUATOR = ROOT / "backend/research/rebuild/a1_exact25_generic_evaluator_v2.py"
SCHEMA = "zel.a1.a4.exact_parent_repair_batch.v1"

A4 = (
    "break_and_continue",
    "supertrend_pullback",
    "keltner_trend",
    "trend_ma_macd",
)

AXES_BY_STRATEGY: dict[str, tuple[str, ...]] = {
    "break_and_continue": (
        "LIQUIDITY_REGIME_OWNER_ONLY",
        "VOLATILITY_REGIME_OWNER_ONLY",
        "SESSION_PRICE_DISCOVERY_OWNER_ONLY",
    ),
    "supertrend_pullback": (
        "TREND_PERSISTENCE_OWNER_ONLY",
        "VOLATILITY_REGIME_OWNER_ONLY",
        "LIQUIDITY_REGIME_OWNER_ONLY",
        "SESSION_PRICE_DISCOVERY_OWNER_ONLY",
    ),
    "keltner_trend": (
        "BAND_EXPANSION_TRANSITION_ONLY",
        "RELATIVE_VOLUME_CONFIRMATION_ONLY",
        "LIQUIDITY_REGIME_OWNER_ONLY",
        "SESSION_PRICE_DISCOVERY_OWNER_ONLY",
    ),
    "trend_ma_macd": (
        "MULTISPEED_TREND_OWNER_ONLY",
        "VOLATILITY_REGIME_OWNER_ONLY",
        "SESSION_PRICE_DISCOVERY_OWNER_ONLY",
    ),
}

UNSUPPORTED_EXACT_IDENTITY_AXES: dict[str, tuple[str, ...]] = {
    "break_and_continue": (
        "BREAKOUT_PERSISTENCE_OWNER_ONLY",
        "COST_TURNOVER_COMPRESSION_ONLY",
    ),
    "supertrend_pullback": (
        "EXIT_TRAILING_ONLY",
    ),
    "keltner_trend": (
        "COST_TURNOVER_COMPRESSION_ONLY",
    ),
    "trend_ma_macd": (
        "REDUNDANT_COMPONENT_ABLATION_ONLY",
        "COST_TURNOVER_COMPRESSION_ONLY",
    ),
}

EVIDENCE_BY_AXIS: dict[str, tuple[str, ...]] = {
    "LIQUIDITY_REGIME_OWNER_ONLY": ("A5E2", "A5E4"),
    "VOLATILITY_REGIME_OWNER_ONLY": ("A5E2", "A5E4"),
    "SESSION_PRICE_DISCOVERY_OWNER_ONLY": ("A5E2", "A5E3"),
    "TREND_PERSISTENCE_OWNER_ONLY": ("A5E2", "A5E3"),
    "BAND_EXPANSION_TRANSITION_ONLY": ("A5E2", "A5E4"),
    "RELATIVE_VOLUME_CONFIRMATION_ONLY": ("A5E2", "A5E4"),
    "MULTISPEED_TREND_OWNER_ONLY": ("A5E2", "A5E3"),
}


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def trade_identity(trade: Mapping[str, Any]) -> str:
    return stable({
        "symbol": trade.get("symbol"),
        "signal_ts": trade.get("signal_ts"),
        "entry_ts": trade.get("entry_ts"),
        "exit_ts": trade.get("exit_ts"),
        "side": trade.get("side"),
        "intent_sha": trade.get("intent_sha"),
    })


def _maps(parent: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[int, int]]]:
    source = parent.get("source") if isinstance(parent.get("source"), Mapping) else {}
    interval = str(source.get("interval") or "1h")
    if interval != "1h":
        raise RuntimeError(f"A4_EXACT_PARENT_INTERVAL_NOT_1H:{interval}")
    symbols = sorted({str(x["symbol"]) for x in parent.get("trades") or []})
    bars_by = {symbol: ev.fetch_bars(symbol, interval, 1000) for symbol in symbols}
    maps = {
        symbol: {int(row["ts_ms"]): idx for idx, row in enumerate(rows)}
        for symbol, rows in bars_by.items()
    }
    return bars_by, maps


def _signal_index(trade: Mapping[str, Any], maps: Mapping[str, dict[int, int]]) -> int | None:
    return maps[str(trade["symbol"])].get(int(trade["signal_ts"]))


def keep_liquidity(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"])
    idx = _signal_index(trade, maps)
    if idx is None or idx < 20:
        return False
    bars = bars_by[symbol]
    current = float(bars[idx]["close"]) * float(bars[idx]["volume"])
    prior = [float(x["close"]) * float(x["volume"]) for x in bars[idx - 20:idx]]
    return current >= statistics.median(prior)


def keep_volatility_regime(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"])
    idx = _signal_index(trade, maps)
    if idx is None or idx < 50:
        return False
    bars = bars_by[symbol][: idx + 1]
    return atr(bars, 14) >= atr(bars, 50)


def keep_session_price_discovery(trade: Mapping[str, Any], _bars_by: Mapping[str, list[dict[str, Any]]], _maps: Mapping[str, dict[int, int]]) -> bool:
    hour = datetime.fromtimestamp(int(trade["signal_ts"]) / 1000.0, tz=timezone.utc).hour
    # Outcome-blind London/New-York overlap owner, already used by the sealed external-research exact8 spec.
    return hour in (13, 14, 15)


def keep_multispeed_trend(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"])
    idx = _signal_index(trade, maps)
    if idx is None or idx < 56:
        return False
    closes = [float(x["close"]) for x in bars_by[symbol][: idx + 1]]
    e21, e50, e55 = ema(closes, 21), ema(closes, 50), ema(closes, 55)
    side = str(trade["side"])
    if side == "long":
        return e21[-1] > e50[-1] > e55[-1] and e21[-1] > e21[-2] and e55[-1] >= e55[-2]
    return e21[-1] < e50[-1] < e55[-1] and e21[-1] < e21[-2] and e55[-1] <= e55[-2]


def keep_band_expansion(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"])
    idx = _signal_index(trade, maps)
    if idx is None or idx < 15:
        return False
    bars = bars_by[symbol]
    now_atr = atr(bars[: idx + 1], 14)
    prev_atr = atr(bars[:idx], 14)
    return now_atr >= prev_atr


def keep_relative_volume(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"])
    idx = _signal_index(trade, maps)
    if idx is None or idx < 20:
        return False
    bars = bars_by[symbol]
    current = float(bars[idx]["volume"])
    prior = [float(x["volume"]) for x in bars[idx - 20:idx]]
    return current >= sum(prior) / len(prior)


FILTERS: dict[str, Callable[[Mapping[str, Any], Mapping[str, list[dict[str, Any]]], Mapping[str, dict[int, int]]], bool]] = {
    "LIQUIDITY_REGIME_OWNER_ONLY": keep_liquidity,
    "VOLATILITY_REGIME_OWNER_ONLY": keep_volatility_regime,
    "SESSION_PRICE_DISCOVERY_OWNER_ONLY": keep_session_price_discovery,
    "TREND_PERSISTENCE_OWNER_ONLY": keep_multispeed_trend,
    "BAND_EXPANSION_TRANSITION_ONLY": keep_band_expansion,
    "RELATIVE_VOLUME_CONFIRMATION_ONLY": keep_relative_volume,
    "MULTISPEED_TREND_OWNER_ONLY": keep_multispeed_trend,
}


def validate_parent(strategy_id: str, parent: Mapping[str, Any]) -> None:
    if strategy_id not in A4:
        raise RuntimeError(f"UNKNOWN_A4_STRATEGY:{strategy_id}")
    if parent.get("strategy_id") != strategy_id:
        raise RuntimeError(f"A4_PARENT_IDENTITY_MISMATCH:{strategy_id}:{parent.get('strategy_id')}")
    if parent.get("parameter_sweep") not in (False, None):
        raise RuntimeError(f"A4_PARENT_PARAMETER_SWEEP_NOT_FALSE:{strategy_id}")
    if parent.get("execution_authority") not in ("NONE", None):
        raise RuntimeError(f"A4_PARENT_EXECUTION_AUTHORITY_NOT_BLOCKED:{strategy_id}")
    if parent.get("order_authority") not in ("BLOCKED", None):
        raise RuntimeError(f"A4_PARENT_ORDER_AUTHORITY_NOT_BLOCKED:{strategy_id}")
    if parent.get("live_trade_authority") not in ("BLOCKED", None):
        raise RuntimeError(f"A4_PARENT_LIVE_AUTHORITY_NOT_BLOCKED:{strategy_id}")
    if int(parent.get("completed_trades") or 0) != len(parent.get("trades") or []):
        raise RuntimeError(f"A4_PARENT_TRADE_COUNT_MISMATCH:{strategy_id}")


def select_axis(
    parent: Mapping[str, Any],
    axis: str,
    bars_by: Mapping[str, list[dict[str, Any]]],
    maps: Mapping[str, dict[int, int]],
) -> list[dict[str, Any]]:
    if axis not in FILTERS:
        raise RuntimeError(f"A4_AXIS_NOT_EXACT_IDENTITY_COMPATIBLE:{axis}")
    trades = [dict(x) for x in parent.get("trades") or []]
    chosen = [x for x in trades if FILTERS[axis](x, bars_by, maps)]
    parent_ids = {trade_identity(x) for x in trades}
    child_ids = {trade_identity(x) for x in chosen}
    if not child_ids.issubset(parent_ids):
        raise RuntimeError(f"A4_EXACT_PARENT_TRADE_IDENTITY_BROKEN:{axis}")
    return chosen


def evaluate_strategy(strategy_id: str, parent: Mapping[str, Any], hard: Mapping[str, Any]) -> dict[str, Any]:
    validate_parent(strategy_id, parent)
    bars_by, maps = _maps(parent)
    parent_trades = [dict(x) for x in parent.get("trades") or []]
    parent_metrics = metrics(parent_trades)
    parent_h5 = concentration(parent_trades, bars_by, maps, hard)
    parent_n = len(parent_trades)
    parent_ids = {trade_identity(x) for x in parent_trades}
    candidates: list[dict[str, Any]] = []

    for axis in AXES_BY_STRATEGY[strategy_id]:
        child_trades = select_axis(parent, axis, bars_by, maps)
        child_ids = {trade_identity(x) for x in child_trades}
        if not child_ids.issubset(parent_ids):
            raise RuntimeError(f"A4_CHILD_NOT_STRICT_PARENT_SUBSET:{strategy_id}:{axis}")
        child_metrics = metrics(child_trades)
        retention = 100.0 * len(child_trades) / max(1, parent_n)
        child_h5 = concentration(child_trades, bars_by, maps, hard)
        economic_ok, economic_blockers = economic_gate(child_metrics, retention, hard)
        h5_improvement = int(child_h5["blocker_count"]) < int(parent_h5["blocker_count"])
        candidate = {
            "candidate_id": f"{strategy_id}__exact_parent__{axis.lower()}",
            "strategy_id": strategy_id,
            "parent_receipt_sha256": parent.get("receipt_sha256"),
            "changed_axis": axis,
            "changed_axis_count": 1,
            "evidence_ids": list(EVIDENCE_BY_AXIS[axis]),
            "parent_trade_identity_subset": True,
            "new_trade_admission_forbidden": True,
            "parent_entry_signal_geometry_changed": False,
            "parent_stop_geometry_changed": False,
            "parent_timeout_changed": False,
            "parent_cost_model_changed": False,
            "post_outcome_trade_deletion": False,
            "parameter_sweep": False,
            "completed_trades": len(child_trades),
            "trade_retention_pct": retention,
            "metrics": child_metrics,
            "concentration": child_h5,
            "economic_gate_pass": economic_ok,
            "economic_gate_blockers": economic_blockers,
            "h5_blocker_count_improved_vs_parent": h5_improvement,
            "development_candidate_ready": bool(economic_ok and h5_improvement),
            "trade_identity_sha256": stable(sorted(child_ids)),
        }
        candidate["candidate_sha256"] = stable(candidate)
        candidates.append(candidate)

    candidates.sort(key=lambda x: (
        not bool(x["development_candidate_ready"]),
        int(x["concentration"]["blocker_count"]),
        -float(x["metrics"].get("net_expectancy_bps") or -1e18),
        -float(x["metrics"].get("profit_factor") or 0.0),
        float(x["metrics"].get("drawdown_bps") or 1e18),
        -float(x["trade_retention_pct"]),
        str(x["candidate_id"]),
    ))
    ready = [x for x in candidates if x["development_candidate_ready"]]
    return {
        "strategy_id": strategy_id,
        "incumbent": strategy_id,
        "parent_state": parent.get("state"),
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "parent_policy_sha": parent.get("policy_sha"),
        "parent_config_sha": parent.get("config_sha"),
        "parent_metrics": parent_metrics,
        "parent_concentration": parent_h5,
        "tested_axes": list(AXES_BY_STRATEGY[strategy_id]),
        "unsupported_exact_identity_axes": list(UNSUPPORTED_EXACT_IDENTITY_AXES.get(strategy_id, ())),
        "candidates": candidates,
        "development_ready_count": len(ready),
        "next_exact_parent_candidate": ready[0] if ready else None,
        "state": "PASS_EXACT_PARENT_DEVELOPMENT_REPAIR_READY" if ready else "HOLD_EXACT_PARENT_NEXT_DISTINCT_AXIS_REQUIRED",
    }


def run(parent_paths: Mapping[str, Path], output: Path) -> dict[str, Any]:
    a5 = read(A5_CONTRACT)
    hard = read(HARDENING_POLICY)
    external_ids = {str(x.get("id")) for x in (a5.get("external_evidence") or []) if isinstance(x, Mapping)}
    for axis, ids in EVIDENCE_BY_AXIS.items():
        if not set(ids).issubset(external_ids):
            raise RuntimeError(f"A4_EVIDENCE_ID_NOT_FROZEN:{axis}")

    results: dict[str, Any] = {}
    all_ready: list[dict[str, Any]] = []
    for strategy_id in A4:
        if strategy_id not in parent_paths:
            raise RuntimeError(f"A4_PARENT_PATH_MISSING:{strategy_id}")
        row = evaluate_strategy(strategy_id, read(parent_paths[strategy_id]), hard)
        results[strategy_id] = row
        for candidate in row["candidates"]:
            if candidate["development_candidate_ready"]:
                all_ready.append(candidate)

    all_ready.sort(key=lambda x: (
        int(x["concentration"]["blocker_count"]),
        -float(x["metrics"].get("net_expectancy_bps") or -1e18),
        -float(x["metrics"].get("profit_factor") or 0.0),
        float(x["metrics"].get("drawdown_bps") or 1e18),
        -float(x["trade_retention_pct"]),
        str(x["candidate_id"]),
    ))
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_A4_EXACT_PARENT_REPAIR_READY" if all_ready else "HOLD_A4_EXACT_PARENT_NEXT_DISTINCT_AXIS_REQUIRED",
        "strategies": results,
        "development_ready_count": len(all_ready),
        "next_exact_parent_candidate": all_ready[0] if all_ready else None,
        "parent_evaluator_path": str(PARENT_EVALUATOR.relative_to(ROOT)),
        "parent_evaluator_sha256": file_sha(PARENT_EVALUATOR),
        "a5_contract_sha256": file_sha(A5_CONTRACT),
        "hardening_policy_sha256": file_sha(HARDENING_POLICY),
        "policy": {
            "exact_parent_trade_identity_required": True,
            "children_are_parent_trade_subsets_only": True,
            "new_trade_admission_forbidden_in_this_lane": True,
            "parent_entry_signal_geometry_frozen": True,
            "parent_stop_timeout_cost_frozen": True,
            "one_axis_only": True,
            "post_outcome_threshold_rescue_forbidden": True,
            "parameter_sweep_forbidden": True,
            "h5_uses_existing_frozen_policy": True,
            "development_pass_requires_positive_economics_and_h5_blocker_reduction": True,
            "fresh_prospective_validation_still_required": True,
            "unsupported_non_subset_axes_require_separate_frozen_child_architecture": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    a5 = read(A5_CONTRACT)
    external_ids = {str(x["id"]) for x in a5["external_evidence"]}
    for strategy_id in A4:
        contract_axes = {str(x["axis"]) for x in a5["strategies"][strategy_id]["repair_axes"]}
        for axis in AXES_BY_STRATEGY[strategy_id]:
            assert axis in contract_axes
            assert axis in FILTERS
            assert set(EVIDENCE_BY_AXIS[axis]).issubset(external_ids)
        for axis in UNSUPPORTED_EXACT_IDENTITY_AXES.get(strategy_id, ()):
            assert axis in contract_axes
            assert axis not in AXES_BY_STRATEGY[strategy_id]
    assert read(HARDENING_POLICY)["survivor_gate"]["minimum_retention_pct"] == 60.0
    assert len(A4) == 4
    print("PASS_A1_A4_EXACT_PARENT_REPAIR_BATCH_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--break-parent", type=Path)
    ap.add_argument("--supertrend-parent", type=Path)
    ap.add_argument("--keltner-parent", type=Path)
    ap.add_argument("--macd-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_a4_exact_parent_repair_batch_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    paths = {
        "break_and_continue": args.break_parent,
        "supertrend_pullback": args.supertrend_parent,
        "keltner_trend": args.keltner_parent,
        "trend_ma_macd": args.macd_parent,
    }
    if any(path is None for path in paths.values()):
        raise SystemExit("all four exact parent receipts are required")
    result = run({k: v for k, v in paths.items() if v is not None}, args.out)
    print("A1_A4_EXACT_PARENT_REPAIR=" + json.dumps({
        "state": result["state"],
        "development_ready_count": result["development_ready_count"],
        "next": (result.get("next_exact_parent_candidate") or {}).get("candidate_id"),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
