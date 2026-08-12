from __future__ import annotations

from backend.production.zel_production_improvement_controller_v1 import stable_sha
from backend.production.zel_production_survivor_rotation_v2 import _eligible_pool_view


def _receipt(row: dict) -> dict:
    out = dict(row)
    out["receipt_sha256"] = stable_sha(out)
    return out


def test_legacy_unqualified_row_is_skipped_without_aborting_fallback_view() -> None:
    legacy = {
        "family_id": "legacy_family",
        "strategy_id": "legacy_strategy",
        "alpha_id": "legacy_alpha",
        "symbol_qualified": False,
        "runtime_symbol": "BTCUSDT",
        "source_hashes": ["a" * 64],
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
    }
    valid = {
        "family_id": "family_valid",
        "strategy_id": "l2_inventory_pressure_v1",
        "alpha_id": "alpha_valid",
        "symbol_qualified": True,
        "runtime_symbol": "BTCUSDT",
        "canary_key": "c" * 32,
        "contract_id": "contract_valid",
        "contract_receipt_sha256": "d" * 64,
        "canary_receipt_sha256": "e" * 64,
        "source_hashes": ["f" * 64],
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "metrics": {},
    }
    pool = _receipt({
        "schema_version": "zel.production_survivor_pool.v1",
        "state": "HOLD_SURVIVOR_POOL_BUILDING",
        "active": [legacy, valid],
        "reserve": [],
        "active_count": 2,
        "reserve_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    })
    view, source_receipt = _eligible_pool_view(
        pool,
        {"risk_request": {"leverage_x": 10, "position_pct": 5.0}},
    )
    assert source_receipt == pool["receipt_sha256"]
    assert view["rotation_ineligible_row_count"] == 1
    assert [row["family_id"] for row in view["active"]] == ["family_valid"]
    assert view["active_count"] == 1
