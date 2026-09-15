from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from backend.research.rebuild import a1_exact25_generic_evaluator_three_lane_v1 as ev
from backend.research.rebuild.policy_kernel_v1 import ema

SOURCES = {
    "supertrend_pullback": Path(
        "/home/z/z/runtime/active5_quality_sweep_v3/supertrend_pullback/cd3.json"
    ),
    "keltner_trend": Path(
        "/home/z/z/runtime/active5_quality_sweep_v3/keltner_trend/cd3.json"
    ),
    "break_and_continue": Path("/home/z/z/runtime/active5_break_alt_v1/body040.json"),
    "trend_ma_macd": Path(
        "/home/z/z/runtime/active5_quality_sweep_v3/trend_ma_macd/chase120.json"
    ),
    "trend_rider": Path(
        "/home/z/z/runtime/active5_quality_sweep_v2/trend_rider_fast2/body040_cd1.json"
    ),
}
BASE_RULE = {
    "supertrend_pullback": {"stale_bars": 12, "stale_frac": 0.25, "stale_mfe_r": 0.5},
    "keltner_trend": {"stale_bars": 18, "stale_frac": 0.25, "stale_mfe_r": 0.5},
    "break_and_continue": {
        "stale_bars": 8,
        "stale_frac": 0.25,
        "stale_mfe_r": 0.75,
        "btc_gate": True,
    },
    "trend_ma_macd": {"btc_gate": True},
    "trend_rider": {
        "stale_bars": 24,
        "stale_frac": 0.25,
        "stale_mfe_r": 0.5,
        "btc_gate": True,
    },
}
CANDIDATES = {
    "late_reduce25": {
        "late_mult": 2.0,
        "late_frac": 0.25,
        "late_mfe_r": 0.75,
        "late_max_close_r": 0.0,
    },
    "late_scratch": {
        "late_mult": 2.0,
        "late_exit": True,
        "late_mfe_r": 0.50,
        "late_max_close_r": -0.25,
    },
    "winner15_2r": {"win_r": 2.0, "win_frac": 0.15},
    "trail_2r": {"trail_start_r": 2.0, "trail_gap_r": 1.25, "trail_floor_r": 0.50},
    "winner15_2r_trail": {
        "win_r": 2.0,
        "win_frac": 0.15,
        "trail_start_r": 2.0,
        "trail_gap_r": 1.25,
        "trail_floor_r": 0.50,
    },
    "late_reduce25_trail": {
        "late_mult": 2.0,
        "late_frac": 0.25,
        "late_mfe_r": 0.75,
        "late_max_close_r": 0.0,
        "trail_start_r": 2.0,
        "trail_gap_r": 1.25,
        "trail_floor_r": 0.50,
    },
}


def metric(vals: list[float]) -> dict[str, Any]:
    w = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    eq = pk = dd = 0.0
    for x in vals:
        eq += x
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    return {
        "T": len(vals),
        "WR": len(w) / len(vals) if vals else None,
        "Net_bps": sum(vals),
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": sum(w) / sum(losses) if losses else None,
        "DD_bps": dd,
    }


def bars6() -> dict[str, list[dict[str, Any]]]:
    return {
        s: ev.fetch_bars(s, "1h", 1000)
        for s in [
            "BTC-USDT",
            "ETH-USDT",
            "SOL-USDT",
            "XRP-USDT",
            "LINK-USDT",
            "DOGE-USDT",
        ]
    }


def btc_states(bars: list[dict[str, Any]]) -> dict[int, int]:
    closes = [float(x["close"]) for x in bars]
    e = ema(closes, 50)
    out = {}
    for i, b in enumerate(bars):
        if i < 1:
            continue
        c = closes[i]
        out[int(b["ts_ms"])] = (
            1
            if c > e[i] and e[i] > e[i - 1]
            else (-1 if c < e[i] and e[i] < e[i - 1] else 0)
        )
    return out


def gate_trade(t: dict[str, Any], states: dict[int, int]) -> bool:
    ts = int(t["signal_ts"])
    candidates = [k for k in states if k <= ts]
    if not candidates:
        return False
    st = states[max(candidates)]
    side = 1 if t["side"] == "long" else -1
    return st == side


