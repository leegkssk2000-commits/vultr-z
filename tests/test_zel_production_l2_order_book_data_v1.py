from __future__ import annotations

import json

import pytest

from backend.production.zel_production_l2_order_book_data_v1 import ENDPOINT, collect_snapshot, normalize


def payload() -> dict:
    return {
        "bids": [["100.0", "2.0"], ["99.0", "1.0"]],
        "asks": [["101.0", "1.0"], ["102.0", "1.0"]],
    }


def fixture_fetch(path: str, params: dict):
    assert path == ENDPOINT
    assert params["limit"] == 100
    assert params["symbol"] in {"BTC-USDT", "ETH-USDT"}
    return payload(), "https://open-api.bingx.com", 7.5


def test_collect_normalized_l2_snapshot_without_trade_authority() -> None:
    out = collect_snapshot(fetcher=fixture_fetch, symbols=("BTC-USDT", "ETH-USDT"), now_ms=1234)
    assert out["state"] == "PASS_L2_ORDER_BOOK_NATIVE_SNAPSHOT"
    assert out["native_endpoint"] == "/openApi/swap/v2/quote/depth"
    assert out["record_count"] == 2
    assert out["history_ready_for_economic_claim"] is False
    assert out["selection_authority"] is False
    assert out["promotion_authority"] is False
    assert out["execution_authority"] == "NONE"
    assert out["order_authority"] == "BLOCKED"
    assert out["exchange_order_submitted"] is False
    assert len(out["receipt_sha256"]) == 64
    for row in out["records"]:
        assert row["best_bid"] == 100.0
        assert row["best_ask"] == 101.0
        assert row["primary_imbalance_sign"] == 1
        assert row["source_endpoint"] == ENDPOINT
        assert len(row["source_payload_sha256"]) == 64


def test_normalizer_rejects_crossed_book() -> None:
    bad = payload()
    bad["asks"][0][0] = "99.5"
    with pytest.raises(RuntimeError, match="CROSSED_BOOK"):
        normalize("BTC-USDT", bad, "x", 1.0, 1)


def test_snapshot_is_json_serializable_and_contains_no_order_surface() -> None:
    out = collect_snapshot(fetcher=fixture_fetch, symbols=("BTC-USDT", "ETH-USDT"), now_ms=1234)
    text = json.dumps(out, sort_keys=True)
    assert "submit_order" not in text
    assert "api_key" not in text.lower()
