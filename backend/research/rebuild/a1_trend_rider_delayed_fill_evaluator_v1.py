#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as v1
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as v2
from backend.research.rebuild import trend_policy_batch_v1 as policy
from backend.research.rebuild.a1_exact25_survivor_gate_v1 import stable_sha
from backend.research.rebuild.policy_kernel_v1 import atr


def build_parent(symbols: str, output: Path, boundary: str) -> dict[str, Any]:
    ledger = json.loads(v1.LEDGER_PATH.read_text())
    ledger["strategies"]["trend_rider"]["prospective_boundary_utc"] = boundary
    ledger["strategies"]["trend_rider"]["status"] = "ACTIVE"
    original_path = v1.LEDGER_PATH
    with tempfile.TemporaryDirectory(prefix="trend-rider-delayed-fill-") as tmp:
        ledger_path = Path(tmp) / "ledger.json"
        ledger_path.write_text(json.dumps(ledger, sort_keys=True))
        v1.LEDGER_PATH = ledger_path
        old_argv = sys.argv
        try:
            sys.argv = [
                "a1_exact25_generic_evaluator_v2",
                "--strategy-id", "trend_rider",
                "--symbols", symbols,
                "--out", str(output),
            ]
            v2.main()
        finally:
            sys.argv = old_argv
            v1.LEDGER_PATH = original_path
    return json.loads(output.read_text())


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(x["net_bps"]) for x in trades]
    gross = [float(x["gross_bps"]) for x in trades]
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    return {
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "net_profit_factor": v1.profit_factor(gp, gl),
        "net_payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_bps": v1.max_drawdown(values),
    }


def transform(parent: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    config = policy.TrendPolicyConfig()
    symbols = sorted({str(x["symbol"]) for x in parent.get("trades") or []})
    bars_by = {symbol: v1.fetch_bars(symbol, "1h", 1000) for symbol in symbols}
    maps = {
        symbol: {int(row["ts_ms"]): index for index, row in enumerate(rows)}
        for symbol, rows in bars_by.items()
    }
    delayed: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for trade in parent.get("trades") or []:
        symbol = str(trade["symbol"])
        bars = bars_by[symbol]
        timestamp_index = maps[symbol]
        entry_index = timestamp_index.get(int(trade["entry_ts"]))
        if entry_index is None or entry_index < 1:
            raise RuntimeError(f"PARENT_ENTRY_BAR_MISSING:{symbol}:{trade['entry_ts']}")
        signal_index = entry_index - 1
        delayed_entry_index = entry_index + 1
        last = min(len(bars) - 1, delayed_entry_index + max(1, config.timeout_bars))
        if delayed_entry_index >= len(bars) or last <= delayed_entry_index:
            dropped.append({"symbol": symbol, "signal_ts": trade["signal_ts"], "reason": "DELAYED_TRADE_NOT_CLOSED"})
            continue
        side = str(trade["side"])
        signal_close = float(bars[signal_index]["close"])
        signal_atr = atr(bars[: signal_index + 1], config.atr_len)
        stop = signal_close - 1.5 * signal_atr if side == "long" else signal_close + 1.5 * signal_atr
        entry = float(bars[delayed_entry_index]["open"])
        exit_price: float | None = None
        exit_index = last
        for index in range(delayed_entry_index, last + 1):
            low = float(bars[index]["low"])
            high = float(bars[index]["high"])
            if (side == "long" and low <= stop) or (side == "short" and high >= stop):
                exit_price = float(stop)
                exit_index = index
                break
        if exit_price is None:
            exit_price = float(bars[last]["close"])
        cost = float(trade["realized_cost_bps"])
        gross = (1.0 if side == "long" else -1.0) * (exit_price / entry - 1.0) * 10000.0
        row = {
            **trade,
            "entry": entry,
            "exit": exit_price,
            "entry_ts": int(bars[delayed_entry_index]["ts_ms"]),
            "exit_ts": int(bars[exit_index]["ts_ms"]),
            "gross_bps": gross,
            "net_bps": gross - cost,
            "entry_delay_bars": 1,
            "parent_entry_ts": int(trade["entry_ts"]),
            "parent_intent_sha": trade.get("intent_sha"),
        }
        row["intent_sha"] = stable_sha({
            "challenger_id": contract["challenger_id"],
            "parent_intent_sha": trade.get("intent_sha"),
            "entry_ts": row["entry_ts"],
            "exit_ts": row["exit_ts"],
        })
        delayed.append(row)
    delayed.sort(key=lambda row: (int(row["entry_ts"]), str(row["symbol"])))
    receipt = dict(parent)
    receipt.update({
        "schema_version": "zel.a1.trend_rider.delayed_fill_economics.v1",
        "challenger_id": contract["challenger_id"],
        "parent_strategy_id": "trend_rider",
        "changed_axis": contract["changed_axis"],
        "contract_sha256": stable_sha(contract),
        "trades": delayed,
        "completed_trades": len(delayed),
        "intent_count": len(delayed),
        "metrics": metrics(delayed),
        "config_sha": stable_sha({
            "parent_config_sha": parent.get("config_sha"),
            "entry_delay_bars": 1,
            "stop_geometry_changed": False,
            "timeout_bars_changed": False,
        }),
        "delayed_fill_integrity": {
            "state": "PASS",
            "parent_completed_trades": int(parent.get("completed_trades") or 0),
            "delayed_completed_trades": len(delayed),
            "not_closed_after_delay_count": len(dropped),
            "dropped_sha256": stable_sha(dropped),
            "entry_delay_bars": 1,
            "signal_policy_changed": False,
            "cost_model_changed": False,
            "fail_closed": True,
        },
        "state": "A1_REBUILT_ECONOMICS_ACTIVE" if delayed else "WAIT_FRESH_PROSPECTIVE_DATA",
        "parameter_sweep": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    })
    receipt["receipt_sha256"] = stable_sha({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--mode", choices=("development", "prospective"), required=True)
    parser.add_argument("--boundary-utc")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    contract = json.loads(Path(args.contract).read_text())
    ledger = json.loads(v1.LEDGER_PATH.read_text())
    original_boundary = str(ledger["strategies"]["trend_rider"]["prospective_boundary_utc"])
    boundary = args.boundary_utc or original_boundary
    if args.mode == "prospective" and boundary != contract["frozen_at_utc"]:
        raise RuntimeError("PROSPECTIVE_BOUNDARY_MUST_MATCH_FROZEN_CONTRACT")
    output = Path(args.out)
    parent_path = output.with_suffix(".parent.json")
    parent = build_parent(args.symbols, parent_path, boundary)
    receipt = transform(parent, contract)
    receipt["evaluation_mode"] = args.mode
    receipt["prospective_boundary_utc"] = boundary if args.mode == "prospective" else None
    receipt["receipt_sha256"] = stable_sha({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print("A1_TREND_RIDER_DELAYED_FILL=" + json.dumps({
        "mode": args.mode,
        "state": receipt["state"],
        "completed_trades": receipt["completed_trades"],
        "metrics": receipt["metrics"],
        "source_quality_state": (receipt.get("source_quality_gate") or {}).get("state"),
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

