from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

streak: Any = importlib.import_module(
    "backend.research.rebuild.a1_keltner_holygrail_streak_guard_v11"
)
v2, sm, web6, v9, rr = streak.v2, streak.sm, streak.web6, streak.v9, streak.rr
TF = 1_800_000
EXP = ("ADA-USDT", "AVAX-USDT", "SUI-USDT", "LTC-USDT")
ROOT = Path("/home/z/z/runtime/keltner_universe_1m_180d_v2/data")
START_MS = 1773822000000
END_MS = 1789374000000


def one_minute_path(symbol: str) -> Path:
    return ROOT / f"{symbol.replace('-', '')}_1m_{START_MS}_{END_MS}.csv.gz"


def load_5m(symbol: str) -> pd.DataFrame:
    p = one_minute_path(symbol)
    x = pd.read_csv(p)
    x = x.rename(columns={"timestamp_ms": "ts_ms"})
    x = x.sort_values("ts_ms").reset_index(drop=True)
    if len(x) != 259200:
        raise RuntimeError(f"ONE_MINUTE_ROW_COUNT:{symbol}:{len(x)}")
    if any(
        int(x.iloc[i]["ts_ms"]) + 60_000 != int(x.iloc[i + 1]["ts_ms"])
        for i in range(len(x) - 1)
    ):
        raise RuntimeError(f"ONE_MINUTE_GAP:{symbol}")
    x["grp"] = range(len(x))
    x["grp"] = x["grp"] // 5
    y = (
        x.groupby("grp", sort=True)
        .agg(
            ts_ms=("ts_ms", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index(drop=True)
    )
    if len(y) != 51840:
        raise RuntimeError(f"FIVE_MINUTE_ROW_COUNT:{symbol}:{len(y)}")
    return y


def replay_symbol(
    symbol: str, frame5: pd.DataFrame, cost_bps: float, spec: dict[str, Any]
) -> list[dict[str, Any]]:
    frame30 = v2.util.enrich(v2.util.resample_frame(frame5, 6))
    frame30 = web6.enrich_web(frame30)
    state = web6.WebState()
    out: list[dict[str, Any]] = []
    i = 121
    while i < len(frame30) - 1:
        signal = v9.rearm_signal(state, i, frame30, spec, cost_bps)
        if signal is None:
            i += 1
            continue
        trade, exit_j = streak.simulate_fee_be(signal, frame30, cost_bps)
        if trade is not None:
            trade["symbol"] = symbol
            out.append(trade)
        i = max(i + 1, exit_j + 1)
    return out


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    trades = sorted(trades, key=lambda t: (int(t["exit_ts"]), str(t["symbol"])))
    m = rr.metrics(trades)
    m["MaxLossStreak"] = streak.max_loss_streak(trades)
    if trades:
        span_days = (
            int(trades[-1]["exit_ts"]) - int(trades[0]["signal_ts"])
        ) / 86_400_000
        m["span_days"] = span_days
        m["T_per_day"] = len(trades) / span_days if span_days > 0 else None
        m["unique_signal_days"] = len(
            {int(t["signal_ts"]) // 86_400_000 for t in trades}
        )
    return m


def main() -> int:
    if not Path(
        "/home/z/z/runtime/keltner_universe_1m_180d_v2/MANIFEST_1M.json"
    ).exists():
        raise RuntimeError("EXPANSION_BACKFILL_NOT_COMPLETE")
    v9.COST_GATE = streak.COST_GATE
    all_spec = sm.load_spec()
    spec_all = web6.build_case_spec(all_spec, "keltner_trend", TF)
    spec = spec_all["children"]["keltner_trend"]
    auth = v2.read_json(v2.COST_PATH)
    costs = {
        s: float(
            v2.cost_ev.fetch_execution_snapshot(s, auth)["pretrade_verified_cost_bps"]
        )
        for s in EXP
    }
    exp_trades: list[dict[str, Any]] = []
    per_symbol = {}
    for symbol in EXP:
        tr = replay_symbol(symbol, load_5m(symbol), costs[symbol], spec)
        exp_trades.extend(tr)
        per_symbol[symbol] = summarize(tr)
        print(
            "KELTNER_EXP_SYMBOL="
            + json.dumps(
                {
                    "symbol": symbol,
                    **{
                        k: per_symbol[symbol].get(k)
                        for k in (
                            "T",
                            "WR",
                            "Exp_bps_T",
                            "PF",
                            "MaxLossStreak",
                            "T_per_day",
                        )
                    },
                },
                sort_keys=True,
            ),
            flush=True,
        )
    base_trades, _, _ = streak.replay()
    combined = sorted(
        base_trades + exp_trades, key=lambda t: (int(t["exit_ts"]), str(t["symbol"]))
    )
    full = summarize(combined)
    cut = int(len(combined) * 0.60)
    hold = summarize(combined[cut:])
    out = {
        "schema": "zel.a1.keltner_holygrail.universe_expansion.v12",
        "state": "DEV_REPLAY_COMPLETE_NOT_FRESH_OOS",
        "base_symbols": list(v2.SYMS6),
        "expansion_symbols": list(EXP),
        "entry_gate_atr_cost": streak.COST_GATE,
        "rr_core": "streak_guard_v11",
        "costs_expansion": costs,
        "per_expansion_symbol": per_symbol,
        "combined": full,
        "combined_holdout40_dev": hold,
        "research_only": True,
        "live_trade_authority": "BLOCKED",
        "trades": combined,
    }
    Path("/home/z/z/runtime/keltner_universe_expansion_v12.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n"
    )
    print(
        "KELTNER_EXP_COMBINED="
        + json.dumps(
            {
                k: full.get(k)
                for k in (
                    "T",
                    "WR",
                    "Exp_bps_T",
                    "PF",
                    "DD_bps",
                    "MaxLossStreak",
                    "T_per_day",
                    "unique_signal_days",
                )
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
