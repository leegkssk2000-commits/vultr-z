import pytest

from backend.production.zel_production_bingx_freshness_v1 import normalize_bingx_ticker


def ticker(**updates):
    row = {
        "ts": 9_900,
        "bid": 99.0,
        "ask": 101.0,
        "last": 100.0,
        "extra": {"provider": "bingx_public", "symbol": "BTCUSDT"},
    }
    row.update(updates)
    return row


def test_native_bingx_quote_passes_and_exposes_mid():
    row = normalize_bingx_ticker(ticker(), symbol="BTCUSDT", max_stale_ms=1_000, now_ms=10_000)
    assert row["state"] == "PASS_BINGX_FRESH"
    assert row["reference_price"] == 100.0
    assert row["dummy_fallback_used"] is False
    assert row["exchange_order_submitted"] is False


def test_dummy_provider_is_forbidden():
    with pytest.raises(RuntimeError, match="NOT_BINGX_NATIVE"):
        normalize_bingx_ticker(
            ticker(extra={"provider": "dummy_fallback", "symbol": "BTCUSDT"}),
            symbol="BTCUSDT",
            max_stale_ms=1_000,
            now_ms=10_000,
        )


def test_stale_and_crossed_market_fail_closed():
    with pytest.raises(RuntimeError, match="MARKET_DATA_STALE"):
        normalize_bingx_ticker(ticker(ts=1), symbol="BTCUSDT", max_stale_ms=1_000, now_ms=10_000)
    with pytest.raises(RuntimeError, match="MARKET_CROSSED_BOOK"):
        normalize_bingx_ticker(ticker(bid=102.0, ask=101.0), symbol="BTCUSDT", max_stale_ms=1_000, now_ms=10_000)


def test_symbol_mismatch_fails_closed():
    with pytest.raises(RuntimeError, match="MARKET_SYMBOL_MISMATCH"):
        normalize_bingx_ticker(ticker(), symbol="ETHUSDT", max_stale_ms=1_000, now_ms=10_000)
