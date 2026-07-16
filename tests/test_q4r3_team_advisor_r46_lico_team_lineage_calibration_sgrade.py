from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from canonical.lico_calibration import (
    ALL_BOTS,
    ALL_TEAMS,
    MODEL_OWNER,
    CalibrationPolicy,
    EvidenceLineage,
    FillObservation,
    LicoCalibrationEnvelope,
    TeamContext,
    evaluate_team_lineage_calibration,
)

ROOT = Path(__file__).parents[1]
D = Decimal


def alpha_team(**changes) -> TeamContext:
    values = {
        "selected_team": "AlphaTeam",
        "main_owner": "LBot",
        "support_owner": "MBot",
        "watcher_owners": ("OBot", "SBot"),
        "reserve_owner": None,
        "helper_owner": None,
        "helper_trigger": "",
        "mission": "trend_primary_continuation",
        "policy_family": "trend_continuation",
    }
    values.update(changes)
    return TeamContext(**values)


def delta_team() -> TeamContext:
    return TeamContext(
        selected_team="DeltaTeam",
        main_owner="SBot",
        support_owner="OBot",
        watcher_owners=("MBot", "LBot"),
        reserve_owner="LBot",
        helper_owner="LBot",
        helper_trigger="regime_shift",
        mission="defense_regime_shift_capital_preservation",
        policy_family="capital_preservation",
    )


def policy(**changes) -> CalibrationPolicy:
    values = {
        "allowed_teams": tuple(sorted(ALL_TEAMS)),
        "required_bots": tuple(sorted(ALL_BOTS)),
        "minimum_sample_count": 3,
        "max_fill_price_error_bps": D("5"),
        "max_fill_latency_error_ms": 100,
        "require_partial_fill_match": True,
        "max_net_r_gap": D("0.10"),
        "policy_refs": ("cf:lico:calibration_policy", "sheets:lico:calibration_policy"),
        "schema_version": "r46-test",
    }
    values.update(changes)
    return CalibrationPolicy(**values)


def lineages(count: int = 3) -> tuple[EvidenceLineage, ...]:
    return tuple(
        EvidenceLineage(
            position_id=f"paper.r46.{index}",
            decision_id=f"decision.r46.{index}",
            strategy_id="strategy.trend.v1",
            method_id="method.pullback.v1",
            skill_id="skill.runner.v1",
            source_ids=("cf:market", "sheets:policy"),
            evidence_ids=(f"shadow:{index}", f"paper:{index}"),
            contract_version="r46-test",
            decision_ts_ms=9000 + index,
        )
        for index in range(1, count + 1)
    )


def observations(
    mode: str,
    links: tuple[EvidenceLineage, ...],
    *,
    price_offset: str = "0",
    latency_offset: int = 0,
    partial_fill: bool = False,
    net_r_offset: str = "0",
) -> tuple[FillObservation, ...]:
    output = []
    for index, link in enumerate(links, start=1):
        base_price = D("100") + D(index)
        base_latency = 20 + index
        base_net_r = D("0.50") + D(index) / D("100")
        output.append(
            FillObservation(
                mode=mode,
                position_id=link.position_id,
                decision_id=link.decision_id,
                symbol="BTCUSDT",
                side="long",
                fill_price=base_price + (D(price_offset) if mode == "paper" else D("0")),
                fill_latency_ms=base_latency + (latency_offset if mode == "paper" else 0),
                partial_fill=partial_fill,
                net_r=base_net_r + (D(net_r_offset) if mode == "paper" else D("0")),
                observed_at_ms=9100 + index,
                evidence_id=f"{mode}:{index}",
            )
        )
    return tuple(output)


def evaluate(
    *,
    team: TeamContext | None = None,
    links: tuple[EvidenceLineage, ...] | None = None,
    shadow: tuple[FillObservation, ...] | None = None,
    paper: tuple[FillObservation, ...] | None = None,
    calibration_policy: CalibrationPolicy | None = None,
) -> LicoCalibrationEnvelope:
    actual_links = links if links is not None else lineages()
    return evaluate_team_lineage_calibration(
        team or alpha_team(),
        actual_links,
        shadow if shadow is not None else observations("shadow", actual_links),
        paper if paper is not None else observations("paper", actual_links, price_offset="0.01", latency_offset=5, net_r_offset="0.01"),
        policy=calibration_policy or policy(),
    )


