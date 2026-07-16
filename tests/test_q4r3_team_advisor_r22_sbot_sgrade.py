from __future__ import annotations

from copy import deepcopy

from canonical.bots.contracts import BotRequest
from canonical.bots.sbot import SBot


def request(*, data_state: str = "FRESH", side: str = "long") -> BotRequest:
    return BotRequest(
        decision_id="decision.r22",
        position_id="position.r22",
        event_id="event.r22",
        parent_event_id="event.parent",
        event_ts="2026-07-15T19:00:00+00:00",
        symbol="BTCUSDT",
        side=side,
        strategy_id="strategy.r22",
        method_id="method.r22",
        skill_id="skill.r22",
        team_id="DeltaTeam",
        team_role="main",
        data_state=data_state,
        freshness_ms=10,
        latency_ms=20,
        role_evidence=evidence(),
        source_ids=("cf:r22.snapshot", "sheets:Z_POLICY.v3"),
        evidence_ids=("zlice:r22",),
    )


def evidence() -> dict:
    snapshot = {
        "price": 100.0,
        "pos_pct": 10.0,
        "lev": 10.0,
        "entry_ts": "2026-07-15T18:00:00+00:00",
        "market_ts": "2026-07-15T19:00:00+00:00",
        "liq_buffer_pct": 20.0,
        "funding_8h_pct": 0.01,
        "dd_day_pct": 1.0,
        "dd_total_pct": 2.0,
        "sl_present": True,
        "order_channel_ok": True,
    }
    sources = {key: f"cf:r22.{key}" for key in snapshot}
    sources["sl_present"] = "sheets:r22.sl"
    return {
        "hard_violations": [],
        "soft_penalties": [],
        "risk_state": "normal",
        "integrity": {
            "ok": True,
            "missing": False,
            "disconnected": False,
            "ts_anomaly": False,
            "key_mismatch": False,
            "stale": False,
        },
        "snapshot": snapshot,
        "metric_sources": sources,
        "rules": [
            {
                "rule_id": "EXPOSURE_MAX",
                "metric": "exposure_pct_x",
                "operator": "gt",
                "limit": 200.0,
                "unit": "%x",
                "severity": "M",
                "action": "reduce25",
                "source_id": "sheets:Z_POLICY.EXPOSURE_MAX",
            },
            {
                "rule_id": "LIQ_BUFFER_MIN",
                "metric": "liq_buffer_pct",
                "operator": "lt",
                "limit": 5.0,
                "unit": "%",
                "severity": "C",
                "action": "block",
                "source_id": "sheets:Z_POLICY.LIQ_BUFFER_MIN",
            },
        ],
    }


def evaluate(value: dict, *, data_state: str = "FRESH", side: str = "long"):
    req = request(data_state=data_state, side=side)
    object.__setattr__(req, "role_evidence", value)
    return SBot().evaluate(req)


def test_normal_snapshot_stays_hold_without_abstention() -> None:
    result = evaluate(evidence())
    assert result.action == "hold"
    assert result.abstain is False
    assert result.veto is False
    assert result.confidence == 0.95
    assert "SBOT_RISK_WITHIN_SSOT" in result.reason_codes


def test_explicit_hard_violation_blocks() -> None:
    value = evidence()
    value["hard_violations"] = ["SL_DESYNC"]
    result = evaluate(value)
    assert result.action == "block"
    assert result.veto is True
    assert result.confidence == 1.0


def test_missing_integrity_fails_closed() -> None:
    value = evidence()
    value.pop("integrity")
    result = evaluate(value)
    assert result.action == "hold"
    assert result.abstain is True


def test_stale_data_fails_closed_before_rules() -> None:
    result = evaluate(evidence(), data_state="STALE")
    assert result.action == "hold"
    assert result.abstain is True
    assert "SBOT_DATA_STALE" in result.reason_codes


def test_missing_min_data_fails_closed() -> None:
    value = evidence()
    value["snapshot"].pop("dd_total_pct")
    result = evaluate(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert any("SBOT_MIN_DATA_MISSING" in code for code in result.reason_codes)


def test_missing_metric_source_fails_closed() -> None:
    value = evidence()
    value["metric_sources"]["dd_day_pct"] = "other:untrusted"
    result = evaluate(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert any("SBOT_SOURCE_MISSING" in code for code in result.reason_codes)


def test_sl_missing_is_universal_hard_veto() -> None:
    value = evidence()
    value["snapshot"]["sl_present"] = False
    result = evaluate(value)
    assert result.action == "block"
    assert result.veto is True
    assert "SBOT_HARD:SL_MISSING" in result.reason_codes


def test_ssot_exposure_breach_reduces() -> None:
    value = evidence()
    value["snapshot"]["pos_pct"] = 25.0
    result = evaluate(value)
    assert result.action == "reduce25"
    assert result.veto is False
    assert any("EXPOSURE_MAX" in code for code in result.reason_codes)


def test_critical_liquidation_buffer_breach_vetoes() -> None:
    value = evidence()
    value["snapshot"]["liq_buffer_pct"] = 3.0
    result = evaluate(value)
    assert result.action == "block"
    assert result.veto is True
    assert any("LIQ_BUFFER_MIN" in code for code in result.reason_codes)


def test_critical_rule_outranks_medium_rule() -> None:
    value = evidence()
    value["snapshot"]["pos_pct"] = 25.0
    value["snapshot"]["liq_buffer_pct"] = 3.0
    result = evaluate(value)
    assert result.action == "block"
    assert result.veto is True
    assert len(result.reason_codes) == 2


def test_invalid_rule_source_fails_closed() -> None:
    value = evidence()
    value["rules"][0]["source_id"] = "other:threshold"
    result = evaluate(value)
    assert result.action == "hold"
    assert result.abstain is True
    assert any("SBOT_RULE_INVALID" in code for code in result.reason_codes)


def test_liquidation_buffer_can_be_derived_for_short() -> None:
    value = evidence()
    value["snapshot"].pop("liq_buffer_pct")
    value["metric_sources"].pop("liq_buffer_pct")
    value["snapshot"]["liq_price"] = 110.0
    value["metric_sources"]["liq_price"] = "cf:r22.liq_price"
    result = evaluate(value, side="short")
    assert result.action == "hold"
    assert result.abstain is False
