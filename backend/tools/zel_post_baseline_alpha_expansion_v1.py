from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

VERSION = "ZEL_POST_BASELINE_ALPHA_EXPANSION_V1"
EXPECTED_STAGES = [
    "A_BASELINE_DECOMPOSITION_AND_KILL_KEEP",
    "B_TIMEFRAME_ECONOMIC_BASELINES",
    "C_NEW_ARCHETYPE_INTAKE",
    "D_STRATEGY_REGIME_ROUTER",
    "E_REAL_EXECUTION_AND_FUNDING_CALIBRATION",
    "F_BASE_EDGE_ONLY_METHOD_SKILL_BOT_ABLATION",
    "G_FRESH_OOS_W4_W5",
    "H_PORTFOLIO_INTERACTION_AND_JOINT_RISK",
]


def load(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text())
    if not isinstance(row, dict):
        raise SystemExit(f"NOT_OBJECT:{path}")
    return row


def validate_design(doc: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if doc.get("schema_version") != "zel.post_baseline.alpha_expansion.v1":
        errors.append("SCHEMA")
    if doc.get("stage_order") != EXPECTED_STAGES:
        errors.append("STAGE_ORDER")
    obj = doc.get("objective") or {}
    if obj.get("primary_hard_gates") != ["net_R_improves", "win_rate_pct_improves"]:
        errors.append("PRIMARY_OBJECTIVE")
    principles = doc.get("research_principles") or {}
    if principles.get("mandatory_strategy_owner") is not False:
        errors.append("MANDATORY_OWNER_FORBIDDEN")
    if principles.get("no_trade_is_valid_output") is not True:
        errors.append("NO_TRADE_REQUIRED")
    if principles.get("entry_time_features_only") is not True:
        errors.append("ENTRY_TIME_CAUSALITY")
    if principles.get("exit_time_regime_for_entry_selection_forbidden") is not True:
        errors.append("LOOKAHEAD_GUARD")
    dep = doc.get("active_baseline_dependency") or {}
    if dep.get("required_state") != "PASS_V2_NEXT_OPEN_BASELINE_45_OF_45":
        errors.append("BASELINE_STATE")
    if dep.get("required_lane_files_total") != 45:
        errors.append("BASELINE_LANE_COUNT")
    if dep.get("must_not_modify_running_baseline") is not True:
        errors.append("BASELINE_MUTATION_GUARD")
    stages = doc.get("stages") or {}
    if set(stages) != set(EXPECTED_STAGES):
        errors.append("STAGE_SET")
    router = (stages.get("D_STRATEGY_REGIME_ROUTER") or {})
    if router.get("default") != "NO_TRADE" or router.get("entry_time_only") is not True:
        errors.append("ROUTER_DEFAULT")
    matrix = router.get("router_matrix") or {}
    if matrix.get("unknown_transition_conflict") != ["NO_TRADE"]:
        errors.append("UNKNOWN_MUST_NO_TRADE")
    portfolio = stages.get("H_PORTFOLIO_INTERACTION_AND_JOINT_RISK") or {}
    if portfolio.get("mandatory_owner") is not False:
        errors.append("PORTFOLIO_MANDATORY_OWNER")
    fresh = stages.get("G_FRESH_OOS_W4_W5") or {}
    if fresh.get("must_be_unseen_during_selection") is not True or fresh.get("selection_reuse_forbidden") is not True:
        errors.append("FRESH_OOS")
    ai = doc.get("ai_council") or {}
    if ai.get("role") != "advisory_only":
        errors.append("AI_AUTHORITY")
    auto = doc.get("automation_after_baseline") or {}
    if auto.get("auto_start_allowed") is not False or auto.get("heavy_replay_before_stage_A_complete") is not False:
        errors.append("PREMATURE_HEAVY_REPLAY")
    safety = doc.get("safety") or {}
    expected_safety = {
        "research_only": True,
        "canonical_mutation": False,
        "runtime_binding": False,
        "shadow_mutation": False,
        "paper_mutation": False,
        "live_mutation": False,
        "registry_mutation": False,
        "formal_ledger_mutation": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    for key, value in expected_safety.items():
        if safety.get(key) != value:
            errors.append(f"SAFETY:{key}")
    archetypes = ((stages.get("C_NEW_ARCHETYPE_INTAKE") or {}).get("candidate_archetypes") or [])
    ids = [str(x.get("archetype_id") or "") for x in archetypes if isinstance(x, dict)]
    if len(ids) < 4 or len(set(ids)) != len(ids):
        errors.append("ARCHETYPE_DIVERSITY")
    tf = ((stages.get("B_TIMEFRAME_ECONOMIC_BASELINES") or {}).get("timeframes") or [])
    if tf != ["1m", "5m", "15m"]:
        errors.append("TIMEFRAME_MAP")
    return {
        "state": "PASS_POST_BASELINE_ALPHA_EXPANSION_DESIGN" if not errors else "HOLD_POST_BASELINE_ALPHA_EXPANSION_DESIGN",
        "version": VERSION,
        "errors": errors,
        "stage_count": len(EXPECTED_STAGES),
        "archetype_count": len(ids),
        "heavy_replay_started": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def baseline_readiness(doc: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    design = validate_design(doc)
    if design["errors"]:
        return {**design, "baseline_ready": False}
    if report is None:
        return {**design, "state": "HOLD_WAITING_FOR_V2_45_LANE_BASELINE", "baseline_ready": False}
    dep = doc["active_baseline_dependency"]
    reasons: list[str] = []
    if report.get("state") != dep["required_state"]:
        reasons.append("BASELINE_NOT_TERMINAL_PASS")
    if int(report.get("lane_files_total") or 0) != int(dep["required_lane_files_total"]):
        reasons.append("BASELINE_LANE_COUNT_MISMATCH")
    strategies = report.get("strategies") or {}
    if set(strategies) != set(dep["strategy_universe"]):
        reasons.append("BASELINE_STRATEGY_SET_MISMATCH")
    if report.get("research_only") is not True:
        reasons.append("BASELINE_NOT_RESEARCH_ONLY")
    if report.get("execution_authority") != "NONE" or report.get("order_authority") != "BLOCKED":
        reasons.append("BASELINE_AUTHORITY_MISMATCH")
    return {
        **design,
        "state": "PASS_READY_FOR_STAGE_A_READ_ONLY_DECOMPOSITION" if not reasons else "HOLD_WAITING_FOR_VALID_V2_BASELINE",
        "baseline_ready": not reasons,
        "baseline_reasons": reasons,
        "next": "A_BASELINE_DECOMPOSITION_AND_KILL_KEEP" if not reasons else "WAIT_FOR_BASELINE",
        "heavy_replay_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", type=Path, default=Path("backend/research/zel_post_baseline_alpha_expansion_v1.json"))
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    doc = load(args.design)
    report = load(args.baseline_report) if args.baseline_report and args.baseline_report.exists() else None
    result = baseline_readiness(doc, report)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    print(text, end="")
    return 0 if result["state"].startswith("PASS_") or result["state"].startswith("HOLD_WAITING_FOR_V2_45_LANE_BASELINE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
