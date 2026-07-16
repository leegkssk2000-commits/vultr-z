from __future__ import annotations

from copy import deepcopy

from canonical.bots.contracts import BotRequest
from canonical.bots.obot import OBot, SNAPSHOT_FIELDS


def base_evidence() -> dict:
    snapshot = {
        "breakout_quality_score": 0.80,
        "fakeout_risk_score": 0.10,
        "momentum_score": 0.78,
        "anomaly_score": 0.08,
        "exhaustion_score": 0.15,
        "mfe_score": 0.70,
        "mae_score": 0.20,
        "volume_confirmation_score": 0.76,
        "confidence_score": 0.82,
        "signal_ts": "2026-07-16T00:00:00+00:00",
        "market_ts": "2026-07-16T00:08:00+00:00",
        "previous_posture": "hold"
    }
    return {
        "breakout_state": "confirmed",
        "fakeout_flags": [],
        "anomaly_flags": [],
        "exhaustion_flags": [],
        "integrity": {
            "ok": True,
            "missing": False,
            "disconnected": False,
            "ts_anomaly": False,
            "key_mismatch": False,
            "stale": False
        },
        "snapshot": snapshot,
        "metric_sources": {key: f"cf:obot/{key}" for key in SNAPSHOT_FIELDS},
        "rules": [{
            "rule_id": "quiet",
            "category": "momentum",
            "metric": "momentum_score",
            "operator": "lt",
            "limit": 0.10,
            "unit": "score",
            "priority": 1,
            "action": "reduce25",
            "source_id": "sheets:ssot/obot/quiet"
        }]
    }


def request(evidence: dict, *, data_state: str = "FRESH") -> BotRequest:
    return BotRequest(
        decision_id="decision.r25",
        position_id="position.r25",
        event_id="event.r25",
        parent_event_id="event.parent",
        event_ts="2026-07-16T00:08:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.breakout",
        method_id="method.confirmation",
        skill_id="skill.runner",
        team_id="GammaTeam",
        team_role="watcher_1",
        data_state=data_state,
        freshness_ms=10,
        latency_ms=20,
        role_evidence=evidence,
        source_ids=("cf:obot/source",),
        evidence_ids=("evidence:obot/r25",)
    )


def test_valid_no_trigger_holds_without_abstaining() -> None:
    result = OBot().assess(base_evidence())
    assert result.action == "hold"
    assert result.abstain is False
    assert result.veto is False
    assert result.confidence == 0.82


def test_failed_breakout_can_route_change_with_ssot_rule() -> None:
    value = base_evidence()
    value["breakout_state"] = "failed"
    value["snapshot"]["breakout_quality_score"] = 0.10
    value["rules"] = [{
        "rule_id": "breakout_failed_route",
        "category": "breakout",
        "metric": "breakout_quality_score",
        "operator": "lte",
        "limit": 0.20,
        "unit": "score",
        "priority": 10,
        "action": "route_change",
        "breakout_states": ["failed"],
        "source_id": "sheets:ssot/obot/breakout"
    }]
    result = OBot().assess(value)
    assert result.action == "route_change"
    assert result.abstain is False
    assert result.veto is False


def test_unresolved_failed_breakout_fails_closed() -> None:
    value = base_evidence()
    value["breakout_state"] = "failed"
    result = OBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "OBOT_UNRESOLVED_BREAKOUT_STATE" in result.reason_codes


def test_fakeout_and_anomaly_require_explicit_rules() -> None:
    value = base_evidence()
    value["fakeout_flags"] = ["LOW_VOLUME_BREAK"]
    result = OBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "OBOT_UNRESOLVED_FAKEOUT_FLAGS" in result.reason_codes

    value = base_evidence()
    value["anomaly_flags"] = ["PRICE_VOLUME_DIVERGENCE"]
    result = OBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert "OBOT_UNRESOLVED_ANOMALY_FLAGS" in result.reason_codes


def test_exhaustion_can_partial_with_ssot_rule() -> None:
    value = base_evidence()
    value["exhaustion_flags"] = ["MOMENTUM_DECAY"]
    value["snapshot"]["exhaustion_score"] = 0.90
    value["rules"] = [{
        "rule_id": "exhaustion_partial",
        "category": "exhaustion",
        "metric": "exhaustion_score",
        "operator": "gte",
        "limit": 0.80,
        "unit": "score",
        "priority": 8,
        "action": "partial30",
        "source_id": "cf:ssot/obot/exhaustion"
    }]
    result = OBot().assess(value)
    assert result.action == "partial30"
    assert result.abstain is False


def test_mfe_mae_spread_can_reduce() -> None:
    value = base_evidence()
    value["snapshot"]["mfe_score"] = 0.25
    value["snapshot"]["mae_score"] = 0.70
    value["rules"] = [{
        "rule_id": "mfe_mae_reduce",
        "category": "mfe_mae",
        "metric": "mfe_mae_spread",
        "operator": "lte",
        "limit": -0.30,
        "unit": "score",
        "priority": 7,
        "action": "reduce25",
        "source_id": "sheets:ssot/obot/mfe_mae"
    }]
    result = OBot().assess(value)
    assert result.action == "reduce25"
    assert result.abstain is False


def test_missing_metric_source_fails_closed() -> None:
    value = base_evidence()
    del value["metric_sources"]["anomaly_score"]
    result = OBot().assess(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert any(code.startswith("OBOT_SOURCE_MISSING") for code in result.reason_codes)


def test_evaluate_preserves_lineage_and_stale_fails_closed() -> None:
    value = base_evidence()
    response = OBot().evaluate(request(value))
    assert response.decision_id == "decision.r25"
    assert response.strategy_id == "strategy.breakout"
    assert response.method_id == "method.confirmation"
    assert response.skill_id == "skill.runner"
    assert response.team_id == "GammaTeam"
    assert response.team_role == "watcher_1"
    assert response.authority == "advisory_only"
    assert response.direct_order_allowed is False

    stale = OBot().evaluate(request(deepcopy(value), data_state="STALE"))
    assert stale.action == "hold"
    assert stale.abstain is True
    assert stale.veto is False
