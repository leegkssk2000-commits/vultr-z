from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGET_CLOSED_COUNT = 100


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def run(args: argparse.Namespace) -> int:
    activation = load_json(args.activation, {})
    trigger = load_json(args.trigger_status, {})
    projection = load_json(args.projection_status, {})
    pair = load_json(args.pair_status, {})
    risk = load_json(args.risk_status, {})
    scoreboard = load_json(args.scoreboard_status, {})

    inputs = {
        "skill_trigger_lineage": trigger,
        "six_profile_projection": projection,
        "future_pair_join": pair,
        "risk_scenario_grid": risk,
        "method_scoreboard": scoreboard,
    }
    issues: list[dict[str, Any]] = []
    for name, payload in inputs.items():
        if payload.get("state") != "PASS":
            issues.append({"code": "UPSTREAM_NOT_PASS", "severity": "C", "detail": name})
        if payload.get("observer_only") is not True:
            issues.append({"code": "UPSTREAM_NOT_OBSERVER_ONLY", "severity": "C", "detail": name})
        if payload.get("formal_ledger_modified") is not False:
            issues.append({"code": "UPSTREAM_LEDGER_MUTATION_FLAG", "severity": "C", "detail": name})

    if projection.get("profile_count") != 6:
        issues.append({"code": "PROFILE_COUNT_MISMATCH", "severity": "C", "detail": str(projection.get("profile_count"))})
    if risk.get("scenario_count") != 12:
        issues.append({"code": "RISK_SCENARIO_COUNT_MISMATCH", "severity": "C", "detail": str(risk.get("scenario_count"))})
    if scoreboard.get("method_count") != 6:
        issues.append({"code": "METHOD_COUNT_MISMATCH", "severity": "C", "detail": str(scoreboard.get("method_count"))})

    closed_count = jsonl_count(args.formal_ledger)
    baseline = int(activation.get("baseline_ledger_rows") or 0)
    post_activation_closed_count = max(0, closed_count - baseline)
    remaining = max(0, TARGET_CLOSED_COUNT - closed_count)
    reached = closed_count >= TARGET_CLOSED_COUNT
    critical = any(row.get("severity") == "C" for row in issues)

    if critical:
        state = "HOLD"
        verdict = "EXACT25_100C_CHECKPOINT_CRITICAL_UPSTREAM_GAP"
    elif not reached:
        state = "PASS"
        verdict = "EXACT25_100C_CHECKPOINT_ARMED_ACCUMULATING"
    else:
        state = "PASS"
        verdict = "EXACT25_100C_REACHED_DEEP_AUDIT_REQUIRED"

    trigger_count = int(trigger.get("skill_triggered_count") or 0)
    blocked_count = int(trigger.get("skill_blocked_count") or 0)
    outcome_count = int(trigger.get("close_outcome_joined_count") or 0)
    exact_pair_count = int(pair.get("exact_pair_count") or 0)

    report = {
        "schema": "q4r3_exact25_100c_checkpoint_status_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "target_closed_count": TARGET_CLOSED_COUNT,
        "current_closed_count": closed_count,
        "remaining_closed_count": remaining,
        "checkpoint_reached": reached,
        "activation_baseline_ledger_rows": baseline,
        "post_activation_closed_count": post_activation_closed_count,
        "skill_triggered_count": trigger_count,
        "skill_blocked_count": blocked_count,
        "close_outcome_joined_count": outcome_count,
        "exact_pair_count": exact_pair_count,
        "method_count": scoreboard.get("method_count"),
        "profile_count": projection.get("profile_count"),
        "risk_scenario_count": risk.get("scenario_count"),
        "deep_audit_dimensions": [
            "source_parity_and_contamination",
            "strategy_and_method_performance",
            "skill_trigger_block_outcome_coverage",
            "third_vs_fourth_delta",
            "bad_context_filter_and_cooldown",
            "short_restriction",
            "fee_slippage_funding_market_impact",
            "mfe_mae_hold_time",
            "dd_exposure_regime_side_symbol_session",
            "a_c_mirror_and_display_integrity",
            "zbot_family_cost_and_interaction",
            "pre_200c_fix_queue",
        ],
        "deep_audit_enabled": False,
        "ranking_enabled": False,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "historical_backfill_performed": False,
        "observer_only": True,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "violation_count": len(issues),
        "violation_severity": "C" if critical else None,
        "action": "hold",
    }
    violations = {
        "schema": "q4r3_exact25_100c_checkpoint_violations_v1",
        "generated_at": now_iso(),
        "state": "VIOLATION" if issues else "CLEAR",
        "count": len(issues),
        "severity": "C" if critical else None,
        "notify": critical,
        "violations": issues,
        "action": "hold",
    }
    atomic_json(args.status, report)
    atomic_json(args.violations, violations)
    return 0 if state == "PASS" else 2


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--formal-ledger", type=Path, required=True)
    p.add_argument("--activation", type=Path, required=True)
    p.add_argument("--trigger-status", type=Path, required=True)
    p.add_argument("--projection-status", type=Path, required=True)
    p.add_argument("--pair-status", type=Path, required=True)
    p.add_argument("--risk-status", type=Path, required=True)
    p.add_argument("--scoreboard-status", type=Path, required=True)
    p.add_argument("--status", type=Path, required=True)
    p.add_argument("--violations", type=Path, required=True)
    return p


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
