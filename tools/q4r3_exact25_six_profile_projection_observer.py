#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

UTC = timezone.utc
PROFILES = (
    "scalp_first/revert",
    "scalp_first/continuation",
    "scalp_first/liquidity_reclaim",
    "intraday/breakout_probe",
    "intraday/rescue",
    "tactical_swing/continuation",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def fnum(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return rows, errors
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            errors.append({"line": line_no, "error": f"{type(exc).__name__}:{exc}"})
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        else:
            errors.append({"line": line_no, "error": "ROW_NOT_OBJECT"})
    return rows, errors


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def project(events: list[dict[str, Any]]) -> dict[str, Any]:
    triggers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outcomes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    blocked: dict[str, int] = defaultdict(int)

    for row in events:
        method_id = str(row.get("method_id") or "")
        if method_id not in PROFILES:
            continue
        event_type = row.get("event_type")
        if event_type == "skill_triggered":
            triggers[method_id].append(row)
        elif event_type == "skill_blocked":
            blocked[method_id] += 1
        elif event_type == "close_outcome_joined":
            outcomes[method_id].append(row)

    rows: list[dict[str, Any]] = []
    for method_id in PROFILES:
        trigger_rows = triggers[method_id]
        outcome_rows = outcomes[method_id]
        realized = [value for value in (fnum(row.get("realized_r")) for row in outcome_rows) if value is not None]
        fees = [value for value in (fnum(row.get("fee_bps")) for row in outcome_rows) if value is not None]
        slippage = [value for value in (fnum(row.get("slippage_bps")) for row in outcome_rows) if value is not None]
        mfe = [value for value in (fnum(row.get("mfe_r")) for row in outcome_rows) if value is not None]
        mae = [value for value in (fnum(row.get("mae_r")) for row in outcome_rows) if value is not None]
        hold = [value for value in (fnum(row.get("exposure_time_min")) for row in outcome_rows) if value is not None]
        strategy_ids = sorted({str(row.get("strategy_id")) for row in trigger_rows if row.get("strategy_id")})
        skill_ids = sorted({str(row.get("skill_id")) for row in trigger_rows if row.get("skill_id")})
        rows.append({
            "method_id": method_id,
            "trigger_count": len(trigger_rows),
            "blocked_count": blocked[method_id],
            "outcome_join_count": len(outcome_rows),
            "unique_position_count": len({str(row.get("position_id")) for row in trigger_rows if row.get("position_id")}),
            "strategy_ids": strategy_ids,
            "skill_ids": skill_ids,
            "realized_r_count": len(realized),
            "net_r": sum(realized),
            "avg_r": mean(realized),
            "positive_rate_pct": (sum(value > 0 for value in realized) * 100.0 / len(realized)) if realized else None,
            "profit_factor": (sum(value for value in realized if value > 0) / abs(sum(value for value in realized if value < 0))) if any(value < 0 for value in realized) else None,
            "max_drawdown_r": max_drawdown(realized),
            "avg_fee_bps": mean(fees),
            "avg_slippage_bps": mean(slippage),
            "avg_mfe_r": mean(mfe),
            "avg_mae_r": mean(mae),
            "avg_hold_min": mean(hold),
            "evidence_ready": bool(trigger_rows and outcome_rows),
            "decision_enabled": False,
            "promotion_enabled": False,
            "action": "hold",
        })

    return {
        "schema": "q4r3_exact25_six_profile_projection_v1",
        "generated_at": now_iso(),
        "profile_count": len(rows),
        "profiles_with_trigger": sum(row["trigger_count"] > 0 for row in rows),
        "profiles_with_outcome": sum(row["outcome_join_count"] > 0 for row in rows),
        "total_trigger_count": sum(row["trigger_count"] for row in rows),
        "total_blocked_count": sum(row["blocked_count"] for row in rows),
        "total_outcome_join_count": sum(row["outcome_join_count"] for row in rows),
        "rows": rows,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "observer_only": True,
        "action": "hold",
    }


def run(args: argparse.Namespace) -> int:
    trigger_status = load_json(args.trigger_status, {})
    if trigger_status.get("state") != "PASS":
        raise RuntimeError("SKILL_TRIGGER_LINEAGE_OBSERVER_NOT_PASS")
    if trigger_status.get("observer_only") is not True:
        raise RuntimeError("SKILL_TRIGGER_LINEAGE_NOT_OBSERVER_ONLY")
    if trigger_status.get("formal_ledger_modified") is not False:
        raise RuntimeError("FORMAL_LEDGER_MUTATION_DETECTED")

    events, parse_errors = read_jsonl(args.events)
    projection = project(events)
    issues = [
        {
            "code": "SKILL_EVENT_LEDGER_PARSE_ERROR",
            "severity": "C",
            "detail": f"line={row['line']}:{row['error']}",
            "source": str(args.events),
        }
        for row in parse_errors
    ]
    if projection["profile_count"] != 6:
        issues.append({"code": "PROFILE_COUNT_MISMATCH", "severity": "C", "detail": str(projection["profile_count"]), "source": "projection"})

    state = "HOLD" if any(row["severity"] == "C" for row in issues) else "PASS"
    if state == "HOLD":
        verdict = "SIX_PROFILE_PROJECTION_CRITICAL_GAP"
    elif projection["total_trigger_count"] == 0:
        verdict = "SIX_PROFILE_PROJECTION_HEALTHY_WAITING_FORWARD_TRIGGER"
    elif projection["total_outcome_join_count"] == 0:
        verdict = "SIX_PROFILE_PROJECTION_HEALTHY_WAITING_CLOSE_OUTCOME"
    else:
        verdict = "SIX_PROFILE_PROJECTION_FORWARD_EVIDENCE_ACTIVE"

    status = {
        "schema": "q4r3_exact25_six_profile_projection_status_v1",
        "state": state,
        "verdict": verdict,
        "generated_at": now_iso(),
        "profile_count": projection["profile_count"],
        "profiles_with_trigger": projection["profiles_with_trigger"],
        "profiles_with_outcome": projection["profiles_with_outcome"],
        "total_trigger_count": projection["total_trigger_count"],
        "total_blocked_count": projection["total_blocked_count"],
        "total_outcome_join_count": projection["total_outcome_join_count"],
        "violation_count": len(issues),
        "historical_backfill_performed": False,
        "observer_only": True,
        "strategy_modified": False,
        "trade_method_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
    }
    violations = {
        "schema": "q4r3_exact25_six_profile_projection_violations_v1",
        "generated_at": now_iso(),
        "state": "CLEAR" if not issues else "VIOLATION",
        "count": len(issues),
        "notify": bool(any(row["severity"] == "C" for row in issues)),
        "violations": issues,
        "action": "hold",
    }
    atomic_json(args.output, projection)
    atomic_json(args.status, status)
    atomic_json(args.violations, violations)
    print(json.dumps(status, sort_keys=True))
    return 0 if state == "PASS" else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--trigger-status", type=Path, required=True)
    value.add_argument("--events", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--status", type=Path, required=True)
    value.add_argument("--violations", type=Path, required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
