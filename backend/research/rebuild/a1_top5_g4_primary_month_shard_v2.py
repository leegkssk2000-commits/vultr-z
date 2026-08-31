#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as core

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_primary_month_sharded_fasttrack_v2.json"
SCHEMA = "zel.a1.top5.g4.primary_month_shard.receipt.v2"
LANE_ID = "trend_rider_primary_wr8125"
ALLOWED_SYMBOLS = {"BTC-USDT", "ETH-USDT"}

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def days(start_ms: int, end_ms: int) -> float:
    return max(0.0, (end_ms - start_ms) / 86_400_000.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--window-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    symbol = str(args.symbol).upper()
    if symbol not in ALLOWED_SYMBOLS:
        raise RuntimeError(f"SYMBOL_NOT_PREREGISTERED:{symbol}")

    contract = read(CONTRACT)
    windows = {str(x["window_id"]): dict(x) for x in contract.get("historical_windows", [])}
    if args.window_id not in windows:
        raise RuntimeError(f"WINDOW_NOT_PREREGISTERED:{args.window_id}")
    window = windows[args.window_id]
    start_ms = utc_ms(str(window["start_utc"]))
    end_ms = utc_ms(str(window["end_utc"]))

    trades, source = core.primary_trades(start_ms, end_ms, [symbol])
    rows = [dict(x) for x in trades if start_ms <= int(x["signal_ts"]) < end_ms]
    if len(rows) != len(trades):
        raise RuntimeError("PRIMARY_MONTH_WINDOW_LEAKAGE")
    if any(str(x.get("lane_id")) != LANE_ID for x in rows):
        raise RuntimeError("PRIMARY_MONTH_LANE_DRIFT")
    if any(str(x.get("symbol")) != symbol for x in rows):
        raise RuntimeError("PRIMARY_MONTH_SYMBOL_DRIFT")
    trade_ids = [str(x.get("trade_id") or "") for x in rows]
    if any(not x for x in trade_ids) or len(set(trade_ids)) != len(trade_ids):
        raise RuntimeError("PRIMARY_MONTH_DUPLICATE_OR_EMPTY_TRADE_ID")

    payload = {
        "schema_version": SCHEMA,
        "state": "PRIMARY_MONTH_SHARD_OK",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": file_sha(CONTRACT),
        "lane_id": LANE_ID,
        "symbol": symbol,
        "window_id": args.window_id,
        "window": window,
        "source": source,
        "metrics": core.metrics(rows, days(start_ms, end_ms)),
        "trades": rows,
        "integrity": {
            "signal_ts_inside_preregistered_window": True,
            "unique_trade_ids": True,
            "symbol_exact": True,
            "lane_exact": True,
            "strategy_semantics_changed": False,
            "threshold_sweep": False,
            "window_sweep": False,
            "cost_bps_per_trade": core.COST_BPS,
        },
        "formal_credit": {"fresh_g4_T": 0, "g5_T": 0},
        "paid_provider_calls": 0,
        **AUTH,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "symbol": symbol,
        "window_id": args.window_id,
        "closed_T": payload["metrics"]["closed_T"],
        "net_pnl_bps": payload["metrics"]["net_pnl_bps"],
        "profit_factor": payload["metrics"]["profit_factor"],
        "out": str(out),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
