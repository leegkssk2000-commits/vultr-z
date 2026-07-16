from __future__ import annotations

import json
from pathlib import Path

from policy import zbot_attribution as attribution
from policy import zbot_drift as drift
from policy import zbot_sgrade as sgrade

ROOT = Path(__file__).parents[1]
PROVIDERS = ("openai", "gemini")


def outcomes() -> tuple[attribution.ProviderOutcome, ...]:
    rows = []
    for index in range(3):
        for provider_id in PROVIDERS:
            rows.append(attribution.ProviderOutcome(
                observation_id=f"obs.{index}.{provider_id}",
                receipt_id=f"zbot.receipt.r55.{index}",
                provider_id=provider_id,
                task_kind="risk_review",
                model_id=f"{provider_id}.model.r55",
                proposed_action="hold",
                realized_r=0.30 + index * 0.05,
                baseline_r=0.10,
                input_tokens=500,
                output_tokens=200,
                cost_micro_usd=50,
                observed_at_ms=9900 + index,
                outcome_ref=f"sheets:zbot:outcome:{index}:{provider_id}",
            ))
    return tuple(rows)


def attribution_policy(**changes) -> attribution.AttributionPolicy:
    values = {
        "min_samples_per_provider": 3,
        "max_sample_age_ms": 1000,
        "max_cost_per_positive_r_micro_usd": 1000,
        "min_net_value_r": 0.10,
        "policy_ref": "sheets:zbot:attribution",
    }
    values.update(changes)
    return attribution.AttributionPolicy(**values)


def snapshots(*, current: bool = False) -> tuple[drift.QualitySnapshot, ...]:
    return tuple(
        drift.QualitySnapshot(
            provider_id=provider_id,
            model_id=f"{provider_id}.model.r55",
            sample_count=100,
            mean_confidence=0.78 if current else 0.76,
            positive_value_rate=0.63 if current else 0.62,
            action_disagreement_rate=0.08 if current else 0.07,
            schema_failure_rate=0.01,
            mean_cost_micro_usd=52.0 if current else 50.0,
            observed_at_ms=9950 if current else 9900,
            metric_ref=f"sheets:zbot:quality:{provider_id}:{'current' if current else 'reference'}",
        )
        for provider_id in PROVIDERS
    )


def drift_policy(**changes) -> drift.DriftPolicy:
    values = {
        "min_samples": 30,
        "max_snapshot_age_ms": 1000,
        "max_confidence_shift": 0.10,
        "max_positive_value_rate_drop": 0.10,
        "max_disagreement_rate_increase": 0.10,
        "max_schema_failure_rate_increase": 0.05,
        "max_cost_ratio": 1.50,
        "policy_ref": "sheets:zbot:drift",
    }
    values.update(changes)
    return drift.DriftPolicy(**values)


def ready_attribution() -> attribution.AttributionResult:
    return attribution.evaluate_attribution(
        outcomes(), expected_provider_ids=PROVIDERS, now_ms=10000, policy=attribution_policy()
    )


def ready_drift() -> drift.DriftResult:
    return drift.evaluate_quality_drift(
        snapshots(), snapshots(current=True), expected_provider_ids=PROVIDERS,
        now_ms=10000, policy=drift_policy(),
    )


def test_cost_performance_attribution_ready() -> None:
    result = ready_attribution()
    assert result.state == "READY"
    assert result.attribution_ready is True
    assert result.ensemble_sample_count == 3
    assert result.ensemble_net_value_r > 0
    assert len(result.provider_rows) == 2
    assert all(row.sample_count == 3 for row in result.provider_rows)
    assert all(row.net_value_r > 0 for row in result.provider_rows)


def test_duplicate_receipt_provider_fails_closed() -> None:
    rows = list(outcomes())
    rows.append(rows[0])
    result = attribution.evaluate_attribution(
        rows, expected_provider_ids=PROVIDERS, now_ms=10000, policy=attribution_policy()
    )
    assert result.state == "HOLD"
    assert "ATTRIBUTION_OBSERVATION_ID_INVALID_OR_DUPLICATE" in result.reason_codes
    assert "ATTRIBUTION_RECEIPT_PROVIDER_DUPLICATE" in result.reason_codes


def test_attribution_sample_floor_fails_closed() -> None:
    result = attribution.evaluate_attribution(
        outcomes()[:2], expected_provider_ids=PROVIDERS, now_ms=10000, policy=attribution_policy()
    )
    assert result.state == "HOLD"
    assert "ATTRIBUTION_SAMPLE_COUNT_BELOW_MIN" in result.reason_codes


