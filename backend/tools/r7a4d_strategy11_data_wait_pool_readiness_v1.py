from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


INTERVAL_MS = 900_000
PRIMARY_REVIEW_QUEUE = ("alpha_combo", "turtle_trend", "ema_ribbon_scalp")
VERSION = "R7A4D_STRATEGY11_DATA_WAIT_POOL_READINESS_V1"


def strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def iso(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").isoformat()


def align_closed_end(now_ms: int) -> int:
    return ((now_ms // INTERVAL_MS) - 1) * INTERVAL_MS


def manifest_max_end(manifest: Mapping[str, Any]) -> int:
    values: list[int] = []
    for row in manifest.get("files", []):
        if isinstance(row, Mapping) and row.get("state") == "PASS":
            values.append(int(row.get("evaluation_end_ms") or 0))
    if not values or max(values) <= 0:
        raise RuntimeError("MANIFEST_EVALUATION_END_MISSING")
    return max(values)


def summary_row(path: Path) -> dict[str, Any]:
    payload = strict_json(path)
    baseline = payload.get("baseline") if isinstance(payload.get("baseline"), Mapping) else {}
    return {
        "strategy_id": str(payload.get("strategy_id") or path.parent.name),
        "state": payload.get("state"),
        "trade_count": int(baseline.get("trade_count") or 0),
        "win_rate_pct": baseline.get("win_rate_pct"),
        "net_return_pct_sum": baseline.get("net_return_pct_sum"),
        "net_profit_factor": baseline.get("net_profit_factor"),
        "payoff_ratio": baseline.get("payoff_ratio"),
        "max_drawdown_pct": baseline.get("max_drawdown_pct"),
        "positive_fresh_windows_pct": baseline.get("positive_fresh_windows_pct"),
        "baseline_summary_path": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh-manifest", required=True)
    parser.add_argument("--sealed-contract-manifest", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--alpha-terminal-summary", required=True)
    parser.add_argument("--turtle-terminal-summary", required=True)
    parser.add_argument("--ema-terminal-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--as-of-ms", type=int)
    args = parser.parse_args()

    fresh_path = Path(args.fresh_manifest).resolve()
    sealed_contract_path = Path(args.sealed_contract_manifest).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    alpha_path = Path(args.alpha_terminal_summary).resolve()
    turtle_path = Path(args.turtle_terminal_summary).resolve()
    ema_path = Path(args.ema_terminal_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    fresh = strict_json(fresh_path)
    sealed_contract = strict_json(sealed_contract_path)
    alpha = strict_json(alpha_path)
    turtle = strict_json(turtle_path)
    ema = strict_json(ema_path)
    ssot = strict_json(ssot_path)

    blockers: list[str] = []
    if fresh.get("state") != "PASS" or fresh.get("blockers"):
        blockers.append("FRESH_AUTHORITY_NOT_PASS")
    if sealed_contract.get("state") != "PASS" or sealed_contract.get("blockers"):
        blockers.append("SEALED_CONTRACT_NOT_PASS")
    if sealed_contract.get("sealed") is not True or sealed_contract.get("one_shot_only") is not True:
        blockers.append("SEALED_CONTRACT_FLAGS_INVALID")
    if sealed_contract.get("repair_read_allowed") is not False:
        blockers.append("SEALED_REPAIR_READ_ALLOWED")

    if alpha.get("state") != "SEALED_REJECT_ROLLBACK" or alpha.get("next") != "ADVANCE_TURTLE_TREND_REVIEW":
        blockers.append("ALPHA_TERMINAL_AUTHORITY_INVALID")
    if alpha.get("sealed_one_shot_consumed") is not True:
        blockers.append("ALPHA_SEALED_CONSUMPTION_MISSING")
    if turtle.get("state") != "RETAIN_INCUMBENT" or turtle.get("next") != "ADVANCE_EMA_RIBBON_SCALP_REVIEW":
        blockers.append("TURTLE_TERMINAL_AUTHORITY_INVALID")
    if ema.get("state") != "STRUCTURAL_REJECT" or ema.get("next") != "START_DATA_WAIT_POOL_REFRESH":
        blockers.append("EMA_TERMINAL_AUTHORITY_INVALID")
    if not bool((ema.get("iteration_budget") or {}).get("exhausted")):
        blockers.append("EMA_REPAIR_BUDGET_NOT_EXHAUSTED")

    paths = sorted(evidence_root.glob("*/summary.json"))
    rows = [summary_row(path) for path in paths]
    ids = sorted(row["strategy_id"] for row in rows)
    if len(ids) != 25 or len(set(ids)) != 25:
        blockers.append(f"EVIDENCE_STRATEGY_COUNT:{len(ids)}")

    primary = set(PRIMARY_REVIEW_QUEUE)
    wait_pool = sorted(row["strategy_id"] for row in rows if row["strategy_id"] not in primary)
    if len(wait_pool) != 22:
        blockers.append(f"DATA_WAIT_POOL_COUNT:{len(wait_pool)}")

    min_trades = int(ssot["data_adequacy"]["min_fresh_trades_per_promoted_candidate"])
    row_by_id = {row["strategy_id"]: row for row in rows}
    unexpected_eligible = [sid for sid in wait_pool if int(row_by_id[sid]["trade_count"]) >= min_trades]
    if unexpected_eligible:
        blockers.append("WAIT_POOL_ALREADY_ELIGIBLE:" + ",".join(unexpected_eligible))

    last_used_end_ms = max(manifest_max_end(fresh), manifest_max_end(sealed_contract))
    evaluation_bars = int(ssot["data_adequacy"]["fresh_evaluation_bars_per_window"])
    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) if args.as_of_ms is None else int(args.as_of_ms)
    latest_closed_end_ms = align_closed_end(now_ms)
    available_new_bars = max(0, (latest_closed_end_ms - last_used_end_ms) // INTERVAL_MS)
    next_window_start_ms = last_used_end_ms + INTERVAL_MS
    next_window_end_ms = last_used_end_ms + evaluation_bars * INTERVAL_MS
    ready = available_new_bars >= evaluation_bars

    state = "HOLD" if blockers else ("READY" if ready else "WAIT_DATA")
    next_action = (
        "REPAIR_READINESS_SINGLE_CAUSE" if blockers
        else ("BUILD_DATA_WAIT_POOL_WINDOW_1" if ready else "WAIT_UNTIL_NEXT_WINDOW_CLOSED")
    )

    pool_rows = [row_by_id[sid] for sid in wait_pool]
    atomic_json(out / "data_wait_pool.json", {
        "schema_version": "1.0",
        "state": state,
        "pool_count": len(pool_rows),
        "minimum_cumulative_fresh_trades": min_trades,
        "strategies": pool_rows,
    })
    atomic_json(out / "summary.json", {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "stage": "DATA_WAIT_POOL_REFRESH_READINESS",
        "primary_review_queue": list(PRIMARY_REVIEW_QUEUE),
        "primary_terminal_states": {
            "alpha_combo": alpha.get("state"),
            "turtle_trend": turtle.get("state"),
            "ema_ribbon_scalp": ema.get("state"),
        },
        "data_wait_pool_count": len(wait_pool),
        "data_wait_pool": wait_pool,
        "last_used_evaluation_end_ms": last_used_end_ms,
        "last_used_evaluation_end": iso(last_used_end_ms),
        "latest_closed_end_ms": latest_closed_end_ms,
        "latest_closed_end": iso(latest_closed_end_ms),
        "available_new_closed_bars": int(available_new_bars),
        "required_new_closed_bars": evaluation_bars,
        "next_window_id": "W1",
        "next_window_evaluation_start_ms": next_window_start_ms,
        "next_window_evaluation_start": iso(next_window_start_ms),
        "next_window_ready_end_ms": next_window_end_ms,
        "next_window_ready_end": iso(next_window_end_ms),
        "ready_to_build_window": ready,
        "blockers": blockers,
        "next": next_action,
        "fresh_manifest_path": str(fresh_path),
        "sealed_contract_manifest_path": str(sealed_contract_path),
        "ssot_path": str(ssot_path),
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
    })
    print(json.dumps({
        "STATE": state,
        "AVAILABLE": int(available_new_bars),
        "REQUIRED": evaluation_bars,
        "READY_END": iso(next_window_end_ms),
        "BLOCKERS": blockers,
        "NEXT": next_action,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
