#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
DECISION = ROOT / "backend/research/rebuild/a1_top5_g4_donor_salvage_decision_v3.json"
BREAK_FREEZE = ROOT / "backend/research/contracts/a1_break_supertrend_mom_filter_salvage_freeze_v1.json"
SUPER_FREEZE = ROOT / "backend/research/contracts/a1_supertrend_union_veto_g5_shadow_freeze_v1.json"
BREAK_FRESH = ROOT / "backend/research/rebuild/a1_break_supertrend_mom_filter_salvage_fresh_latest.json"
OUT = ROOT / "out/a1_top5_latest_only_ssot_v1.json"


def read(path: Path, optional: bool = False) -> dict[str, Any] | None:
    if optional and not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _decision(decision: Mapping[str, Any], recipient: str, semantics: str) -> dict[str, Any]:
    for row in decision.get("decisions") or []:
        if row.get("recipient") == recipient and row.get("donor_semantics") == semantics:
            return dict(row)
    raise RuntimeError(f"DECISION_MISSING:{recipient}:{semantics}")


def sync(
    ssot: Mapping[str, Any],
    decision: Mapping[str, Any],
    break_freeze: Mapping[str, Any],
    super_freeze: Mapping[str, Any],
    break_fresh: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out = copy.deepcopy(dict(ssot))
    assert out["schema_version"] == "zel.a1.top5.latest_only_ssot.v1"
    assert out["state"] == "CURRENT_TOP5_ONLY"
    assert decision["schema_version"] == "zel.a1.top5.g4.donor_salvage.decision.v3"
    assert decision["state"] == "PASS_DONOR_SALVAGE_DECISION_FROZEN"
    assert break_freeze["schema_version"] == "zel.a1.break.supertrend_mom_filter_salvage.freeze.v1"
    assert break_freeze["state"] == "FROZEN_CONFIRMED_HISTORICAL_SALVAGE_CHILD_PRE_FRESH"
    assert super_freeze["schema_version"] == "zel.a1.supertrend.union_veto_g5_shadow.freeze.v1"
    assert super_freeze["state"] == "FROZEN_CONFIRMED_RISK_OVERLAY_FOR_G5_SHADOW_ONLY"

    break_dec = _decision(decision, "break_and_continue_main", "SUPERTREND_MOMENTUM_FILTER")
    super_union = _decision(decision, "supertrend_pullback_main", "BREAKOUT50_OR_KELTNER_RECLAIM_UNION_AS_NEGATIVE_VETO")
    super_keltner = _decision(decision, "supertrend_pullback_main", "KELTNER_RECLAIM_AS_NEGATIVE_VETO")
    assert break_dec["state"] == "CONFIRMED_HISTORICAL_SALVAGE_CANDIDATE_FRESH_REQUIRED"
    assert super_union["state"] == "CONFIRMED_RISK_FILTER_DONOR_ONLY"
    assert super_keltner["state"] == "CONFIRMED_RISK_FILTER_DONOR_ONLY"

    fresh_summary: dict[str, Any] = {
        "state": "WAIT_FRESH_COLLECTOR_FIRST_RUN",
        "fresh_T": 0,
        "minimum_fresh_T_before_gate": int(break_freeze["fresh_policy"]["minimum_fresh_T_before_formal_gate"]),
        "metrics": None,
        "receipt_sha256": None,
    }
    if break_fresh is not None:
        assert break_fresh["schema_version"] == "zel.a1.break.supertrend_mom_filter_salvage.fresh.receipt.v1"
        assert break_fresh["child_id"] == break_freeze["child_id"]
        assert break_fresh["activation_id"] == break_freeze["activation_id"]
        assert break_fresh["cohort_id"] == break_freeze["cohort_id"]
        assert int(break_fresh["historical_credit_T"]) == 0
        fresh_summary = {
            "state": break_fresh["state"],
            "fresh_T": int(break_fresh["fresh_T"]),
            "minimum_fresh_T_before_gate": int(break_fresh["minimum_fresh_T_before_gate"]),
            "metrics": break_fresh["metrics"],
            "receipt_sha256": break_fresh.get("receipt_sha256"),
        }

    out["donor_transplant_sync"] = {
        "state": "CONFIRMED_DONORS_BOUND_TO_TOP5_WITHOUT_PROMOTION",
        "source_decision_path": str(DECISION.relative_to(ROOT)),
        "break_salvage_freeze_path": str(BREAK_FREEZE.relative_to(ROOT)),
        "supertrend_g5_overlay_freeze_path": str(SUPER_FREEZE.relative_to(ROOT)),
        "break_fresh_collector_path": str(BREAK_FRESH.relative_to(ROOT)),
        "primary_deferred": bool(decision.get("primary_deferred", True)),
        "bound_recipient_count": 2,
        "formal_g4_credit": 0,
        "formal_g5_credit": 0,
        "promotion_authority": False,
    }

    lanes = {str(x.get("lane_id")): x for x in out.get("top5") or []}
    if set(("break_and_continue_main", "keltner_trend_main", "supertrend_pullback_main")) - set(lanes):
        raise RuntimeError("TOP5_RECIPIENT_LANE_MISSING")

    br = lanes["break_and_continue_main"]
    br["transplant_role"] = "CONFIRMED_SALVAGE_CHILD_BOUND_PARALLEL_FRESH"
    br["salvage_child"] = {
        "state": break_freeze["state"],
        "child_id": break_freeze["child_id"],
        "parent_child_id": break_freeze["parent_child_id"],
        "activation_id": break_freeze["activation_id"],
        "cohort_id": break_freeze["cohort_id"],
        "prospective_boundary": break_freeze["prospective_boundary"],
        "symbol_universe": break_freeze["symbol_universe"],
        "entry_semantics": break_freeze["entry_semantics"],
        "exit_semantics": break_freeze["exit_semantics"],
        "cost_model": break_freeze["cost_model"],
        "historical_confirmation": break_freeze["historical_confirmation"],
        "fresh_policy": break_freeze["fresh_policy"],
        "fresh_collector": fresh_summary,
        "historical_is_not_formal_g4_pass": True,
        "historical_is_not_formal_g5_pass": True,
        "roadmap_blocking": False,
        "selection_authority": False,
        "promotion_authority": False,
    }
    br["donor_exports"] = {
        "to_supertrend_g5_shadow": {
            "component": "BREAKOUT50_STANDALONE_NEGATIVE_VETO",
            "state": "KEEP_ONLY_AS_INCREMENTAL_COMPONENT_OF_UNION_VETO",
        }
    }

    kt = lanes["keltner_trend_main"]
    kt["donor_exports"] = {
        "to_supertrend_g5_shadow": {
            "component": "KELTNER_RECLAIM_AS_NEGATIVE_VETO",
            "state": "CONFIRMED_RISK_FILTER_DONOR_ONLY",
            "historical_9m": super_freeze["backup_overlay"]["historical_9m"],
        }
    }

    st = lanes["supertrend_pullback_main"]
    st["transplant_role"] = "G5_SHADOW_RISK_OVERLAY_BOUND_PARENT_UNCHANGED"
    st["g5_risk_overlay"] = {
        "state": super_freeze["state"],
        "selected": super_freeze["selected_overlay"],
        "backup": super_freeze["backup_overlay"],
        "component_policy": super_freeze["component_policy"],
        "shadow_policy": super_freeze["shadow_policy"],
        "parent_terminal_state_unchanged": True,
        "formal_g4_credit": 0,
        "formal_g5_credit": 0,
        "selection_authority": False,
        "promotion_authority": False,
    }

    rules = out.setdefault("reporting_rules", {})
    rules["confirmed_historical_salvage_must_not_be_reported_as_formal_g4_pass"] = True
    rules["confirmed_risk_overlay_is_g5_shadow_only"] = True
    rules["fresh_failure_invalidates_break_historical_salvage_candidate"] = True
    rules["top5_parent_metrics_and_terminal_states_remain_controls_until_fresh_gate"] = True
    out["selection_authority"] = False
    out["promotion_authority"] = False
    out["execution_authority"] = "NONE"
    out["order_authority"] = "BLOCKED"
    out["live_trade_authority"] = "BLOCKED"
    return out


def self_test() -> int:
    assert BREAK_FREEZE.name.endswith("salvage_freeze_v1.json")
    assert SUPER_FREEZE.name.endswith("g5_shadow_freeze_v1.json")
    print("PASS_TOP5_TRANSPLANT_BIND_SYNC_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssot", type=Path, default=SSOT)
    ap.add_argument("--decision", type=Path, default=DECISION)
    ap.add_argument("--break-freeze", type=Path, default=BREAK_FREEZE)
    ap.add_argument("--super-freeze", type=Path, default=SUPER_FREEZE)
    ap.add_argument("--break-fresh", type=Path, default=BREAK_FRESH)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = sync(
        read(args.ssot),
        read(args.decision),
        read(args.break_freeze),
        read(args.super_freeze),
        read(args.break_fresh, optional=True),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=False, allow_nan=False) + "\n", encoding="utf-8")
    lanes = {x["lane_id"]: x for x in result["top5"]}
    print(json.dumps({
        "state": result["donor_transplant_sync"]["state"],
        "break_child": lanes["break_and_continue_main"]["salvage_child"]["child_id"],
        "break_fresh_T": lanes["break_and_continue_main"]["salvage_child"]["fresh_collector"]["fresh_T"],
        "supertrend_overlay": lanes["supertrend_pullback_main"]["g5_risk_overlay"]["selected"]["overlay_id"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