def test_negative_net_value_fails_closed() -> None:
    rows = tuple(
        attribution.ProviderOutcome(**{
            **item.__dict__,
            "realized_r": -0.20,
            "baseline_r": 0.10,
        })
        for item in outcomes()
    )
    result = attribution.evaluate_attribution(
        rows, expected_provider_ids=PROVIDERS, now_ms=10000, policy=attribution_policy()
    )
    assert result.state == "HOLD"
    assert "ATTRIBUTION_NET_VALUE_BELOW_MIN" in result.reason_codes


def test_model_quality_drift_ready() -> None:
    result = ready_drift()
    assert result.state == "READY"
    assert result.quality_drift_ready is True
    assert result.drifted_provider_count == 0
    assert all(not row.drifted for row in result.provider_rows)


def test_confidence_drift_fails_closed() -> None:
    current = list(snapshots(current=True))
    current[0] = drift.QualitySnapshot(**{
        **current[0].__dict__,
        "mean_confidence": 0.99,
    })
    result = drift.evaluate_quality_drift(
        snapshots(), current, expected_provider_ids=PROVIDERS,
        now_ms=10000, policy=drift_policy(max_confidence_shift=0.10),
    )
    assert result.state == "HOLD"
    assert "DRIFT_CONFIDENCE_SHIFT_EXCEEDED" in result.reason_codes


def test_schema_failure_drift_fails_closed() -> None:
    current = list(snapshots(current=True))
    current[1] = drift.QualitySnapshot(**{
        **current[1].__dict__,
        "schema_failure_rate": 0.20,
    })
    result = drift.evaluate_quality_drift(
        snapshots(), current, expected_provider_ids=PROVIDERS,
        now_ms=10000, policy=drift_policy(),
    )
    assert result.state == "HOLD"
    assert "DRIFT_SCHEMA_FAILURE_RATE_INCREASE_EXCEEDED" in result.reason_codes


def test_provider_set_mismatch_fails_closed() -> None:
    result = drift.evaluate_quality_drift(
        snapshots()[:1], snapshots(current=True), expected_provider_ids=PROVIDERS,
        now_ms=10000, policy=drift_policy(),
    )
    assert result.state == "HOLD"
    assert "DRIFT_REFERENCE_PROVIDER_SET_MISMATCH" in result.reason_codes


def test_zbot_sgrade_lock_passes_only_at_24_surfaces() -> None:
    result = sgrade.evaluate_sgrade_lock(
        prior_ready_surface_count=22,
        closed_surfaces=("cost_performance_attribution", "model_quality_drift_evaluation"),
        attribution=ready_attribution(),
        drift=ready_drift(),
        observer_only=True,
        proposal_only=True,
        provider_invocation_enabled=False,
        runtime_enabled=False,
        execution_authority="none",
        order_authority="none",
        human_approval_required=True,
        same_epoch_auto_apply=False,
    )
    assert result.state == "PASS"
    assert result.ready_surface_count == 24
    assert result.remaining_surface_count == 0
    assert result.sgrade_ready is True


def test_sgrade_lock_rejects_runtime_or_authority() -> None:
    result = sgrade.evaluate_sgrade_lock(
        prior_ready_surface_count=22,
        closed_surfaces=("cost_performance_attribution", "model_quality_drift_evaluation"),
        attribution=ready_attribution(),
        drift=ready_drift(),
        observer_only=True,
        proposal_only=True,
        provider_invocation_enabled=True,
        runtime_enabled=True,
        execution_authority="write",
        order_authority="order",
        human_approval_required=True,
        same_epoch_auto_apply=False,
    )
    assert result.state == "HOLD"
    assert result.sgrade_ready is False
    assert "SGRADE_RUNTIME_PROVIDER_BOUNDARY_INVALID" in result.reason_codes
    assert "SGRADE_AUTHORITY_BOUNDARY_INVALID" in result.reason_codes


def test_contract_closes_all_surfaces_without_runtime_enablement() -> None:
    contract = json.loads((ROOT / "config/q4r3_zbot_attribution_drift_sgrade_lock_v1.json").read_text(encoding="utf-8"))
    assert contract["surface_count"] == {
        "prior_ready": 22,
        "closed_now": 2,
        "total_ready": 24,
        "total": 24,
    }
    assert contract["remaining_surfaces"] == []
    assert contract["authority"]["provider_invocation_enabled"] is False
    assert contract["authority"]["runtime_enabled"] is False
    assert contract["authority"]["execution_authority"] == "none"
    assert contract["authority"]["order_authority"] == "none"
