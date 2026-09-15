from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
SELECTED = {
    "supertrend_pullback": Path(
        "/home/z/z/runtime/active5_quality_sweep_v3/supertrend_pullback/cd3.json"
    ),
    "keltner_trend": Path(
        "/home/z/z/runtime/active5_quality_sweep_v3/keltner_trend/cd3.json"
    ),
    "break_and_continue": Path(
        "/home/z/z/runtime/active5_quality_sweep_v3/break_and_continue/baseline.json"
    ),
    "trend_ma_macd": Path(
        "/home/z/z/runtime/active5_quality_sweep_v3/trend_ma_macd/chase120.json"
    ),
    "trend_rider": Path(
        "/home/z/z/runtime/active5_quality_sweep_v2/trend_rider_fast2/body040_cd1.json"
    ),
}
VARIANTS = {
    "tp30_1r": {"tp_r": 1.0, "tp_frac": 0.30},
    "loss25_m05r": {"loss_r": 0.50, "loss_frac": 0.25},
    "tp30_1r_loss25_m05r": {
        "tp_r": 1.0,
        "tp_frac": 0.30,
        "loss_r": 0.50,
        "loss_frac": 0.25,
    },
    "tp30_1r_be": {"tp_r": 1.0, "tp_frac": 0.30, "be_after_tp": True},
    "stale25_12b": {"stale_bars": 12, "stale_frac": 0.25, "stale_mfe_r": 0.50},
    "tp30_1r_stale25_12b": {
        "tp_r": 1.0,
        "tp_frac": 0.30,
        "stale_bars": 12,
        "stale_frac": 0.25,
        "stale_mfe_r": 0.50,
    },
}


def metrics(vals: list[float]) -> dict[str, float | int | None]:
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    eq = peak = dd = 0.0
    for x in vals:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "T": len(vals),
        "WR": len(wins) / len(vals) if vals else None,
        "Net_bps": sum(vals),
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": gp / gl if gl > 0 else None,
        "DD_bps": dd,
    }


def load_bars() -> dict[str, list[dict[str, Any]]]:
    out = {}
    for sym in [
        "BTC-USDT",
        "ETH-USDT",
        "SOL-USDT",
        "XRP-USDT",
        "LINK-USDT",
        "DOGE-USDT",
    ]:
        out[sym] = ev.fetch_bars(sym, "1h", 1000)
    return out


