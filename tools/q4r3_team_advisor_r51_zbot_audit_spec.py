from __future__ import annotations

SCHEMA = "q4r3_team_advisor_r51_zbot_sgrade_gap_audit_v1"
SURFACES: dict[str, tuple[str, ...]] = {
    "unique_canonical_owner": ("canonical/zbot", "zbot_owner", "zbot_manifest"),
    "typed_decision_contract": ("decision_envelope", "input_schema", "output_schema", "typed_input", "typed_output"),
    "provider_registry": ("provider_registry", "model_registry", "provider_id", "model_id"),
    "openai_provider_adapter": ("openai", "chatgpt", "gpt-"),
    "gemini_provider_adapter": ("gemini", "google.genai", "google.generativeai"),
    "dual_provider_independence": ("dual_review", "independent_review", "provider_independence", "cross_provider"),
    "task_routing_policy": ("task_class", "route_policy", "provider_route", "model_route", "routing_policy"),
    "budget_token_accounting": ("token_budget", "cost_budget", "daily_budget", "api_cost_usd", "input_tokens", "output_tokens"),
    "prompt_versioning": ("prompt_version", "prompt_hash", "system_prompt_id", "prompt_registry"),
    "input_evidence_lineage": ("decision_id", "evidence_ids", "source_refs", "contract_version", "request_id"),
    "point_in_time_guard": ("point_in_time", "decision_ts", "observed_at_ms", "source_age_ms", "stale"),
    "response_schema_validation": ("json_schema", "schema_validation", "validate_response", "response_schema"),
    "response_normalization": ("normalized_response", "normalized_decision", "canonical_response", "normalize_response"),
    "disagreement_arbitration": ("disagreement", "arbitration", "tiebreak", "provider_consensus"),
    "timeout_retry_circuit_breaker": ("timeout", "retry", "circuit_breaker", "backoff"),
    "idempotency_cache_dedup": ("idempotency", "request_hash", "cache_key", "dedup"),
    "privacy_secret_boundary": ("secret_ref", "api_key_env", "secret_manager", "redact", "provider_secret"),
    "allowed_action_boundary": ("allowed_actions", "execution_authority", "order_authority", "proposal_only"),
    "fail_closed_abstain": ("fail_closed", "abstain", "hold", "route_change"),
    "audit_receipt": ("receipt", "response_hash", "audit_log", "provider_receipt"),
    "cost_performance_attribution": ("incremental_net_r", "api_cost_usd", "zbot_attribution", "baseline_delta"),
    "same_epoch_guard": ("same_epoch_auto_apply", "new_epoch_validation", "observer_only", "proposal_only"),
    "human_approval_boundary": ("human_approval", "approval_required", "manual_review", "review_required"),
    "model_quality_drift_evaluation": ("model_version", "evaluation_set", "quality_score", "model_drift", "shadow_compare"),
}
