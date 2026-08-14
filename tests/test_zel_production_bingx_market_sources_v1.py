from __future__ import annotations

import json
from pathlib import Path

from backend.production import zel_production_bingx_market_sources_v1 as m


def policy():
    return {
        "schema_version": m.POLICY_SCHEMA,
        "state": "FROZEN_PAPER_PUBLIC_SOURCE_VERIFY",
        "mode": "PAPER",
        "role": "PUBLIC_MARKET_SOURCE_VERIFIER_NOT_STRATEGY",
        "base_url": "https://open-api.bingx.com",
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "kline_interval": "15m",
        "kline_limit": 96,
        "depth_limit": 20,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def fake_fetch(url: str):
    if "/klines?" in url:
        return {
            "code": 0,
            "msg": "",
            "data": [
                [1, "100", "102", "99", "101", "10", 2, "1010", 8, "6", "606"],
                [3, "101", "103", "100", "102", "12", 4, "1224", 9, "7", "714"],
            ],
        }
    if "/depth?" in url:
        return {"code": 0, "msg": "", "data": {"bids": [["101.9", "2"]], "asks": [["102.1", "3"]], "T": 5}}
    raise AssertionError(url)


def test_verify_sources_is_public_data_only_and_non_authoritative():
    out = m.verify_sources(policy(), fetcher=fake_fetch, now_ms=10)
    assert out["state"] == "PASS_BINGX_PUBLIC_MARKET_SOURCES_VERIFIED"
    assert out["verified_sources"] == ["ohlcv", "volume", "l2_order_book"]
    assert out["source_bindings"] == {
        "ohlcv_source_bound": True,
        "volume_source_bound": True,
        "l2_order_book_source_bound": True,
    }
    assert out["history_coverage_bound"] is False
    assert out["economic_signal_enabled"] is False
    assert out["selection_authority"] is False
    assert out["promotion_authority"] is False
    assert out["execution_authority"] == "NONE"
    assert out["order_authority"] == "BLOCKED"
    assert out["live_trade_authority"] == "BLOCKED"
    assert out["exchange_order_submitted"] is False
    assert out["symbols"][0]["kline"]["last_base_volume"] == 12.0
    assert out["symbols"][0]["depth"]["spread_bps"] > 0


def test_invalid_authority_fails_closed():
    bad = policy()
    bad["selection_authority"] = True
    try:
        m.validate_policy(bad)
    except RuntimeError as exc:
        assert "SELECTION_AUTHORITY_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("selection authority must fail closed")


def test_bad_market_schema_fails_closed():
    def bad_fetch(url: str):
        if "/klines?" in url:
            return {"code": 0, "msg": "", "data": [[1, "1"]]}
        return {"code": 0, "msg": "", "data": {"bids": [], "asks": []}}

    try:
        m.verify_sources(policy(), fetcher=bad_fetch, now_ms=10)
    except RuntimeError as exc:
        assert "BINGX_MARKET_SOURCE_KLINES_INSUFFICIENT" in str(exc) or "BINGX_MARKET_SOURCE_KLINE_SCHEMA_INVALID" in str(exc)
    else:
        raise AssertionError("invalid market schema must fail closed")


def test_frozen_policy_file_matches_contract():
    cfg = json.loads(Path("config/zel_production_bingx_market_sources_v1.json").read_text())
    assert m.validate_policy(cfg)["base_url"] == "https://open-api.bingx.com"
    assert cfg["source_contract"]["ohlcv_endpoint"] == "/openApi/swap/v3/quote/klines"
    assert cfg["source_contract"]["depth_endpoint"] == "/openApi/swap/v2/quote/depth"
