#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as econ

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_break_atr_nonexpanding_breakout_challenger_v1.json"
BASELINE_LOCK = ROOT / "backend/research/contracts/a1_break_atr_nonexpanding_breakout_baseline_lock_v1.json"
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_break_atr_nonexpanding_breakout_challenger_latest.json"
SCHEMA = "zel.a1.break.atr_nonexpanding_breakout_challenger.receipt.v1"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def candidate(contract: Mapping[str, Any]) -> dict[str, Any]:
    arch = contract["architecture"]
    spec = {
        "bar_interval": arch["bar_interval"],
        "features": arch["features"],
        "entry_rule": arch["entry_rule"],
        "side_rule": arch["side_rule"],
        "exit_rule": arch["exit_rule"],
        "max_hold_bars": arch["max_hold_bars"],
        "entry_timing": arch["entry_timing"],
        "cost_model": "20_bps_per_trade_fixed",
        "development_data_rule": "strictly_pre_2026-08-16T18:45:01Z",
        "parameter_provenance": "pre_result_contract_no_threshold_sweep",
    }
    return {
        "candidate_id": arch["challenger_id"],
        "mode": "NEW_ARCHITECTURE",
        "strategy_id": "break_and_continue",
        "architecture_family": arch["family"],
        "changed_axis": arch["changed_axis"],
        "mechanism": arch["family"],
        "payer": "preboundary_price_volume_volatility_structure",
        "entry_event": arch["entry_rule"],
        "direction_rule": "long",
        "native_horizon": "4h_x_6_bars",
        "regime_owner": "ATR_PCT_NONEXPANSION_ON_BREAKOUT",
        "invalidation": "development_economics_fail_or_no_quality_improvement",
        "exit_logic": "time_stop",
        "time_stop_rationale": "inherited_break_replacement_horizon_6_bars",
        "turnover_cost_budget": "20_bps_per_trade_fixed",
        "required_sources": ["ohlcv", "volume"],
        "evidence_ids": ["break_native_preentry_attribution_atr_pct", "break_replacement_breakout50_v2"],
        "expected_move_cost_multiple_target": 1.0,
        "falsification": "fixed development economics or locked baseline-improvement gate fails",
        "forbidden_changes": [
            "numeric_atr_cutoff_from_outcomes",
            "threshold_sweep",
            "post_result_retune",
            "future_or_sealed_outcome_use",
        ],
        "why_distinct": "existing Break breakout replacement plus independently preserved ATR_PCT non-expansion state",
        "provider": "deterministic_causal_repair_v1",
        "executable_spec": spec,
    }


