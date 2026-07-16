from __future__ import annotations

from copy import deepcopy

from canonical.bots.contracts import BotRequest
from canonical.bots.lbot import LBot, SNAPSHOT_FIELDS


def base_evidence() -> dict:
    snapshot = {
        "trend_direction": "long",
        "trend_strength_score": 0.80,
        "continuation_score": 0.75,
        "structure_score": 0.78,
        "momentum_score": 0.72,
        "invalidation_score": 0.10,
        "conflict_score": 0.10,
        "regime_stability_score": 0.85,
        "confidence_score": 0.82,
        "trend_ts": "2026-07-16T00:00:00+00:00",
        "market_ts": "2026-07-16T00:10:00+00:00",
        "previous_posture": "hold",
    }
    return {
        "trend_thesis": "trend_continuation",
        "invalidation_flags": [],
        "conflict_flags": [],
        "integrity": {
            "ok": True,
            "missing": False,
            "disconnected": False,
            "ts_anomaly": False,
            "key_mismatch": False,
            "stale": False,
        },
        "snapshot": snapshot,
        "metric_sources": {key: f"cf:lbot/{key}" for key in SNAPSHOT_FIELDS},
        "rules": [
            {
                "rule_id": "quiet",
                "category": "strength",
                "metric": "trend_strength_score",
                "operator": "lt",
                "limit": 0.10,
                "unit": "score",
                "priority": 1,
                "action": "reduce25",
                "source_id": "sheets:ssot/lbot/quiet",
            }
        ],
    }


def request(evidence: dict, *, data_state: str = "FRESH") -> BotRequest:
    return BotRequest(
        decision_id="decision.r23",
        position_id="position.r23",
        event_id="event.r23",
        parent_event_id="event.parent",
        event_ts="2026-07-16T00:10:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.trend",
        method_id="method.pullback",
        skill_id="skill.runner",
        team_id="AlphaTeam",
        team_role="main",
        data_state=data_state,
        freshness_ms=10,
        latency_ms=20,
        role_evidence=evidence,
        source_ids=("cf:lbot/source",),
        evidence_ids=("evidence:lbot/r23",),
    )


def test_valid_no_trigger_holds_without_abstaining() -> None:
    result = LBot().assess(base_evidence())
    assert result.action == "hold"
    assert result.abstain is False
    assert result.veto is False
    assert result.confidence == 0.82


def test_invalidation_rule_reduces_without_veto() -> None:
    value = base_evidence()
    value["invalidation_flags"] = ["STRUCTURE_BREAK"]
    value["snapshot"]["invalidation_score"] = 0.90
    value["rules"] = [{
        "rule_id": "invalidate_reduce",
        "category": "invalidation",
        "metric": "invalidation_score",
        "operator": "gte",
        "limit": 0.70,
        "unit": "score",
        "priority": 10,
        "action": "reduce25",
        "source_id": "sheets:ssot/lbot/invalidation",
    }]
    result = LBot().assess(value)
    assert result.action == "reduce25"
    assert result.abstain is False
    assert result.veto is False
    assert any("STRUCTURE_BREAK" in code for code in result.reason_codes)


def test_unresolved_invalidation_fails_closed() -> None:
    value = base_evidence()
    value["invalidation_flags"] = ["STRUCTURE_BREAK"]
    result = LBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "LBOT_UNRESOLVED_INVALIDATION_FLAGS" in result.reason_codes


def test_continuation_transition_requires_hysteresis() -> None:
    value = base_evidence()
    value["snapshot"]["continuation_score"] = 0.90
    value["rules"] = [{
        "rule_id": "continue_partial",
        "category": "continuation",
        "metric": "continuation_score",
        "operator": "gte",
        "limit": 0.80,
        "unit": "score",
        "priority": 5,
        "action": "partial30",
        "source_id": "cf:ssot/lbot/continuation",
    }]
    result = LBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "LBOT_HYSTERESIS_TRANSITION_UNAUTHORIZED" in result.reason_codes


def test_matching_hysteresis_authorizes_transition() -> None:
    value = base_evidence()
    value["snapshot"]["continuation_score"] = 0.90
    value["rules"] = [
        {
            "rule_id": "continue_partial",
            "category": "continuation",
            "metric": "continuation_score",
            "operator": "gte",
            "limit": 0.80,
            "unit": "score",
            "priority": 5,
            "action": "partial30",
            "source_id": "cf:ssot/lbot/continuation",
        },
        {
            "rule_id": "hysteresis_partial",
            "category": "hysteresis",
            "metric": "regime_stability_score",
            "operator": "gte",
            "limit": 0.80,
            "unit": "score",
            "priority": 5,
            "action": "partial30",
            "from_postures": ["hold"],
            "source_id": "sheets:ssot/lbot/hysteresis",
        },
    ]
    result = LBot().assess(value)
    assert result.action == "partial30"
    assert result.abstain is False


def test_unresolved_conflict_fails_closed() -> None:
    value = base_evidence()
    value["conflict_flags"] = ["TIMEFRAME_DIVERGENCE"]
    result = LBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "LBOT_UNRESOLVED_CONFLICT_FLAGS" in result.reason_codes


def test_missing_metric_source_fails_closed() -> None:
    value = base_evidence()
    del value["metric_sources"]["momentum_score"]
    result = LBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert any(code.startswith("LBOT_SOURCE_MISSING") for code in result.reason_codes)


def test_evaluate_preserves_lineage_and_stale_fails_closed() -> None:
    value = base_evidence()
    response = LBot().evaluate(request(value))
    assert response.decision_id == "decision.r23"
    assert response.strategy_id == "strategy.trend"
    assert response.method_id == "method.pullback"
    assert response.skill_id == "skill.runner"
    assert response.team_id == "AlphaTeam"
    assert response.authority == "advisory_only"
    assert response.direct_order_allowed is False

    stale = LBot().evaluate(request(deepcopy(value), data_state="STALE"))
    assert stale.action == "hold"
    assert stale.abstain is True
    assert stale.veto is False
