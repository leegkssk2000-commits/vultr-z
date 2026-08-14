from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_pre_survivor_research_comparator_v1 import compare_tick

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/zel_production_pre_survivor_research_comparator_v1.json").read_text())
TS = 1_780_000_000_000


def evidence(
    family_id: str,
    *,
    trade_count: int,
    win_rate_pct: float,
    net_expectancy: float,
    profit_factor: float,
    net_pnl: float,
    max_dd_pct: float,
) -> dict:
    return {
        "state": "PASS_RESEARCH_EVIDENCE",
        "family_id": family_id,
        "trade_count": trade_count,
        "win_rate_pct": win_rate_pct,
        "net_expectancy": net_expectancy,
        "profit_factor": profit_factor,
        "net_pnl": net_pnl,
        "max_dd_pct": max_dd_pct,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def test_challenger_requires_joint_economic_improvement_and_no_wr_dd_pf_regression() -> None:
    reference = evidence(
        "reference_family",
        trade_count=20,
        win_rate_pct=55.0,
        net_expectancy=3.0,
        profit_factor=1.20,
        net_pnl=60.0,
        max_dd_pct=1.5,
    )
    challenger = evidence(
        "challenger_family",
        trade_count=20,
        win_rate_pct=57.0,
        net_expectancy=3.5,
        profit_factor=1.25,
        net_pnl=70.0,
        max_dd_pct=1.4,
    )
    out = compare_tick(POLICY, reference=reference, challenger=challenger, now_ms=TS)
    assert out["state"] == "PASS_PRE_SURVIVOR_RESEARCH_COMPARISON_CAPTURED"
    assert out["research_preference"] == "CHALLENGER_RESEARCH_PREFERRED"
    assert all(out["research_guards"].values())
    assert out["win_rate_role"] == "RESEARCH_GUARD_NOT_PROMOTION_GATE"
    assert out["preference_is_authority"] is False
    assert out["selection_authority"] is False
    assert out["promotion_authority"] is False
    assert out["execution_authority"] == "NONE"
    assert out["order_authority"] == "BLOCKED"
    assert out["live_trade_authority"] == "BLOCKED"
    assert out["action"] == "hold"


def test_better_expectancy_alone_cannot_override_worse_win_rate() -> None:
    reference = evidence(
        "reference_family",
        trade_count=20,
        win_rate_pct=55.0,
        net_expectancy=3.0,
        profit_factor=1.20,
        net_pnl=60.0,
        max_dd_pct=1.5,
    )
    challenger = evidence(
        "challenger_family",
        trade_count=20,
        win_rate_pct=50.0,
        net_expectancy=4.0,
        profit_factor=1.30,
        net_pnl=80.0,
        max_dd_pct=1.4,
    )
    out = compare_tick(POLICY, reference=reference, challenger=challenger, now_ms=TS)
    assert out["research_preference"] == "REFERENCE_RESEARCH_PREFERRED"
    assert out["research_guards"]["win_rate_not_worse"] is False
    assert out["research_guards"]["expectancy_improved"] is True


def test_lower_drawdown_and_higher_wr_cannot_override_worse_pnl_or_expectancy() -> None:
    reference = evidence(
        "reference_family",
        trade_count=20,
        win_rate_pct=55.0,
        net_expectancy=3.0,
        profit_factor=1.20,
        net_pnl=60.0,
        max_dd_pct=1.5,
    )
    challenger = evidence(
        "challenger_family",
        trade_count=20,
        win_rate_pct=60.0,
        net_expectancy=2.5,
        profit_factor=1.30,
        net_pnl=50.0,
        max_dd_pct=1.0,
    )
    out = compare_tick(POLICY, reference=reference, challenger=challenger, now_ms=TS)
    assert out["research_preference"] == "REFERENCE_RESEARCH_PREFERRED"
    assert out["research_guards"]["expectancy_improved"] is False
    assert out["research_guards"]["net_pnl_improved"] is False


def test_less_evidence_cannot_be_research_preferred() -> None:
    reference = evidence(
        "reference_family",
        trade_count=20,
        win_rate_pct=55.0,
        net_expectancy=3.0,
        profit_factor=1.20,
        net_pnl=60.0,
        max_dd_pct=1.5,
    )
    challenger = evidence(
        "challenger_family",
        trade_count=19,
        win_rate_pct=60.0,
        net_expectancy=4.0,
        profit_factor=1.40,
        net_pnl=80.0,
        max_dd_pct=1.0,
    )
    out = compare_tick(POLICY, reference=reference, challenger=challenger, now_ms=TS)
    assert out["research_preference"] == "REFERENCE_RESEARCH_PREFERRED"
    assert out["research_guards"]["evidence_not_less"] is False


def test_missing_reference_metrics_hold_without_crashing() -> None:
    reference = {
        "state": "HOLD_PRE_SURVIVOR_RESEARCH_REFERENCE_METRICS_MISSING",
        "family_id": "reference_family",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    challenger = evidence(
        "challenger_family",
        trade_count=20,
        win_rate_pct=57.0,
        net_expectancy=3.5,
        profit_factor=1.25,
        net_pnl=70.0,
        max_dd_pct=1.4,
    )
    out = compare_tick(POLICY, reference=reference, challenger=challenger, now_ms=TS)
    assert out["state"] == "HOLD_PRE_SURVIVOR_RESEARCH_REFERENCE_METRICS_MISSING"
    assert out["research_preference"] == "NONE"
    assert "METRICS_MISSING:reference" in out["reference_metric_error"]
    assert out["selection_authority"] is False
    assert out["promotion_authority"] is False
    assert out["execution_authority"] == "NONE"
    assert out["order_authority"] == "BLOCKED"
    assert out["live_trade_authority"] == "BLOCKED"


def test_invalid_reference_metric_holds_without_crashing() -> None:
    reference = evidence(
        "reference_family",
        trade_count=20,
        win_rate_pct=55.0,
        net_expectancy=3.0,
        profit_factor=1.20,
        net_pnl=60.0,
        max_dd_pct=1.5,
    )
    reference["net_expectancy"] = "not-a-number"
    challenger = evidence(
        "challenger_family",
        trade_count=20,
        win_rate_pct=57.0,
        net_expectancy=3.5,
        profit_factor=1.25,
        net_pnl=70.0,
        max_dd_pct=1.4,
    )
    out = compare_tick(POLICY, reference=reference, challenger=challenger, now_ms=TS)
    assert out["state"] == "HOLD_PRE_SURVIVOR_RESEARCH_REFERENCE_METRICS_INVALID"
    assert out["research_preference"] == "NONE"
    assert out["order_authority"] == "BLOCKED"


def test_missing_challenger_holds_without_authority() -> None:
    reference = evidence(
        "reference_family",
        trade_count=20,
        win_rate_pct=55.0,
        net_expectancy=3.0,
        profit_factor=1.20,
        net_pnl=60.0,
        max_dd_pct=1.5,
    )
    out = compare_tick(POLICY, reference=reference, challenger=None, now_ms=TS)
    assert out["state"] == "HOLD_PRE_SURVIVOR_RESEARCH_CHALLENGER_MISSING"
    assert out["research_preference"] == "NONE"
    assert out["order_authority"] == "BLOCKED"
    assert out["live_trade_authority"] == "BLOCKED"


def test_authority_drift_fails_closed() -> None:
    reference = evidence(
        "reference_family",
        trade_count=20,
        win_rate_pct=55.0,
        net_expectancy=3.0,
        profit_factor=1.20,
        net_pnl=60.0,
        max_dd_pct=1.5,
    )
    challenger = evidence(
        "challenger_family",
        trade_count=20,
        win_rate_pct=57.0,
        net_expectancy=3.5,
        profit_factor=1.25,
        net_pnl=70.0,
        max_dd_pct=1.4,
    )
    challenger["order_authority"] = "OPEN"
    try:
        compare_tick(POLICY, reference=reference, challenger=challenger, now_ms=TS)
    except RuntimeError as exc:
        assert "EXECUTION_AUTHORITY_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("authority drift must fail closed")
