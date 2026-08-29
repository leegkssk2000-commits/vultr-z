#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import evaluate_queue

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_replacement_primitive_tournament_v1.json"
TOP5_PARALLEL = ROOT / "backend/research/rebuild/a1_top5_parallel_prospective_latest.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_top5_replacement_primitive_tournament_latest.json"
SCHEMA = "zel.a1.top5.replacement_primitive_tournament.receipt.v1"

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


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _candidate(
    *,
    candidate_id: str,
    strategy_id: str,
    family: str,
    changed_axis: str,
    features: list[dict[str, str]],
    entry_rule: str,
    max_hold_bars: int,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "mode": "NEW_ARCHITECTURE",
        "strategy_id": strategy_id,
        "architecture_family": family,
        "changed_axis": changed_axis,
        "mechanism": family,
        "payer": "preboundary_price_volume_structure",
        "entry_event": entry_rule,
        "direction_rule": "long",
        "native_horizon": f"4h_x_{max_hold_bars}_bars",
        "regime_owner": family,
        "invalidation": "development_economics_fail_or_unexecutable_spec",
        "exit_logic": "time_stop",
        "time_stop_rationale": f"frozen_primitive_horizon_{max_hold_bars}_bars",
        "turnover_cost_budget": "14_bps_per_trade_fixed",
        "required_sources": ["ohlcv", "volume"],
        "evidence_ids": ["a1_alpha_primitive_miner_v1"],
        "expected_move_cost_multiple_target": 1.0,
        "falsification": "generic evaluator fails fixed development economics gate",
        "forbidden_changes": [
            "old_failed_lane_trade_union",
            "post_result_retune",
            "threshold_sweep",
            "future_or_sealed_outcome_use",
        ],
        "why_distinct": family,
        "provider": "fixed_primitive_replacement_v1",
        "executable_spec": {
            "bar_interval": "4h",
            "features": features,
            "entry_rule": entry_rule,
            "side_rule": "long",
            "exit_rule": "time_stop",
            "max_hold_bars": max_hold_bars,
            "entry_timing": "next_bar_open",
            "cost_model": "14_bps_per_trade_fixed",
            "development_data_rule": "strictly_pre_2026-08-16T18:45:01Z",
            "parameter_provenance": "fixed_alpha_primitive_library_no_threshold_sweep",
        },
    }


def candidates() -> list[dict[str, Any]]:
    return [
        _candidate(
            candidate_id="break_replacement_breakout50_long_4h_h6_v1",
            strategy_id="break_and_continue",
            family="VOLUME_CONFIRMED_50BAR_BREAKOUT_CONTINUATION",
            changed_axis="ARCHITECTURE_REPLACEMENT_BREAKOUT50",
            features=[
                {"name": "ema20", "formula": "ema(close,20)"},
                {"name": "ema50", "formula": "ema(close,50)"},
                {"name": "highest50", "formula": "highest(high,50)"},
            ],
            entry_rule="close > lag('highest50',1) and ema20 > ema50 and vol_ratio(20) >= 1.1",
            max_hold_bars=6,
        ),
        _candidate(
            candidate_id="keltner_replacement_trend_pull_long_4h_h12_v1",
            strategy_id="keltner_trend",
            family="EMA20_RECLAIM_WITH_EMA50_TREND_OWNERSHIP",
            changed_axis="ARCHITECTURE_REPLACEMENT_TREND_PULL_RECLAIM",
            features=[
                {"name": "ema20", "formula": "ema(close,20)"},
                {"name": "ema50", "formula": "ema(close,50)"},
            ],
            entry_rule="ema20 > ema50 and lag('close',1) <= lag('ema20',1) and close > ema20",
            max_hold_bars=12,
        ),
        _candidate(
            candidate_id="supertrend_replacement_highvol_mom_long_4h_h12_v1",
            strategy_id="supertrend_pullback",
            family="HIGH_VOLATILITY_MOMENTUM_REGIME_OWNER",
            changed_axis="ARCHITECTURE_REPLACEMENT_HIGHVOL_MOMENTUM",
            features=[
                {"name": "ema20", "formula": "ema(close,20)"},
                {"name": "ema50", "formula": "ema(close,50)"},
                {"name": "ret1", "formula": "ret(1)"},
                {"name": "retstd20", "formula": "std(ret1,20)"},
            ],
            entry_rule="abs(ret1) >= 1.5 * retstd20 and ret1 > 0 and ema20 > ema50",
            max_hold_bars=12,
        ),
    ]


