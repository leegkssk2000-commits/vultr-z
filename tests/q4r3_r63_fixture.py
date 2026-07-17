from __future__ import annotations

from policy.zbot_external_canary_types import (
    ExternalCanaryApprovalCandidate,
    ExternalCanaryApprovalPolicy,
)


def policy(**changes) -> ExternalCanaryApprovalPolicy:
    values = dict(
        allowed_providers=("openai", "gemini"),
        allowed_routes=("risk_review",),
        min_window_ms=60000,
        max_window_ms=900000,
        max_calls_total=2,
        max_calls_per_provider=1,
        max_input_tokens=1000,
        max_output_tokens=400,
        max_cost_micro_usd=20000,
        policy_ref="sheets:zbot:external-canary-approval",
    )
    values.update(changes)
    return ExternalCanaryApprovalPolicy(**values)


def candidate(**changes) -> ExternalCanaryApprovalCandidate:
    values = dict(
        approval_id="approval.r63.fixture.001",
        requested_at_ms=10000,
        approved_at_ms=11000,
        expires_at_ms=310000,
        approved_by="human:owner",
        approval_nonce="0123456789abcdef0123456789abcdef",
        approval_ref="sheets:zbot:approval:r63:fixture",
        providers=("openai", "gemini"),
        routes=("risk_review",),
        max_calls_total=2,
        max_calls_per_provider=1,
        max_input_tokens=800,
        max_output_tokens=300,
        max_cost_micro_usd=15000,
        credential_refs=(
            ("openai", "secret-ref:zbot/openai"),
            ("gemini", "secret-ref:zbot/gemini"),
        ),
        kill_switch_ref="cf:zbot:external-canary-kill-switch",
        rollback_ref="sheets:zbot:external-canary-rollback",
        dryrun_evidence_sha256="sha256:" + "a" * 64,
    )
    values.update(changes)
    return ExternalCanaryApprovalCandidate(**values)
