from __future__ import annotations

import argparse, json, math, os, tempfile, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from r7a4d_integrated_supertrend_pullback_replay import run_replay

INTERVAL = "15m"
INTERVAL_MS = 900_000
REQUEST_LIMIT = 1000
ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v3/quote/klines",
    "https://open-api.bingx.com/openApi/swap/v2/quote/klines",
)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
GEOMETRY = (
    "structure_long", "structure_short", "sr_touch", "trendline_touch",
    "ma50_touch", "counter_trend_break_up", "counter_trend_break_down",
)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    def safe(item: Any) -> Any:
        if isinstance(item, dict): return {str(k): safe(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)): return [safe(v) for v in item]
        if isinstance(item, (pd.Timestamp, datetime)): return item.isoformat()
        if isinstance(item, np.generic): return safe(item.item())
        if isinstance(item, float) and not math.isfinite(item): return None
        return item
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(safe(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text); temporary = Path(handle.name)
    os.replace(temporary, path)


def norm_symbol(value: str) -> str:
    value = "".join(c for c in value.upper() if c.isalnum())
    if not value.endswith("USDT"): raise ValueError(f"SYMBOL_INVALID:{value}")
    return value


def request_json(url: str) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ZEL-R7A4D-OOS/1.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict): raise ValueError("RESPONSE_NOT_OBJECT")
            return value
        except Exception as exc:
            error = exc; time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"BINGX_REQUEST_FAILED:{type(error).__name__}:{error}")


def parse_row(row: Any) -> tuple[int, float, float, float, float, float] | None:
    if isinstance(row, dict):
        raw = (row.get("time", row.get("timestamp", row.get("openTime"))), row.get("open"), row.get("high"), row.get("low"), row.get("close"), row.get("volume", row.get("vol")))
    elif isinstance(row, (list, tuple)) and len(row) >= 6: raw = tuple(row[:6])
    else: return None
    try:
        ts = int(float(raw[0])); ts = ts * 1000 if ts < 10_000_000_000 else ts // 1000 if ts > 10_000_000_000_000 else ts
        o, h, l, c, v = map(float, raw[1:6])
    except (TypeError, ValueError): return None
    if not all(math.isfinite(x) for x in (o, h, l, c, v)): return None
    if o <= 0 or c <= 0 or v < 0 or h < max(o, c) or l > min(o, c) or h < l: return None
    return ts, o, h, l, c, v


def fetch(symbol: str, bars: int) -> tuple[pd.DataFrame, str]:
    end = (int(datetime.now(timezone.utc).timestamp() * 1000) // INTERVAL_MS - 2) * INTERVAL_MS
    start = end - (bars - 1) * INTERVAL_MS
    request_start = start - INTERVAL_MS
    request_end = end + INTERVAL_MS
    max_requests = max(8, math.ceil((bars + 2) / max(REQUEST_LIMIT - 1, 1)) + 4)
    errors: list[str] = []
    for endpoint in ENDPOINTS:
        try:
            found: dict[int, tuple[int, float, float, float, float, float]] = {}
            cursor = request_start
            requests = 0
            while cursor <= request_end and requests < max_requests:
                window_end = min(request_end, cursor + REQUEST_LIMIT * INTERVAL_MS)
                query = urllib.parse.urlencode({"symbol": symbol[:-4] + "-USDT", "interval": INTERVAL, "limit": REQUEST_LIMIT, "startTime": cursor, "endTime": window_end})
                payload = request_json(endpoint + "?" + query)
                if payload.get("code") not in (None, 0, "0"): raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
                data: Any = payload.get("data")
                if isinstance(data, dict):
                    data = next((data[k] for k in ("data", "rows", "klines", "list") if isinstance(data.get(k), list)), [])
                page = [item for item in (parse_row(row) for row in (data if isinstance(data, list) else [])) if item is not None]
                requests += 1
                if not page: raise ValueError(f"EMPTY_PAGE:{cursor}:{window_end}")
                for item in page:
                    if start <= item[0] <= end: found[item[0]] = item
                if len(found) >= bars and min(found) == start and max(found) == end:
                    break
                max_seen = max(item[0] for item in page)
                if max_seen <= cursor: raise ValueError(f"PAGINATION_STALLED:{cursor}:{max_seen}")
                cursor = max_seen
            frame = pd.DataFrame([found[k] for k in sorted(found)], columns=("timestamp_ms", "open", "high", "low", "close", "volume"))
            validate(frame, bars)
            frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
            return frame, endpoint
        except Exception as exc: errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("BINGX_ENDPOINTS_FAILED:" + "|".join(errors))


def validate(frame: pd.DataFrame, bars: int) -> None:
    if len(frame) != bars: raise ValueError(f"ROWS:{len(frame)}!={bars}")
    ts = frame["timestamp_ms"].astype("int64")
    if ts.duplicated().any(): raise ValueError("DUPLICATE_TIMESTAMP")
    if not bool((ts.diff().dropna() == INTERVAL_MS).all()): raise ValueError("TIMESTAMP_GAP_OR_WRONG_INTERVAL")
    values = frame[["open", "high", "low", "close", "volume"]].to_numpy(float)
    if not np.isfinite(values).all(): raise ValueError("OHLC_NONFINITE")


def rma(series: pd.Series, length: int) -> pd.Series:
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) < length: return out
    prev = float(series.iloc[:length].mean()); out.iloc[length - 1] = prev
    for i in range(length, len(series)):
        prev = ((length - 1) * prev + float(series.iloc[i])) / length; out.iloc[i] = prev
    return out