def _parallel_lanes(parallel: Mapping[str, Any]) -> Mapping[str, Any]:
    lanes = parallel.get("lanes")
    if not isinstance(lanes, Mapping):
        raise RuntimeError("TOP5_PARALLEL_LANES_MISSING")
    return lanes


def _validate_preconditions(contract: Mapping[str, Any], parallel: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != "zel.a1.top5.replacement_primitive_tournament.v1":
        raise RuntimeError("CONTRACT_SCHEMA_DRIFT")
    if contract.get("state") != "PREREGISTERED_DEVELOPMENT_TOURNAMENT":
        raise RuntimeError("CONTRACT_NOT_PREREGISTERED")
    data_policy = contract.get("data_policy") or {}
    if data_policy.get("development_data_only") is not True:
        raise RuntimeError("DEVELOPMENT_ONLY_REQUIRED")
    if data_policy.get("future_or_sealed_outcomes_used") is not False:
        raise RuntimeError("SEALED_OUTCOME_USE_FORBIDDEN")
    if data_policy.get("old_failed_lane_trade_union_into_child") is not False:
        raise RuntimeError("OLD_FAILED_LANE_UNION_FORBIDDEN")
    if data_policy.get("current_parallel_raw_observer_used_for_selection") is not False:
        raise RuntimeError("RAW_OBSERVER_SELECTION_FORBIDDEN")
    if data_policy.get("threshold_sweep") is not False or data_policy.get("post_result_retune") is not False:
        raise RuntimeError("RETUNE_OR_SWEEP_FORBIDDEN")
    paid = contract.get("paid_ai") or {}
    if paid.get("paid_provider_calls_allowed") is not False:
        raise RuntimeError("PAID_AI_MUST_BE_BLOCKED")

    if parallel.get("state") != "PASS_TOP5_PARALLEL_PROSPECTIVE_ACTIVE":
        raise RuntimeError("TOP5_PARALLEL_NOT_ACTIVE")
    lanes = _parallel_lanes(parallel)
    expected = {
        "break_and_continue_main": "break_and_continue",
        "keltner_trend_main": "keltner_trend",
        "supertrend_pullback_main": "supertrend_pullback",
    }
    for lane_id, strategy_id in expected.items():
        lane = lanes.get(lane_id)
        if not isinstance(lane, Mapping):
            raise RuntimeError(f"LANE_MISSING:{lane_id}")
        if lane.get("terminal_state") != "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED":
            raise RuntimeError(f"LANE_NOT_TERMINAL_FALSIFIED:{lane_id}")
        if lane.get("replacement_child_frozen") is not False:
            raise RuntimeError(f"REPLACEMENT_CHILD_ALREADY_FROZEN:{lane_id}")
        if int(lane.get("consumable_g4_T") or 0) != 0 or int(lane.get("consumable_g5_T") or 0) != 0:
            raise RuntimeError(f"OLD_T_CONSUMPTION_DRIFT:{lane_id}")
        if lane.get("old_architecture_trade_use") != "RAW_OBSERVER_ONLY_NOT_G4_OR_G5_EVIDENCE":
            raise RuntimeError(f"RAW_OBSERVER_SEMANTICS_DRIFT:{lane_id}")
        if not strategy_id:
            raise RuntimeError("UNREACHABLE")


def run(output: Path) -> dict[str, Any]:
    contract = _read(CONTRACT)
    parallel = _read(TOP5_PARALLEL)
    _validate_preconditions(contract, parallel)

    queue = candidates()
    if len(queue) != 3 or len({x["strategy_id"] for x in queue}) != 3:
        raise RuntimeError("EXACT_THREE_DISTINCT_STRATEGIES_REQUIRED")

    evaluation = evaluate_queue(queue)
    rows = evaluation.get("rows") or []
    if len(rows) != 3:
        raise RuntimeError(f"EVALUATOR_ROW_COUNT_DRIFT:{len(rows)}")

    row_by_id = {
        str(row.get("candidate_id")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    contract_by_strategy = {
        str(row.get("strategy_id")): row
        for row in (contract.get("candidate_policy") or [])
        if isinstance(row, Mapping)
    }
    queue_by_strategy = {str(row["strategy_id"]): row for row in queue}
    lane_map = {
        "break_and_continue": "break_and_continue_main",
        "keltner_trend": "keltner_trend_main",
        "supertrend_pullback": "supertrend_pullback_main",
    }
    lanes = _parallel_lanes(parallel)
    out_lanes: dict[str, Any] = {}
    for strategy_id, lane_id in lane_map.items():
        candidate = queue_by_strategy[strategy_id]
        candidate_id = str(candidate["candidate_id"])
        row = row_by_id.get(candidate_id)
        if not isinstance(row, Mapping):
            raise RuntimeError(f"EVALUATION_ROW_MISSING:{candidate_id}")
        prereg = contract_by_strategy.get(strategy_id)
        if not isinstance(prereg, Mapping) or prereg.get("candidate_id") != candidate_id:
            raise RuntimeError(f"PREREGISTRATION_MISMATCH:{strategy_id}")
        economic_pass = row.get("economic_pass") is True
        out_lanes[lane_id] = {
            "strategy_id": strategy_id,
            "terminal_state_before": lanes[lane_id].get("terminal_state"),
            "raw_observer_T": len(lanes[lane_id].get("raw_observer_closed_trade_ids") or []),
            "raw_observer_consumed_for_tournament": False,
            "candidate_id": candidate_id,
            "architecture_family": candidate.get("architecture_family"),
            "candidate_sha256": _sha(candidate),
            "evaluation": dict(row),
            "freeze_eligible": economic_pass,
            "replacement_child_frozen": False,
            "prospective_child_T": 0,
            "next": (
                "CREATE_SEPARATE_POST_RESULT_CHILD_FREEZE_CONTRACT_WITH_NEW_BOUNDARY"
                if economic_pass
                else "KEEP_TERMINAL_FALSIFIED_AND_RAW_OBSERVER_ONLY"
            ),
        }

    pass_lanes = [lane_id for lane_id, row in out_lanes.items() if row["freeze_eligible"]]
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_REPLACEMENT_PRIMITIVE_TOURNAMENT_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "top5_parallel_path": str(TOP5_PARALLEL.relative_to(ROOT)),
        "development_boundary": evaluation.get("boundary"),
        "development_only": evaluation.get("development_only") is True,
        "prospective": False,
        "cost_bps_per_trade": evaluation.get("cost_bps_per_trade"),
        "candidate_count": int(evaluation.get("candidate_count") or 0),
        "economic_pass_count": int(evaluation.get("economic_pass_count") or 0),
        "economic_fail_count": int(evaluation.get("economic_fail_count") or 0),
        "insufficient_event_count": int(evaluation.get("insufficient_event_count") or 0),
        "source_skip_count": int(evaluation.get("source_skip_count") or 0),
        "spec_reject_count": int(evaluation.get("spec_reject_count") or 0),
        "freeze_eligible_lane_count": len(pass_lanes),
        "freeze_eligible_lanes": pass_lanes,
        "automatic_child_freeze": False,
        "separate_post_result_contract_required": True,
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "old_failed_lane_trade_union": False,
        "parallel_raw_observer_selection_use": False,
        "lanes": out_lanes,
        **AUTH,
    }
    result["receipt_sha256"] = _sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    queue = candidates()
    assert len(queue) == 3
    assert len({x["strategy_id"] for x in queue}) == 3
    by = {x["strategy_id"]: x for x in queue}
    assert by["break_and_continue"]["executable_spec"]["max_hold_bars"] == 6
    assert by["keltner_trend"]["executable_spec"]["max_hold_bars"] == 12
    assert by["supertrend_pullback"]["executable_spec"]["max_hold_bars"] == 12
    for row in queue:
        assert row["provider"] == "fixed_primitive_replacement_v1"
        assert row["required_sources"] == ["ohlcv", "volume"]
        assert row["executable_spec"]["bar_interval"] == "4h"
        assert row["executable_spec"]["side_rule"] == "long"
        assert row["executable_spec"]["exit_rule"] == "time_stop"
    assert AUTH["execution_authority"] == "NONE"
    assert AUTH["order_authority"] == "BLOCKED" and AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_REPLACEMENT_PRIMITIVE_TOURNAMENT_V1_SELF_TEST")
    print("PASS_NO_PAID_PROVIDER_AND_NO_AUTOMATIC_CHILD_FREEZE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_top5_replacement_primitive_tournament_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({
        "state": result["state"],
        "candidate_count": result["candidate_count"],
        "economic_pass_count": result["economic_pass_count"],
        "freeze_eligible_lanes": result["freeze_eligible_lanes"],
        "paid_provider_calls": result["paid_provider_calls"],
        "receipt": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
