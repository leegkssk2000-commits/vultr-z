from __future__ import annotations

import pytest

from backend.production.zel_production_improvement_controller_v1 import stable_sha
from backend.production.zel_production_v2_family_signal_v1 import build_signal


def seal(row: dict) -> dict:
    row["receipt_sha256"] = stable_sha(row)
    return row


def authority(strategy_id: str, *, symbol: str = "BTCUSDT") -> dict:
    return {
        "strategy_id": strategy_id,
        "alpha_id": "alpha.family.v1",
        "family_id": strategy_id.removesuffix("_v1"),
        "symbol": symbol,
        "contract_id": "contract-1",
        "canary_key": "canary-key-1",
        "contract_receipt_sha256": "a" * 64,
    }


def canary_state(auth: dict, *, status: str = "PASS") -> dict:
    result = seal({
        "schema_version": "zel.production_family_paper_canary_result.v1",
        "state": "PASS_FAMILY_PAPER_CANARY",
        "prospective_only": True,
        "admission_history_reuse_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    })
    meta = {
        "status": status,
        "family_id": auth["family_id"],
        "strategy_id": auth["strategy_id"],
        "contract_id": auth["contract_id"],
        "contract_receipt_sha256": auth["contract_receipt_sha256"],
        "result": result,
    }
    return {
        "schema_version": "zel.production_family_paper_canary_runner.v1",
        "state": "HOLD_FAMILY_PAPER_CANARY_TERMINAL_ONLY",
        "canaries": {auth["canary_key"]: meta},
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def carry_snapshot(*, observed_at_ms: int = 1000, basis_bps: float = 5.0, funding_rate: float = 0.001, oi: float = 110.0) -> dict:
    return seal({
        "schema_version": "zel.production_carry_flow_data.v1",
        "state": "PASS_CARRY_POSITIONING_RAW_DATA",
        "observed_at_ms": observed_at_ms,
        "records": [
            {
                "feature": "premium_index",
                "symbol": "BTC-USDT",
                "raw": {"markPrice": 100.0, "indexPrice": 99.95, "lastFundingRate": funding_rate},
                "derived_observation": {"basis_bps": basis_bps},
                "source_payload_sha256": "b" * 64,
            },
            {
                "feature": "open_interest",
                "symbol": "BTC-USDT",
                "raw": {"openInterest": oi},
                "source_payload_sha256": "c" * 64,
            },
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    })


def l2_snapshot(*, observed_at_ms: int = 1100, sign: int = 1) -> dict:
    return seal({
        "schema_version": "zel.production_l2_order_book_data.v1",
        "state": "PASS_L2_ORDER_BOOK_NATIVE_SNAPSHOT",
        "observed_at_ms": observed_at_ms,
        "records": [
            {
                "symbol": "BTC-USDT",
                "imbalance_returned_book": 0.25 * sign,
                "primary_imbalance_sign": sign,
                "source_payload_sha256": "d" * 64,
            }
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    })


def history_row(*, basis_bps: float = 2.0, oi: float = 100.0) -> dict:
    return seal({
        "schema_version": "zel.production_ai_admission_observation.v1",
        "contract_id": "contract-1",
        "family_id": "basis_oi_deleveraging",
        "template_id": "basis_oi_deleveraging_v1",
        "symbol": "BTC-USDT",
        "observed_at_ms": 500,
        "outcome_candle_ts_ms": 400,
        "basis_bps": basis_bps,
        "open_interest": oi,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    })


def test_l2_inventory_pressure_follows_verified_primary_imbalance() -> None:
    auth = authority("l2_inventory_pressure_v1")
    signal = build_signal(
        auth,
        canary_state=canary_state(auth),
        history=[],
        l2_snapshot=l2_snapshot(sign=1),
        carry_snapshot=carry_snapshot(basis_bps=5.0),
        now_ms=1200,
        max_stale_ms=1000,
    )
    assert signal["signal"] == "LONG"
    assert signal["features"]["context_pass"] is True
    assert signal["features"]["primary_imbalance_sign"] == 1
    assert signal["source"]["provider"] == "verified_native_bingx_snapshots"
    assert signal["order_authority"] == "BLOCKED"
    assert signal["live_trade_authority"] == "BLOCKED"
    assert signal["exchange_order_submitted"] is False


def test_funding_l2_exhaustion_fades_matching_positive_funding() -> None:
    auth = authority("funding_l2_inventory_exhaustion_v1")
    signal = build_signal(
        auth,
        canary_state=canary_state(auth),
        history=[],
        l2_snapshot=l2_snapshot(sign=1),
        carry_snapshot=carry_snapshot(funding_rate=0.001),
        now_ms=1200,
        max_stale_ms=1000,
    )
    assert signal["signal"] == "SHORT"
    assert signal["features"]["context_pass"] is True
    assert signal["features"]["funding_sign"] == 1


def test_basis_oi_deleveraging_uses_verified_prior_canary_observation() -> None:
    auth = authority("basis_oi_deleveraging_v1")
    signal = build_signal(
        auth,
        canary_state=canary_state(auth),
        history=[history_row(basis_bps=2.0, oi=100.0)],
        l2_snapshot=None,
        carry_snapshot=carry_snapshot(basis_bps=5.0, oi=110.0),
        now_ms=1200,
        max_stale_ms=1000,
    )
    assert signal["signal"] == "SHORT"
    assert signal["features"]["basis_delta_bps"] == pytest.approx(3.0)
    assert signal["features"]["open_interest_delta"] == pytest.approx(10.0)
    assert signal["features"]["context_pass"] is True


def test_same_verified_snapshot_reuses_exact_signal_without_refreshing_timestamp() -> None:
    auth = authority("funding_l2_inventory_exhaustion_v1")
    l2 = l2_snapshot(sign=-1)
    carry = carry_snapshot(funding_rate=-0.001)
    first = build_signal(
        auth,
        canary_state=canary_state(auth),
        history=[],
        l2_snapshot=l2,
        carry_snapshot=carry,
        now_ms=1200,
        max_stale_ms=1000,
    )
    second = build_signal(
        auth,
        canary_state=canary_state(auth),
        history=[],
        l2_snapshot=l2,
        carry_snapshot=carry,
        prior_signal=first,
        now_ms=1500,
        max_stale_ms=1000,
    )
    assert second == first
    assert second["signal_ts"] == first["signal_ts"]
    assert second["receipt_sha256"] == first["receipt_sha256"]


def test_stale_native_snapshot_fails_closed() -> None:
    auth = authority("l2_inventory_pressure_v1")
    with pytest.raises(RuntimeError, match="L2_STALE"):
        build_signal(
            auth,
            canary_state=canary_state(auth),
            history=[],
            l2_snapshot=l2_snapshot(observed_at_ms=100),
            carry_snapshot=carry_snapshot(observed_at_ms=100),
            now_ms=5000,
            max_stale_ms=1000,
        )


def test_nonpassing_canary_cannot_produce_runtime_signal() -> None:
    auth = authority("basis_oi_deleveraging_v1")
    with pytest.raises(RuntimeError, match="CANARY_NOT_PASS"):
        build_signal(
            auth,
            canary_state=canary_state(auth, status="REJECT"),
            history=[history_row()],
            l2_snapshot=None,
            carry_snapshot=carry_snapshot(),
            now_ms=1200,
            max_stale_ms=1000,
        )
