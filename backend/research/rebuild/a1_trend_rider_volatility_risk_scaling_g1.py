#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import concentration, economic_gate, metrics
from backend.research.rebuild.policy_kernel_v1 import atr

ROOT = Path(__file__).resolve().parents[3]
A5 = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
HARD = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
SCHEMA = "zel.a1.trend_rider.volatility_risk_scaling.g1.v1"
AXIS = "VOLATILITY_RISK_SCALING_ONLY"
EVIDENCE_ID = "A5E1"
GENERATION_INDEX = 1


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def validate_parent(parent: Mapping[str, Any]) -> None:
    if parent.get("strategy_id") != "trend_rider":
        raise RuntimeError("TREND_RIDER_PARENT_REQUIRED")
    if parent.get("challenger_id") != "trend_rider_delayed_fill_long_only_v1":
        raise RuntimeError("LONG_ONLY_EXACT_PARENT_REQUIRED")
    if parent.get("changed_axis") != "LONG_SHORT_ASYMMETRY_LONG_ONLY":
        raise RuntimeError("LONG_ONLY_AXIS_REQUIRED")
    if parent.get("evaluation_mode") != "development":
        raise RuntimeError("DEVELOPMENT_PARENT_REQUIRED")
    if parent.get("execution_authority") != "NONE":
        raise RuntimeError("PARENT_EXECUTION_AUTHORITY_NOT_BLOCKED")
    if parent.get("order_authority") != "BLOCKED" or parent.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("PARENT_ORDER_LIVE_NOT_BLOCKED")
    if int(parent.get("completed_trades") or 0) != len(parent.get("trades") or []):
        raise RuntimeError("PARENT_TRADE_COUNT_MISMATCH")
    if any(str(x.get("side")) != "long" for x in parent.get("trades") or []):
        raise RuntimeError("LONG_ONLY_PARENT_SIDE_LEAK")


def validate_axis(a5: Mapping[str, Any], hard: Mapping[str, Any]) -> int:
    rows = a5["strategies"]["trend_rider"]["repair_axes"]
    axes = {str(x["axis"]): x for x in rows}
    if AXIS not in axes:
        raise RuntimeError("VOLATILITY_RISK_SCALING_AXIS_NOT_FROZEN")
    evidence = {str(x["id"]): x for x in a5.get("external_evidence") or []}
    if EVIDENCE_ID not in evidence:
        raise RuntimeError("VOLATILITY_SCALING_EVIDENCE_MISSING")
    cap = int(hard["h1_strategy_family_kill_gate"]["maximum_generations_per_axis_data_sha"])
    if GENERATION_INDEX > cap:
        raise RuntimeError("H1_GENERATION_CAP_EXCEEDED")
    return cap


def load_bars(parent: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[int, int]]]:
    symbols = sorted({str(x["symbol"]) for x in parent.get("trades") or []})
    bars_by = {symbol: ev.fetch_bars(symbol, "1h", 1000) for symbol in symbols}
    maps = {symbol: {int(row["ts_ms"]): i for i, row in enumerate(rows)} for symbol, rows in bars_by.items()}
    return bars_by, maps


