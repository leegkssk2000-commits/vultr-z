"""One frozen RSI2 trend-bounce ZEL hypothesis; offline USED DEV only. No orders or network."""

import json
import hashlib
import datetime
from pathlib import Path
import numpy as np
import pandas as pd

H = 3600000


def ms(x):
    return int(datetime.datetime.fromisoformat(x).timestamp() * 1000)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def validate(t):
    stamps = np.asarray(t, dtype=np.int64)
    if len(stamps) < 240 or not np.all(np.diff(stamps) == H):
        raise ValueError("INCOMPLETE_OR_UNSORTED_SOURCE_HOURS")


def exit_fill(o, h, low, sl, tp, first=False):
    if not first and o <= sl:
        return float(o), "STOP_GAP"
    if low <= sl:
        return float(sl), "STOP_FIRST"
    if not first and o >= tp:
        return float(tp), "TARGET_GAP_CAPPED"
    if h >= tp:
        return float(tp), "TARGET"
    return None, None


def features(df):
    c = df.close.astype(float)
    p = c.shift(1)
    delta = c.diff().fillna(0)
    gains = delta.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    losses = (-delta.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    rsi = 100 * gains / (gains + losses)
    tr = pd.concat(
        [df.high - df.low, (df.high - p).abs(), (df.low - p).abs()], axis=1
    ).max(axis=1)
    return pd.DataFrame(
        dict(
            ema20=c.ewm(span=20, adjust=False).mean(),
            ema200=c.ewm(span=200, adjust=False).mean(),
            rsi2=rsi,
            atr14=tr.ewm(alpha=1 / 14, adjust=False).mean(),
        )
    )


def signal(i, df, f):
    if i < 240 or i < 24:
        return False
    x = f.iloc[i]
    old = f.iloc[i - 24]
    return bool(
        np.isfinite([x.ema20, x.ema200, x.rsi2, x.atr14]).all()
        and x.atr14 > 0
        and x.ema200 > old.ema200
        and df.close.iloc[i] > x.ema200
        and df.close.iloc[i] < x.ema20
        and x.rsi2 <= 10
    )


def source(symbol, root):
    files = sorted((root / symbol).glob("*.csv.gz"))
    if not files:
        raise ValueError("SOURCE_FILES_MISSING:" + symbol)
    parts = []
    pins = {}
    for p in files:
        raw = p.read_bytes()
        pins[p.name] = sha(raw)
        part = pd.read_csv(p)
        if list(part.columns) != [
            "timestamp_ms",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]:
            raise ValueError("SOURCE_SCHEMA_CHANGED")
        parts.append(part)
    df = pd.concat(parts, ignore_index=True)
    validate(df.timestamp_ms.values)
    for x in ("open", "high", "low", "close"):
        if not np.isfinite(df[x]).all() or not (df[x] > 0).all():
            raise ValueError("INVALID_PRICE")
    if not (
        (df.high >= df[["open", "close", "low"]].max(axis=1))
        & (df.low <= df[["open", "close", "high"]].min(axis=1))
    ).all():
        raise ValueError("INVALID_OHLC")
    return df, pins


def simulate(symbol, df, f, start, end):
    times = df.timestamp_ms.values
    trades = []
    censored = []
    i = int(np.searchsorted(times, start))
    while i < len(times) and int(times[i]) < end:
        if not signal(i, df, f):
            i += 1
            continue
        enter_i = i + 1
        if enter_i >= len(times) or int(times[enter_i]) >= end:
            censored.append(
                dict(
                    symbol=symbol,
                    signal_ts_ms=int(times[i]),
                    reason="NO_NEXT_OPEN_IN_WINDOW",
                )
            )
            break
        entry = float(df.open.iloc[enter_i])
        atr = float(f.atr14.iloc[i])
        sl = entry - 1.5 * atr
        tp = entry + 3 * atr
        if sl <= 0:
            i += 1
            continue
        exit_i = None
        reason = None
        exitprice = None
        for j in range(enter_i, min(enter_i + 24, len(times))):
            if int(times[j]) >= end:
                break
            exitprice, reason = exit_fill(
                float(df.open.iloc[j]),
                float(df.high.iloc[j]),
                float(df.low.iloc[j]),
                sl,
                tp,
                first=(j == enter_i),
            )
            if exitprice is not None:
                exit_i = j
                break
        if exit_i is None:
            j = enter_i + 24
            if j < len(times) and int(times[j]) < end:
                exit_i = j
                exitprice = float(df.open.iloc[j])
                reason = "TIME_NEXT_OPEN"
            else:
                censored.append(
                    dict(
                        symbol=symbol,
                        entry_ts_ms=int(times[enter_i]),
                        reason="END_WINDOW_UNRESOLVED",
                    )
                )
                break
        gross = 10000 * (exitprice / entry - 1)
        trades.append(
            dict(
                symbol=symbol,
                signal_ts_ms=int(times[i]),
                entry_ts_ms=int(times[enter_i]),
                exit_ts_ms=int(times[exit_i]),
                entry_price=entry,
                exit_price=exitprice,
                stop_price=sl,
                target_price=tp,
                entry_atr14=atr,
                reason=reason,
                gross_bps=gross,
                net1x_bps=gross - 20,
                net2x_bps=gross - 40,
            )
        )
        i = exit_i + 1
    return trades, censored


def metrics(rows, begin, end):
    n = len(rows)
    last = datetime.datetime.fromtimestamp(
        (end - 1) / 1000, datetime.timezone.utc
    ).date()
    first = datetime.datetime.fromtimestamp(begin / 1000, datetime.timezone.utc).date()
    days = (last - first).days + 1
    arr = [r["net2x_bps"] for r in rows]
    arr1 = [r["net1x_bps"] for r in rows]
    by_exit = {}
    for x in rows:
        by_exit.setdefault(x["exit_ts_ms"], []).append(x)
    eq = peak = dd = 0.0
    streak = mx = 0
    for stamp in sorted(by_exit):
        cohort = by_exit[stamp]
        for x in sorted(cohort, key=lambda z: z["symbol"]):
            loss = x["net2x_bps"] < 0
            streak = streak + 1 if loss else 0
            mx = max(mx, streak)
        eq += sum(x["net2x_bps"] for x in cohort)
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    pos = sum(max(0, v) for v in arr)
    neg = -sum(min(0, v) for v in arr)
    dates = {
        datetime.datetime.fromtimestamp(
            x["entry_ts_ms"] / 1000, datetime.timezone.utc
        ).date()
        for x in rows
    }
    unique_epochs = len({x["entry_ts_ms"] for x in rows})
    plus = sorted([v for v in arr if v > 0], reverse=True)
    return dict(
        T=n,
        T_per_day=n / days,
        unique_entry_epochs=unique_epochs,
        distinct_epochs_day=unique_epochs / days,
        active_days=len(dates),
        idle_days=days - len(dates),
        net1x_bps=sum(arr1),
        net2x_bps=sum(arr),
        PF2x=(pos / neg if neg else None),
        WR2x_pct=(100 * sum(v > 0 for v in arr) / n if n else None),
        max_loss_streak_cost2x=mx,
        realized_DD_cost2x_trade_bps=dd,
        top2_winner_share=(sum(plus[:2]) / pos if pos else None),
    )


def run(root, out):
    spec = json.loads((out / "FREEZE.json").read_text())
    if spec["candidate"] != "ZEL_RSI2_TREND_BOUNCE_LONG_1H_V1" or spec[
        "cost_round_trip_bps"
    ] != [20, 40]:
        raise ValueError("RULE_FREEZE_CHANGED")
    alltrades = []
    pars = []
    inputs = {}
    for s in spec["symbols"]:
        df, pins = source(s, root)
        f = features(df)
        inputs[s] = dict(
            files=len(pins),
            first_open_ms=int(df.timestamp_ms.iloc[0]),
            last_open_ms=int(df.timestamp_ms.iloc[-1]),
            bars=len(df),
            file_sha256=pins,
            candle_table_sha256=sha(df.to_csv(index=False).encode()),
        )
        for label, (begin, end) in [
            ("TRAIN", spec["training_signal_range_utc"]),
            ("LATER", spec["later_signal_range_utc"]),
        ]:
            b, e = ms(begin), ms(end)
            t, c = simulate(s, df, f, b, e)
            for x in t:
                x["partition"] = label
            for x in c:
                x["partition"] = label
            alltrades.extend(t)
            pars.extend(c)
        print(
            "SYMBOL_DONE",
            s,
            "TRAIN",
            sum(x["symbol"] == s and x["partition"] == "TRAIN" for x in alltrades),
            "LATER",
            sum(x["symbol"] == s and x["partition"] == "LATER" for x in alltrades),
            flush=True,
        )
    scores = {}
    for label, dates in [
        ("TRAIN", spec["training_signal_range_utc"]),
        ("LATER", spec["later_signal_range_utc"]),
    ]:
        rows = [x for x in alltrades if x["partition"] == label]
        scores[label] = metrics(rows, ms(dates[0]), ms(dates[1]))
    report = dict(
        candidate=spec["candidate"],
        rule_sha256=sha((out / "FREEZE.json").read_bytes()),
        source_root=str(root),
        source_manifest_sha256=sha((root.parent / "MANIFEST.json").read_bytes()),
        input_pins=inputs,
        economics=scores,
        censored=pars,
        trade_rows=alltrades,
        claims={
            "used_historical": True,
            "fresh_OOS": False,
            "market_api": 0,
            "orders": 0,
            "global_heavy_FULL": 0,
            "actual_funding": None,
            "true_asof_price_receipts": False,
            "portfolio_NAV": False,
            "no_parameter_search": True,
            "no_adoption": True,
        },
    )
    raw = (
        json.dumps(
            report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        + "\n"
    ).encode()
    with (out / "RESULT.json").open("xb") as h:
        h.write(raw)
    summary = dict(
        candidate=spec["candidate"],
        rule_sha256=report["rule_sha256"],
        source_manifest_sha256=report["source_manifest_sha256"],
        economics=scores,
        censored_count=len(pars),
        sample_count=len(alltrades),
        result_sha256=sha(raw),
        source="USED_ARCHIVE_NOT_INDEPENDENT_OOS",
        action="hold",
    )
    (out / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    print("DEV_COMPLETED", json.dumps(summary, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    p = Path("/home/z/zel_rsi2_trendbounce_useddev_20261024")
    run(Path(json.loads((p / "FREEZE.json").read_text())["source_root"]), p)
