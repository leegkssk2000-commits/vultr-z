from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.engine.market_data_service import BingXPublicAdapter, _norm_symbol, _norm_timeframe
from backend.production.zel_production_bingx_freshness_v1 import fetch_fresh_bingx_quote

SCHEMA = "zel.production_trend_momentum.v2"
SIGNAL_SCHEMA = "zel.production_alpha_signal.v1"
FACTORY_SCHEMA = "zel.production_alpha_factory.v1"
DEFAULT_CONFIG = Path("config/zel_production_alpha_factory_v1.json")
STRATEGY_ID = "trend_momentum_v1"
SUPPORTED_SYMBOLS = {"BTCUSDT", "ETHUSDT"}
TIMEFRAME_MS = {"1h": 3_600_000}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _float(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"TREND_MOMENTUM_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"TREND_MOMENTUM_NUMERIC_NONFINITE:{name}")
    return out


def _int(value: Any, name: str) -> int:
    out = _float(value, name)
    if not out.is_integer():
        raise RuntimeError(f"TREND_MOMENTUM_INTEGER_INVALID:{name}")
    return int(out)


def _symbol(value: Any) -> str:
    symbol = str(value or "").replace("-", "").upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise RuntimeError(f"TREND_MOMENTUM_SYMBOL_UNSUPPORTED:{symbol or 'MISSING'}")
    return symbol


def _ts_ms(value: Any) -> int:
    out = _int(value, "candle.ts")
    if 0 < out < 100_000_000_000:
        out *= 1000
    return out


def _ema(values: Sequence[float], span: int) -> float:
    if span < 2 or len(values) < span:
        raise RuntimeError(f"TREND_MOMENTUM_EMA_HISTORY_SHORT:{span}:{len(values)}")
    alpha = 2.0 / (span + 1.0)
    ema = float(values[0])
    for value in values[1:]:
        ema = alpha * float(value) + (1.0 - alpha) * ema
    return ema


def evaluate_completed_trend(
    closes: Sequence[float],
    *,
    ema_fast: int = 50,
    ema_slow: int = 200,
    history_bars: int = 200,
) -> dict[str, Any]:
    """Evaluate the exact production trend rule on completed closes only.

    The live producer and historical seed qualification both call this function,
    preventing runtime/backtest signal drift. The trailing history is bounded to
    the same number of completed bars fetched by production.
    """
    fast = int(ema_fast)
    slow = int(ema_slow)
    history = int(history_bars)
    if not (2 <= fast < slow <= history):
        raise RuntimeError("TREND_MOMENTUM_WINDOW_CONTRACT_INVALID")
    if len(closes) < history:
        raise RuntimeError(f"TREND_MOMENTUM_HISTORY_SHORT:{len(closes)}:{history}")
    window = [_float(v, "completed_close") for v in closes[-history:]]
    if any(v <= 0 for v in window):
        raise RuntimeError("TREND_MOMENTUM_CLOSE_NONPOSITIVE")
    px = float(window[-1])
    fast_value = _ema(window, fast)
    slow_value = _ema(window, slow)
    bullish = px > fast_value > slow_value
    return {
        "signal": "LONG" if bullish else "EXIT",
        "price": px,
        "ema_fast": fast_value,
        "ema_slow": slow_value,
        "ema_spread_pct": (fast_value / slow_value - 1.0) * 100.0,
        "price_to_fast_pct": (px / fast_value - 1.0) * 100.0,
        "bullish_alignment": bullish,
        "completed_bar_only": True,
        "history_bars": history,
    }


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    row = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError("TREND_MOMENTUM_FACTORY_NOT_OBJECT")
    return row


def trend_config(factory: Mapping[str, Any]) -> dict[str, Any]:
    if factory.get("schema_version") != FACTORY_SCHEMA:
        raise RuntimeError("TREND_MOMENTUM_FACTORY_SCHEMA_INVALID")
    if str(factory.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("TREND_MOMENTUM_FACTORY_NON_PAPER_FORBIDDEN")
    if factory.get("order_authority") != "BLOCKED" or factory.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("TREND_MOMENTUM_FACTORY_LIVE_AUTHORITY_FORBIDDEN")
    families = factory.get("families")
    cfg = families.get("trend_momentum") if isinstance(families, Mapping) else None
    if not isinstance(cfg, Mapping):
        raise RuntimeError("TREND_MOMENTUM_CONFIG_MISSING")
    if cfg.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("TREND_MOMENTUM_STRATEGY_ID_INVALID")
    if cfg.get("status") != "IMPLEMENTED_PRIMARY_SEED":
        raise RuntimeError("TREND_MOMENTUM_NOT_IMPLEMENTED")
    if cfg.get("promotion_authority") is not False or cfg.get("execution_authority") != "PAPER_SIGNAL_ONLY":
        raise RuntimeError("TREND_MOMENTUM_CONFIG_AUTHORITY_INVALID")
    if cfg.get("short_enabled") is not False or cfg.get("long_enabled") is not True:
        raise RuntimeError("TREND_MOMENTUM_LONG_ONLY_CONTRACT_INVALID")
    if cfg.get("timeframe") not in TIMEFRAME_MS:
        raise RuntimeError("TREND_MOMENTUM_TIMEFRAME_INVALID")
    fast = _int(cfg.get("ema_fast"), "ema_fast")
    slow = _int(cfg.get("ema_slow"), "ema_slow")
    history = _int(cfg.get("history_bars"), "history_bars")
    if not (2 <= fast < slow <= history <= 200):
        raise RuntimeError("TREND_MOMENTUM_WINDOW_CONTRACT_INVALID")
    lineage = cfg.get("parameter_lineage")
    if not isinstance(lineage, Mapping) or lineage.get("source_sha256") != "a060529401c9a218cfa04be0511d5f7ab0cdecff":
        raise RuntimeError("TREND_MOMENTUM_PARAMETER_LINEAGE_INVALID")
    if lineage.get("completed_rows_only") is not True:
        raise RuntimeError("TREND_MOMENTUM_COMPLETED_ROWS_LINEAGE_REQUIRED")
    return dict(cfg)


def normalize_completed_candles(
    candles: Sequence[Mapping[str, Any]],
    *,
    timeframe: str,
    now_ms: int,
) -> list[dict[str, Any]]:
    interval_ms = TIMEFRAME_MS[timeframe]
    by_ts: dict[int, dict[str, Any]] = {}
    for row in candles:
        if not isinstance(row, Mapping):
            raise RuntimeError("TREND_MOMENTUM_CANDLE_NOT_MAPPING")
        ts = _ts_ms(row.get("ts"))
        op = _float(row.get("op"), "candle.open")
        hi = _float(row.get("hi"), "candle.high")
        lo = _float(row.get("lo"), "candle.low")
        cl = _float(row.get("cl"), "candle.close")
        vol = _float(row.get("vol", 0.0), "candle.volume")
        if min(op, hi, lo, cl) <= 0 or vol < 0:
            raise RuntimeError("TREND_MOMENTUM_CANDLE_NONPOSITIVE")
        if hi < max(op, cl, lo) or lo > min(op, cl, hi):
            raise RuntimeError("TREND_MOMENTUM_CANDLE_OHLC_INVALID")
        if ts <= 0 or ts > now_ms:
            raise RuntimeError("TREND_MOMENTUM_CANDLE_TIMESTAMP_INVALID")
        if ts + interval_ms > now_ms:
            continue
        if ts in by_ts:
            raise RuntimeError("TREND_MOMENTUM_DUPLICATE_CANDLE_TS")
        by_ts[ts] = {"ts": ts, "op": op, "hi": hi, "lo": lo, "cl": cl, "vol": vol}
    return [by_ts[ts] for ts in sorted(by_ts)]


def build_signal(
    *,
    authority: Mapping[str, Any],
    factory: Mapping[str, Any],
    candles: Sequence[Mapping[str, Any]],
    quote: Mapping[str, Any],
    now_ms: int | None = None,
) -> dict[str, Any]:
    cfg = trend_config(factory)
    strategy_id = str(authority.get("strategy_id") or "")
    alpha_id = str(authority.get("alpha_id") or "")
    symbol = _symbol(authority.get("symbol"))
    if strategy_id != STRATEGY_ID or not alpha_id:
        raise RuntimeError("TREND_MOMENTUM_AUTHORITY_IDENTITY_INVALID")
    if symbol not in {_symbol(v) for v in cfg.get("symbols") or []}:
        raise RuntimeError("TREND_MOMENTUM_SYMBOL_NOT_CONFIGURED")

    if quote.get("state") != "PASS_BINGX_FRESH" or quote.get("provider") != "bingx_public":
        raise RuntimeError("TREND_MOMENTUM_QUOTE_NOT_FRESH_BINGX")
    if _symbol(quote.get("symbol")) != symbol:
        raise RuntimeError("TREND_MOMENTUM_QUOTE_SYMBOL_MISMATCH")
    quote_receipt = str(quote.get("receipt_sha256") or "")
    if len(quote_receipt) != 64:
        raise RuntimeError("TREND_MOMENTUM_QUOTE_RECEIPT_MISSING")

    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    timeframe = str(cfg["timeframe"])
    interval_ms = TIMEFRAME_MS[timeframe]
    completed = normalize_completed_candles(candles, timeframe=timeframe, now_ms=now)
    history_bars = _int(cfg["history_bars"], "history_bars")
    if len(completed) < history_bars:
        raise RuntimeError(f"TREND_MOMENTUM_HISTORY_SHORT:{len(completed)}:{history_bars}")
    prior = completed[-history_bars:]
    features = evaluate_completed_trend(
        [float(row["cl"]) for row in prior],
        ema_fast=_int(cfg["ema_fast"], "ema_fast"),
        ema_slow=_int(cfg["ema_slow"], "ema_slow"),
        history_bars=history_bars,
    )

    candle_receipt = stable_sha(prior)
    config_receipt = stable_sha(cfg)
    decision_bar_close_ms = int(prior[-1]["ts"]) + interval_ms
    result = {
        "schema_version": SIGNAL_SCHEMA,
        "producer_schema_version": SCHEMA,
        "state": "PASS_ACTIVE_ALPHA_SIGNAL",
        "strategy_id": strategy_id,
        "alpha_id": alpha_id,
        "symbol": symbol,
        "signal": features["signal"],
        # Signal freshness reflects the current verified refresh; economic state
        # is still based only on the last completed 1h bar.
        "signal_ts": int(quote.get("observed_at_ms") or now),
        "family": "trend_momentum",
        "timeframe": timeframe,
        "features": features,
        "source": {
            "provider": "bingx_public",
            "completed_candle_count": len(prior),
            "last_completed_candle_ts": int(prior[-1]["ts"]),
            "decision_bar_close_ms": decision_bar_close_ms,
            "quote_age_ms": int(quote.get("age_ms") or 0),
            "quote_used_for_signal_price": False,
            "dummy_fallback_used": False,
        },
        "source_hashes": [quote_receipt, candle_receipt, config_receipt],
        "promotion_authority": False,
        "execution_authority": "PAPER_SIGNAL_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def _required_data_stale_ms() -> float:
    raw = os.environ.get("ZEL_DATA_STALE_MS")
    if raw is None or not raw.strip():
        raise RuntimeError("TREND_MOMENTUM_DATA_STALE_ENV_UNBOUND:ZEL_DATA_STALE_MS")
    value = _float(raw, "ZEL_DATA_STALE_MS")
    if value <= 0:
        raise RuntimeError("TREND_MOMENTUM_DATA_STALE_NONPOSITIVE")
    return value


def _normalize_api_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, Mapping):
        for key in ("items", "list", "candles", "rows", "klines"):
            value = data.get(key)
            if isinstance(value, list):
                data = value
                break
    if not isinstance(data, list):
        raise RuntimeError("TREND_MOMENTUM_CANDLES_NOT_LIST")
    out: list[dict[str, Any]] = []
    for row in data:
        if isinstance(row, (list, tuple)) and len(row) >= 6:
            out.append({"ts": row[0], "op": row[1], "hi": row[2], "lo": row[3], "cl": row[4], "vol": row[5]})
        elif isinstance(row, Mapping):
            out.append({
                "ts": row.get("openTime") or row.get("time") or row.get("ts") or row.get("timestamp"),
                "op": row.get("open") or row.get("openPrice") or row.get("o"),
                "hi": row.get("high") or row.get("highPrice") or row.get("h"),
                "lo": row.get("low") or row.get("lowPrice") or row.get("l"),
                "cl": row.get("close") or row.get("closePrice") or row.get("c"),
                "vol": row.get("volume") or row.get("vol") or row.get("v") or 0,
            })
        else:
            raise RuntimeError("TREND_MOMENTUM_CANDLE_ROW_SHAPE_INVALID")
    return out


async def _fetch_completed_window(
    adapter: BingXPublicAdapter,
    symbol: str,
    timeframe: str,
    history_bars: int,
    now_ms: int,
) -> list[dict[str, Any]]:
    interval_ms = TIMEFRAME_MS[timeframe]
    end_exclusive = (int(now_ms) // interval_ms) * interval_ms
    start_ms = end_exclusive - int(history_bars) * interval_ms
    # The collector already proved BingX v3 klines accepts startTime/endTime.
    # endTime is set to one millisecond before the current bar so the 200-limit
    # response contains 200 completed bars, never the in-progress candle.
    def _work() -> list[dict[str, Any]]:
        payload = adapter._get_json(
            "/openApi/swap/v3/quote/klines",
            {
                "symbol": _norm_symbol(symbol),
                "interval": _norm_timeframe(timeframe),
                "startTime": start_ms,
                "endTime": end_exclusive - 1,
                "limit": int(history_bars),
            },
        )
        if isinstance(payload, Mapping) and int(payload.get("code", 0) or 0) != 0:
            raise RuntimeError(f"TREND_MOMENTUM_BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
        data = adapter._extract_data(payload)
        return _normalize_api_rows(data)

    rows = await asyncio.to_thread(_work)
    completed = normalize_completed_candles(rows, timeframe=timeframe, now_ms=now_ms)
    in_window = [row for row in completed if start_ms <= int(row["ts"]) < end_exclusive]
    if len(in_window) != history_bars:
        raise RuntimeError(f"TREND_MOMENTUM_COMPLETED_WINDOW_INCOMPLETE:{len(in_window)}:{history_bars}")
    expected = list(range(start_ms, end_exclusive, interval_ms))
    actual = [int(row["ts"]) for row in in_window]
    if actual != expected:
        raise RuntimeError("TREND_MOMENTUM_COMPLETED_WINDOW_GAP")
    return in_window


def generate_live_signal(
    authority: Mapping[str, Any],
    *,
    factory: Mapping[str, Any] | None = None,
    adapter: BingXPublicAdapter | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    cfg_root = dict(factory) if factory is not None else load_config()
    cfg = trend_config(cfg_root)
    symbol = _symbol(authority.get("symbol"))
    native = adapter or BingXPublicAdapter()
    stale_ms = _required_data_stale_ms()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    quote = fetch_fresh_bingx_quote(symbol, max_stale_ms=stale_ms, now_ms=now, adapter=native)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        candles = asyncio.run(
            _fetch_completed_window(native, symbol, str(cfg["timeframe"]), int(cfg["history_bars"]), now)
        )
    else:
        raise RuntimeError("TREND_MOMENTUM_SYNC_CALLED_INSIDE_RUNNING_EVENT_LOOP")
    return build_signal(authority=authority, factory=cfg_root, candles=candles, quote=quote, now_ms=now)