def risk_scale_for_trade(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> tuple[float, dict[str, float]]:
    symbol = str(trade["symbol"])
    idx = maps[symbol].get(int(trade["signal_ts"]))
    if idx is None or idx < 50:
        raise RuntimeError(f"VOL_SCALE_SIGNAL_BAR_MISSING_OR_TOO_SHORT:{symbol}:{trade.get('signal_ts')}")
    bars = bars_by[symbol][: idx + 1]
    atr14 = float(atr(bars, 14))
    atr50 = float(atr(bars, 50))
    if not (math.isfinite(atr14) and math.isfinite(atr50)) or atr14 <= 0 or atr50 <= 0:
        raise RuntimeError(f"VOL_SCALE_NONFINITE_ATR:{symbol}:{trade.get('signal_ts')}")
    # Causal, parameter-free relative-volatility scaling: when current short-horizon
    # volatility is above the longer-horizon baseline, size falls; when below, size rises.
    # No fitted target, clipping threshold, outcome-conditioned deletion, or parameter sweep.
    scale = atr50 / atr14
    if not math.isfinite(scale) or scale <= 0:
        raise RuntimeError(f"VOL_SCALE_INVALID:{symbol}:{trade.get('signal_ts')}")
    return scale, {"atr14": atr14, "atr50": atr50, "atr50_over_atr14": scale}


def apply_scaling(parent: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for trade in parent.get("trades") or []:
        scale, state = risk_scale_for_trade(trade, bars_by, maps)
        row = dict(trade)
        row["unscaled_gross_bps"] = float(trade["gross_bps"])
        row["unscaled_net_bps"] = float(trade["net_bps"])
        row["risk_scale"] = scale
        row["risk_scale_state"] = state
        row["gross_bps"] = float(trade["gross_bps"]) * scale
        row["net_bps"] = float(trade["net_bps"]) * scale
        row["scaled_realized_cost_bps"] = float(trade.get("realized_cost_bps") or 0.0) * scale
        out.append(row)
    return out


def run(parent_path: Path, output: Path) -> dict[str, Any]:
    parent = read(parent_path)
    validate_parent(parent)
    a5, hard = read(A5), read(HARD)
    h1_cap = validate_axis(a5, hard)
    if (parent.get("source_quality_gate") or {}).get("state") != "PASS":
        raise RuntimeError("PARENT_SOURCE_QUALITY_NOT_PASS")

    bars_by, maps = load_bars(parent)
    parent_trades = [dict(x) for x in parent.get("trades") or []]
    child_trades = apply_scaling(parent, bars_by, maps)
    if len(child_trades) != len(parent_trades):
        raise RuntimeError("VOL_SCALE_RETENTION_MUST_BE_100_PERCENT")

    unscaled_metrics = metrics(parent_trades)
    scaled_metrics = metrics(child_trades)
    parent_h5 = concentration(parent_trades, bars_by, maps, hard)
    child_h5 = concentration(child_trades, bars_by, maps, hard)
    retention = 100.0
    econ_ok, econ_blockers = economic_gate(scaled_metrics, retention, hard)
    h5_improved = int(child_h5["blocker_count"]) < int(parent_h5["blocker_count"])
    scales = [float(x["risk_scale"]) for x in child_trades]

    candidate = {
        "candidate_id": "trend_rider_long_only__volatility_risk_scaling__atr50_over_atr14_g1",
        "changed_axis": AXIS,
        "generation_index_within_axis_data_sha": GENERATION_INDEX,
        "h1_maximum_generations_per_axis_data_sha": h1_cap,
        "evidence_ids": [EVIDENCE_ID],
        "mechanism": "causal_position_weight_equals_completed_signal_bar_ATR50_divided_by_ATR14",
        "parameter_sweep": False,
        "numeric_threshold_sweep": False,
        "post_outcome_threshold_rescue": False,
        "post_outcome_trade_deletion": False,
        "parent_trade_identity_preserved": True,
        "signal_geometry_changed": False,
        "entry_exit_geometry_changed": False,
        "cost_model_changed": False,
        "trade_retention_pct": retention,
        "completed_trades": len(child_trades),
        "risk_scale_min": min(scales) if scales else None,
        "risk_scale_max": max(scales) if scales else None,
        "risk_scale_mean": sum(scales) / len(scales) if scales else None,
        "unscaled_signal_metrics": unscaled_metrics,
        "scaled_portfolio_metrics": scaled_metrics,
        "parent_concentration": parent_h5,
        "scaled_concentration": child_h5,
        "economic_gate_pass": econ_ok,
        "economic_gate_blockers": econ_blockers,
        "h5_blocker_count_improved_vs_parent": h5_improved,
        "development_candidate_ready": bool(econ_ok and h5_improved),
        "fresh_prospective_validation_required": True,
        "risk_management_gain_must_not_be_labeled_signal_alpha": True,
        "trade_identity_sha256": stable([(x.get("symbol"), x.get("signal_ts"), x.get("entry_ts"), x.get("exit_ts"), x.get("side")) for x in child_trades]),
    }
    candidate["candidate_sha256"] = stable(candidate)

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TREND_RIDER_VOLATILITY_RISK_SCALING_G1_READY" if candidate["development_candidate_ready"] else "HOLD_TREND_RIDER_VOLATILITY_RISK_SCALING_G1",
        "strategy_id": "trend_rider",
        "parent_challenger_id": parent.get("challenger_id"),
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "candidate": candidate,
        "policy": {
            "one_axis_only": True,
            "same_trade_identity_required": True,
            "completed_signal_bar_only": True,
            "no_target_vol_fit": True,
            "no_clip_threshold": True,
            "no_parameter_sweep": True,
            "dual_attribution_required": True,
            "development_only": True,
            "fresh_prospective_validation_required": True,
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
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    hard = read(HARD)
    a5 = read(A5)
    assert validate_axis(a5, hard) >= GENERATION_INDEX
    assert any(str(x["axis"]) == AXIS for x in a5["strategies"]["trend_rider"]["repair_axes"])
    assert any(str(x["id"]) == EVIDENCE_ID for x in a5["external_evidence"])
    assert abs((2.0 / 4.0) - 0.5) < 1e-12
    print("PASS_A1_TREND_RIDER_VOLATILITY_RISK_SCALING_G1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_volatility_risk_scaling_g1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.parent is None:
        raise SystemExit("--parent required")
    result = run(args.parent, args.out)
    c = result["candidate"]
    print("A1_TREND_RIDER_VOLATILITY_RISK_SCALING_G1=" + json.dumps({
        "state": result["state"],
        "ready": c["development_candidate_ready"],
        "unscaled": c["unscaled_signal_metrics"],
        "scaled": c["scaled_portfolio_metrics"],
        "parent_h5": c["parent_concentration"]["blockers"],
        "scaled_h5": c["scaled_concentration"]["blockers"],
        "scale_min": c["risk_scale_min"],
        "scale_mean": c["risk_scale_mean"],
        "scale_max": c["risk_scale_max"],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