def simulate_trade(
    t: dict[str, Any], bars: list[dict[str, Any]], rule: dict[str, Any]
) -> float:
    entry = float(t["entry"])
    side = 1 if t["side"] == "long" else -1
    geom = t.get("intent_geometry") or {}
    sl = geom.get("sl")
    if sl is None:
        return float(t["net_bps"])
    sl = float(sl)
    rpx = abs(entry - sl)
    _r_bps = rpx / entry * 10000.0
    if rpx <= 0:
        return float(t["net_bps"])
    idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    if int(t["entry_ts"]) not in idx or int(t["exit_ts"]) not in idx:
        return float(t["net_bps"])
    i0, i1 = idx[int(t["entry_ts"])], idx[int(t["exit_ts"])]
    rem = 1.0
    gross_parts = []
    tp_done = loss_done = stale_done = False
    mfe_r = 0.0
    be = False
    final_px = float(t["exit"])
    _final_ts = int(t["exit_ts"])
    for k in range(i0, i1 + 1):
        b = bars[k]
        hi = float(b["high"])
        lo = float(b["low"])
        close = float(b["close"])
        fav = ((hi - entry) if side == 1 else (entry - lo)) / rpx
        adv = ((entry - lo) if side == 1 else (hi - entry)) / rpx
        mfe_r = max(mfe_r, fav)
        # adverse event first, matching baseline SL-first ambiguity policy
        if (
            not loss_done
            and rule.get("loss_r") is not None
            and adv >= float(rule["loss_r"])
            and rem > 0
        ):
            frac = min(rem, float(rule.get("loss_frac", 0.25)) * rem)
            px = entry - side * float(rule["loss_r"]) * rpx
            gross_parts.append(frac * side * (px - entry) / entry * 10000.0)
            rem -= frac
            loss_done = True
        if (
            be
            and rem > 0
            and ((side == 1 and lo <= entry) or (side == -1 and hi >= entry))
        ):
            gross_parts.append(rem * 0.0)
            rem = 0
            _final_ts = int(b["ts_ms"])
            break
        if (
            not tp_done
            and rule.get("tp_r") is not None
            and fav >= float(rule["tp_r"])
            and rem > 0
        ):
            frac = min(rem, float(rule.get("tp_frac", 0.30)) * rem)
            px = entry + side * float(rule["tp_r"]) * rpx
            gross_parts.append(frac * side * (px - entry) / entry * 10000.0)
            rem -= frac
            tp_done = True
            if rule.get("be_after_tp"):
                be = True
        if (
            not stale_done
            and rule.get("stale_bars") is not None
            and k - i0 + 1 >= int(rule["stale_bars"])
            and mfe_r < float(rule.get("stale_mfe_r", 0.5))
            and rem > 0
        ):
            frac = min(rem, float(rule.get("stale_frac", 0.25)) * rem)
            gross_parts.append(frac * side * (close - entry) / entry * 10000.0)
            rem -= frac
            stale_done = True
    if rem > 0:
        gross_parts.append(rem * side * (final_px - entry) / entry * 10000.0)
    gross = sum(gross_parts)
    # Conservative: retain the original full-trade realized cost instead of crediting reduced holding/funding.
    return gross - float(t.get("realized_cost_bps") or 0.0)


def split_metrics(rows: list[dict[str, Any]], values: list[float]) -> dict[str, Any]:
    cut = int(len(rows) * 0.60)
    return {
        "full": metrics(values),
        "train60": metrics(values[:cut]),
        "holdout40": metrics(values[cut:]),
    }


def main() -> int:
    bars = load_bars()
    result: dict[str, Any] = {
        "schema": "zel.a1.active5.partial_overlay.v1",
        "cost_policy": "ORIGINAL_REALIZED_COST_CONSERVATIVE",
        "strategies": {},
    }
    for sid, path in SELECTED.items():
        d = json.loads(path.read_text())
        trades = sorted(
            d.get("trades") or [], key=lambda x: (int(x["exit_ts"]), str(x["symbol"]))
        )
        base = [float(t["net_bps"]) for t in trades]
        item = {"baseline": split_metrics(trades, base), "variants": {}}
        for name, rule in VARIANTS.items():
            vals = [simulate_trade(t, bars[str(t["symbol"])], rule) for t in trades]
            m = split_metrics(trades, vals)
            bm = item["baseline"]["full"]
            fm = m["full"]
            hm = m["holdout40"]
            bh = item["baseline"]["holdout40"]
            m["multi_metric_pass"] = bool(
                fm["T"] == bm["T"]
                and fm["WR"] >= bm["WR"]
                and fm["Net_bps"] >= bm["Net_bps"]
                and (fm["PF"] or 0) >= (bm["PF"] or 0)
                and fm["DD_bps"] <= bm["DD_bps"]
                and hm["Net_bps"] >= bh["Net_bps"]
                and hm["WR"] >= bh["WR"]
            )
            item["variants"][name] = m
        result["strategies"][sid] = item
    out = Path("/home/z/z/runtime/active5_partial_overlay_v1/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for sid, item in result["strategies"].items():
        print("PARTIAL_BASE", sid, json.dumps(item["baseline"]["full"], sort_keys=True))
        for name, m in item["variants"].items():
            print(
                "PARTIAL_ROW",
                sid,
                name,
                json.dumps(
                    {
                        "full": m["full"],
                        "holdout40": m["holdout40"],
                        "pass": m["multi_metric_pass"],
                    },
                    sort_keys=True,
                ),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