def validate_pre_result(contract: Mapping[str, Any], baseline: Mapping[str, Any], freeze: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != "zel.a1.break.atr_nonexpanding_breakout_challenger.contract.v1":
        raise RuntimeError("CONTRACT_SCHEMA_DRIFT")
    if contract.get("state") != "PREREGISTERED_DEVELOPMENT_REPLAY_BEFORE_RESULT":
        raise RuntimeError("CONTRACT_NOT_PREREGISTERED")
    root = contract.get("root_evidence") or {}
    if root.get("axis") != "ATR_PCT" or root.get("qualitative_seed_only") is not True or root.get("numeric_cutoff_from_outcomes_forbidden") is not True:
        raise RuntimeError("ATR_ROOT_EVIDENCE_DRIFT")
    policy = contract.get("development_policy") or {}
    if policy.get("threshold_sweep") is not False or policy.get("post_result_retune") is not False or int(policy.get("paid_ai_calls") or 0) != 0:
        raise RuntimeError("DEVELOPMENT_POLICY_DRIFT")
    if float(policy.get("fixed_cost_bps_per_trade") or 0.0) != 20.0:
        raise RuntimeError("COST_POLICY_DRIFT")
    if baseline.get("state") != "LOCKED_BEFORE_CHALLENGER_RESULT":
        raise RuntimeError("BASELINE_NOT_PRELOCKED")
    if baseline.get("baseline_child_id") != "break_replacement_breakout50_long_4h_h6_v2":
        raise RuntimeError("BASELINE_CHILD_DRIFT")
    children = [x for x in freeze.get("children") or [] if isinstance(x, Mapping) and x.get("lane_id") == "break_and_continue_main"]
    if len(children) != 1:
        raise RuntimeError("BREAK_V2_BASELINE_REQUIRED")
    child = children[0]
    locked = baseline["baseline_metrics"]
    current = child["development_metrics_at_20bps"]
    for key in ("trades", "net_expectancy_bps", "net_pnl_bps", "profit_factor", "win_rate", "drawdown_bps"):
        if abs(float(locked[key]) - float(current[key])) > 1e-9:
            raise RuntimeError(f"BASELINE_METRIC_DRIFT:{key}")
    arch = contract["architecture"]
    if tuple(arch["symbol_universe"]) != tuple(baseline["comparable_conditions"]["symbol_universe"]):
        raise RuntimeError("SYMBOL_UNIVERSE_DRIFT")
    if "atr_pct <= lag('atr_pct',1)" not in str(arch["entry_rule"]):
        raise RuntimeError("ATR_NONEXPANSION_RULE_DRIFT")


def run(output: Path) -> dict[str, Any]:
    contract = read(CONTRACT)
    baseline = read(BASELINE_LOCK)
    freeze = read(V2_FREEZE)
    validate_pre_result(contract, baseline, freeze)

    old_cost, old_symbols, old_boundary = econ.COST_BPS, econ.SYMBOLS, econ.BOUNDARY
    try:
        econ.COST_BPS = float(contract["development_policy"]["fixed_cost_bps_per_trade"])
        econ.SYMBOLS = tuple(contract["architecture"]["symbol_universe"])
        econ.BOUNDARY = str(contract["development_policy"]["boundary_utc"])
        evaluation = econ.evaluate_queue([candidate(contract)])
    finally:
        econ.COST_BPS, econ.SYMBOLS, econ.BOUNDARY = old_cost, old_symbols, old_boundary

    rows = evaluation.get("rows") or []
    if len(rows) != 1:
        raise RuntimeError(f"EVALUATOR_ROW_COUNT_DRIFT:{len(rows)}")
    row = dict(rows[0])
    if int(evaluation.get("source_skip_count") or 0) != 0 or int(evaluation.get("spec_reject_count") or 0) != 0:
        raise RuntimeError("SOURCE_OR_SPEC_REJECTED")
    if abs(float(evaluation.get("cost_bps_per_trade") or 0.0) - 20.0) > 1e-12:
        raise RuntimeError("EVALUATOR_COST_DRIFT")
    source = row.get("source_summary") or {}
    expected_symbols = set(contract["architecture"]["symbol_universe"])
    if set(source) != expected_symbols:
        raise RuntimeError(f"EVALUATOR_SYMBOL_SET_DRIFT:{sorted(source)}")

    metrics = row.get("metrics") or {}
    base = baseline["baseline_metrics"]
    improvements = {
        "net_expectancy_bps": metrics.get("net_expectancy_bps") is not None and float(metrics["net_expectancy_bps"]) > float(base["net_expectancy_bps"]),
        "profit_factor": metrics.get("profit_factor") is not None and float(metrics["profit_factor"]) > float(base["profit_factor"]),
        "drawdown_bps": metrics.get("drawdown_bps") is not None and float(metrics["drawdown_bps"]) < float(base["drawdown_bps"]),
    }
    quality_improvement = any(improvements.values())
    generic_pass = bool(row.get("economic_pass"))
    final_pass = generic_pass and quality_improvement
    deltas = {
        "trades": int(metrics.get("trades") or 0) - int(base["trades"]),
        "net_expectancy_bps": None if metrics.get("net_expectancy_bps") is None else float(metrics["net_expectancy_bps"]) - float(base["net_expectancy_bps"]),
        "net_pnl_bps": float(metrics.get("net_pnl_bps") or 0.0) - float(base["net_pnl_bps"]),
        "profit_factor": None if metrics.get("profit_factor") is None else float(metrics["profit_factor"]) - float(base["profit_factor"]),
        "win_rate": None if metrics.get("win_rate") is None else float(metrics["win_rate"]) - float(base["win_rate"]),
        "drawdown_bps": None if metrics.get("drawdown_bps") is None else float(metrics["drawdown_bps"]) - float(base["drawdown_bps"]),
    }
    state = "PASS_DEVELOPMENT_ELIGIBLE_FOR_NEW_G4_CHALLENGER" if final_pass else "FALSIFIED_ATR_NONEXPANDING_V1"
    deterministic = {
        "contract_sha256": file_sha(CONTRACT),
        "baseline_lock_sha256": file_sha(BASELINE_LOCK),
        "v2_freeze_sha256": file_sha(V2_FREEZE),
        "evaluation": evaluation,
        "improvements": improvements,
        "deltas": deltas,
        "final_pass": final_pass,
    }
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_master_sha": git_head(),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": file_sha(CONTRACT),
        "baseline_lock_path": str(BASELINE_LOCK.relative_to(ROOT)),
        "baseline_lock_sha256": file_sha(BASELINE_LOCK),
        "v2_freeze_path": str(V2_FREEZE.relative_to(ROOT)),
        "v2_freeze_sha256": file_sha(V2_FREEZE),
        "challenger_id": contract["architecture"]["challenger_id"],
        "generic_development_economic_pass": generic_pass,
        "baseline_quality_improvement_pass": quality_improvement,
        "quality_improvements": improvements,
        "baseline_metrics": base,
        "metrics": metrics,
        "delta_vs_break_v2": deltas,
        "evaluation_state": row.get("state"),
        "source_summary": source,
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "historical_seed_credit_to_g4_T": 0,
        "development_T_credit_to_g4": 0,
        "fresh_g4_T": 0,
        "new_g4_activation_created": False,
        "new_g4_cohort_created": False,
        "next": "FREEZE_NEW_G4_CHALLENGER_WITH_FRESH_BOUNDARY" if final_pass else "STOP_ATR_NONEXPANDING_V1_WITHOUT_POST_RESULT_RETUNE",
        "deterministic_result_sha256": stable(deterministic),
        **AUTH,
    }
    receipt = dict(result)
    receipt.pop("observed_at_utc", None)
    receipt.pop("source_master_sha", None)
    result["receipt_sha256"] = stable(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = read(CONTRACT)
    assert c["root_evidence"]["axis"] == "ATR_PCT"
    assert c["root_evidence"]["numeric_cutoff_from_outcomes_forbidden"] is True
    assert c["architecture"]["entry_rule"].endswith("atr_pct <= lag('atr_pct',1)")
    assert len(c["architecture"]["symbol_universe"]) == 7
    b = read(BASELINE_LOCK)
    assert b["state"] == "LOCKED_BEFORE_CHALLENGER_RESULT"
    assert b["challenger_acceptance"]["post_result_rule_change"] is False
    print("PASS_A1_BREAK_ATR_NONEXPANDING_CHALLENGER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_atr_nonexpanding_breakout_challenger_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "generic_pass": result["generic_development_economic_pass"],
        "quality_improvement": result["baseline_quality_improvement_pass"],
        "metrics": result["metrics"],
        "delta_vs_break_v2": result["delta_vs_break_v2"],
        "quality_improvements": result["quality_improvements"],
        "deterministic_result_sha256": result["deterministic_result_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
