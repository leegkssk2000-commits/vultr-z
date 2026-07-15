from __future__ import annotations

import json
from pathlib import Path

from canonical.bots import ALLOWED_ACTIONS, BotRequest, LBot, MBot, OBot, SBot

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "canonical/bots/manifest.json"


def make_request(data_state: str = "FRESH", evidence: dict | None = None) -> BotRequest:
    return BotRequest(
        decision_id="decision.test",
        position_id="position.test",
        event_id="event.test",
        parent_event_id="event.parent",
        event_ts="2026-07-15T00:00:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.test",
        method_id="method.test",
        skill_id="skill.test",
        team_id="AlphaTeam",
        team_role="main",
        data_state=data_state,
        freshness_ms=100,
        latency_ms=25,
        role_evidence=evidence or {},
        source_ids=("src:test",),
        evidence_ids=("evidence:test",),
    )


def test_manifest_and_action_contract() -> None:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(value["owners"]) == {"LBot", "MBot", "OBot", "SBot"}
    assert value["contract_version"] == "canonical-bot/1.1.0"
    assert value["response_lineage_complete"] is True
    assert value["latency_contract_required"] is True
    assert value["runtime_binding"] is False
    assert value["systemd_binding"] is False
    assert value["execution_authority"] == "none"
    assert value["direct_order_allowed"] is False
    assert value["external_advisor_included"] is False
    assert ALLOWED_ACTIONS == {
        "reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"
    }


def test_all_bots_fail_closed_on_stale_or_missing_evidence() -> None:
    for bot in (LBot(), MBot(), OBot(), SBot()):
        stale = bot.evaluate(make_request(data_state="STALE"))
        assert stale.action == "hold"
        assert stale.abstain is True
        assert stale.authority == "advisory_only"
        assert stale.direct_order_allowed is False
        missing = bot.evaluate(make_request())
        assert missing.action == "hold"
        assert missing.abstain is True


def test_response_carries_complete_request_lineage() -> None:
    request = make_request(evidence={
        "trend_thesis": "continuation",
        "hold_reduce_posture": "hold",
        "invalidation_flags": [],
        "suggested_action": "hold",
        "confidence": 0.7,
    })
    response = LBot().evaluate(request)
    for field in (
        "decision_id", "position_id", "event_id", "parent_event_id", "event_ts",
        "symbol", "side", "strategy_id", "method_id", "skill_id", "team_id",
        "team_role", "data_state", "freshness_ms", "latency_ms",
    ):
        assert getattr(response, field) == getattr(request, field)
    assert response.contract_version == "canonical-bot/1.1.0"


def test_role_specific_contracts() -> None:
    lbot = LBot().evaluate(make_request(evidence={
        "trend_thesis": "continuation", "hold_reduce_posture": "hold",
        "invalidation_flags": [], "suggested_action": "hold", "confidence": 0.7,
    }))
    mbot = MBot().evaluate(make_request(evidence={
        "method_fit": "fit", "range_state": "neutral", "timing_quality": "valid",
        "conflict_flags": [], "suggested_action": "partial30", "confidence": 0.6,
    }))
    obot = OBot().evaluate(make_request(evidence={
        "breakout_quality": "confirmed", "anomaly_flags": [], "mfe_mae_context": {},
        "suggested_action": "hold", "confidence": 0.8,
    }))
    assert (lbot.action, mbot.action, obot.action) == ("hold", "partial30", "hold")


def test_sbot_guard_precedence() -> None:
    response = SBot().evaluate(make_request(evidence={
        "hard_violations": ["RISK_LIMIT"], "soft_penalties": [], "risk_state": "critical",
        "suggested_action": "hold", "confidence": 0.1,
    }))
    assert response.action == "block"
    assert response.veto is True
    assert response.confidence == 1.0


def test_external_advisor_not_exported() -> None:
    import canonical.bots as package
    assert not hasattr(package, "ZBot")
