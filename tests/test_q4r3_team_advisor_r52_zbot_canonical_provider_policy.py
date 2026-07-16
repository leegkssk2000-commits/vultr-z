from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "canonical/zbot.py"
spec = importlib.util.spec_from_file_location("canonical_zbot_r52_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def evidence(*, available_at_ms: int = 9000, source_ref: str = "cf:zbot:context"):
    return module.EvidenceItem(
        evidence_id="evidence.r52.001",
        source_ref=source_ref,
        available_at_ms=available_at_ms,
        schema_version="r52-test",
    )


def request(**overrides):
    values = {
        "request_id": "zbot.r52.001",
        "task_kind": "risk_review",
        "decision_ts_ms": 10000,
        "epoch_id": "shadow.epoch.r52",
        "evidence": (evidence(),),
        "payload": {"symbol": "BTCUSDT", "risk_state": "review"},
        "requested_action": "hold",
    }
    values.update(overrides)
    return module.ZBotTaskRequest(**values)


def assert_hold(result, reason: str) -> None:
    assert result.state == "HOLD"
    assert result.action == "hold"
    assert result.provider_requests == ()
    assert result.execution_authority == "none"
    assert result.order_authority == "none"
    assert result.same_epoch_auto_apply is False
    assert reason in result.reason_codes


def test_canonical_owner_and_authority_boundary() -> None:
    assert module.ZBOT_OWNER == "canonical/zbot.py"
    assert module.OBSERVER_ONLY is True
    assert module.PROPOSAL_ONLY is True
    assert module.EXECUTION_AUTHORITY == "none"
    assert module.ORDER_AUTHORITY == "none"
    assert module.RUNTIME_ENABLED is False
    assert module.SAME_EPOCH_AUTO_APPLY is False
    assert module.HUMAN_APPROVAL_REQUIRED is True


def test_paid_provider_registry_is_dual_and_inactive() -> None:
    assert set(module.PROVIDER_REGISTRY) == {"openai", "gemini"}
    for provider_id, adapter in module.PROVIDER_REGISTRY.items():
        assert adapter.provider_id == provider_id
        assert adapter.external_paid_provider is True
        assert adapter.receives_peer_output is False
        assert adapter.execution_authority == "none"
        assert adapter.runtime_enabled is False
        assert adapter.credential_handle.startswith("credential-ref:")


def test_decision_task_creates_independent_dual_requests() -> None:
    result = module.build_provider_requests(request())
    assert result.state == "PROPOSAL_READY"
    assert result.required_providers == ("openai", "gemini")
    assert result.dual_provider_independent is True
    assert result.input_lineage_valid is True
    assert result.point_in_time_valid is True
    assert result.privacy_boundary_valid is True
    assert result.human_approval_required is True
    assert result.proposal_only is True
    assert len(result.provider_requests) == 2
    assert len({item.isolation_group for item in result.provider_requests}) == 2
    assert all(item.peer_output_included is False for item in result.provider_requests)


def test_post_trade_explanation_routes_single_provider_without_execution() -> None:
    result = module.build_provider_requests(request(task_kind="post_trade_explanation"))
    assert result.state == "PROPOSAL_READY"
    assert result.required_providers == ("openai",)
    assert result.dual_provider_independent is False
    assert result.execution_authority == "none"
    assert result.human_approval_required is True


def test_future_evidence_fails_closed() -> None:
    result = module.build_provider_requests(request(evidence=(evidence(available_at_ms=10001),)))
    assert_hold(result, "POINT_IN_TIME_VIOLATION")


def test_missing_source_lineage_fails_closed() -> None:
    result = module.build_provider_requests(request(evidence=(evidence(source_ref="invalid"),)))
    assert_hold(result, "EVIDENCE_SOURCE_REF_INVALID")


def test_private_payload_fails_closed() -> None:
    result = module.build_provider_requests(request(payload={"credential_value": "redacted"}))
    assert_hold(result, "PRIVACY_BOUNDARY_VIOLATION")


def test_unknown_task_and_action_fail_closed() -> None:
    unknown_task = module.build_provider_requests(request(task_kind="unknown"))
    assert_hold(unknown_task, "TASK_ROUTE_UNREGISTERED")
    unknown_action = module.build_provider_requests(request(requested_action="execute"))
    assert_hold(unknown_action, "ACTION_OUTSIDE_POLICY")


def test_duplicate_evidence_id_fails_closed() -> None:
    item = evidence()
    result = module.build_provider_requests(request(evidence=(item, item)))
    assert_hold(result, "EVIDENCE_ID_INVALID_OR_DUPLICATE")
