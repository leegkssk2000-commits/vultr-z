#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping


def _finite(value: Any, *, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise RuntimeError(f"FINITE_{name}_REQUIRED:{value!r}")
    return float(value)


def exit_bucket_net_bps(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate realized trade PnL by exit timestamp before ordering.

    Multi-symbol receipts may append trades symbol-by-symbol. Realized portfolio
    drawdown must therefore be independent of append order. Trades sharing an
    exit timestamp are bucketed together so arbitrary ordering within a single
    timestamp cannot create or hide an intra-timestamp drawdown path.
    """
    buckets: dict[int, dict[str, Any]] = {}
    for row in trades:
        if not isinstance(row, Mapping):
            raise RuntimeError("TRADE_OBJECT_REQUIRED")
        raw_ts = row.get("exit_ts")
        if not isinstance(raw_ts, int):
            raise RuntimeError(f"INTEGER_EXIT_TS_REQUIRED:{raw_ts!r}")
        net = _finite(row.get("net_bps"), name="NET_BPS")
        bucket = buckets.setdefault(raw_ts, {"exit_ts": raw_ts, "net_bps": 0.0, "trade_count": 0})
        bucket["net_bps"] = float(bucket["net_bps"]) + net
        bucket["trade_count"] = int(bucket["trade_count"]) + 1
    return [buckets[ts] for ts in sorted(buckets)]


def max_drawdown_from_buckets_bps(buckets: list[dict[str, Any]]) -> float:
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for bucket in buckets:
        equity += _finite(bucket.get("net_bps"), name="BUCKET_NET_BPS")
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def realized_drawdown_bps(trades: list[dict[str, Any]]) -> float:
    return max_drawdown_from_buckets_bps(exit_bucket_net_bps(trades))


def drawdown_integrity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    legacy = metrics.get("max_drawdown_bps")
    buckets = exit_bucket_net_bps(trades)
    authoritative = max_drawdown_from_buckets_bps(buckets)
    symbols = sorted({str(x.get("symbol") or "UNKNOWN") for x in trades})
    result = {
        "schema_version": "zel.a1.multisymbol_realized_dd_integrity.v1",
        "state": "PASS_REALIZED_DD_EXIT_BUCKET_ORDERING",
        "ordering_authority": "EXIT_TIMESTAMP_BUCKET_ASC",
        "simultaneous_exit_ordering": "NET_PNL_AGGREGATED_PER_EXIT_TS",
        "append_order_independent": True,
        "trade_count": len(trades),
        "exit_bucket_count": len(buckets),
        "symbol_count": len(symbols),
        "symbols": symbols,
        "legacy_receipt_max_drawdown_bps": float(legacy) if isinstance(legacy, (int, float)) and math.isfinite(float(legacy)) else None,
        "realized_exit_bucket_max_drawdown_bps": authoritative,
        "legacy_dd_authoritative": len(symbols) <= 1,
        "legacy_vs_realized_delta_bps": None if not isinstance(legacy, (int, float)) or not math.isfinite(float(legacy)) else authoritative - float(legacy),
        "note": "For multi-symbol receipts, use realized_exit_bucket_max_drawdown_bps as the authoritative realized portfolio DD. Legacy receipt DD may reflect symbol append order.",
    }
    return result


def self_test() -> int:
    # Deliberately symbol-appended order: legacy path sees +100,-120,-100,+150.
    # Chronological exit buckets see -100,+100,+150,-120.
    trades = [
        {"symbol": "BTC-USDT", "exit_ts": 2, "net_bps": 100.0},
        {"symbol": "BTC-USDT", "exit_ts": 4, "net_bps": -120.0},
        {"symbol": "ETH-USDT", "exit_ts": 1, "net_bps": -100.0},
        {"symbol": "ETH-USDT", "exit_ts": 3, "net_bps": 150.0},
    ]
    legacy = max_drawdown_from_buckets_bps([{"net_bps": x["net_bps"]} for x in trades])
    corrected = realized_drawdown_bps(trades)
    assert legacy == 220.0, legacy
    assert corrected == 120.0, corrected

    # Same timestamp must be order-independent: +200 and -180 realize as +20.
    simultaneous = [
        {"symbol": "BTC-USDT", "exit_ts": 10, "net_bps": 200.0},
        {"symbol": "ETH-USDT", "exit_ts": 10, "net_bps": -180.0},
        {"symbol": "SOL-USDT", "exit_ts": 11, "net_bps": -10.0},
    ]
    buckets = exit_bucket_net_bps(simultaneous)
    assert buckets[0]["net_bps"] == 20.0 and buckets[0]["trade_count"] == 2, buckets
    assert realized_drawdown_bps(simultaneous) == 10.0
    print("PASS_A1_MULTISYMBOL_REALIZED_DD_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.receipt is None:
        raise RuntimeError("--receipt REQUIRED")
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    result = drawdown_integrity(receipt)
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
