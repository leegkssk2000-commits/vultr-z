from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

INTERVAL_MS = 900_000
WINDOW_BARS = 480
PRIMARY_REVIEW_QUEUE = {"alpha_combo", "turtle_trend", "ema_ribbon_scalp"}
PIPELINE_VERSION = "R7A4D_STRATEGY11_DATA_WAIT_POOL_REFRESH_V1"


def strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def iso(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").isoformat()


def aligned_closed_end(now_ms: int) -> int:
    return ((now_ms // INTERVAL_MS) - 1) * INTERVAL_MS


def read_ranking(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if len(rows) != 25:
        raise RuntimeError(f"RANKING_STRATEGY_COUNT:{len(rows)}")
    return rows


def parse_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh-manifest", required=True)
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--ema-terminal", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--as-of-ms", type=int)
    args = parser.parse_args()

    manifest_path = Path(args.fresh_manifest).resolve()
    ranking_path = Path(args.ranking).resolve()
    terminal_path = Path(args.ema_terminal).resolve()
    out = Path(args.out).resolve()

    manifest = strict_json(manifest_path)
    terminal = strict_json(terminal_path)
    ranking = read_ranking(ranking_path)

    blockers: list[str] = []
    if manifest.get("state") != "PASS" or manifest.get("blockers"):
        blockers.append("FRESH_AUTHORITY_NOT_PASS")
    if terminal.get("strategy_id") != "ema_ribbon_scalp":
        blockers.append("EMA_TERMINAL_STRATEGY_MISMATCH")
    if terminal.get("state") != "STRUCTURAL_REJECT":
        blockers.append(f"EMA_TERMINAL_STATE:{terminal.get('state')}")
    if terminal.get("next") != "START_DATA_WAIT_POOL_REFRESH":
        blockers.append(f"EMA_TERMINAL_NEXT:{terminal.get('next')}")
    budget = terminal.get("iteration_budget") if isinstance(terminal.get("iteration_budget"), Mapping) else {}
    if not bool(budget.get("exhausted")) or int(budget.get("used_iterations") or 0) != 3:
        blockers.append("EMA_REPAIR_BUDGET_NOT_EXHAUSTED")
    if bool(terminal.get("sealed_holdback_read")):
        blockers.append("EMA_SEALED_HOLDBACK_UNEXPECTEDLY_READ")

    pool_rows: list[dict[str, Any]] = []
    for row in ranking:
        strategy_id = str(row.get("strategy_id") or "")
        if strategy_id in PRIMARY_REVIEW_QUEUE:
            continue
        trades = parse_int(row.get("trade_count"))
        pool_rows.append({
            "strategy_id": strategy_id,
            "prior_fresh_trade_count": trades,
            "prior_state": str(row.get("state") or ""),
            "wait_class": "NO_SIGNAL_WAIT" if trades == 0 else "LOW_SAMPLE_WAIT",
        })
    if len(pool_rows) != 22:
        blockers.append(f"DATA_WAIT_POOL_COUNT:{len(pool_rows)}")

    last_end_ms = int(manifest.get("latest_closed_end_ms") or 0)
    if last_end_ms <= 0:
        blockers.append("FRESH_LATEST_CLOSED_END_MISSING")
    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) if args.as_of_ms is None else int(args.as_of_ms)
    latest_closed_ms = aligned_closed_end(now_ms)
    available_bars = max(0, (latest_closed_ms - last_end_ms) // INTERVAL_MS) if last_end_ms > 0 else 0
    required_end_ms = last_end_ms + WINDOW_BARS * INTERVAL_MS if last_end_ms > 0 else 0

    if blockers:
        state = "HOLD"
        next_step = "REPAIR_LINEAGE_OR_AUTHORITY"
    elif available_bars < WINDOW_BARS:
        state = "WAIT_DATA"
        next_step = "WAIT_FOR_COMPLETE_NON_OVERLAP_480_BAR_WINDOW"
    else:
        state = "READY"
        next_step = "CREATE_DATA_WAIT_POOL_REFRESH_COMPUTE_CHILD"

    payload = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "authority": "READ_ONLY_DATA_WAIT_POOL_AVAILABILITY_NO_EXECUTION",
        "state": state,
        "blockers": blockers,
        "source_fresh_manifest_sha256": sha256(manifest_path),
        "source_ranking_sha256": sha256(ranking_path),
        "source_ema_terminal_sha256": sha256(terminal_path),
        "source_fresh_run_id": "30252022416",
        "source_data_gate_run_id": "30255639710",
        "source_ema_terminal_run_id": "30282593225",
        "primary_review_queue_terminal": {
            "alpha_combo": "INCUMBENT_CONTROL_RETAINED_AFTER_SEALED_ONE_SHOT_FAIL",
            "turtle_trend": "INCUMBENT_CONTROL_RETAINED",
            "ema_ribbon_scalp": "STRUCTURAL_REJECT",
        },
        "data_wait_pool_count": len(pool_rows),
        "data_wait_pool": pool_rows,
        "interval_ms": INTERVAL_MS,
        "required_new_window_bars": WINDOW_BARS,
        "authority_last_used_end_ms": last_end_ms,
        "authority_last_used_end": iso(last_end_ms) if last_end_ms > 0 else None,
        "latest_closed_end_ms": latest_closed_ms,
        "latest_closed_end": iso(latest_closed_ms),
        "available_non_overlap_bars": int(available_bars),
        "missing_bars": max(0, WINDOW_BARS - int(available_bars)),
        "next_eligible_window_end_ms": required_end_ms,
        "next_eligible_window_end": iso(required_end_ms) if required_end_ms > 0 else None,
        "next": next_step,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "shadow_allowed": False,
        "execution_allowed": False,
    }
    atomic_json(out / "status.json", payload)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("## Strategy11 DATA_WAIT_POOL_REFRESH\n\n")
            handle.write(f"- state: `{state}`\n")
            handle.write(f"- pool: `{len(pool_rows)}` strategies\n")
            handle.write(f"- available bars: `{available_bars}/{WINDOW_BARS}`\n")
            handle.write(f"- missing bars: `{max(0, WINDOW_BARS - int(available_bars))}`\n")
            handle.write(f"- next eligible end: `{payload['next_eligible_window_end']}`\n")
            handle.write(f"- next: `{next_step}`\n")

    print(json.dumps({
        "STATE": state,
        "POOL": len(pool_rows),
        "AVAILABLE_BARS": int(available_bars),
        "MISSING_BARS": max(0, WINDOW_BARS - int(available_bars)),
        "NEXT_ELIGIBLE_END": payload["next_eligible_window_end"],
        "BLOCKERS": blockers,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
