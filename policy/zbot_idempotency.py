from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Sequence

POLICY_OWNER = "policy/zbot_idempotency.py"
RUNTIME_ENABLED = False


@dataclass(frozen=True)
class IdempotencyResult:
    state: str
    reason_codes: tuple[str, ...]
    idempotency_key: str
    duplicate_blocked: bool


def build_idempotency_key(decision: Any, prompt_id: str, prompt_version: str) -> str:
    payload = {
        "request_id": str(getattr(decision, "request_id", "")),
        "task_kind": str(getattr(decision, "task_kind", "")),
        "epoch_id": str(getattr(decision, "epoch_id", "")),
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "providers": sorted(str(value) for value in getattr(decision, "required_providers", ())),
        "evidence": sorted(str(value) for value in getattr(decision, "input_evidence_ids", ())),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_idempotency(
    decision: Any,
    *,
    prompt_id: str,
    prompt_version: str,
    prior_keys: Sequence[str],
) -> IdempotencyResult:
    reasons: list[str] = []
    if getattr(decision, "state", None) != "PROPOSAL_READY":
        reasons.append("CANONICAL_DECISION_NOT_READY")
    if not prompt_id or not prompt_version:
        reasons.append("PROMPT_IDENTITY_MISSING")
    key = build_idempotency_key(decision, prompt_id, prompt_version)
    duplicate = key in set(prior_keys)
    if duplicate:
        reasons.append("IDEMPOTENCY_DUPLICATE")
    state = "READY" if not reasons else "HOLD"
    return IdempotencyResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("IDEMPOTENCY_READY",),
        idempotency_key=key,
        duplicate_blocked=duplicate,
    )
