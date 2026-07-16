from __future__ import annotations

import hashlib
import json
import string
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from policy.zbot_arbitration import ArbitrationResult

POLICY_OWNER = "policy/zbot_receipt.py"
RUNTIME_ENABLED = False
RECEIPT_WRITE_ENABLED = False
GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditReceipt:
    schema: str
    receipt_id: str
    created_at_ms: int
    request_id: str
    task_kind: str
    epoch_id: str
    prompt_id: str
    prompt_version: str
    response_schema_id: str
    evidence_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    provider_ids: tuple[str, ...]
    provider_actions: tuple[str, ...]
    response_hashes: tuple[str, ...]
    arbitration_state: str
    arbitration_action: str
    proposed_action: str
    reason_codes: tuple[str, ...]
    consensus_confidence: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost_micro_usd: int
    previous_receipt_hash: str
    receipt_hash: str
    chain_hash: str
    execution_authority: str
    order_authority: str
    runtime_enabled: bool
    write_enabled: bool


@dataclass(frozen=True)
class ReceiptResult:
    state: str
    reason_codes: tuple[str, ...]
    receipt: AuditReceipt | None
    integrity_valid: bool
    fail_closed: bool


def _hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_hash(value: str) -> bool:
    return len(value) == 64 and all(char in string.hexdigits for char in value)


def build_audit_receipt(
    *,
    request_id: str,
    task_kind: str,
    epoch_id: str,
    prompt_id: str,
    prompt_version: str,
    response_schema_id: str,
    evidence_ids: tuple[str, ...],
    source_refs: tuple[str, ...],
    arbitration: ArbitrationResult,
    created_at_ms: int,
    previous_receipt_hash: str = GENESIS_HASH,
) -> ReceiptResult:
    reasons: list[str] = []
    if not request_id or not task_kind or not epoch_id:
        reasons.append("RECEIPT_IDENTITY_MISSING")
    if not prompt_id or not prompt_version or not response_schema_id:
        reasons.append("RECEIPT_PROMPT_IDENTITY_MISSING")
    if created_at_ms < 0:
        reasons.append("RECEIPT_TIMESTAMP_INVALID")
    if not _valid_hash(previous_receipt_hash):
        reasons.append("RECEIPT_PREVIOUS_HASH_INVALID")
    if not evidence_ids or not source_refs:
        reasons.append("RECEIPT_LINEAGE_MISSING")
    if len(set(evidence_ids)) != len(evidence_ids) or len(set(source_refs)) != len(source_refs):
        reasons.append("RECEIPT_LINEAGE_DUPLICATE")
    if arbitration.execution_authority != "none" or arbitration.order_authority != "none":
        reasons.append("RECEIPT_AUTHORITY_INVALID")
    if arbitration.runtime_enabled:
        reasons.append("RECEIPT_RUNTIME_BOUNDARY_INVALID")
    if len(arbitration.provider_ids) != len(arbitration.response_hashes):
        reasons.append("RECEIPT_RESPONSE_HASH_COUNT_MISMATCH")
    if any(not _valid_hash(value) for value in arbitration.response_hashes):
        reasons.append("RECEIPT_RESPONSE_HASH_INVALID")
    if reasons:
        return ReceiptResult(
            state="HOLD",
            reason_codes=tuple(sorted(set(reasons))),
            receipt=None,
            integrity_valid=False,
            fail_closed=True,
        )

    core = {
        "schema": "zbot.audit_receipt.v1",
        "created_at_ms": created_at_ms,
        "request_id": request_id,
        "task_kind": task_kind,
        "epoch_id": epoch_id,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "response_schema_id": response_schema_id,
        "evidence_ids": tuple(sorted(evidence_ids)),
        "source_refs": tuple(sorted(source_refs)),
        "provider_ids": arbitration.provider_ids,
        "provider_actions": arbitration.provider_actions,
        "response_hashes": arbitration.response_hashes,
        "arbitration_state": arbitration.state,
        "arbitration_action": arbitration.action,
        "proposed_action": arbitration.proposed_action,
        "reason_codes": arbitration.reason_codes,
        "consensus_confidence": arbitration.consensus_confidence,
        "total_input_tokens": arbitration.total_input_tokens,
        "total_output_tokens": arbitration.total_output_tokens,
        "total_cost_micro_usd": arbitration.total_cost_micro_usd,
        "previous_receipt_hash": previous_receipt_hash,
        "execution_authority": "none",
        "order_authority": "none",
        "runtime_enabled": False,
        "write_enabled": False,
    }
    receipt_hash = _hash(core)
    chain_hash = _hash({"previous_receipt_hash": previous_receipt_hash, "receipt_hash": receipt_hash})
    receipt = AuditReceipt(
        receipt_id=f"zbot.receipt.{receipt_hash[:20]}",
        receipt_hash=receipt_hash,
        chain_hash=chain_hash,
        **core,
    )
    return ReceiptResult(
        state="RECEIPT_READY",
        reason_codes=("AUDIT_RECEIPT_READY",),
        receipt=receipt,
        integrity_valid=verify_audit_receipt(receipt),
        fail_closed=True,
    )


def verify_audit_receipt(receipt: AuditReceipt) -> bool:
    payload = asdict(receipt)
    receipt_hash = payload.pop("receipt_hash")
    chain_hash = payload.pop("chain_hash")
    payload.pop("receipt_id")
    expected_receipt_hash = _hash(payload)
    expected_chain_hash = _hash({
        "previous_receipt_hash": receipt.previous_receipt_hash,
        "receipt_hash": expected_receipt_hash,
    })
    return (
        receipt_hash == expected_receipt_hash
        and chain_hash == expected_chain_hash
        and receipt.receipt_id == f"zbot.receipt.{receipt_hash[:20]}"
    )
