import pytest

from backend.production.zel_production_trend_momentum_v1 import build_signal


QUOTE_SHA = "a" * 64


def factory():
    return {
        "schema_version": "zel.production_alpha_factory.v1",
        "mode": "PAPER",
        "families": {
            "trend_momentum": {
                "strategy_id": "trend_momentum_v1",
                "status": "IMPLEMENTED_PRIMARY_SEED",
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "timeframe": "1h",
                "history_bars": 200,
                "long_enabled": True,
                "short_enabled": False,
                "ema_fast": 50,
                "ema_slow": 200,
                "parameter_lineage": {
                    "source": "strategies/evidence_alpha_v1.py:_htf_bias",
                    "source_sha256": "a060529401c9a218cfa04be0511d5f7ab0cdecff",
                    "inherited_rule": "price > EMA50 > EMA200",
                },
                "promotion_authority": False,
                "execution_authority": "PAPER_SIGNAL_ONLY",
            }
        },
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def authority(symbol="BTCUSDT"):
    return {
        "strategy_id": "trend_momentum_v1",
        "alpha_id": "trend.seed.v1",
        "symbol": symbol,
    }


def candles(*, rising=True, count=199, now_ms=2_000_000_000_000):
    interval = 3_600_000
    start = now_ms - (count + 1) * interval
    rows = []
    for idx in range(count):
        close = 100.0 + idx if rising else 400.0 - idx
        rows.append(
            {
                "ts": start + idx * interval,
                "op": close - 0.2,
                "hi": close + 0.5,
                "lo": close - 0.5,
                "cl": close,
                "vol": 10.0 + idx,
            }
        )
    return rows


def quote(price, now_ms=2_000_000_000_000, symbol="BTCUSDT"):
    return {
        "state": "PASS_BINGX_FRESH",
        "provider": "bingx_public",
        "symbol": symbol,
        "last": price,
        "observed_at_ms": now_ms,
        "age_ms": 0,
        "receipt_sha256": QUOTE_SHA,
    }


def test_bullish_alignment_produces_long_with_lineage():
    now = 2_000_000_000_000
    result = build_signal(
        authority=authority(),
        factory=factory(),
        candles=candles(rising=True, now_ms=now),
        quote=quote(320.0, now_ms=now),
        now_ms=now,
    )
    assert result["signal"] == "LONG"
    assert result["features"]["price"] > result["features"]["ema_fast"] > result["features"]["ema_slow"]
    assert result["features"]["bullish_alignment"] is True
    assert result["source"]["provider"] == "bingx_public"
    assert result["source"]["completed_candle_count"] == 199
    assert result["source"]["dummy_fallback_used"] is False
    assert len(result["source_hashes"]) == 3
    assert QUOTE_SHA in result["source_hashes"]
    assert result["promotion_authority"] is False
    assert result["execution_authority"] == "PAPER_SIGNAL_ONLY"
    assert result["exchange_order_submitted"] is False


def test_non_bullish_alignment_exits_instead_of_shorting():
    now = 2_000_000_000_000
    result = build_signal(
        authority=authority(),
        factory=factory(),
        candles=candles(rising=False, now_ms=now),
        quote=quote(180.0, now_ms=now),
        now_ms=now,
    )
    assert result["signal"] == "EXIT"
    assert result["features"]["bullish_alignment"] is False
    assert result["signal"] != "SHORT"


def test_duplicate_candle_timestamp_fails_closed():
    now = 2_000_000_000_000
    rows = candles(rising=True, now_ms=now)
    rows.append(dict(rows[-1]))
    with pytest.raises(RuntimeError, match="DUPLICATE_CANDLE_TS"):
        build_signal(
            authority=authority(),
            factory=factory(),
            candles=rows,
            quote=quote(320.0, now_ms=now),
            now_ms=now,
        )


def test_bad_ohlc_and_short_history_fail_closed():
    now = 2_000_000_000_000
    rows = candles(rising=True, now_ms=now)
    rows[0]["hi"] = rows[0]["lo"] - 1.0
    with pytest.raises(RuntimeError, match="CANDLE_OHLC_INVALID"):
        build_signal(
            authority=authority(), factory=factory(), candles=rows,
            quote=quote(320.0, now_ms=now), now_ms=now,
        )
    with pytest.raises(RuntimeError, match="HISTORY_SHORT"):
        build_signal(
            authority=authority(), factory=factory(), candles=candles(count=50, now_ms=now),
            quote=quote(320.0, now_ms=now), now_ms=now,
        )


def test_parameter_lineage_and_bingx_quote_are_hard_gates():
    now = 2_000_000_000_000
    bad = factory()
    bad["families"]["trend_momentum"]["parameter_lineage"]["source_sha256"] = "b" * 40
    with pytest.raises(RuntimeError, match="PARAMETER_LINEAGE_INVALID"):
        build_signal(
            authority=authority(), factory=bad, candles=candles(now_ms=now),
            quote=quote(320.0, now_ms=now), now_ms=now,
        )
    bad_quote = quote(320.0, now_ms=now)
    bad_quote["provider"] = "dummy_fallback"
    with pytest.raises(RuntimeError, match="QUOTE_NOT_FRESH_BINGX"):
        build_signal(
            authority=authority(), factory=factory(), candles=candles(now_ms=now),
            quote=bad_quote, now_ms=now,
        )