def geometry(frame: pd.DataFrame, warmup: int = 400) -> pd.DataFrame:
    out = frame.copy().reset_index(drop=True)
    prev_close = out["close"].shift(1)
    tr = pd.concat((out["high"] - out["low"], (out["high"] - prev_close).abs(), (out["low"] - prev_close).abs()), axis=1).max(axis=1)
    atr, ma50 = rma(tr, 14), out["close"].rolling(50, min_periods=50).mean()
    flags = {name: np.zeros(len(out), dtype=bool) for name in GEOMETRY}
    highs: list[tuple[int, float]] = []; lows: list[tuple[int, float]] = []
    for i in range(len(out)):
        center = i - 3
        if center >= 3:
            hi = out["high"].iloc[center - 3:center + 4]; lo = out["low"].iloc[center - 3:center + 4]
            cvh, cvl = float(out["high"].iloc[center]), float(out["low"].iloc[center])
            if cvh == float(hi.max()) and int((hi == cvh).sum()) == 1: highs.append((center, cvh))
            if cvl == float(lo.min()) and int((lo == cvl).sum()) == 1: lows.append((center, cvl))
        if len(highs) >= 2 and len(lows) >= 2:
            flags["structure_long"][i] = highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]
            flags["structure_short"][i] = highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1]
        a = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else math.nan
        if not math.isfinite(a) or a <= 0: continue
        tol, close, high, low = .25 * a, float(out["close"].iloc[i]), float(out["high"].iloc[i]), float(out["low"].iloc[i])
        recent = sorted(highs + lows, key=lambda item: item[0])[-6:]
        flags["sr_touch"][i] = any(low - tol <= p <= high + tol or abs(close - p) <= tol for _, p in recent)
        for pivots in (lows, highs):
            if len(pivots) >= 2:
                (x1, y1), (x2, y2) = pivots[-2], pivots[-1]
                projected = y2 + (y2 - y1) / (x2 - x1) * (i - x2)
                if abs(close - projected) <= tol or low - tol <= projected <= high + tol: flags["trendline_touch"][i] = True
        m = float(ma50.iloc[i]) if pd.notna(ma50.iloc[i]) else math.nan
        flags["ma50_touch"][i] = math.isfinite(m) and low - tol <= m <= high + tol
        if i >= 8:
            x = np.arange(8, dtype=float)
            sh, ih = np.polyfit(x, out["high"].iloc[i-8:i].to_numpy(float), 1); ph = ih + sh * 8
            sl, il = np.polyfit(x, out["low"].iloc[i-8:i].to_numpy(float), 1); pl = il + sl * 8
            flags["counter_trend_break_up"][i] = sh < 0 and close > ph + .05 * a
            flags["counter_trend_break_down"][i] = sl > 0 and close < pl - .05 * a
    for name, values in flags.items():
        out[name] = values; out.loc[:warmup - 1, name] = False
    out["atr14_geometry"] = atr; out["ma50_geometry"] = ma50
    return out


def prefix_check(frame: pd.DataFrame, warmup: int) -> int:
    full = geometry(frame, warmup)
    points = np.linspace(warmup, len(frame) - 1, num=8, dtype=int)
    for point in sorted(set(map(int, points))):
        prefix = geometry(frame.iloc[:point + 1], warmup)
        for name in GEOMETRY:
            if bool(full[name].iloc[point]) != bool(prefix[name].iloc[-1]): raise RuntimeError(f"LOOKAHEAD:{point}:{name}")
    return len(set(map(int, points)))


