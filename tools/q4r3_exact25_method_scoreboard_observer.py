from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

METHODS = (
    "scalp_first/revert",
    "scalp_first/continuation",
    "scalp_first/liquidity_reclaim",
    "intraday/breakout_probe",
    "intraday/rescue",
    "tactical_swing/continuation",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def fnum(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def ratio(numerator: Any, denominator: Any) -> float | None:
    left = fnum(numerator)
    right = fnum(denominator)
    if left is None or right is None or right == 0:
        return None
    return round(left / right, 8)


def build_scoreboard(projection: dict[str, Any], risk_grid: dict[str, Any]) -> list[dict[str, Any]]:
    projection_rows = {
        str(row.get("method_id")): row
        for row in projection.get("rows", [])
        if isinstance(row, dict) and row.get("method_id")
    }
    scenario_count = int(risk_grid.get("scenario_count") or 0)
    exact_pair_count = int(risk_grid.get("exact_pair_count") or 0)
    risk_context_ready = bool(
        scenario_count == 12
        and exact_pair_count > 0
        and not risk_grid.get("missing_risk_fields")
    )

    rows: list[dict[str, Any]] = []
    for method_id in METHODS:
        source = projection_rows.get(method_id, {})
        trigger_count = int(source.get("trigger_count") or 0)
        outcome_count = int(source.get("outcome_join_count") or 0)
        if trigger_count == 0:
            evidence_state = "WAITING_FORWARD_TRIGGER"
        elif outcome_count == 0:
            evidence_state = "WAITING_CLOSE_OUTCOME"
        elif not risk_context_ready:
            evidence_state = "WAITING_COMPLETE_RISK_CONTEXT"
        else:
            evidence_state = "FORWARD_EVIDENCE_ACTIVE"

        rows.append({
            "method_id": method_id,
            "evidence_state": evidence_state,
            "trigger_count": trigger_count,
            "blocked_count": int(source.get("blocked_count") or 0),
            "outcome_join_count": outcome_count,
            "unique_position_count": int(source.get("unique_position_count") or 0),
            "strategy_ids": list(source.get("strategy_ids") or []),
            "skill_ids": list(source.get("skill_ids") or []),
            "net_r": fnum(source.get("net_r")),
            "avg_r": fnum(source.get("avg_r")),
            "positive_rate_pct": fnum(source.get("positive_rate_pct")),
            "profit_factor": fnum(source.get("profit_factor")),
            "max_drawdown_r": fnum(source.get("max_drawdown_r")),
            "avg_fee_bps": fnum(source.get("avg_fee_bps")),
            "avg_slippage_bps": fnum(source.get("avg_slippage_bps")),
            "avg_mfe_r": fnum(source.get("avg_mfe_r")),
            "avg_mae_r": fnum(source.get("avg_mae_r")),
            "avg_hold_min": fnum(source.get("avg_hold_min")),
            "return_to_drawdown_ratio": ratio(source.get("net_r"), source.get("max_drawdown_r")),
            "mfe_capture_ratio": ratio(source.get("avg_r"), source.get("avg_mfe_r")),
            "risk_grid_scenario_count": scenario_count,
            "risk_grid_exact_pair_count": exact_pair_count,
            "risk_context_ready": risk_context_ready,
            "comparison_eligible": False,
            "rank": None,
            "promotion_enabled": False,
            "action": "hold",
        })
    return rows


def run(args: argparse.Namespace) -> int:
    projection_status = load_json(args.projection_status, {})
    projection = load_json(args.projection, {})
    risk_status = load_json(args.risk_status, {})
    risk_grid = load_json(args.risk_grid, {})
    pair_status = load_json(args.pair_status, {})

    issues: list[dict[str, Any]] = []
    if projection_status.get("state") != "PASS" or projection_status.get("profile_count") != 6:
        issues.append({"code": "SIX_PROFILE_PROJECTION_NOT_HEALTHY", "severity": "C", "detail": str(projection_status.get("verdict"))})
    if risk_status.get("state") != "PASS" or risk_status.get("scenario_count") != 12:
        issues.append({"code": "RISK_SCENARIO_GRID_NOT_HEALTHY", "severity": "C", "detail": str(risk_status.get("verdict"))})
    if pair_status.get("state") != "PASS" or pair_status.get("observer_only") is not True:
        issues.append({"code": "FUTURE_PAIR_JOIN_NOT_HEALTHY", "severity": "C", "detail": str(pair_status.get("verdict"))})

    rows = build_scoreboard(projection, risk_grid)
    if len(rows) != 6:
        issues.append({"code": "METHOD_COUNT_MISMATCH", "severity": "C", "detail": str(len(rows))})

    critical = any(row.get("severity") == "C" for row in issues)
    methods_with_trigger = sum(row["trigger_count"] > 0 for row in rows)
    methods_with_outcome = sum(row["outcome_join_count"] > 0 for row in rows)
    methods_risk_ready = sum(row["risk_context_ready"] for row in rows)

    if critical:
        state = "HOLD"
        verdict = "METHOD_SCOREBOARD_CRITICAL_GAP"
    elif methods_with_trigger == 0:
        state = "PASS"
        verdict = "METHOD_SCOREBOARD_HEALTHY_WAITING_FORWARD_TRIGGER"
    elif methods_with_outcome == 0:
        state = "PASS"
        verdict = "METHOD_SCOREBOARD_HEALTHY_WAITING_CLOSE_OUTCOME"
    elif methods_risk_ready == 0:
        state = "PASS"
        verdict = "METHOD_SCOREBOARD_HEALTHY_WAITING_COMPLETE_RISK_CONTEXT"
    else:
        state = "PASS"
        verdict = "METHOD_SCOREBOARD_FORWARD_EVIDENCE_ACTIVE_DECISION_LOCKED"

    report = {
        "schema": "q4r3_exact25_method_scoreboard_report_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "method_count": len(rows),
        "methods_with_trigger": methods_with_trigger,
        "methods_with_outcome": methods_with_outcome,
        "methods_risk_ready": methods_risk_ready,
        "rows": rows,
        "ranking_enabled": False,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "observer_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
    }
    status = {key: value for key, value in report.items() if key != "rows"}
    status.update({
        "violation_count": len(issues),
        "violation_severity": "C" if critical else None,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "historical_backfill_performed": False,
    })
    violations = {
        "schema": "q4r3_exact25_method_scoreboard_violations_v1",
        "generated_at": now_iso(),
        "state": "VIOLATION" if issues else "CLEAR",
        "count": len(issues),
        "severity": "C" if critical else None,
        "notify": critical,
        "violations": issues,
        "action": "hold",
    }

    atomic_json(args.output, report)
    atomic_json(args.status, status)
    atomic_json(args.violations, violations)
    return 0 if state == "PASS" else 2


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--projection-status", type=Path, required=True)
    value.add_argument("--projection", type=Path, required=True)
    value.add_argument("--risk-status", type=Path, required=True)
    value.add_argument("--risk-grid", type=Path, required=True)
    value.add_argument("--pair-status", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--status", type=Path, required=True)
    value.add_argument("--violations", type=Path, required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
