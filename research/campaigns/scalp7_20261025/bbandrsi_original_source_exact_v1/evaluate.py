"""BbandRsi source-anchored bounded spot-equivalent 1h economic screening.

No API, no exchange orders, no Paper/Live. Underlying native OHLC is used-DEV.
The original Freqtrade RSI/Bollinger signal is reproduced; intrabar ROI/SL fills
remain conservative approximations, NOT a claim of engine fill parity.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
HOUR = 3_600_000
ONE_UNIT_BPS = 10_000.0
BAND_WINDOW = 20
RSI_WINDOW = 14
STOP = 0.75
ROI = 1.10


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def wilder_rsi_talib_seeded(close: np.ndarray, period: int = RSI_WINDOW) -> np.ndarray:
    """TA-Lib RSI average of first 14 deltas followed by Wilder recursion."""
    prices = np.asarray(close, dtype=np.float64)
    out = np.full(prices.shape, np.nan, dtype=np.float64)
    if len(prices) <= period:
        return out
    diffs = np.diff(prices)
    up = np.maximum(diffs, 0.0)
    down = np.maximum(-diffs, 0.0)
    avg_gain = float(np.mean(up[:period]))
    avg_loss = float(np.mean(down[:period]))

    def relative_strength(gain: float, loss: float) -> float:
        total = gain + loss
        return 100.0 * gain / total if total else 0.0

    out[period] = relative_strength(avg_gain, avg_loss)
    for i in range(period + 1, len(prices)):
        avg_gain = (avg_gain * (period - 1) + float(up[i - 1])) / period
        avg_loss = (avg_loss * (period - 1) + float(down[i - 1])) / period
        out[i] = relative_strength(avg_gain, avg_loss)
    return out


def indicators(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.copy()
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    # technical/vendor/qtpylib/indicators.py: bollinger_bands invokes
    # rolling_mean(...,min_periods=1) and rolling_std(...,min_periods=1)
    # -> pandas rolling std ddof=1. Old screen incorrectly used ddof=0.
    mean = typical.rolling(BAND_WINDOW, min_periods=1).mean()
    std = typical.rolling(BAND_WINDOW, min_periods=1).std(ddof=1)
    frame["rsi14"] = wilder_rsi_talib_seeded(frame["close"].to_numpy())
    frame["boll_lower"] = mean - 2.0 * std
    frame["signal_long"] = (frame["rsi14"] < 30.0) & (
        frame["close"] < frame["boll_lower"]
    )
    frame["signal_exit"] = frame["rsi14"] > 70.0
    return frame


def simulate_symbol(
    frame: pd.DataFrame, fee_bps: float, entry_delay_bars: int = 0
) -> dict[str, Any]:
    """One native long open at a time, original ROI/stop, spot-only 1 unit."""
    assert entry_delay_bars in (0, 1)
    assert fee_bps in (20, 40)
    if frame.empty:
        raise ValueError("NO_DATA")
    trades = []
    cash_profit = 0.0
    position: dict[str, Any] | None = None
    planned_entry_index: int | None = None
    planned_exit_index: int | None = None
    equity_curve = []
    exit_price: float | None = None
    signal_count = int(frame["signal_long"].sum())
    skipped_open_signals = 0
    open_at_end = None
    for i in range(len(frame)):
        bar = frame.iloc[i]
        start_price = float(bar["open"])
        close_price = float(bar["close"])
        low = float(bar["low"])
        high = float(bar["high"])
        if (
            not 0
            < low
            <= min(start_price, close_price)
            <= max(start_price, close_price)
            <= high
        ):
            raise ValueError("INVALID_OHLC")
        if planned_exit_index == i and position is not None:
            # Signal observed only at *prior completed close*, exit
            # hypothetically at this candle open; cannot exit the prior close.
            reason = "RSI_GT70_NEXT_OPEN"
            exit_price = start_price
            planned_exit_index = None
            gross = exit_price / float(position["entry_price"]) - 1.0
            cash_profit += gross - fee_bps / 2.0 / ONE_UNIT_BPS
            trades.append(
                {
                    "entry_ts_ms": position["entry_ts_ms"],
                    "exit_ts_ms": int(bar["ts_ms"]),
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "gross_bps": gross * ONE_UNIT_BPS,
                    "net_bps": gross * ONE_UNIT_BPS - fee_bps,
                    "reason": reason,
                }
            )
            position = None
        if planned_entry_index == i and position is None:
            position = {
                "entry_index": i,
                "entry_ts_ms": int(bar["ts_ms"]),
                "entry_price": start_price,
            }
            cash_profit -= fee_bps / 2.0 / ONE_UNIT_BPS
            planned_entry_index = None
        if position is not None:
            entry = float(position["entry_price"])
            stop_price = entry * STOP
            roi_price = entry * ROI
            why = None
            exit_price = None
            if start_price <= stop_price:
                why = "STOP_GAP_ACTUAL_OPEN"
                exit_price = start_price
            elif low <= stop_price:
                why = "STOP_FIRST"
                exit_price = stop_price
            elif high >= roi_price:
                why = "ROI_10PCT"
                exit_price = roi_price
            if why is not None:
                assert exit_price is not None
                gross = float(exit_price) / entry - 1.0
                cash_profit += gross - fee_bps / 2.0 / ONE_UNIT_BPS
                trades.append(
                    {
                        "entry_ts_ms": position["entry_ts_ms"],
                        "exit_ts_ms": int(bar["ts_ms"]),
                        "entry_price": entry,
                        "exit_price": float(exit_price),
                        "gross_bps": gross * ONE_UNIT_BPS,
                        "net_bps": gross * ONE_UNIT_BPS - fee_bps,
                        "reason": why,
                    }
                )
                position = None
                planned_exit_index = None
        # EOD mark includes STILL OPEN loss; entry half roundtrip cost
        # is already deducted. Force-liquidation forecast is tracked separately.
        mtm = (close_price / float(position["entry_price"]) - 1) if position else 0.0
        equity_curve.append(1.0 + cash_profit + mtm)
        if i == len(frame) - 1:
            break
        if (
            position is not None
            and bool(bar["signal_exit"])
            and planned_exit_index is None
        ):
            planned_exit_index = i + 1
        if (
            position is None
            and planned_entry_index is None
            and bool(bar["signal_long"])
        ):
            if i + 1 + entry_delay_bars < len(frame):
                planned_entry_index = i + 1 + entry_delay_bars
        elif position is not None and bool(bar["signal_long"]):
            skipped_open_signals += 1
    last_mark = float(frame.iloc[-1]["close"])
    if position is not None:
        gross_open = last_mark / float(position["entry_price"]) - 1.0
        open_at_end = {
            "entry_ts_ms": int(position["entry_ts_ms"]),
            "entry_price": float(position["entry_price"]),
            "last_mark_price": last_mark,
            "unrealized_gross_bps": gross_open * ONE_UNIT_BPS,
            "hypothetical_net_bps_at_last_close_after_exit_fee": (
                gross_open * ONE_UNIT_BPS - fee_bps
            ),
            "not_realized": True,
        }
    return {
        "signals_T": signal_count,
        "entered_T": len(trades) + int(position is not None),
        "closed_T": len(trades),
        "still_open_T": int(position is not None),
        "skipped_signals_while_owned": skipped_open_signals,
        "trades": trades,
        "open_at_end": open_at_end,
        "equity_curve": equity_curve,
        "terminal_equity_unit": equity_curve[-1],
        "terminal_equity_if_marked_liquidation": equity_curve[-1]
        - (fee_bps / 2 / ONE_UNIT_BPS if position else 0),
    }


def summarize_run(results: dict[str, Any], fee_bps: float) -> dict[str, Any]:
    trades = [
        {**t, "symbol": s}
        for s, record in sorted(results.items())
        for t in record["trades"]
    ]
    vals = [float(t["net_bps"]) for t in trades]
    wins = sum(max(0.0, v) for v in vals)
    losses = -sum(min(0.0, v) for v in vals)
    ordered = sorted(trades, key=lambda t: (t["exit_ts_ms"], t["symbol"]))
    runloss = maxloss = 0
    for row in ordered:
        runloss = runloss + 1 if row["net_bps"] < 0 else 0
        maxloss = max(maxloss, runloss)
    m = len(next(iter(results.values()))["equity_curve"])
    if any(len(x["equity_curve"]) != m for x in results.values()):
        raise ValueError("MISALIGNED_MARKET_CLOCK")
    eq = [
        sum(float(rec["equity_curve"][i]) for rec in results.values()) for i in range(m)
    ]
    peak = 12.0
    maxdd = 0.0
    maxddpct = 0.0
    for value in eq:
        peak = max(peak, value)
        maxdd = max(maxdd, peak - value)
        maxddpct = max(maxddpct, (peak - value) / peak)
    openlegs = [
        {"symbol": sym, **r["open_at_end"]}
        for sym, r in results.items()
        if r["open_at_end"] is not None
    ]
    completed_net = sum(vals)
    final_liquidate = sum(
        x["terminal_equity_if_marked_liquidation"] for x in results.values()
    )
    return {
        "closed_trades_T": len(trades),
        "entered_T": sum(x["entered_T"] for x in results.values()),
        "open_positions_T": len(openlegs),
        "open_positions": openlegs,
        "original_matching_signal_candles_T": sum(
            x["signals_T"] for x in results.values()
        ),
        "closed_only_Net_sum_trade_bps": completed_net,
        "closed_only_PF": wins / losses if losses else None,
        "closed_only_winrate": sum(v > 0 for v in vals) / len(vals) if vals else None,
        "closed_only_max_consecutive_losses": maxloss,
        "closed_only_largest_winner_bps": max(vals) if vals else None,
        "closed_only_worst_loser_bps": min(vals) if vals else None,
        "closed_only_Net_excluding_best2_bps": completed_net
        - sum(sorted([x for x in vals if x > 0], reverse=True)[:2]),
        "open_unrealized_gross_sum_bps": sum(
            x["unrealized_gross_bps"] for x in openlegs
        ),
        "terminal_Net_including_open_marks_equal_units_pct": 100 * (eq[-1] / 12 - 1),
        "terminal_Net_if_all_open_settled_at_last_close_pct": 100
        * (final_liquidate / 12 - 1),
        "portfolio_mark_to_market_max_drawdown_pct": maxddpct * 100,
        "portfolio_mark_to_market_max_drawdown_capital_units": maxdd,
        "initial_capital_units": 12,
        "max_concurrent_open_possible": 12,
        "leverage": 1,
        "account_return_claim": False,
        "realized_funding_verified": False,
        "source_received_at_causal_history": False,
        "trade_ledger": trades,
        "equity_curve_12_equal_units": eq,
        "fee_bps_per_completed_roundtrip": fee_bps,
    }


def run(target: Path) -> dict[str, Any]:
    freeze = (ROOT / "FREEZE.json").read_bytes()
    spec = json.loads(freeze)
    src = ROOT.parent / "trendrider_two_stage_v1/MARKET_1H_SNAPSHOT.json.gz"
    raw = src.read_bytes()
    if (
        spec["schema"]
        != "zel.bbandrsi.public_source_exact_port_spot_risk_screen.freeze.v1"
        or sha(raw) != spec["source_1h_snapshot_sha256"]
    ):
        raise RuntimeError("FROZEN_INPUT_CHANGED")
    archive = json.loads(gzip.decompress(raw))
    seen = dt.datetime.fromisoformat(archive["utc_retrieved_at"])
    cutoff_ms = int(seen.timestamp() * 1000)
    market = {}
    expected_ts = None
    excluded_forming = {}
    for symbol, bars in sorted(archive["symbols"].items()):
        frame = pd.DataFrame(bars)
        # Protect LAST still-forming archived 1h candle, all historical
        # received_at are still UNKNOWN (as documented).
        complete = (
            frame[frame["ts_ms"] + HOUR <= cutoff_ms].copy().reset_index(drop=True)
        )
        excluded_forming[symbol] = len(frame) - len(complete)
        if len(complete) < 20:
            raise RuntimeError("INSUFFICIENT_CLOSED_1H")
        ts = complete["ts_ms"].to_numpy(dtype=np.int64)
        if not np.all(np.diff(ts) == HOUR):
            raise RuntimeError("MISSING_SOURCE_1H")
        if expected_ts is None:
            expected_ts = ts
        elif not np.array_equal(ts, expected_ts):
            raise RuntimeError("MISALIGNED_SYMBOL_TIMELINE")
        market[symbol] = indicators(complete)
    assert expected_ts is not None
    runs: dict[str, Any] = {}
    for latency in (0, 1):
        for cost in (20, 40):
            cases = {
                symbol: simulate_symbol(frame, cost, latency)
                for symbol, frame in market.items()
            }
            name = f"fee{cost}_delay{latency}h"
            score = summarize_run(cases, cost)
            score["per_symbol"] = cases
            runs[name] = score
            print(
                "SCREEN",
                name,
                "CLOSED",
                score["closed_trades_T"],
                "OPEN",
                score["open_positions_T"],
                "CLOSED_NET_BPS",
                round(score["closed_only_Net_sum_trade_bps"], 2),
                "EQUITY_NET_MTM_PCT",
                round(score["terminal_Net_including_open_marks_equal_units_pct"], 3),
                "PORTFOLIO_DD_PCT",
                round(score["portfolio_mark_to_market_max_drawdown_pct"], 3),
                flush=True,
            )
    output = {
        "schema": "zel.bbandrsi.public_source_exact_spot_screen.result.v1",
        "frozen_sha256": sha(freeze),
        "source_1h_sha256": sha(raw),
        "source_used_data_not_OOS": True,
        "source_asof": archive["utc_retrieved_at"],
        "first_and_last_complete_1h_open_ms": [
            int(expected_ts[0]),
            int(expected_ts[-1]),
        ],
        "forming_last_hour_excluded_each_symbol": excluded_forming,
        "source_signal_exactness": "RSI14_WILDER_SEEDED_AND_QTPYLIB_STD_SAMPLE_1",
        "execution_limitations": "NO_TALIB_FREQTRADE_ENGINE_FULL_PARITY; MODEL_SPOT_NEXT_OPEN_INTRABAR_STOP_FIRST_ONLY; HISTORICAL_RECEIVED_AT_UNKNOWN",
        "risk_transfer_to_BingX_10x_20x": "REJECT_ORIGINAL_25PCT_STOP_FOR_LEVERAGED_FUTURES",
        "formal_shadow_admission": "HOLD",
        "orders": 0,
        "market_api_calls": 0,
        "no_new_full": True,
        "simulations": runs,
    }
    result = (
        json.dumps(output, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    target.write_bytes(result)
    print("COMPLETE_READONLY_RESULT_SHA256", sha(result), flush=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "RESULT.json")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("EXISTING_RESULT_NOT_OVERWRITTEN")
    run(args.output)
