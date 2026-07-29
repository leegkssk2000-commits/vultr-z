from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

VERSION = "STRATEGY11_HUMAN_GOVERNED_CAPITAL_CONTRACT_V1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "live_activation_allowed": False,
    "order_submission_allowed": False,
    "capital_allocation_execute_allowed": False,
    "external_manual_enable_required": True,
    "ai_approval_authority": False,
}


class HumanGovernanceContractError(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    state: str
    action: str
    blockers: tuple[str, ...]
    metrics: Mapping[str, Any]
    lineage: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "strategy11.human_governed_capital_preflight.v1",
            "version": VERSION,
            "state": self.state,
            "action": self.action,
            "blockers": list(self.blockers),
            "metrics": dict(self.metrics),
            "lineage": dict(self.lineage),
            **SAFETY,
        }


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HumanGovernanceContractError(f"INVALID_NUMBER:{name}") from exc
    if not math.isfinite(number):
        raise HumanGovernanceContractError(f"NONFINITE_NUMBER:{name}")
    return number


def require_sha(value: Any, name: str) -> str:
    text = str(value or "").lower()
    if not SHA_RE.fullmatch(text):
        raise HumanGovernanceContractError(f"INVALID_SHA:{name}")
    return text


def require_nonempty(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HumanGovernanceContractError(f"EMPTY_FIELD:{name}")
    return text


def verify_policy(policy_input: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(policy_input)
    expected = {
        "fixture_only": True,
        "threshold_authority": False,
        "runtime_activation_allowed": False,
        "live_activation_allowed": False,
        "order_submission_allowed": False,
        "capital_allocation_execute_allowed": False,
        "external_manual_enable_required": True,
        "ai_approval_authority": False,
    }
    for key, value in expected.items():
        if policy.get(key) is not value:
            raise HumanGovernanceContractError(f"POLICY_FAIL_CLOSED_MISMATCH:{key}")
    material = {key: value for key, value in policy.items() if key != "policy_sha"}
    actual = stable_sha(material)
    if policy.get("policy_sha") != actual:
        raise HumanGovernanceContractError(f"POLICY_SHA_MISMATCH:{actual}:{policy.get('policy_sha')}")
    stages = [str(value) for value in policy.get("canary_stages") or []]
    if not stages or len(stages) != len(set(stages)):
        raise HumanGovernanceContractError("INVALID_CANARY_STAGES")
    upstream = policy.get("required_upstream_states") or {}
    if set(upstream) != {"ADAPTIVE_EXECUTION", "SELF_HEALING_OPERATIONS", "CHAMPION_CHALLENGER", "MARKET_DIGITAL_TWIN"}:
        raise HumanGovernanceContractError("INVALID_UPSTREAM_GATE_SET")
    return policy


def verify_binding(binding_input: Mapping[str, Any], policy_sha: str) -> dict[str, str]:
    binding = {
        "source_sha": require_sha(binding_input.get("source_sha"), "source_sha"),
        "data_sha": require_sha(binding_input.get("data_sha"), "data_sha"),
        "portfolio_sha": require_sha(binding_input.get("portfolio_sha"), "portfolio_sha"),
        "policy_sha": require_sha(binding_input.get("policy_sha"), "policy_sha"),
        "run_id": require_nonempty(binding_input.get("run_id"), "run_id"),
        "artifact_id": require_nonempty(binding_input.get("artifact_id"), "artifact_id"),
    }
    if binding["policy_sha"] != policy_sha:
        raise HumanGovernanceContractError("REQUEST_POLICY_SHA_MISMATCH")
    return binding


def verify_upstream_gates(gates_input: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    expected = policy["required_upstream_states"]
    blockers: list[str] = []
    normalized: dict[str, Any] = {}
    for stage in sorted(expected):
        row = gates_input.get(stage)
        if not isinstance(row, Mapping):
            blockers.append(f"MISSING_UPSTREAM_GATE:{stage}")
            continue
        state = require_nonempty(row.get("state"), f"upstream.{stage}.state")
        evidence_sha = require_sha(row.get("evidence_sha"), f"upstream.{stage}.evidence_sha")
        normalized[stage] = {"state": state, "evidence_sha": evidence_sha}
        if state != str(expected[stage]):
            blockers.append(f"UPSTREAM_STATE_MISMATCH:{stage}:{state}")
        if stage == "MARKET_DIGITAL_TWIN":
            capital_gate = require_nonempty(row.get("capital_gate"), "upstream.MARKET_DIGITAL_TWIN.capital_gate")
            normalized[stage]["capital_gate"] = capital_gate
            if capital_gate != "PASS_DIGITAL_TWIN_RISK_ENVELOPE":
                blockers.append(f"DIGITAL_TWIN_CAPITAL_GATE:{capital_gate}")
    return blockers, normalized


def approval_material(approval: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in approval.items() if key != "approval_sha"}


def verify_approval(
    approval_input: Mapping[str, Any] | None,
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    now_ms: int,
) -> tuple[list[str], dict[str, Any] | None]:
    if not approval_input:
        return ["EXPLICIT_USER_APPROVAL_MISSING"], None
    approval = dict(approval_input)
    approval_sha = require_sha(approval.get("approval_sha"), "approval.approval_sha")
    actual_sha = stable_sha(approval_material(approval))
    if approval_sha != actual_sha:
        raise HumanGovernanceContractError(f"APPROVAL_SHA_MISMATCH:{actual_sha}:{approval_sha}")

    blockers: list[str] = []
    approver_type = require_nonempty(approval.get("approver_type"), "approval.approver_type")
    approved_by = require_nonempty(approval.get("approved_by"), "approval.approved_by")
    issued_at_ms = int(finite(approval.get("issued_at_ms"), "approval.issued_at_ms"))
    expires_at_ms = int(finite(approval.get("expires_at_ms"), "approval.expires_at_ms"))
    stage = require_nonempty(approval.get("stage"), "approval.stage")
    policy_sha = require_sha(approval.get("policy_sha"), "approval.policy_sha")
    if approver_type not in set(policy["allowed_approver_types"]):
        blockers.append("APPROVER_TYPE_NOT_HUMAN")
    if approval.get("revoked") is not False:
        blockers.append("APPROVAL_REVOKED")
    if policy_sha != policy["policy_sha"]:
        blockers.append("APPROVAL_POLICY_SHA_MISMATCH")
    if stage != str(request.get("requested_stage") or ""):
        blockers.append("APPROVAL_STAGE_MISMATCH")
    if issued_at_ms > now_ms or expires_at_ms <= now_ms or expires_at_ms <= issued_at_ms:
        blockers.append("APPROVAL_EXPIRED_OR_INVALID_TIME")
    if expires_at_ms - issued_at_ms > int(policy["max_approval_lifetime_ms"]):
        blockers.append("APPROVAL_LIFETIME_LIMIT")
    if finite(request.get("requested_capital_usdt"), "requested_capital_usdt") > finite(approval.get("max_capital_usdt"), "approval.max_capital_usdt"):
        blockers.append("APPROVAL_CAPITAL_SCOPE")
    if finite(request.get("requested_leverage"), "requested_leverage") > finite(approval.get("max_leverage"), "approval.max_leverage"):
        blockers.append("APPROVAL_LEVERAGE_SCOPE")
    if finite(request.get("requested_exposure_pct"), "requested_exposure_pct") > finite(approval.get("max_exposure_pct"), "approval.max_exposure_pct"):
        blockers.append("APPROVAL_EXPOSURE_SCOPE")
    approved_exchanges = {str(value).upper() for value in approval.get("allowed_exchanges") or []}
    approved_symbols = {str(value).upper() for value in approval.get("allowed_symbols") or []}
    if str(request.get("exchange") or "").upper() not in approved_exchanges:
        blockers.append("APPROVAL_EXCHANGE_SCOPE")
    requested_symbols = {str(value).upper() for value in request.get("symbols") or []}
    if not requested_symbols.issubset(approved_symbols):
        blockers.append("APPROVAL_SYMBOL_SCOPE")
    normalized = {
        "approval_sha": approval_sha,
        "approver_type": approver_type,
        "approved_by": approved_by,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": expires_at_ms,
        "stage": stage,
        "policy_sha": policy_sha,
        "revoked": approval.get("revoked"),
    }
    return blockers, normalized


def evaluate_human_governance(
    request: Mapping[str, Any],
    policy_input: Mapping[str, Any],
    approval_input: Mapping[str, Any] | None,
) -> dict[str, Any]:
    policy = verify_policy(policy_input)
    binding = verify_binding(request.get("source_binding") or {}, str(policy["policy_sha"]))
    now_ms = int(finite(request.get("now_ms"), "now_ms"))
    stage = require_nonempty(request.get("requested_stage"), "requested_stage")
    stages = [str(value) for value in policy["canary_stages"]]
    if stage not in stages:
        raise HumanGovernanceContractError("UNKNOWN_CANARY_STAGE")
    stage_index = stages.index(stage)
    completed_stages = [str(value) for value in request.get("completed_stages") or []]
    required_prior = stages[:stage_index]

    blockers: list[str] = []
    if completed_stages != required_prior:
        blockers.append("CANARY_SEQUENCE_MISMATCH")
    exchange = require_nonempty(request.get("exchange"), "exchange").upper()
    symbols = sorted({str(value).upper() for value in request.get("symbols") or []})
    if not symbols:
        raise HumanGovernanceContractError("EMPTY_SYMBOL_SET")
    if exchange not in {str(value).upper() for value in policy["allowed_exchanges"]}:
        blockers.append("EXCHANGE_NOT_ALLOWED")
    if not set(symbols).issubset({str(value).upper() for value in policy["allowed_symbols"]}):
        blockers.append("SYMBOL_NOT_ALLOWED")

    capital = finite(request.get("requested_capital_usdt"), "requested_capital_usdt")
    leverage = finite(request.get("requested_leverage"), "requested_leverage")
    exposure = finite(request.get("requested_exposure_pct"), "requested_exposure_pct")
    dd_day = finite(request.get("dd_day_pct"), "dd_day_pct")
    dd_total = finite(request.get("dd_total_pct"), "dd_total_pct")
    if capital <= 0 or capital > finite(policy["max_capital_usdt"], "policy.max_capital_usdt"):
        blockers.append("CAPITAL_LIMIT")
    if leverage <= 0 or leverage > finite(policy["max_leverage"], "policy.max_leverage"):
        blockers.append("LEVERAGE_LIMIT")
    if exposure <= 0 or exposure > finite(policy["max_exposure_pct"], "policy.max_exposure_pct"):
        blockers.append("EXPOSURE_LIMIT")
    if dd_day > finite(policy["max_dd_day_pct"], "policy.max_dd_day_pct"):
        blockers.append("DD_DAY_LIMIT")
    if dd_total > finite(policy["max_dd_total_pct"], "policy.max_dd_total_pct"):
        blockers.append("DD_TOTAL_LIMIT")
    if request.get("kill_switch_engaged") is True:
        blockers.append("KILL_SWITCH_ENGAGED")
    if request.get("emergency_stop_available") is not True:
        blockers.append("EMERGENCY_STOP_UNAVAILABLE")

    upstream_blockers, upstream = verify_upstream_gates(request.get("upstream_gates") or {}, policy)
    blockers.extend(upstream_blockers)
    approval_blockers, approval = verify_approval(approval_input, request, policy, now_ms)
    blockers.extend(approval_blockers)
    blockers = sorted(set(blockers))

    hard_block_prefixes = (
        "APPROVER_TYPE_NOT_HUMAN", "APPROVAL_REVOKED", "APPROVAL_EXPIRED_OR_INVALID_TIME",
        "KILL_SWITCH_ENGAGED", "CAPITAL_LIMIT", "LEVERAGE_LIMIT", "EXPOSURE_LIMIT",
        "DD_DAY_LIMIT", "DD_TOTAL_LIMIT", "EXCHANGE_NOT_ALLOWED", "SYMBOL_NOT_ALLOWED",
        "DIGITAL_TWIN_CAPITAL_GATE", "UPSTREAM_STATE_MISMATCH", "MISSING_UPSTREAM_GATE",
    )
    if any(value.startswith(hard_block_prefixes) for value in blockers):
        state = "BLOCK_HUMAN_GOVERNED_CAPITAL"
        action = "block"
    elif blockers:
        state = "HOLD_HUMAN_GOVERNANCE_PREFLIGHT"
        action = "hold"
    else:
        state = "PASS_HUMAN_GOVERNANCE_PREFLIGHT"
        action = "hold"

    metrics = {
        "requested_stage": stage,
        "stage_index": stage_index,
        "completed_stages": completed_stages,
        "required_prior_stages": required_prior,
        "exchange": exchange,
        "symbols": symbols,
        "requested_capital_usdt": capital,
        "requested_leverage": leverage,
        "requested_exposure_pct": exposure,
        "dd_day_pct": dd_day,
        "dd_total_pct": dd_total,
        "kill_switch_engaged": request.get("kill_switch_engaged") is True,
        "external_manual_enable_required": True,
        "preflight_pass_does_not_enable_live": True,
    }
    lineage = {
        **binding,
        "upstream_gate_sha": stable_sha(upstream),
        "approval_sha": approval["approval_sha"] if approval else None,
        "request_sha": stable_sha(request),
    }
    result = Decision(state, action, tuple(blockers), metrics, lineage).as_dict()
    result["decision_sha"] = stable_sha(result)
    return result
