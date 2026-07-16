from __future__ import annotations

import pytest

from canonical.bots.contracts import ALLOWED_ACTIONS, CONTRACT_VERSION, BotRequest, BotResponse
from canonical.bots.lbot import LBOT_ALLOWED_ACTIONS, LBot
from canonical.bots.mbot import MBOT_ALLOWED_ACTIONS, MBot
from canonical.bots.obot import OBOT_ALLOWED_ACTIONS, OBot
from canonical.bots.sbot import ACTION_PRIORITY as SBOT_ACTION_PRIORITY, SBot

BOT_CLASSES = (LBot, MBot, OBot, SBot)
LINEAGE_FIELDS = (
    "decision_id", "position_id", "event_id", "parent_event_id", "event_ts",
    "symbol", "side", "strategy_id", "method_id", "skill_id", "team_id",
    "team_role", "data_state", "freshness_ms", "latency_ms",
)


def request(*, state: str = "FRESH", with_sources: bool = True, role_evidence: dict | None = None) -> BotRequest:
    return BotRequest(
        decision_id="decision.r26",
        position_id="position.r26",
        event_id="event.r26",
        parent_event_id="event.parent.r26",
        event_ts="2026-07-16T00:00:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.r26",
        method_id="method.r26",
        skill_id="skill.r26",
        team_id="AlphaTeam",
        team_role="watcher_1",
        data_state=state,
        freshness_ms=10,
        latency_ms=20,
        role_evidence=role_evidence or {},
        source_ids=("cf:r26",) if with_sources else (),
        evidence_ids=("zlice:r26",) if with_sources else (),
    )


def test_exact_four_unique_canonical_owners() -> None:
    bots = [cls() for cls in BOT_CLASSES]
    assert [bot.bot_id for bot in bots] == ["LBot", "MBot", "OBot", "SBot"]
    assert len({bot.bot_id for bot in bots}) == 4
    assert len({bot.semantic_role for bot in bots}) == 4
    assert all(bot.required_evidence for bot in bots)
    assert CONTRACT_VERSION == "canonical-bot/1.1.0"


def test_all_bots_fail_closed_on_stale_and_preserve_lineage() -> None:
    req = request(state="STALE")
    for cls in BOT_CLASSES:
        response = cls().evaluate(req)
        assert response.action == "hold"
        assert response.abstain is True
        assert response.veto is False
        assert response.authority == "advisory_only"
        assert response.direct_order_allowed is False
        for field in LINEAGE_FIELDS:
            assert getattr(response, field) == getattr(req, field)


def test_all_bots_fail_closed_when_source_or_evidence_lineage_missing() -> None:
    req = request(with_sources=False)
    for cls in BOT_CLASSES:
        response = cls().evaluate(req)
        assert response.action == "hold"
        assert response.abstain is True
        assert response.veto is False


def test_only_sbot_can_emit_hard_veto() -> None:
    sbot = SBot().evaluate(request(role_evidence={"hard_violations": ["SL_MISSING"]}))
    assert sbot.action == "block"
    assert sbot.veto is True
    assert sbot.confidence == 1.0
    for cls in (LBot, MBot, OBot):
        response = cls().evaluate(request(role_evidence={}))
        assert response.veto is False


def test_action_boundaries_are_exact() -> None:
    ordinary = frozenset({"hold", "reduce25", "partial30", "route_change"})
    assert LBOT_ALLOWED_ACTIONS == ordinary
    assert MBOT_ALLOWED_ACTIONS == ordinary
    assert OBOT_ALLOWED_ACTIONS == ordinary
    assert frozenset(SBOT_ACTION_PRIORITY) == ALLOWED_ACTIONS


def test_contract_rejects_direct_order_authority() -> None:
    req = request(state="STALE")
    response = LBot().evaluate(req)
    values = {name: getattr(response, name) for name in response.__dataclass_fields__}
    values["direct_order_allowed"] = True
    with pytest.raises(ValueError, match="BOT_AUTHORITY_VIOLATION"):
        BotResponse(**values)
