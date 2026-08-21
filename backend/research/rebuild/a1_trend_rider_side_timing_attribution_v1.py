#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_trend_rider_h4_h5_hardening_v1 import (
    one_bar_delay_net_R,
    paired_stats,
    stable,
)
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig


def summarize(values: list[float]) -> dict[str, Any]:
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    gp, gl = sum(wins), sum(losses)
    return {
        "trades": len(values),
        "net_R": sum(values),
        "expectancy_R": sum(values) / len(values) if values else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "win_rate": len(wins) / len(values) if values else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    receipt = json.loads(Path(args.receipt).read_text())
    trades = list(receipt.get("trades") or [])
    if receipt.get("strategy_id") != "trend_rider" or len(trades) < 25:
        raise RuntimeError("TREND_RIDER_TIER_A_RECEIPT_REQUIRED")

    cfg = TrendPolicyConfig()
    symbols = sorted({str(row["symbol"]) for row in trades})
    bars_by = {symbol: ev.fetch_bars(symbol, "1h", 1000) for symbol in symbols}
    maps = {
        symbol: {int(bar["ts_ms"]): index for index, bar in enumerate(bars)}
        for symbol, bars in bars_by.items()
    }

    candidate = [float(row["net_bps"]) / 100.0 for row in trades]
    further_delay = [
        one_bar_delay_net_R(row, bars_by[str(row["symbol"])], maps[str(row["symbol"])], cfg)
        for row in trades
    ]

    by_side: dict[str, Any] = {}
    for side in ("long", "short"):
        indices = [i for i, row in enumerate(trades) if str(row["side"]) == side]
        cand = [candidate[i] for i in indices]
        delayed = [further_delay[i] for i in indices]
        ci, p = paired_stats(cand, delayed, int(stable({
            "receipt": receipt.get("receipt_sha256"),
            "side": side,
            "control": "additional_one_bar_delay",
        })[:16], 16))
        by_side[side] = {
            "candidate": summarize(cand),
            "additional_one_bar_delay": summarize(delayed),
            "candidate_minus_delay_net_R": sum(cand) - sum(delayed),
            "candidate_minus_delay_ci_low_R": ci,
            "candidate_superiority_p_value": p,
            "delay_strictly_superior": sum(delayed) > sum(cand) and ci < 0 and p > 0.95,
        }

    side_net = {
        side: sum(float(row["net_bps"]) for row in trades if str(row["side"]) == side) / 100.0
        for side in ("long", "short")
    }
    total_net = sum(side_net.values())
    output = {
        "schema_version": "zel.a1.trend_rider.side_timing_attribution.v1",
        "state": "PASS_CAUSAL_ATTRIBUTION",
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "candidate_trade_count": len(trades),
        "all_candidate": summarize(candidate),
        "all_additional_one_bar_delay": summarize(further_delay),
        "by_side": by_side,
        "leave_one_side_out_net_R": {
            side: total_net - side_net[side] for side in ("long", "short")
        },
        "short_side_non_positive": side_net["short"] <= 0,
        "short_delay_strictly_superior": bool(by_side["short"]["delay_strictly_superior"]),
        "long_delay_strictly_superior": bool(by_side["long"]["delay_strictly_superior"]),
        "parameter_sweep": False,
        "thresholds_changed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    output["receipt_sha256"] = stable(output)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print("A1_TREND_RIDER_SIDE_TIMING_ATTRIBUTION=" + json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
