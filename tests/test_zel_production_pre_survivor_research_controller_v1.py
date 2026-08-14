from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_pre_survivor_research_controller_v1 import (
    ACCUMULATING_STATE,
    INCUMBENT_SCHEMA,
    prepare_reference,
    update_incumbent,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/zel_production_pre_survivor_research_controller_v1.json").read_text())
NOW = 1_780_000_000_000


def safety() -> dict:
    return {
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def metrics(*, trades: int, wr: float, exp: float, pf: float, pnl: float, dd: float) -> dict:
    return {
        "trade_count": trades,
        "win_rate_pct": wr,
        "net_expectancy": exp,
        "profit_factor": pf,
        "net_pnl": pnl,
        "max_dd_pct": dd,
    }


def active_row(**overrides) -> dict:
    row = {
        "schema_version": "zel.production_pre_survivor_feedback_bridge.v1",
        "state": ACCUMULATING_STATE,
        "family_id": "active_family",
        "contract_id": "a" * 32,
        "template_id": "funding_volume_elasticity_v1",
        **metrics(trades=10, wr=50.0, exp=-2.0, pf=0.9, pnl=-20.0, dd=0.7),
        **safety(),
    }
    row.update(overrides)
    return row


def incumbent_row(**overrides) -> dict:
    row = {
        "schema_version": INCUMBENT_SCHEMA,
        "state": "PASS_PRE_SURVIVOR_RESEARCH_INCUMBENT",
        "family_id": "incumbent_family",
        "contract_id": "b" * 32,
        "template_id": "basis_oi_deleveraging_v1",
        "generation": 1,
        **metrics(trades=10, wr=60.0, exp=2.0, pf=1.2, pnl=20.0, dd=0.5),
        **safety(),
    }
    row.update(overrides)
    return row


def comparison(preferred: list[str]) -> dict:
    return {
        "schema_version": "zel.production_pre_survivor_research_comparator.v1",
        "state": "PASS_PRE_SURVIVOR_RESEARCH_COMPARISON_CAPTURED",
        "preferred_challenger_family_ids": preferred,
        "receipt_sha256": "c" * 64,
        **safety(),
    }


def evidence(row: dict) -> dict:
    return {
        "schema_version": "zel.production_pre_survivor_challenger_evidence.v1",
        "state": "PASS_PRE_SURVIVOR_CHALLENGER_EVIDENCE_CAPTURED",
        "challengers": [row],
        **safety(),
    }


def challenger(**overrides) -> dict:
    row = {
        "family_id": "challenger_family",
        "contract_id": "d" * 32,
        "template_id": "basis_oi_deleveraging_v1",
        **metrics(trades=12, wr=65.0, exp=3.0, pf=1.3, pnl=36.0, dd=0.4),
        **safety(),
    }
    row.update(overrides)
    return row


def test_prepare_uses_active_without_incumbent() -> None:
    out = prepare_reference(POLICY, active=active_row(), incumbent=None, now_ms=NOW)
    assert out["family_id"] == "active_family"
    assert out["research_reference_source"] == "ACTIVE_PRE_SURVIVOR"
    assert out["selection_authority"] is False
    assert out["promotion_authority"] is False
    assert out["execution_authority"] == "NONE"
    assert out["order_authority"] == "BLOCKED"
    assert out["live_trade_authority"] == "BLOCKED"


def test_prepare_holds_when_active_exists_without_required_metrics() -> None:
    active = active_row()
    for key in ("trade_count", "win_rate_pct", "net_expectancy", "profit_factor", "net_pnl", "max_dd_pct"):
        active.pop(key)
    out = prepare_reference(POLICY, active=active, incumbent=None, now_ms=NOW)
    assert out["state"] == "HOLD_PRE_SURVIVOR_RESEARCH_REFERENCE_METRICS_MISSING"
    assert out["family_id"] == "active_family"
    assert out["research_reference_source"] == "NONE"
    assert out["missing_metrics"] == ["trade_count", "win_rate_pct", "net_expectancy", "profit_factor", "net_pnl", "max_dd_pct"]
    assert out["selection_authority"] is False
    assert out["promotion_authority"] is False
    assert out["execution_authority"] == "NONE"
    assert out["order_authority"] == "BLOCKED"
    assert out["live_trade_authority"] == "BLOCKED"


def test_prepare_uses_valid_incumbent_when_active_metrics_are_missing() -> None:
    active = active_row()
    for key in ("trade_count", "win_rate_pct", "net_expectancy", "profit_factor", "net_pnl", "max_dd_pct"):
        active.pop(key)
    out = prepare_reference(POLICY, active=active, incumbent=incumbent_row(), now_ms=NOW)
    assert out["family_id"] == "incumbent_family"
    assert out["research_reference_source"] == "RESEARCH_INCUMBENT"
    assert out["state"] == ACCUMULATING_STATE


def test_update_creates_first_research_incumbent_only_when_comparator_prefers() -> None:
    ch = challenger()
    out, changed = update_incumbent(
        POLICY,
        comparison=comparison(["challenger_family"]),
        challenger_evidence=evidence(ch),
        previous=None,
        now_ms=NOW,
    )
    assert changed is True
    assert out is not None
    assert out["schema_version"] == INCUMBENT_SCHEMA
    assert out["family_id"] == "challenger_family"
    assert out["generation"] == 1
    assert out["research_incumbent_only"] is True
    assert out["production_promotion_applied"] is False
    assert out["selection_authority"] is False
    assert out["promotion_authority"] is False


def test_prepare_uses_better_research_incumbent_as_next_generation_feedback() -> None:
    out = prepare_reference(POLICY, active=active_row(), incumbent=incumbent_row(), now_ms=NOW)
    assert out["family_id"] == "incumbent_family"
    assert out["research_reference_source"] == "RESEARCH_INCUMBENT"
    assert out["progress_direction"] == "RESEARCH_INCUMBENT"
    assert out["state"] == ACCUMULATING_STATE
    assert out["win_rate_role"] == "RESEARCH_GUARD_NOT_PROMOTION_GATE"


def test_active_can_retake_reference_when_it_strictly_beats_incumbent() -> None:
    active = active_row(**metrics(trades=12, wr=70.0, exp=4.0, pf=1.4, pnl=48.0, dd=0.3))
    out = prepare_reference(POLICY, active=active, incumbent=incumbent_row(), now_ms=NOW)
    assert out["family_id"] == "active_family"
    assert out["research_reference_source"] == "ACTIVE_PRE_SURVIVOR"


def test_previous_incumbent_is_kept_when_new_winner_is_not_strictly_better() -> None:
    prev = incumbent_row()
    weak = challenger(
        trade_count=12,
        win_rate_pct=60.0,
        net_expectancy=2.0,
        profit_factor=1.2,
        net_pnl=20.0,
        max_dd_pct=0.5,
    )
    out, changed = update_incumbent(
        POLICY,
        comparison=comparison(["challenger_family"]),
        challenger_evidence=evidence(weak),
        previous=prev,
        now_ms=NOW,
    )
    assert changed is False
    assert out == prev
