from __future__ import annotations

import json
from pathlib import Path

from backend.production import zel_production_external_research_quota_guard_v1 as m


def cfg():
    return {
        "cooldown_ms": 21_600_000,
        "output_path": "/tmp/evidence.json",
        "factory_path": "/tmp/factory.json",
        "context_factory_output_path": "/tmp/context.json",
    }


def previous_failure(error_code: str | None = None):
    return {
        "schema_version": m.core.SCHEMA,
        "state": "HOLD_EXTERNAL_RESEARCH_CALL_FAILED",
        "error_class": "RuntimeError",
        "error_code": error_code or "EXTERNAL_RESEARCH_SEARCH_FAILED:models/gemini-test:HTTP_429:RESOURCE_EXHAUSTED quota exceeded",
        "updated_at_ms": 1_000_000,
        "ai_call_made": True,
        "ai_call_succeeded": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "external_content_instruction_authority": False,
    }


def full_policy(tmp_path: Path) -> dict:
    return {
        "schema_version": m.core.POLICY_SCHEMA,
        "mode": "PAPER",
        "role": "ADVISORY_EXTERNAL_EVIDENCE_OBSERVER_NOT_ROUTE",
        "progress_path": str(tmp_path / "progress.json"),
        "next_hypothesis_path": str(tmp_path / "next.json"),
        "factory_path": str(tmp_path / "factory.json"),
        "manual_video_registry_path": str(tmp_path / "videos.json"),
        "output_path": str(tmp_path / "evidence.json"),
        "context_factory_output_path": str(tmp_path / "context.json"),
        "cooldown_ms": 21_600_000,
        "max_sources": 8,
        "max_youtube_videos": 2,
        "preferred_min_view_count": 30_000,
        "source_hierarchy": ["NATIVE", "ACADEMIC", "YOUTUBE"],
        "models": ["models/gemini-test"],
        "external_content_instruction_authority": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def test_quota_classifier_is_specific_to_verified_markers():
    assert m.is_quota_error("HTTP_429 RESOURCE_EXHAUSTED") is True
    assert m.is_quota_error("quota exceeded") is True
    assert m.is_quota_error("HTTP_500 internal error") is False
    assert m.is_quota_error("JSON decode failed") is False


def test_quota_classifies_transient_daily_and_billing_states():
    assert m.quota_class("GenerateRequestsPerMinutePerProjectPerModel retry in 41.5s") == "TRANSIENT_RATE_LIMIT"
    assert m.quota_class("GenerateRequestsPerDayPerProjectPerModel-FreeTier") == "DAILY_QUOTA"
    assert m.quota_class("Your prepayment credits are depleted") == "PREPAY_DEPLETED"
    assert m.quota_class("Please enable billing on your project") == "BILLING_REQUIRED"
    assert m.quota_class("generate_content_free_tier_requests limit: 0") == "FREE_TIER_ZERO_LIMIT"


def test_transient_retry_uses_retry_delay_not_six_hour_blanket():
    err = "HTTP_429 RESOURCE_EXHAUSTED GenerateRequestsPerMinutePerProjectPerModel Please retry in 41.5s"
    policy = m.recovery_policy(cfg(), err)
    assert policy["quota_class"] == "TRANSIENT_RATE_LIMIT"
    assert policy["parsed_retry_delay_ms"] == 41_500
    assert policy["cooldown_ms"] == 60_000
    assert policy["quota_manual_action_required"] is False


def test_billing_failure_marks_manual_action_but_rechecks_boundedly():
    err = "HTTP_429 RESOURCE_EXHAUSTED Your prepayment credits are depleted"
    policy = m.recovery_policy(cfg(), err)
    assert policy["quota_class"] == "PREPAY_DEPLETED"
    assert policy["cooldown_ms"] == 7_200_000
    assert policy["quota_manual_action_required"] is True


def test_quota_hold_uses_original_failure_time_across_context_changes():
    prior = previous_failure()
    first = m.build_quota_hold(
        cfg(),
        prior,
        state="HOLD_EXTERNAL_RESEARCH_QUOTA_EXHAUSTED",
        now_ms=1_000_100,
        context_sha="context-a",
    )
    assert first["quota_failure_at_ms"] == 1_000_000
    assert first["quota_retry_after_ms"] == 22_600_000
    assert first["quota_call_suppressed"] is False
    assert first["quota_class"] == "GENERIC_QUOTA"

    second = m.build_quota_hold(
        cfg(),
        first,
        state="HOLD_EXTERNAL_RESEARCH_QUOTA_COOLDOWN",
        now_ms=1_500_000,
        context_sha="context-b",
    )
    assert second["context_sha256"] == "context-b"
    assert second["quota_failure_at_ms"] == 1_000_000
    assert second["quota_retry_after_ms"] == 22_600_000
    assert second["quota_remaining_ms"] == 21_100_000
    assert second["quota_call_suppressed"] is True
    assert second["ai_call_made"] is False
    assert second["selection_authority"] is False
    assert second["execution_authority"] == "NONE"
    assert second["order_authority"] == "BLOCKED"


def test_run_guard_suppresses_call_when_context_changes_during_quota(monkeypatch, tmp_path):
    policy_path = tmp_path / "policy.json"
    policy = full_policy(tmp_path)
    policy_path.write_text(json.dumps(policy))
    (tmp_path / "evidence.json").write_text(json.dumps(previous_failure()))
    (tmp_path / "factory.json").write_text(json.dumps({"families": {}}))

    monkeypatch.setattr(m, "current_context_sha", lambda cfg: "new-context-sha")
    persisted = {}
    monkeypatch.setattr(m, "persist", lambda cfg, evidence: persisted.update(evidence))

    called = {"value": False}

    def should_not_call(argv):
        called["value"] = True
        raise AssertionError("Gemini core must not run during quota cooldown")

    monkeypatch.setattr(m.core, "main", should_not_call)

    out = m.run_guard(policy_path, now_ms=1_500_000)
    assert out["state"] == "HOLD_EXTERNAL_RESEARCH_QUOTA_COOLDOWN"
    assert out["ai_call_executed"] is False
    assert called["value"] is False
    assert persisted["context_sha256"] == "new-context-sha"
    assert persisted["quota_failure_at_ms"] == 1_000_000


def test_transient_quota_expires_quickly_and_allows_retry(monkeypatch, tmp_path):
    policy_path = tmp_path / "policy.json"
    policy = full_policy(tmp_path)
    policy_path.write_text(json.dumps(policy))
    transient = previous_failure(
        "EXTERNAL_RESEARCH_SEARCH_FAILED:HTTP_429:RESOURCE_EXHAUSTED GenerateRequestsPerMinutePerProjectPerModel retry in 41s"
    )
    (tmp_path / "evidence.json").write_text(json.dumps(transient))
    (tmp_path / "factory.json").write_text(json.dumps({"families": {}}))
    monkeypatch.setattr(m, "current_context_sha", lambda cfg: "retry-context")

    called = {"value": False}

    def fake_core(argv):
        called["value"] = True
        row = {
            "state": "HOLD_EXTERNAL_RESEARCH_NOT_REQUIRED",
            "updated_at_ms": 1_070_000,
            "receipt_sha256": "ok",
        }
        Path(policy["output_path"]).write_text(json.dumps(row))
        return 0

    monkeypatch.setattr(m.core, "main", fake_core)
    out = m.run_guard(policy_path, now_ms=1_070_000)
    assert called["value"] is True
    assert out["state"] == "HOLD_EXTERNAL_RESEARCH_NOT_REQUIRED"


def test_expired_generic_quota_allows_one_retry_and_classifies_new_429(monkeypatch, tmp_path):
    policy_path = tmp_path / "policy.json"
    policy = full_policy(tmp_path)
    policy_path.write_text(json.dumps(policy))
    (tmp_path / "evidence.json").write_text(json.dumps(previous_failure()))
    (tmp_path / "factory.json").write_text(json.dumps({"families": {}}))
    monkeypatch.setattr(m, "current_context_sha", lambda cfg: "retry-context")

    def fake_core(argv):
        row = previous_failure()
        row["updated_at_ms"] = 30_000_000
        Path(policy["output_path"]).write_text(json.dumps(row))
        return 0

    monkeypatch.setattr(m.core, "main", fake_core)
    monkeypatch.setattr(m, "persist", lambda cfg, evidence: Path(policy["output_path"]).write_text(json.dumps(evidence)))

    out = m.run_guard(policy_path, now_ms=30_000_000)
    saved = json.loads(Path(policy["output_path"]).read_text())
    assert out["state"] == "HOLD_EXTERNAL_RESEARCH_QUOTA_EXHAUSTED"
    assert out["ai_call_executed"] is True
    assert saved["quota_failure_at_ms"] == 30_000_000
    assert saved["quota_retry_after_ms"] == 51_600_000
    assert saved["quota_class"] == "GENERIC_QUOTA"
