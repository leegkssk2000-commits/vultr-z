"""Read-only adapters for frozen native owners; never writes their artifacts."""
from __future__ import annotations
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import gzip
import json
from pathlib import Path

from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as owner
from backend.research.rebuild import trend_policy_batch_v1 as native
from backend.research.rebuild import trend_rider_wr80_us_chase_cooling_child_policy_v1 as primary
from backend.research.rebuild import policy_kernel_v1 as kernel
from backend.research.architecture_factory import g5a_development_probe_v1 as dev

HOUR = 3_600_000


def collect_native(start, end, destination):
    """Existing public owner, fixed whole development calendar, no holdout request."""
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    result = {}
    for symbol in ("BTC-USDT", "ETH-USDT"):
        path = destination / (symbol + ".json.gz")
        if path.exists():
            rows = json.loads(gzip.decompress(path.read_bytes()))
            result[symbol] = {"path": str(path), "rows": len(rows), "reused": True}
            continue
        rows = {}; pages = []; cursor = end - HOUR
        for _ in range(12):
            raw = owner.req({"symbol": symbol, "interval": "1h", "limit": 1000, "endTime": cursor})
            page = sorted(owner.decode(raw), key=lambda r: r["ts"])
            if len(page) != len(raw.get("data", [])) or not page:
                raise RuntimeError("NATIVE_SOURCE_DECODE_OR_EMPTY:" + symbol)
            if len({r['ts'] for r in page}) != len(page):
                raise RuntimeError("NATIVE_PAGE_DUPLICATE")
            pages.append({"request_end_ms": cursor, "payload_sha256": owner.stable(raw), "rows": len(page)})
            for row in page:
                ts = int(row["ts"])
                if start <= ts and ts + HOUR <= end:
                    if ts in rows and rows[ts] != row:
                        raise RuntimeError("NATIVE_SOURCE_CONFLICT")
                    rows[ts] = row
            oldest = int(page[0]["ts"])
            if oldest <= start:
                break
            if oldest >= cursor:
                raise RuntimeError("NATIVE_PAGINATION_STALLED")
            cursor = oldest - HOUR
        ordered = [rows[k] for k in sorted(rows)]
        validate_native(ordered, start, end)
        content = dev.canonical(ordered)
        path.write_bytes(gzip.compress(content, mtime=0))
        result[symbol] = {"path": str(path), "rows": len(ordered), "first_open_ms": start,
                          "last_close_ms": end, "pages": pages, "file_sha256": owner.file_sha(path),
                          "rows_sha256": owner.stable(ordered), "holdout_rows": 0}
        print("NATIVE_DEVELOPMENT_FROZEN", symbol, len(ordered), flush=True)
    return result


def validate_native(rows, start, end):
    kernel.validate_bars(rows, minimum=64)
    expected = list(range(start, end, HOUR))
    if [r["ts_ms"] for r in rows] != expected:
        raise RuntimeError("NATIVE_DEVELOPMENT_COVERAGE_GAP_OR_DUPLICATE")


