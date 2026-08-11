import pytest

from backend.production.zel_production_carry_flow_data_v1 import collect_snapshot


def fetcher(path, params):
    symbol = params["symbol"]
    if path.endswith("premiumIndex"):
        return {
            "symbol": symbol,
            "markPrice": "101.0",
            "indexPrice": "100.0",
            "lastFundingRate": "0.0001",
            "fundingIntervalHours": 8,
            "nextFundingTime": 20_000,
            "updateTime": 9_900,
        }, "https://open-api.bingx.com", 12.0
    if path.endswith("openInterest"):
        return {
            "symbol": symbol,
            "openInterest": "1234.5",
            "time": 9_900,
        }, "https://open-api.bingx.com", 11.0
    raise AssertionError(path)


def test_collects_exact_two_symbols_two_native_features_without_signal_authority():
    row = collect_snapshot(fetcher=fetcher, now_ms=10_000_000)
    assert row["state"] == "PASS_CARRY_POSITIONING_RAW_DATA"
    assert row["record_count"] == 4
    assert row["funding_source_bound"] is True
    assert row["basis_source_bound"] is True
    assert row["open_interest_source_bound"] is True
    assert row["flow_source_bound"] is False
    assert row["economic_signal_generated"] is False
    assert row["promotion_authority"] is False
    assert row["execution_authority"] == "NONE"
    assert row["order_authority"] == "BLOCKED"
    assert row["exchange_order_submitted"] is False

    premium = [r for r in row["records"] if r["feature"] == "premium_index"]
    oi = [r for r in row["records"] if r["feature"] == "open_interest"]
    assert len(premium) == 2 and len(oi) == 2
    assert all(round(r["derived_observation"]["basis_bps"], 8) == 100.0 for r in premium)
    assert all(r["raw"]["openInterest"] == 1234.5 for r in oi)
    assert all(len(r["source_payload_sha256"]) == 64 for r in row["records"])


def test_missing_required_numeric_field_fails_closed():
    def broken(path, params):
        payload, base, latency = fetcher(path, params)
        if path.endswith("premiumIndex"):
            payload = dict(payload)
            payload.pop("lastFundingRate")
        return payload, base, latency

    with pytest.raises(RuntimeError, match="CARRY_FLOW_NUMERIC_INVALID"):
        collect_snapshot(fetcher=broken, now_ms=10_000_000)


def test_negative_open_interest_fails_closed():
    def broken(path, params):
        payload, base, latency = fetcher(path, params)
        if path.endswith("openInterest"):
            payload = dict(payload)
            payload["openInterest"] = "-1"
        return payload, base, latency

    with pytest.raises(RuntimeError, match="CARRY_FLOW_OI_NEGATIVE"):
        collect_snapshot(fetcher=broken, now_ms=10_000_000)
