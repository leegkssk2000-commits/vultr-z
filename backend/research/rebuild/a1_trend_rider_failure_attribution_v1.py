#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.research.rebuild import a1_trend_rider_momentum_frozen_w123_ab_v2 as mom

SCHEMA = "zel.a1_trend_rider_failure_attribution.v1"
STATE = "PASS_FROZEN_W123_MOMENTUM_FAILURE_ATTRIBUTION"
DAY_MS = 86_400_000


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("symbol")),
        int(row.get("signal_ts")),
        int(row.get("entry_ts")),
        str(row.get("side")),
    )


def _window(entry_ts: int) -> str:
    boundary_ms = int(datetime.fromisoformat(mom.FROZEN_BOUNDARY_UTC.replace("Z", "+00:00")).timestamp() * 1000)
    offset = int(entry_ts) - boundary_ms
    if 0 <= offset < DAY_MS:
        return "W1"
    if DAY_MS <= offset < 2 * DAY_MS:
        return "W2"
    if 2 * DAY_MS <= offset < 3 * DAY_MS:
        return "W3"
    return "OUTSIDE_W123"


def _metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    pnl = [float(x.get("net_bps") or 0.0) for x in items]
    wins = [x for x in pnl if x > 0.0]
    losses = [x for x in pnl if x < 0.0]
    n = len(items)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "flats": n - len(wins) - len(losses),
        "win_rate": (len(wins) / n) if n else None,
        "net_pnl_bps": sum(pnl),
        "net_expectancy_bps": (sum(pnl) / n) if n else None,
        "positive_contribution_bps": sum(wins),
        "negative_contribution_bps": sum(losses),
        "avg_win_bps": (sum(wins) / len(wins)) if wins else None,
        "avg_loss_bps": (sum(losses) / len(losses)) if losses else None,
    }


def _group(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
    buckets: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(str(row[k]) for k in keys)].append(row)
    out: dict[str, Any] = {}
    for key, bucket in sorted(buckets.items()):
        out["|".join(key)] = _metrics(bucket)
    return out


