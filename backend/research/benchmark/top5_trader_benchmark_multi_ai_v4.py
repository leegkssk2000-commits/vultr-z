#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from backend.research.benchmark import top5_trader_benchmark_multi_ai_v2 as v2
from backend.research.benchmark import top5_trader_benchmark_multi_ai_v3 as v3

_ORIGINAL_V2_HOLY_GRAIL = v2.holy_grail_replay


def repair_entry_bar_intrabar_stops(child: dict[str, Any]) -> dict[str, Any]:
    """Remove pre-entry-open price fabrication from ambiguous entry-bar stops.

    If a stop-entry fills and the same OHLC bar also traverses the protective
    stop, OHLC data cannot prove the intrabar sequence after the fill.  The
    conservative causal price is therefore the already-sealed protective stop,
    never the bar open (which may have occurred before the position existed).
    """
    repaired = 0
    for trade in child.get("trades") or []:
        if trade.get("reason") != "CONSERVATIVE_INTRABAR_STOP":
            continue
        side = str(trade["side"])
        entry = float(trade["entry"])
        stop = float(trade["initial_stop"])
        if side == "long":
            gross = (stop - entry) / entry * 10_000.0
        elif side == "short":
            gross = (entry - stop) / entry * 10_000.0
        else:
            raise RuntimeError(f"BAD_TRADE_SIDE:{side}")
        trade["exit"] = stop
        trade["gross_bps"] = gross
        trade["net_bps"] = gross - float(trade.get("realized_cost_bps") or 0.0)
        trade["entry_bar_stop_price_authority"] = "SEALED_PROTECTIVE_STOP_POST_FILL"
        repaired += 1
    child["entry_bar_intrabar_stop_repairs"] = repaired
    child["entry_bar_stop_pricing"] = "POST_FILL_PROTECTIVE_STOP_NOT_PRE_ENTRY_OPEN"
    child["metrics"] = v3.chronological_metrics(list(child.get("trades") or []))
    return child


def holy_grail_replay(
    symbols: list[str],
    bars_cache: dict[tuple[str, str, int], list[dict[str, Any]]],
    snapshot_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return repair_entry_bar_intrabar_stops(_ORIGINAL_V2_HOLY_GRAIL(symbols, bars_cache, snapshot_cache))


def execute() -> dict[str, Any]:
    # V3 keeps the authoritative exit-timestamp DD path. Replace V2's active
    # candidate replay with the post-fill stop-pricing repair before V3 binds
    # the replay into the shared base execution pipeline.
    v2.holy_grail_replay = holy_grail_replay
    result = v3.execute()
    result["schema_version"] = "zel.top5.trader_benchmark.multi_ai.v4"
    result["entry_bar_stop_repair"] = "POST_FILL_PROTECTIVE_STOP_PRICE_ONLY"
    v2.base.write(v2.base.OUT / "FINAL.json", result)
    v2.base.write_report(result)
    return result


def self_test() -> int:
    long_child = {
        "trades": [
            {
                "reason": "CONSERVATIVE_INTRABAR_STOP", "side": "long", "entry": 105.0,
                "initial_stop": 95.0, "exit": 90.0, "entry_ts": 1, "exit_ts": 1,
                "gross_bps": -1428.0, "realized_cost_bps": 10.0, "net_bps": -1438.0,
            }
        ]
    }
    repaired = repair_entry_bar_intrabar_stops(long_child)
    t = repaired["trades"][0]
    assert t["exit"] == 95.0, t
    assert abs(t["gross_bps"] - ((95.0 - 105.0) / 105.0 * 10_000.0)) < 1e-9, t
    assert t["entry_bar_stop_price_authority"] == "SEALED_PROTECTIVE_STOP_POST_FILL"

    short_child = {
        "trades": [
            {
                "reason": "CONSERVATIVE_INTRABAR_STOP", "side": "short", "entry": 95.0,
                "initial_stop": 105.0, "exit": 110.0, "entry_ts": 2, "exit_ts": 2,
                "gross_bps": -1578.0, "realized_cost_bps": 10.0, "net_bps": -1588.0,
            }
        ]
    }
    repaired = repair_entry_bar_intrabar_stops(short_child)
    t = repaired["trades"][0]
    assert t["exit"] == 105.0, t
    assert abs(t["gross_bps"] - ((95.0 - 105.0) / 95.0 * 10_000.0)) < 1e-9, t

    untouched = {
        "trades": [
            {
                "reason": "INITIAL_SWING_STOP", "side": "long", "entry": 100.0,
                "initial_stop": 95.0, "exit": 95.0, "entry_ts": 1, "exit_ts": 2,
                "gross_bps": -500.0, "realized_cost_bps": 10.0, "net_bps": -510.0,
            }
        ]
    }
    repaired = repair_entry_bar_intrabar_stops(untouched)
    assert repaired["entry_bar_intrabar_stop_repairs"] == 0
    assert repaired["trades"][0]["exit"] == 95.0
    assert v3.self_test() == 0
    print("PASS_TOP5_TRADER_BENCHMARK_MULTI_AI_V4_ENTRY_BAR_STOP_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.run:
        result = execute()
        print(
            "TOP5_BENCHMARK_V4="
            + json.dumps(
                {
                    "state": result["state"],
                    "gemini": result["providers"]["gemini"]["state"],
                    "openai": result["providers"]["openai"]["state"],
                    "economic_pass": result["economic_pass"],
                    "timing_repair": result["timing_repair"],
                    "drawdown_repair": result["drawdown_repair"],
                    "entry_bar_stop_repair": result["entry_bar_stop_repair"],
                    "report_only": result["report_only"],
                },
                sort_keys=True,
            )
        )
        return 0
    print(json.dumps(v2.base.dry_run(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
