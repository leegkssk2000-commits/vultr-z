from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POSITION_SIZES = (5, 10, 15, 20)
LEVERAGES = (10, 15, 20)
SCENARIO_COUNT = len(POSITION_SIZES) * len(LEVERAGES)
REQUIRED_FORWARD_FIELDS = (
    "realized_r",
    "fee_bps",
    "slippage_bps",
    "funding_bps",
    "liq_buffer_pct",
    "mfe_r",
    "mae_r",
    "exposure_time_min",
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


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def build_grid(pairs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    exact_pairs = [
        row
        for row in pairs
        if row.get("pair_state") == "EXACT_CLOSE_JOINED" and row.get("exact_join") is True
    ]
    missing_fields: set[str] = set()
    for row in exact_pairs:
        for field in REQUIRED_FORWARD_FIELDS:
            if fnum(row.get(field)) is None:
                missing_fields.add(field)

    realized_r = [value for row in exact_pairs if (value := fnum(row.get("realized_r"))) is not None]
    fee_bps = [fnum(row.get("fee_bps")) or 0.0 for row in exact_pairs]
    slippage_bps = [fnum(row.get("slippage_bps")) or 0.0 for row in exact_pairs]
    funding_bps = [fnum(row.get("funding_bps")) or 0.0 for row in exact_pairs]
    liq_buffers = [value for row in exact_pairs if (value := fnum(row.get("liq_buffer_pct"))) is not None]

    grid: list[dict[str, Any]] = []
    for size_pct in POSITION_SIZES:
        for leverage in LEVERAGES:
            notional_exposure_pct = float(size_pct * leverage)
            execution_cost_equity_pct = sum(
                notional_exposure_pct * ((fee + slip) / 10000.0)
                for fee, slip in zip(fee_bps, slippage_bps)
            )
            funding_cost_equity_pct = sum(
                notional_exposure_pct * (funding / 10000.0)
                for funding in funding_bps
            )
            total_cost_equity_pct = execution_cost_equity_pct + funding_cost_equity_pct
            risk_context_ready = bool(exact_pairs) and not missing_fields
            grid.append({
                "scenario_id": f"P{size_pct}_L{leverage}",
                "position_size_pct": size_pct,
                "leverage_x": leverage,
                "notional_exposure_pct": notional_exposure_pct,
                "exact_pair_count": len(exact_pairs),
                "net_r": round(sum(realized_r), 8) if realized_r else None,
                "max_drawdown_r": round(max_drawdown(realized_r), 8) if realized_r else None,
                "minimum_liq_buffer_pct": round(min(liq_buffers), 8) if liq_buffers else None,
                "estimated_execution_cost_equity_pct": round(execution_cost_equity_pct, 8) if exact_pairs else None,
                "estimated_funding_cost_equity_pct": round(funding_cost_equity_pct, 8) if exact_pairs else None,
                "estimated_total_cost_equity_pct": round(total_cost_equity_pct, 8) if exact_pairs else None,
                "risk_context_ready": risk_context_ready,
                "decision_eligible": False,
                "promotion_enabled": False,
                "action": "hold",
            })
    return grid, sorted(missing_fields)


def run(args: argparse.Namespace) -> int:
    pair_status = load_json(args.pair_status, {})
    pair_report = load_json(args.pair_report, {})
    projection_status = load_json(args.projection_status, {})

    issues: list[dict[str, Any]] = []
    if pair_status.get("state") != "PASS" or pair_status.get("observer_only") is not True:
        issues.append({"code": "PAIR_JOIN_NOT_HEALTHY", "severity": "C", "detail": str(pair_status.get("verdict"))})
    if projection_status.get("state") != "PASS" or projection_status.get("profile_count") != 6:
        issues.append({"code": "SIX_PROFILE_PROJECTION_NOT_HEALTHY", "severity": "C", "detail": str(projection_status.get("verdict"))})

    pairs = pair_report.get("pairs") if isinstance(pair_report, dict) else []
    if not isinstance(pairs, list):
        pairs = []
    grid, missing_fields = build_grid(pairs)

    exact_pair_count = sum(
        1
        for row in pairs
        if row.get("pair_state") == "EXACT_CLOSE_JOINED" and row.get("exact_join") is True
    )
    critical = any(row.get("severity") == "C" for row in issues)
    state = "HOLD" if critical else "PASS"
    if critical:
        verdict = "RISK_SCENARIO_GRID_CRITICAL_GAP"
    elif exact_pair_count == 0:
        verdict = "RISK_SCENARIO_GRID_HEALTHY_WAITING_EXACT_PAIR"
    elif missing_fields:
        verdict = "RISK_SCENARIO_GRID_HEALTHY_WAITING_COMPLETE_RISK_CONTEXT"
    else:
        verdict = "RISK_SCENARIO_GRID_HEALTHY_FORWARD_EVIDENCE_ACTIVE"

    report = {
        "schema": "q4r3_exact25_risk_scenario_grid_report_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "scenario_count": len(grid),
        "position_size_presets_pct": list(POSITION_SIZES),
        "leverage_presets_x": list(LEVERAGES),
        "exact_pair_count": exact_pair_count,
        "required_forward_fields": list(REQUIRED_FORWARD_FIELDS),
        "missing_risk_fields": missing_fields,
        "scenarios": grid,
        "observer_only": True,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
    }
    status = {key: value for key, value in report.items() if key != "scenarios"}
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
        "schema": "q4r3_exact25_risk_scenario_grid_violations_v1",
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
    value.add_argument("--pair-status", type=Path, required=True)
    value.add_argument("--pair-report", type=Path, required=True)
    value.add_argument("--projection-status", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--status", type=Path, required=True)
    value.add_argument("--violations", type=Path, required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