def assert_hold(result: LicoCalibrationEnvelope, reason: str) -> None:
    assert result.state == "HOLD"
    assert result.action == "hold"
    assert result.fail_closed is True
    assert result.abstain is True
    assert result.execution_authority == "none"
    assert reason in result.reason_codes


def test_alpha_team_lineage_calibration_sgrade_ready() -> None:
    result = evaluate()
    assert MODEL_OWNER == "canonical/lico.py"
    assert result.state == "READY"
    assert result.action == "hold"
    assert result.team_context is True
    assert result.evidence_lineage is True
    assert result.actual_vs_simulated is True
    assert result.sample_count == 3
    assert result.partial_fill_match is True
    assert result.calibration is True
    assert result.sgrade_ready is True
    assert result.accepted is True
    assert result.runtime_enabled is False
    assert result.order_enabled is False


def test_delta_team_dynamic_helper_structure_is_valid() -> None:
    result = evaluate(team=delta_team())
    assert result.state == "READY"
    assert result.selected_team == "DeltaTeam"
    assert result.sgrade_ready is True


def test_four_bot_team_coverage_failure_holds() -> None:
    result = evaluate(team=alpha_team(watcher_owners=("OBot", "MBot")))
    assert_hold(result, "TEAM_CONTEXT_FOUR_BOT_COVERAGE_INVALID")


def test_duplicate_lineage_holds() -> None:
    links = lineages()
    duplicate = (links[0], links[0], links[2])
    result = evaluate(
        links=duplicate,
        shadow=observations("shadow", duplicate),
        paper=observations("paper", duplicate),
    )
    assert_hold(result, "EVIDENCE_LINEAGE_POSITION_DUPLICATE")


def test_missing_cf_source_lineage_holds() -> None:
    links = lineages()
    bad = (replace(links[0], source_ids=("sheets:policy",)), *links[1:])
    result = evaluate(links=bad)
    assert_hold(result, "EVIDENCE_LINEAGE_CF_SOURCE_MISSING")


def test_point_in_time_violation_holds() -> None:
    links = lineages()
    shadow = list(observations("shadow", links))
    shadow[0] = replace(shadow[0], observed_at_ms=links[0].decision_ts_ms - 1)
    result = evaluate(links=links, shadow=tuple(shadow))
    assert_hold(result, "CALIBRATION_LOOKAHEAD_OR_TIMESTAMP_INVALID")


def test_insufficient_calibration_samples_hold() -> None:
    links = lineages(2)
    result = evaluate(
        links=links,
        shadow=observations("shadow", links),
        paper=observations("paper", links),
    )
    assert_hold(result, "CALIBRATION_SAMPLE_COUNT_BELOW_POLICY")


def test_fill_error_excess_routes_change() -> None:
    links = lineages()
    result = evaluate(
        links=links,
        paper=observations("paper", links, price_offset="1"),
    )
    assert result.state == "READY"
    assert result.action == "route_change"
    assert result.calibration is False
    assert result.sgrade_ready is False
    assert "CALIBRATION_FILL_PRICE_ERROR_EXCEEDED" in result.reason_codes


def test_partial_fill_mismatch_routes_change() -> None:
    links = lineages()
    result = evaluate(
        links=links,
        paper=observations("paper", links, partial_fill=True),
    )
    assert result.state == "READY"
    assert result.action == "route_change"
    assert result.partial_fill_match is False
    assert "CALIBRATION_PARTIAL_FILL_MISMATCH" in result.reason_codes


def test_contract_uses_ssot_and_forbids_same_epoch_mutation() -> None:
    contract = json.loads(
        (ROOT / "config/q4r3_lico_team_lineage_calibration_sgrade_contract_v1.json").read_text(encoding="utf-8")
    )
    calibration = contract["shadow_paper_calibration_policy"]
    assert calibration["minimum_sample_count"] == "SSOT.LICO.CALIBRATION_MIN_SAMPLES"
    assert calibration["max_fill_price_error_bps"] == "SSOT.LICO.MAX_FILL_PRICE_ERROR_BPS"
    assert calibration["max_fill_latency_error_ms"] == "SSOT.LICO.MAX_FILL_LATENCY_ERROR_MS"
    assert calibration["max_net_r_gap"] == "SSOT.LICO.MAX_NET_R_GAP"
    assert calibration["same_epoch_auto_apply"] is False
    assert contract["sgrade_lock"]["remaining_gap_count"] == 0
    assert contract["authority"]["execution_authority"] == "none"
    assert contract["next_stage"] == "R5.1"
