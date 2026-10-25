#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from backend.research.benchmark import top5_trader_benchmark_multi_ai_v2 as v2
from backend.research.rebuild.a1_multisymbol_realized_dd_v1 import exit_bucket_net_bps, realized_drawdown_bps

_ORIGINAL_METRICS = v2.base.metrics_from_trades


def chronological_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Preserve scalar trade economics while fixing order-dependent risk metrics.

    Parent and child receipts are appended symbol-by-symbol.  Portfolio realized
    DD and loss streak must therefore be calculated from exit-timestamp buckets,
    not append order.  Simultaneous exits are netted before the path is scored.
    """
    metrics = dict(_ORIGINAL_METRICS(trades))
    buckets = exit_bucket_net_bps(trades)
    current = maximum = 0
    for bucket in buckets:
        current = current + 1 if float(bucket["net_bps"]) < 0.0 else 0
        maximum = max(maximum, current)
    metrics["drawdown_bps"] = realized_drawdown_bps(trades)
    metrics["max_losing_streak"] = maximum
    metrics["drawdown_authority"] = "EXIT_TIMESTAMP_BUCKET_ASC"
    metrics["simultaneous_exit_ordering"] = "NET_PNL_AGGREGATED_PER_EXIT_TS"
    metrics["exit_bucket_count"] = len(buckets)
    return metrics


def execute() -> dict[str, Any]:
    # Keep v2's immediate-next-bar order semantics and replace only the
    # portfolio path metrics used by both parent and child comparison gates.
    v2.base.metrics_from_trades = chronological_metrics
    result = v2.execute()
    result["schema_version"] = "zel.top5.trader_benchmark.multi_ai.v3"
    result["drawdown_repair"] = "AUTHORITATIVE_EXIT_TIMESTAMP_BUCKET_ORDERING"
    result["risk_path_ordering"] = "EXIT_TIMESTAMP_BUCKET_ASC_SIMULTANEOUS_NETTED"
    v2.base.write(v2.base.OUT / "FINAL.json", result)
    v2.base.write_report(result)
    return result


def self_test() -> int:
    # Symbol-append order is intentionally different from exit chronology.
    trades = [
        {"symbol": "BTC-USDT", "entry_ts": 0, "exit_ts": 2, "net_bps": 100.0, "realized_cost_bps": 1.0},
        {"symbol": "BTC-USDT", "entry_ts": 2, "exit_ts": 4, "net_bps": -120.0, "realized_cost_bps": 1.0},
        {"symbol": "ETH-USDT", "entry_ts": 0, "exit_ts": 1, "net_bps": -100.0, "realized_cost_bps": 1.0},
        {"symbol": "ETH-USDT", "entry_ts": 1, "exit_ts": 3, "net_bps": 150.0, "realized_cost_bps": 1.0},
    ]
    metrics = chronological_metrics(trades)
    assert metrics["drawdown_bps"] == 120.0, metrics
    assert metrics["max_losing_streak"] == 1, metrics
    assert metrics["drawdown_authority"] == "EXIT_TIMESTAMP_BUCKET_ASC"

    simultaneous = [
        {"symbol": "BTC-USDT", "entry_ts": 0, "exit_ts": 10, "net_bps": 200.0, "realized_cost_bps": 1.0},
        {"symbol": "ETH-USDT", "entry_ts": 0, "exit_ts": 10, "net_bps": -180.0, "realized_cost_bps": 1.0},
        {"symbol": "SOL-USDT", "entry_ts": 10, "exit_ts": 11, "net_bps": -10.0, "realized_cost_bps": 1.0},
    ]
    sm = chronological_metrics(simultaneous)
    assert sm["drawdown_bps"] == 10.0, sm
    assert sm["max_losing_streak"] == 1, sm
    assert v2.self_test() == 0
    print("PASS_TOP5_TRADER_BENCHMARK_MULTI_AI_V3_RISK_PATH_SELF_TEST")
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
            "TOP5_BENCHMARK_V3="
            + json.dumps(
                {
                    "state": result["state"],
                    "gemini": result["providers"]["gemini"]["state"],
                    "openai": result["providers"]["openai"]["state"],
                    "economic_pass": result["economic_pass"],
                    "timing_repair": result["timing_repair"],
                    "drawdown_repair": result["drawdown_repair"],
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
