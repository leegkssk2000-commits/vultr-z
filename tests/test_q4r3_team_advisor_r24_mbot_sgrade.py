from __future__ import annotations

from copy import deepcopy

from canonical.bots.contracts import BotRequest
from canonical.bots.mbot import MBot, SNAPSHOT_FIELDS


def base_evidence() -> dict:
    snapshot = {
        "method_fit_score": 0.85,
        "range_quality_score": 0.70,
        "timing_quality_score": 0.80,
        "retest_quality_score": 0.75,
        "entry_quality_score": 0.78,
        "volatility_fit_score": 0.76,
        "conflict_score": 0.10,
        "helper_need_score": 0.10,
        "confidence_score": 0.81,
        "method_ts": "2026-07-16T00:00:00+00:00",
        "market_ts": "2026-07-16T00:10:00+00:00",
        "previous_posture": "hold"
    }
    return {
        "method_fit": "fit",
        "range_state": "range",
        "conflict_flags": [],
        "helper_flags": [],
        "integrity": {
            "ok": True,
            "missing": False,
            "disconnected": False,
            "ts_anomaly": False,
            "key_mismatch": False,
            "stale": False
        },
        "snapshot": snapshot,
        "metric_sources": {key: f"cf:mbot/{key}" for key in SNAPSHOT_FIELDS},
        "rules": [{
            "rule_id": "quiet",
            "category": "timing",
            "metric": "timing_quality_score",
            "operator": "lt",
            "limit": 0.10,
            "unit": "score",
            "priority": 1,
            "action": "reduce25",
            "source_id": "sheets:ssot/mbot/quiet"
        }]
    }


def request(evidence: dict, *, data_state: str = "FRESH") -> BotRequest:
    return BotRequest(
        decision_id="decision.r24",
        position_id="position.r24",
        event_id="event.r24",
        parent_event_id="event.parent",
        event_ts="2026-07-16T00:10:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.range",
        method_id="method.retest",
        skill_id="skill.partial",
        team_id="BetaTeam",
        team_role="main",
        data_state=data_state,
        freshness_ms=10,
        latency_ms=20,
        role_evidence=evidence,
        source_ids=("cf:mbot/source",),
        evidence_ids=("evidence:mbot/r24",)
    )


def test_valid_no_trigger_holds_without_abstaining() -> None:
    result = MBot().assess(base_evidence())
    assert result.action == "hold"
    assert result.abstain is False
    assert result.veto is False
    assert result.confidence == 0.81


def test_method_mismatch_can_route_change_with_ssot_rule() -> None:
    value = base_evidence()
    value["method_fit"] = "mismatch"
    value["snapshot"]["method_fit_score"] = 0.10
    value["rules"] = [{
        "rule_id": "method_mismatch_route",
        "category": "method",
        "metric": "method_fit_score",
        "operator": "lte",
        "limit": 0.20,
        "unit": "score",
        "priority": 10,
        "action": "route_change",
        "method_states": ["mismatch"],
        "source_id": "sheets:ssot/mbot/method"
    }]
    result = MBot().assess(value)
    assert result.action == "route_change"
    assert result.abstain is False
    assert result.veto is False


def test_unresolved_method_mismatch_fails_closed() -> None:
    value = base_evidence()
    value["method_fit"] = "mismatch"
    result = MBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "MBOT_UNRESOLVED_METHOD_FIT" in result.reason_codes


def test_poor_timing_can_reduce() -> None:
    value = base_evidence()
    value["snapshot"]["timing_quality_score"] = 0.20
    value["rules"] = [{
        "rule_id": "timing_reduce",
        "category": "timing",
        "metric": "timing_quality_score",
        "operator": "lte",
        "limit": 0.30,
        "unit": "score",
        "priority": 7,
        "action": "reduce25",
        "range_states": ["range"],
        "source_id": "cf:ssot/mbot/timing"
    }]
    result = MBot().assess(value)
    assert result.action == "reduce25"
    assert result.abstain is False


def test_unresolved_conflict_fails_closed() -> None:
    value = base_evidence()
    value["conflict_flags"] = ["METHOD_TIMEFRAME_DIVERGENCE"]
    result = MBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "MBOT_UNRESOLVED_CONFLICT_FLAGS" in result.reason_codes


def test_helper_trigger_requires_explicit_helper_rule() -> None:
    value = base_evidence()
    value["helper_flags"] = ["RETEST_CONFIRMATION_REQUIRED"]
    result = MBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "MBOT_UNRESOLVED_HELPER_FLAGS" in result.reason_codes

    value["snapshot"]["helper_need_score"] = 0.90
    value["rules"] = [{
        "rule_id": "helper_route",
        "category": "helper",
        "metric": "helper_need_score",
        "operator": "gte",
        "limit": 0.80,
        "unit": "score",
        "priority": 9,
        "action": "route_change",
        "source_id": "sheets:ssot/mbot/helper"
    }]
    resolved = MBot().assess(value)
    assert resolved.action == "route_change"
    assert resolved.abstain is False


def test_missing_metric_source_fails_closed() -> None:
    value = base_evidence()
    del value["metric_sources"]["retest_quality_score"]
    result = MBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert any(code.startswith("MBOT_SOURCE_MISSING") for code in result.reason_codes)


def test_evaluate_preserves_lineage_and_stale_fails_closed() -> None:
    value = base_evidence()
    response = MBot().evaluate(request(value))
    assert response.decision_id == "decision.r24"
    assert response.strategy_id == "strategy.range"
    assert response.method_id == "method.retest"
    assert response.skill_id == "skill.partial"
    assert response.team_id == "BetaTeam"
    assert response.authority == "advisory_only"
    assert response.direct_order_allowed is False

    stale = MBot().evaluate(request(deepcopy(value), data_state="STALE"))
    assert stale.action == "hold"
    assert stale.abstain is True
    assert stale.veto is False