class NativeFeatureCache:
    """Exact prefix recurrence of native EMA/ATR/Supertrend, with parity tests.

    Native _supertrend_state recomputes every earlier ATR for every signal.
    This cache retains its exact arithmetic and prefix seeds, including its
    branch convention; it changes no policy rule or intent builder.
    """
    def __init__(self, rows, cfg):
        kernel.validate_bars(rows, minimum=64)
        self.rows = rows; self.cfg = cfg
        self.indices = {r["ts_ms"]: i for i, r in enumerate(rows)}
        closes = [r["close"] for r in rows]
        self.ema = kernel.ema(closes, cfg.ema_trend_len)
        trs = kernel.true_ranges(rows)
        def atr_series(length):
            values = []
            for i in range(len(rows)):
                n = min(length, i + 1)
                v = sum(trs[:n]) / n if i < length else ((length - 1) * values[-1] + trs[i]) / length
                values.append(v)
            return values
        self.atr = atr_series(cfg.atr_len); st_atr = atr_series(cfg.supertrend_len)
        line = (rows[0]["high"] + rows[0]["low"]) / 2
        final_upper = final_lower = prev_line = line; prev_close = closes[0]
        self.st = [(line, 1)]
        for i in range(1, len(rows)):
            hl2 = (rows[i]["high"] + rows[i]["low"]) / 2
            upper = hl2 + cfg.supertrend_mult * st_atr[i]; lower = hl2 - cfg.supertrend_mult * st_atr[i]
            final_upper = upper if upper < final_upper or prev_close > final_upper else final_upper
            final_lower = lower if lower > final_lower or prev_close < final_lower else final_lower
            if prev_line == final_upper:
                line, direction = (final_upper, -1) if closes[i] <= final_upper else (final_lower, 1)
            else:
                line, direction = (final_lower, 1) if closes[i] >= final_lower else (final_upper, -1)
            prev_line, prev_close = line, closes[i]
            self.st.append((float(line), int(direction)))

    def feature(self, bars, *, symbol, now_ts_ms, config=None):
        cfg = config or self.cfg; i = self.indices[bars[-1]["ts_ms"]]
        if len(bars) != i + 1 or i < 63 or cfg.sha != self.cfg.sha:
            raise ValueError("NATIVE_CACHE_PREFIX_OR_CONFIG")
        close = bars[-1]["close"]; a = self.atr[i]; st, direction = self.st[i]
        prev = bars[-2]
        values = {"supertrend": st, "direction": direction, "ema50": self.ema[i],
                  "long_confirm": direction == 1 and close > st and close > self.ema[i] and self.ema[i] > self.ema[i-1] and prev["close"] >= prev["open"],
                  "short_confirm": direction == -1 and close < st and close < self.ema[i] and self.ema[i] < self.ema[i-1] and prev["close"] <= prev["open"],
                  "st_gap_atr": abs(close-st)/max(a,1e-12), "chase_atr": abs(close-self.ema[i])/max(a,1e-12)}
        return native._snapshot("trend_rider", symbol, bars, now_ts_ms, close, a, values, cfg)


def native_replay(rows, symbol, lane, start, end, admission=None, policy_sha=None):
    """Reuse the existing native SL-first/timeout/ownership evaluator verbatim."""
    cfg = primary.TrendRiderWR80USChaseCoolingConfig() if lane == "primary" else native.TrendPolicyConfig()
    cache = NativeFeatureCache(rows, cfg); events = []
    compute = primary.compute_trend_rider_feature if lane == "primary" else cache.feature
    build = primary.build_trend_rider_intent if lane == "primary" else native.build_trend_rider_intent
    def observed_build(feature, **kwargs):
        intent = build(feature, **kwargs)
        if not intent.no_trade:
            i = cache.indices[feature.signal_ts]
            allowed = admission(i, feature, intent) if admission else True
            events.append({"symbol": symbol, "signal_index": i, "signal_ts": feature.signal_ts+HOUR,
                           "native_signal_bar_open_ts": feature.signal_ts, "side": intent.side,
                           "features": dict(feature.values), "admission": bool(allowed),
                           "sl": intent.sl, "tp": intent.tp, "timeout": dict(intent.timeout),
                           "risk_size": dict(intent.risk_size), "exposure": dict(intent.exposure)})
            if not allowed:
                return replace(intent, no_trade=True)
        return intent
    facade = SimpleNamespace(TrendRiderWR80USChaseCoolingConfig=lambda: cfg,
                             compute_trend_rider_feature=compute, build_trend_rider_intent=observed_build)
    with patch.object(native, "compute_trend_rider_feature", cache.feature), patch.object(owner, "primary_policy", facade), \
         patch.object(owner, "paged_bars", lambda *a: rows), patch.object(owner.ev, "git_blob_sha", lambda path: policy_sha):
        trades, _ = owner.primary_trades(start, end, [symbol])
    return trades, events