def pf(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0); losses = abs(sum(v for v in values if v < 0))
    return gains / losses if losses else None


def main() -> int:
    parser = argparse.ArgumentParser(description="BingX public 15m real-OOS replay for the single integrated Supertrend pullback strategy")
    parser.add_argument("--root", default="/home/z/z"); parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--evaluation-bars", type=int, default=3600); parser.add_argument("--warmup-bars", type=int, default=400)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0); parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args(); root = Path(args.root).resolve(); output = root / "runtime/r7a4d_integrated_supertrend_bingx_real_oos_v1"
    symbols = list(dict.fromkeys(norm_symbol(s) for s in args.symbols.split(",") if s.strip()))
    if args.evaluation_bars < 1000 or args.warmup_bars < 250: raise ValueError("BAR_CONTRACT_INVALID")
    results: list[dict[str, Any]] = []; blockers: list[str] = []; returns: list[float] = []
    for symbol in symbols:
        try:
            raw, endpoint = fetch(symbol, args.evaluation_bars + args.warmup_bars); enriched = geometry(raw, args.warmup_bars)
            checks = prefix_check(raw, args.warmup_bars); csv = output / f"{symbol.lower()}_15m.csv"; csv.parent.mkdir(parents=True, exist_ok=True); enriched.to_csv(csv, index=False)
            replay = run_replay(enriched, symbol=symbol, timeframe=INTERVAL, replay_fold_id="BINGX_REAL_OOS_FIXED_WINDOW", cost_bps_per_side=args.cost_bps_per_side)
            atomic_json(output / f"{symbol.lower()}_replay.json", replay); net = [float(t["net_return_pct"]) for t in replay["trades"]]; returns.extend(net)
            results.append({"symbol": symbol, "status": "PASS", "endpoint": endpoint, "rows": len(raw), "prefix_checks": checks, "csv": str(csv), "trade_count": replay["trade_count"], "win_count": replay["win_count"], "win_rate_pct": replay["win_rate_pct"], "net_return_pct": replay["net_return_pct"], "net_profit_factor": replay["net_profit_factor"], "max_drawdown_pct": replay["max_drawdown_pct"]})
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"; blockers.append(error); results.append({"symbol": symbol, "status": "HOLD", "error": error})
    passed = [r for r in results if r["status"] == "PASS"]; trades = sum(int(r.get("trade_count", 0)) for r in passed); wins = sum(int(r.get("win_count", 0)) for r in passed)
    state = "PASS_R7A4D_INTEGRATED_SUPERTREND_BINGX_REAL_OOS" if len(passed) == len(symbols) and trades > 0 else "HOLD_R7A4D_INTEGRATED_SUPERTREND_BINGX_REAL_OOS"
    summary = {"state": state, "authority": "RESEARCH_ONLY_NO_EXECUTION", "target_sha": args.target_sha, "source": "BingX public perpetual klines", "interval": INTERVAL, "symbols": symbols, "evaluation_bars": args.evaluation_bars, "warmup_bars": args.warmup_bars, "cost_bps_per_side": args.cost_bps_per_side, "geometry": {"pivot": "3L3R confirmed only", "levels": "last 6 confirmed pivots", "touch": "0.25 ATR14", "trendline": "last 2 confirmed pivots projected", "counter_trend": "8 prior bars + 0.05 ATR break"}, "results": results, "aggregate": {"trade_count": trades, "win_count": wins, "win_rate_pct": wins / trades * 100 if trades else None, "net_return_pct_sum": sum(returns), "net_profit_factor": pf(returns), "positive_symbol_count": sum(float(r.get("net_return_pct", 0)) > 0 for r in passed)}, "blockers": blockers, "performance_claim_allowed": False, "promotion_allowed": False, "paper_live_order_allowed": False}
    atomic_json(output / "summary_v1.json", summary)
    print(f"STATE={state}\nPASSED_SYMBOLS={len(passed)}/{len(symbols)}\nTRADES={trades}\nWIN_RATE_PCT={summary['aggregate']['win_rate_pct']}\nNET_RETURN_PCT_SUM={sum(returns):.6f}\nNET_PF={summary['aggregate']['net_profit_factor']}\nSUMMARY_JSON={output / 'summary_v1.json'}\nBLOCKERS={json.dumps(blockers)}\nRC={0 if state.startswith('PASS') else 2}")
    return 0 if state.startswith("PASS") else 2


if __name__ == "__main__": raise SystemExit(main())