def simulate(
    t: dict[str, Any],
    bars: list[dict[str, Any]],
    base: dict[str, Any],
    extra: dict[str, Any],
) -> float:
    entry = float(t["entry"])
    side = 1 if t["side"] == "long" else -1
    geom = t.get("intent_geometry") or {}
    sl = geom.get("sl")
    if sl is None:
        return float(t["net_bps"])
    sl = float(sl)
    rpx = abs(entry - sl)
    if rpx <= 0:
        return float(t["net_bps"])
    idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    i0 = idx.get(int(t["entry_ts"]))
    i1 = idx.get(int(t["exit_ts"]))
    if i0 is None or i1 is None:
        return float(t["net_bps"])
    rem = 1.0
    parts = []
    mfe = 0.0
    stale_done = late_done = win_done = False
    peak_prior = 0.0
    final = float(t["exit"])
    for k in range(i0, i1 + 1):
        b = bars[k]
        hi = float(b["high"])
        lo = float(b["low"])
        cl = float(b["close"])
        bars_held = k - i0 + 1
        fav = ((hi - entry) if side == 1 else (entry - lo)) / rpx
        close_r = side * (cl - entry) / rpx
        # trailing uses only peak known before this bar; adverse check first.
        if peak_prior >= float(extra.get("trail_start_r", 1e9)) and rem > 0:
            tr = max(
                float(extra.get("trail_floor_r", 0)),
                peak_prior - float(extra.get("trail_gap_r", 1.0)),
            )
            hit = (lo <= entry + tr * rpx) if side == 1 else (hi >= entry - tr * rpx)
            if hit:
                px = entry + side * tr * rpx
                parts.append(rem * side * (px - entry) / entry * 10000)
                rem = 0
                break
        mfe = max(mfe, fav)
        if (
            not stale_done
            and base.get("stale_bars")
            and bars_held >= int(base["stale_bars"])
            and mfe < float(base["stale_mfe_r"])
            and rem > 0
        ):
            frac = min(rem, float(base["stale_frac"]) * rem)
            parts.append(frac * side * (cl - entry) / entry * 10000)
            rem -= frac
            stale_done = True
        late_bar = int(
            round(
                float(base.get("stale_bars") or 24) * float(extra.get("late_mult", 999))
            )
        )
        if (
            not late_done
            and extra.get("late_mult")
            and bars_held >= late_bar
            and mfe < float(extra.get("late_mfe_r", 0.75))
            and close_r <= float(extra.get("late_max_close_r", 0))
            and rem > 0
        ):
            if extra.get("late_exit"):
                parts.append(rem * side * (cl - entry) / entry * 10000)
                rem = 0
            else:
                frac = min(rem, float(extra.get("late_frac", 0.25)) * rem)
                parts.append(frac * side * (cl - entry) / entry * 10000)
                rem -= frac
            late_done = True
        if (
            not win_done
            and extra.get("win_r") is not None
            and fav >= float(extra["win_r"])
            and rem > 0
        ):
            frac = min(rem, float(extra.get("win_frac", 0.15)) * rem)
            px = entry + side * float(extra["win_r"]) * rpx
            parts.append(frac * side * (px - entry) / entry * 10000)
            rem -= frac
            win_done = True
        peak_prior = max(peak_prior, fav)
    if rem > 0:
        parts.append(rem * side * (final - entry) / entry * 10000)
    return sum(parts) - float(t.get("realized_cost_bps") or 0)


def split(rows: list[dict[str, Any]], vals: list[float]) -> dict[str, Any]:
    cut = int(len(rows) * 0.60)
    return {
        "full": metric(vals),
        "train60": metric(vals[:cut]),
        "holdout40": metric(vals[cut:]),
    }


def main() -> int:
    bars = bars6()
    states = btc_states(bars["BTC-USDT"])
    res = {
        "schema": "zel.a1.active5.lifecycle_overlay.v2",
        "research_only": True,
        "strategies": {},
    }
    portfolio = {name: [] for name in ["baseline", *CANDIDATES]}
    portfolio_rows = {name: [] for name in portfolio}
    for sid, path in SOURCES.items():
        d = json.loads(path.read_text())
        tr = sorted(
            d.get("trades") or [], key=lambda x: (int(x["exit_ts"]), str(x["symbol"]))
        )
        base = BASE_RULE[sid]
        if base.get("btc_gate"):
            tr = [t for t in tr if gate_trade(t, states)]
        basevals = [simulate(t, bars[str(t["symbol"])], base, {}) for t in tr]
        item = {"baseline": split(tr, basevals), "variants": {}}
        portfolio["baseline"] += basevals
        portfolio_rows["baseline"] += tr
        for name, extra in CANDIDATES.items():
            vals = [simulate(t, bars[str(t["symbol"])], base, extra) for t in tr]
            m = split(tr, vals)
            bm = item["baseline"]
            fm = m["full"]
            hm = m["holdout40"]
            m["pass"] = bool(
                fm["T"] == bm["full"]["T"]
                and fm["Net_bps"] >= bm["full"]["Net_bps"]
                and (fm["PF"] or 0) >= (bm["full"]["PF"] or 0)
                and fm["DD_bps"] <= bm["full"]["DD_bps"]
                and fm["WR"] >= bm["full"]["WR"]
                and hm["Net_bps"] >= bm["holdout40"]["Net_bps"]
                and hm["WR"] >= bm["holdout40"]["WR"]
            )
            item["variants"][name] = m
            portfolio[name] += vals
            portfolio_rows[name] += tr
        res["strategies"][sid] = item
    res["portfolio"] = {}
    for name, vals in portfolio.items():
        rows = portfolio_rows[name]
        order = sorted(
            range(len(rows)),
            key=lambda i: (int(rows[i]["exit_ts"]), str(rows[i]["symbol"])),
        )
        sv = [vals[i] for i in order]
        sr = [rows[i] for i in order]
        res["portfolio"][name] = split(sr, sv)
    out = Path("/home/z/z/runtime/active5_lifecycle_overlay_v2/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    print("PORT_BASE", json.dumps(res["portfolio"]["baseline"], sort_keys=True))
    for n in CANDIDATES:
        print("PORT_ROW", n, json.dumps(res["portfolio"][n], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