def run(output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    ab_path = output.parent / "momentum_ab_receipt.json"
    ab = mom.run(ab_path)
    parent_current = _read(output.parent / "trend_rider_parent_current_receipt.json")
    child_current = _read(output.parent / "trend_rider_momentum_child_current_receipt.json")
    parent_frozen = mom._freeze_parent(parent_current)
    child_frozen = mom._freeze_child(parent_frozen, child_current)

    child_ids = {_identity(x) for x in (child_frozen.get("trades") or [])}
    rows: list[dict[str, Any]] = []
    for row in parent_frozen.get("trades") or []:
        item = dict(row)
        item["momentum_gate"] = "RETAINED" if _identity(row) in child_ids else "REMOVED"
        item["window"] = _window(int(row["entry_ts"]))
        item["outcome"] = "WIN" if float(row.get("net_bps") or 0.0) > 0 else "LOSS" if float(row.get("net_bps") or 0.0) < 0 else "FLAT"
        rows.append(item)

    parent_metrics = _metrics(rows)
    retained = [x for x in rows if x["momentum_gate"] == "RETAINED"]
    removed = [x for x in rows if x["momentum_gate"] == "REMOVED"]
    retained_metrics = _metrics(retained)
    removed_metrics = _metrics(removed)

    expected = mom.EXPECTED_PARENT
    parent_anchor_match = (
        int(parent_metrics["trades"]) == int(expected["trades"])
        and math.isclose(float(parent_metrics["win_rate"]), float(expected["win_rate"]), rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(float(parent_metrics["net_pnl_bps"]), float(expected["net_pnl_bps"]), rel_tol=0.0, abs_tol=1e-9)
    )
    partition_integrity = len(rows) == len(retained) + len(removed) and len(rows) == 22 and len(retained) == 10 and len(removed) == 12
    contribution_identity = math.isclose(
        float(parent_metrics["net_pnl_bps"]),
        float(retained_metrics["net_pnl_bps"]) + float(removed_metrics["net_pnl_bps"]),
        rel_tol=0.0,
        abs_tol=1e-9,
    )

    removed_winners = sorted(
        (x for x in removed if x["outcome"] == "WIN"),
        key=lambda x: float(x.get("net_bps") or 0.0),
        reverse=True,
    )
    removed_losses = sorted(
        (x for x in removed if x["outcome"] == "LOSS"),
        key=lambda x: float(x.get("net_bps") or 0.0),
    )

    diagnosis = {
        "momentum_removes_losses_count": len(removed_losses),
        "momentum_removes_winners_count": len(removed_winners),
        "removed_net_pnl_bps": removed_metrics["net_pnl_bps"],
        "removed_positive_contribution_bps": removed_metrics["positive_contribution_bps"],
        "removed_negative_contribution_bps": removed_metrics["negative_contribution_bps"],
        "removed_set_is_net_profitable": bool(float(removed_metrics["net_pnl_bps"]) > 0.0),
        "interpretation": "MOMENTUM_FILTER_HAS_REAL_LOSS_REJECTION_BUT_OVERSELECTS_AND_DELETES_POSITIVE_TAIL",
        "next_axis_requirement": "PREENTRY_CONTEXT_DISCRIMINATOR_THAT_SEPARATES_REMOVED_LOSSES_FROM_REMOVED_WINNERS_WITHOUT_USING_POST_OUTCOME_DATA",
        "next_step": "PRECOMMIT_ONE_DISTINCT_PREENTRY_CONTEXT_AXIS_THEN_DIRECT_FROZEN_W123_AB",
    }

    result = {
        "schema_version": SCHEMA,
        "state": STATE if parent_anchor_match and partition_integrity and contribution_identity else "HOLD_ATTRIBUTION_INTEGRITY",
        "strategy_id": "trend_rider",
        "baseline_identity": mom.BASELINE_IDENTITY,
        "frozen_observation_run_id": mom.FROZEN_OBSERVATION_RUN_ID,
        "boundary_utc": mom.FROZEN_BOUNDARY_UTC,
        "parent_anchor_match": parent_anchor_match,
        "partition_integrity": partition_integrity,
        "contribution_identity": contribution_identity,
        "parent": parent_metrics,
        "momentum_retained": retained_metrics,
        "momentum_removed": removed_metrics,
        "by_gate_window": _group(rows, ("momentum_gate", "window")),
        "by_gate_symbol": _group(rows, ("momentum_gate", "symbol")),
        "by_gate_side": _group(rows, ("momentum_gate", "side")),
        "by_gate_exit_reason": _group(rows, ("momentum_gate", "reason")),
        "by_gate_window_symbol": _group(rows, ("momentum_gate", "window", "symbol")),
        "top_removed_winners": [
            {k: x.get(k) for k in ("symbol", "signal_ts", "entry_ts", "side", "reason", "net_bps", "window")}
            for x in removed_winners[:5]
        ],
        "top_removed_losses": [
            {k: x.get(k) for k in ("symbol", "signal_ts", "entry_ts", "side", "reason", "net_bps", "window")}
            for x in removed_losses[:5]
        ],
        "diagnosis": diagnosis,
        "direct_ab_receipt_sha256": ab.get("receipt_sha256"),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert mom.EXPECTED_PARENT["trades"] == 22
    assert math.isclose(float(mom.EXPECTED_PARENT["win_rate"]), 13 / 22, rel_tol=0.0, abs_tol=1e-15)
    assert _window(int(datetime.fromisoformat(mom.FROZEN_BOUNDARY_UTC.replace("Z", "+00:00")).timestamp() * 1000)) == "W1"
    print("PASS_A1_TREND_RIDER_FAILURE_ATTRIBUTION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_failure_attribution_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "parent": result["parent"],
        "retained": result["momentum_retained"],
        "removed": result["momentum_removed"],
        "diagnosis": result["diagnosis"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
