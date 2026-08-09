from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_V2_CONTRACT_1"
STRATEGY_UNIVERSE = ("vwap_revert", "support_resistance", "liquidity_sweep")
AXES = (
    "FREQUENCY",
    "COST_EXECUTION",
    "RISK_SIZING",
    "INTERACTION",
    "PORTFOLIO",
    "ROBUSTNESS",
)

# Primary objective is deliberately not collapsed into one scalar score.
# PnL and win-rate must improve together on every selection window.
MIN_ABS_TRADES = 30
MIN_SAMPLE_RETENTION = 0.50
MAX_DD_REGRESSION_MULT = 1.15
MAX_DD_REGRESSION_ABS_R = 0.25
MIN_PF_RETENTION = 0.85


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]


def _f(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if value is None:
        return 0.0
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"NONFINITE:{key}:{value}")
    return out


def _i(row: dict[str, Any], key: str) -> int:
    return int(row.get(key) or 0)


def pnl_wr_gate(base: dict[str, Any], cand: dict[str, Any]) -> GateResult:
    reasons: list[str] = []
    if _f(cand, "net_R") <= _f(base, "net_R"):
        reasons.append("PNL_NOT_IMPROVED")
    if _f(cand, "win_rate_pct") <= _f(base, "win_rate_pct"):
        reasons.append("WR_NOT_IMPROVED")
    sample_floor = max(MIN_ABS_TRADES, int(math.ceil(_i(base, "sample_count") * MIN_SAMPLE_RETENTION)))
    if _i(cand, "sample_count") < sample_floor:
        reasons.append("SAMPLE_COLLAPSE")
    base_pf = _f(base, "profit_factor")
    cand_pf = _f(cand, "profit_factor")
    if base_pf > 0.0 and cand_pf < base_pf * MIN_PF_RETENTION:
        reasons.append("PF_QUALITY_COLLAPSE")
    base_dd = _f(base, "max_drawdown_R")
    cand_dd = _f(cand, "max_drawdown_R")
    if cand_dd > base_dd * MAX_DD_REGRESSION_MULT + MAX_DD_REGRESSION_ABS_R:
        reasons.append("DD_GUARD_FAIL")
    return GateResult(not reasons, tuple(reasons))


def multi_window_gate(
    baseline_by_window: dict[str, dict[str, Any]],
    candidate_by_window: dict[str, dict[str, Any]],
    windows: list[str],
) -> dict[str, Any]:
    per_window: dict[str, Any] = {}
    all_pass = True
    for window in windows:
        if window not in baseline_by_window or window not in candidate_by_window:
            per_window[window] = {"pass": False, "reasons": ["WINDOW_MISSING"]}
            all_pass = False
            continue
        gate = pnl_wr_gate(baseline_by_window[window], candidate_by_window[window])
        per_window[window] = {"pass": gate.passed, "reasons": list(gate.reasons)}
        all_pass = all_pass and gate.passed
    return {"pass": all_pass, "per_window": per_window}


def final_fresh_oos_gate(metrics: dict[str, Any]) -> GateResult:
    reasons: list[str] = []
    if _f(metrics, "net_R") <= 0.0:
        reasons.append("ABSOLUTE_PNL_NOT_POSITIVE")
    if _f(metrics, "profit_factor") <= 1.0:
        reasons.append("PF_NOT_ABOVE_ONE")
    if _i(metrics, "sample_count") < MIN_ABS_TRADES:
        reasons.append("FRESH_OOS_SAMPLE_TOO_SMALL")
    return GateResult(not reasons, tuple(reasons))


def axis_contract() -> dict[str, Any]:
    return {
        "FREQUENCY": {
            "purpose": "control when setups are allowed, not merely scale exits",
            "required_mechanisms": ["entry_regime_gate", "entry_session_gate", "setup_quality_gate", "cooldown"],
            "forbidden_shortcut": "stop_target_only",
        },
        "COST_EXECUTION": {
            "purpose": "measure edge after realistic execution drag",
            "required_mechanisms": ["fee_bps", "slippage_bps", "latency_ms", "fill_model"],
            "forbidden_shortcut": "min_risk_distance_as_cost_proxy",
        },
        "RISK_SIZING": {
            "purpose": "control capital at risk and time exposure",
            "required_mechanisms": ["position_size_pct", "risk_per_trade_pct", "leverage", "max_hold_min"],
            "forbidden_shortcut": "stop_mult_only",
        },
        "INTERACTION": {
            "purpose": "model simultaneous or conflicting strategy signals",
            "required_mechanisms": ["conflict_policy", "correlation_limit", "duplicate_exposure_guard"],
            "forbidden_shortcut": "parameter_bundle_only",
        },
        "PORTFOLIO": {
            "purpose": "allow any strategy to be dropped or reweighted",
            "required_mechanisms": ["enabled_entry_owners", "strategy_weights", "no_mandatory_owner"],
            "forbidden_shortcut": "forced_main_owner",
        },
        "ROBUSTNESS": {
            "purpose": "prove the edge survives unseen data and nearby parameters",
            "required_mechanisms": ["fresh_oos_windows", "parameter_neighborhood", "symbol_holdout", "regime_holdout"],
            "forbidden_shortcut": "same_windows_reused_for_selection",
        },
    }


def contract_document() -> dict[str, Any]:
    return {
        "schema_version": "zel.structural_premium.v2.contract.v1",
        "version": VERSION,
        "strategy_universe": list(STRATEGY_UNIVERSE),
        "mandatory_strategy_owners": [],
        "axes": axis_contract(),
        "selection_objective": {
            "primary_hard_gates": ["net_R_improves", "win_rate_pct_improves"],
            "secondary_quality": ["profit_factor", "expectancy_R"],
            "risk_guard_only": ["max_drawdown_R"],
            "scalar_score_for_primary_selection": False,
        },
        "sample_policy": {
            "min_abs_trades": MIN_ABS_TRADES,
            "min_sample_retention": MIN_SAMPLE_RETENTION,
        },
        "fresh_oos_policy": {
            "selection_windows_must_not_be_reused_as_final_oos": True,
            "final_requires_positive_net_R": True,
            "final_requires_profit_factor_gt_1": True,
        },
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    base = {
        "net_R": -20.0,
        "win_rate_pct": 30.0,
        "sample_count": 100,
        "profit_factor": 0.60,
        "max_drawdown_R": 25.0,
    }
    good = dict(base, net_R=-10.0, win_rate_pct=35.0, sample_count=80, profit_factor=0.62, max_drawdown_R=24.0)
    bad_wr = dict(good, win_rate_pct=29.0)
    bad_sample = dict(good, sample_count=20)
    assert pnl_wr_gate(base, good).passed
    assert "WR_NOT_IMPROVED" in pnl_wr_gate(base, bad_wr).reasons
    assert "SAMPLE_COLLAPSE" in pnl_wr_gate(base, bad_sample).reasons
    assert not final_fresh_oos_gate(good).passed
    profitable = dict(good, net_R=4.0, profit_factor=1.20)
    assert final_fresh_oos_gate(profitable).passed
    doc = contract_document()
    assert doc["mandatory_strategy_owners"] == []
    assert set(doc["axes"]) == set(AXES)
    print(json.dumps({"state": "PASS_STRUCTURAL_PREMIUM_V2_CONTRACT_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    emit = sub.add_parser("emit")
    emit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    row = contract_document()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": "PASS_STRUCTURAL_PREMIUM_V2_CONTRACT_EMITTED", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
