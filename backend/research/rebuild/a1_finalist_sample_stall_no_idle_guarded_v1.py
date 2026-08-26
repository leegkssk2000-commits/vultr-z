#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research import production_economic_guard_v1 as guard
from backend.research.rebuild import a1_finalist_sample_stall_no_idle_router_v1 as base

SCHEMA = "zel.a1.finalist.sample_stall.no_idle.guarded.v1"
_BASE_COMPARISON = base.comparison
TERMINAL_CHILD_STATE = "REJECT_CHILD_PRODUCTION_ECONOMICS"
TERMINAL_CHILD_NEXT = "PRESERVE_INCUMBENT_STOP_FAILED_CHILD_AND_ROTATE_DISTINCT_MECHANISM"


def _guarded_comparison(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(_BASE_COMPARISON(parent, child))
    verdict = guard.evaluate(parent, child)
    result["production_economic_guard"] = verdict
    result["pre_guard_development_prereg_eligible"] = bool(result.get("development_prereg_eligible"))
    result["development_prereg_eligible"] = bool(result.get("development_prereg_eligible") and verdict["pass"])
    result["incumbent_state_action"] = verdict["incumbent_state_action"]
    result["fresh25_state_action"] = verdict["fresh25_state_action"]
    return result


def _terminalize(row: dict[str, Any], verdict: Mapping[str, Any], *, source: str) -> None:
    row["pre_guard_state"] = row.get("state")
    row["pre_guard_next"] = row.get("next")
    row["state"] = TERMINAL_CHILD_STATE
    row["next"] = TERMINAL_CHILD_NEXT
    row["production_child_terminal_reject"] = True
    row["production_child_reject_source"] = source
    row["production_economic_guard"] = dict(verdict)
    row["incumbent_mutated"] = False
    row["restart_from_zero"] = False


def _comparison_verdict(comp: Mapping[str, Any]) -> dict[str, Any] | None:
    existing = comp.get("production_economic_guard")
    if isinstance(existing, Mapping):
        return dict(existing)
    parent = comp.get("parent")
    child = comp.get("child")
    if isinstance(parent, Mapping) and isinstance(child, Mapping):
        return guard.evaluate(parent, child)
    return None


def _apply_row_guard(row: dict[str, Any], *, prior_receipt: bool = False) -> dict[str, Any]:
    comp = row.get("sample_expansion_comparison")
    if isinstance(comp, Mapping):
        verdict = _comparison_verdict(comp)
        if verdict is not None:
            comp2 = dict(comp)
            comp2["production_economic_guard"] = verdict
            comp2["pre_guard_development_prereg_eligible"] = bool(comp2.get("development_prereg_eligible"))
            comp2["development_prereg_eligible"] = bool(comp2.get("development_prereg_eligible") and verdict["pass"])
            row["sample_expansion_comparison"] = comp2
            if verdict.get("hard_fail") is True:
                _terminalize(
                    row,
                    verdict,
                    source="PRIOR_RECEIPT_SAME_BOUNDARY_PARENT_CHILD" if prior_receipt else "SAME_BOUNDARY_PARENT_CHILD_COMPARISON",
                )
                return row

    child_fresh = row.get("child_fresh")
    if isinstance(child_fresh, Mapping):
        verdict = guard.evaluate(None, child_fresh)
        child2 = dict(child_fresh)
        child2["production_economic_guard"] = verdict
        row["child_fresh"] = child2
        if verdict["hard_fail"]:
            _terminalize(
                row,
                verdict,
                source="PRIOR_RECEIPT_FROZEN_CHILD_ECONOMIC_FLOOR" if prior_receipt else "FROZEN_CHILD_STANDALONE_ECONOMIC_FLOOR",
            )
    return row


def _prior_terminal_rows() -> dict[str, dict[str, Any]]:
    if not base.LATEST.exists():
        return {}
    previous = base.read(base.LATEST)
    out: dict[str, dict[str, Any]] = {}
    for raw in previous.get("targets") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        if not sid:
            continue
        row = _apply_row_guard(dict(raw), prior_receipt=True)
        if row.get("production_child_terminal_reject") is not True:
            continue
        row["state"] = TERMINAL_CHILD_STATE
        row["next"] = TERMINAL_CHILD_NEXT
        row["mode"] = "TERMINAL_REJECTED_CHILD_PRESERVED_NO_REPLAY"
        row["incumbent_mutated"] = False
        row["restart_from_zero"] = False
        out[sid] = row
    return out


def _recompute_counts(result: dict[str, Any]) -> None:
    targets = [x for x in result.get("targets") or [] if isinstance(x, Mapping)]
    active = [x for x in targets if x.get("production_child_terminal_reject") is not True]
    result["frozen_child_count"] = sum(bool(x.get("frozen_child_fresh_boundary_utc")) for x in active)
    result["fresh25_ready_count"] = sum(x.get("state") == "READY_CHILD_FRESH_25_FOR_IDENTITY_HARDENING" for x in active)
    result["loss_cluster_routed_count"] = sum(x.get("state") == "ROUTE_EXISTING_LOSS_CLUSTER_REPAIR" for x in active)
    result["sample_stall_hold_count"] = sum(x.get("state") == "HOLD_SAMPLE_EXPANSION_CHILD_NOT_PARETO_USEFUL" for x in active)
    result["production_child_terminal_reject_count"] = sum(x.get("production_child_terminal_reject") is True for x in targets)
    result["production_child_terminal_reject_ids"] = sorted(
        str(x.get("strategy_id")) for x in targets if x.get("production_child_terminal_reject") is True
    )


def run(out: Path) -> dict[str, Any]:
    prior_terminal = _prior_terminal_rows()
    original_comparison = base.comparison
    original_targets = base.TARGETS

    # Fail-closed from already-produced evidence first. Known failed children do
    # not consume another full replay just to reach the same economic verdict.
    base.TARGETS = {sid: spec for sid, spec in original_targets.items() if sid not in prior_terminal}
    try:
        base.comparison = _guarded_comparison
        result = dict(base.run(out))
    finally:
        base.comparison = original_comparison
        base.TARGETS = original_targets

    current = {
        str(row.get("strategy_id")): _apply_row_guard(dict(row))
        for row in result.get("targets") or []
        if isinstance(row, Mapping) and row.get("strategy_id")
    }
    current.update({sid: row for sid, row in prior_terminal.items() if sid not in current})
    result["targets"] = [current[sid] for sid in original_targets if sid in current]

    result["schema_version"] = SCHEMA
    result["production_economic_guard_enabled"] = True
    result["production_economic_guard_rules"] = [
        "ZERO_TRADE_CHILD_HARD_FAIL",
        "TRADE_COUNT_DECREASE_HARD_FAIL",
        "NEGATIVE_CHILD_ECONOMICS_HARD_FAIL",
        "ZERO_TRADE_DD_IMPROVEMENT_INVALID",
        "PNL_AND_EXPECTANCY_BOTH_WORSE_HARD_FAIL",
        "FAILED_FROZEN_CHILD_STOPS_FRESH25_COLLECTION",
        "KNOWN_FAILED_CHILD_TERMINALIZED_FROM_PRIOR_RECEIPT_BEFORE_REPLAY",
        "FAILED_FIXED_CHILD_NOT_REPLAYED_NEXT_RUN",
        "REJECT_PRESERVES_INCUMBENT_AND_FRESH25_STATE",
    ]
    result["incumbent_collectors_continue_on_child_reject"] = True
    result["fresh25_reset_on_child_reject"] = False
    result["failed_child_replay_allowed"] = False
    result["known_failed_child_replay_skipped_count"] = len(prior_terminal)
    result["challenger_slot_policy"] = "ONE_FIXED_CHILD_PER_STRATEGY;TERMINAL_REJECT_BEFORE_DISTINCT_REPLACEMENT"
    _recompute_counts(result)
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = base.stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    parent = {"completed_trades": 9, "net_pnl_bps": 900.0, "net_expectancy_bps": 100.0, "max_drawdown_bps": 300.0}
    zero = {"completed_trades": 0, "net_pnl_bps": 0.0, "net_expectancy_bps": None, "max_drawdown_bps": 0.0}
    comp = _guarded_comparison(parent, zero)
    assert comp["development_prereg_eligible"] is False
    assert comp["production_economic_guard"]["hard_fail"] is True
    assert comp["production_economic_guard"]["zero_trade_dd_improvement_invalid"] is True

    prior_trade_drop = _apply_row_guard({
        "strategy_id": "supertrend_pullback",
        "state": "HOLD_SAMPLE_EXPANSION_CHILD_NOT_PARETO_USEFUL",
        "sample_expansion_comparison": {
            "parent": {"trades": 9, "net_pnl_bps": 900.0, "net_expectancy_bps": 100.0},
            "child": {"trades": 7, "net_pnl_bps": 800.0, "net_expectancy_bps": 90.0},
            "development_prereg_eligible": False,
        },
        "incumbent_mutated": False,
    }, prior_receipt=True)
    assert prior_trade_drop["state"] == TERMINAL_CHILD_STATE
    assert prior_trade_drop["production_child_reject_source"] == "PRIOR_RECEIPT_SAME_BOUNDARY_PARENT_CHILD"

    frozen_zero = _apply_row_guard({
        "strategy_id": "trend_ma_macd",
        "state": "COLLECT_CHILD_FRESH_TO_25",
        "next": "CONTINUE_HOURLY_CHILD_FRESH_COLLECTION",
        "child_fresh": zero,
        "incumbent_mutated": False,
    })
    assert frozen_zero["state"] == TERMINAL_CHILD_STATE and frozen_zero["restart_from_zero"] is False

    frozen_negative = _apply_row_guard({
        "strategy_id": "break_and_continue",
        "state": "COLLECT_CHILD_FRESH_TO_25",
        "child_fresh": {"completed_trades": 3, "net_pnl_bps": -380.0, "net_expectancy_bps": -126.0},
        "incumbent_mutated": False,
    })
    assert frozen_negative["state"] == TERMINAL_CHILD_STATE
    assert "NEGATIVE_CHILD_ECONOMICS" in frozen_negative["production_economic_guard"]["reasons"]

    print("PASS_A1_FINALIST_NO_IDLE_PRODUCTION_GUARD_V1_SELF_TEST")
    print("PASS_KNOWN_FAILED_CHILD_TERMINALIZES_FROM_PRIOR_RECEIPT_NO_REPLAY")
    print("PASS_FAILED_FROZEN_CHILD_STOPS_FRESH25_AND_PRESERVES_INCUMBENT")
    print("PASS_GUARDED_COMPARISON_CALLS_CAPTURED_UPSTREAM_WITHOUT_RECURSION")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_sample_stall_no_idle_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result.get("state"),
        "guard": result.get("production_economic_guard_enabled"),
        "skipped_known_failed_replays": result.get("known_failed_child_replay_skipped_count"),
        "terminal_rejects": result.get("production_child_terminal_reject_ids"),
        "routes": {x["strategy_id"]: x["state"] for x in result.get("targets", [])},
        "receipt": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
