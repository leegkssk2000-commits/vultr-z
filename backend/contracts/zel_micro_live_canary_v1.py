from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "zel.micro_live.approval.v1"
PRIVATE_TOKENS = {"api_key", "apikey", "secret", "credential", "password", "private_key", "access_token", "refresh_token"}
POLICY_FIELDS = {
    "policy_ref", "policy_sha256", "minimum_notional_usdt", "maximum_notional_usdt",
    "maximum_leverage", "maximum_position_pct", "maximum_concurrent_positions",
    "maximum_planned_loss_r", "minimum_liquidation_buffer_pct", "maximum_funding_8h_pct",
    "maximum_exposure_minutes", "maximum_daily_dd_pct", "maximum_total_dd_pct",
}
APPROVAL_FIELDS = {
    "approval_id", "human_approved", "actor_ref", "nonce", "issued_at_ms", "expires_at_ms",
    "p5_state", "p5_result_sha256", "risk_policy_sha256", "strategy_id",
    "strategy_source_sha256", "family", "symbol", "side", "notional_usdt",
    "leverage", "position_pct", "planned_loss_r", "liquidation_buffer_pct",
    "funding_8h_pct", "exposure_minutes", "concurrent_positions", "add_allowed",
    "private_api_scope_ref", "emergency_stop_receipt_sha256", "rollback_receipt_sha256",
    "reconciliation_receipt_sha256", "source_ref", "fixture_only",
}
COMPLETION_FIELDS = {
    "canary_id", "permit_sha256", "source_ref", "source_sha256", "fixture_only",
    "started_at_ms", "ended_at_ms", "closed_position_count", "incident_count",
    "threshold_breach_count", "duplicate_order_count", "unreconciled_position_count",
    "lifecycle_mismatch_count", "formal_ledger_mismatch_count", "display_mismatch_count",
    "emergency_stop_drill_pass", "rollback_drill_pass", "reconciliation_pass",
    "minimum_liquidation_buffer_pct_observed", "maximum_leverage_observed",
    "maximum_position_pct_observed", "maximum_planned_loss_r_observed",
}


class MicroLiveContractError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise MicroLiveContractError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INT_REQUIRED", name)
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    return result


def _reject_private(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lower = str(key).lower()
            if any(token in lower for token in PRIVATE_TOKENS):
                _fail("PRIVATE_FIELD_FORBIDDEN", f"{path}.{key}")
            _reject_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private(child, f"{path}[{index}]")


def normalize_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "policy")
    missing = sorted(POLICY_FIELDS - set(raw))
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    policy = {
        "policy_ref": _string(raw["policy_ref"], "policy_ref"),
        "policy_sha256": _sha(raw["policy_sha256"], "policy_sha256"),
        "minimum_notional_usdt": _number(raw["minimum_notional_usdt"], "minimum_notional_usdt"),
        "maximum_notional_usdt": _number(raw["maximum_notional_usdt"], "maximum_notional_usdt"),
        "maximum_leverage": _number(raw["maximum_leverage"], "maximum_leverage"),
        "maximum_position_pct": _number(raw["maximum_position_pct"], "maximum_position_pct"),
        "maximum_concurrent_positions": _int(raw["maximum_concurrent_positions"], "maximum_concurrent_positions", 1),
        "maximum_planned_loss_r": _number(raw["maximum_planned_loss_r"], "maximum_planned_loss_r"),
        "minimum_liquidation_buffer_pct": _number(raw["minimum_liquidation_buffer_pct"], "minimum_liquidation_buffer_pct"),
        "maximum_funding_8h_pct": _number(raw["maximum_funding_8h_pct"], "maximum_funding_8h_pct"),
        "maximum_exposure_minutes": _number(raw["maximum_exposure_minutes"], "maximum_exposure_minutes"),
        "maximum_daily_dd_pct": _number(raw["maximum_daily_dd_pct"], "maximum_daily_dd_pct"),
        "maximum_total_dd_pct": _number(raw["maximum_total_dd_pct"], "maximum_total_dd_pct"),
    }
    if policy["maximum_leverage"] > 10:
        _fail("MICRO_LIVE_LEVERAGE_CAP_ABOVE_10")
    if not 0 < policy["minimum_notional_usdt"] <= policy["maximum_notional_usdt"]:
        _fail("NOTIONAL_RANGE_INVALID")
    if policy["maximum_concurrent_positions"] != 1:
        _fail("MICRO_LIVE_ONE_POSITION_REQUIRED")
    return policy


def normalize_approval(value: Mapping[str, Any], policy_value: Mapping[str, Any], *, now_ms: int) -> dict[str, Any]:
    raw = _mapping(value, "approval")
    _reject_private(raw)
    policy = normalize_policy(policy_value)
    missing = sorted(APPROVAL_FIELDS - set(raw))
    if missing:
        _fail("APPROVAL_FIELDS_MISSING", ",".join(missing))
    if raw["human_approved"] is not True:
        _fail("HUMAN_APPROVAL_REQUIRED")
    if raw["fixture_only"] is not False:
        _fail("REAL_APPROVAL_REQUIRED")
    issued = _int(raw["issued_at_ms"], "issued_at_ms", 1)
    expires = _int(raw["expires_at_ms"], "expires_at_ms", 1)
    if not issued <= now_ms < expires:
        _fail("APPROVAL_NOT_CURRENT")
    if expires - issued > 3_600_000:
        _fail("APPROVAL_TTL_EXCEEDS_ONE_HOUR")
    if _string(raw["p5_state"], "p5_state") != "PASS_P5_PAPER_30D_CANARY":
        _fail("P5_PASS_REQUIRED")
    if _sha(raw["risk_policy_sha256"], "risk_policy_sha256") != policy["policy_sha256"]:
        _fail("RISK_POLICY_SHA_MISMATCH")
    source_ref = _string(raw["source_ref"], "source_ref")
    if not source_ref.startswith("runtime:"):
        _fail("RUNTIME_SOURCE_REF_REQUIRED")
    private_scope = _string(raw["private_api_scope_ref"], "private_api_scope_ref")
    if not private_scope.startswith("secret-ref:"):
        _fail("SECRET_REFERENCE_REQUIRED_NO_SECRET_VALUE")
    family = _string(raw["family"], "family", maximum=80).upper()
    side = _string(raw["side"], "side", maximum=20).upper()
    if side not in {"LONG", "SHORT"}:
        _fail("SIDE_INVALID")
    numbers = {
        key: _number(raw[key], key)
        for key in (
            "notional_usdt", "leverage", "position_pct", "planned_loss_r",
            "liquidation_buffer_pct", "funding_8h_pct", "exposure_minutes",
        )
    }
    concurrent = _int(raw["concurrent_positions"], "concurrent_positions", 1)
    if not policy["minimum_notional_usdt"] <= numbers["notional_usdt"] <= policy["maximum_notional_usdt"]:
        _fail("NOTIONAL_OUT_OF_POLICY")
    if not 0 < numbers["leverage"] <= policy["maximum_leverage"]:
        _fail("LEVERAGE_OUT_OF_POLICY")
    if not 0 < numbers["position_pct"] <= policy["maximum_position_pct"]:
        _fail("POSITION_PCT_OUT_OF_POLICY")
    if not 0 < numbers["planned_loss_r"] <= policy["maximum_planned_loss_r"]:
        _fail("PLANNED_LOSS_OUT_OF_POLICY")
    if numbers["liquidation_buffer_pct"] < policy["minimum_liquidation_buffer_pct"]:
        _fail("LIQUIDATION_BUFFER_TOO_LOW")
    if abs(numbers["funding_8h_pct"]) > policy["maximum_funding_8h_pct"]:
        _fail("FUNDING_OUT_OF_POLICY")
    if numbers["exposure_minutes"] > policy["maximum_exposure_minutes"]:
        _fail("EXPOSURE_TIME_OUT_OF_POLICY")
    if concurrent != 1:
        _fail("ONE_CONCURRENT_POSITION_REQUIRED")
    if raw["add_allowed"] is not False:
        _fail("MICRO_LIVE_ADD_FORBIDDEN")
    approval = {
        "schema_version": SCHEMA_VERSION,
        "approval_id": _string(raw["approval_id"], "approval_id"),
        "human_approved": True,
        "actor_ref": _string(raw["actor_ref"], "actor_ref"),
        "nonce": _string(raw["nonce"], "nonce", maximum=160),
        "issued_at_ms": issued,
        "expires_at_ms": expires,
        "p5_state": "PASS_P5_PAPER_30D_CANARY",
        "p5_result_sha256": _sha(raw["p5_result_sha256"], "p5_result_sha256"),
        "risk_policy_sha256": policy["policy_sha256"],
        "strategy_id": _string(raw["strategy_id"], "strategy_id", maximum=120),
        "strategy_source_sha256": _sha(raw["strategy_source_sha256"], "strategy_source_sha256"),
        "family": family,
        "symbol": _string(raw["symbol"], "symbol", maximum=30).upper(),
        "side": side,
        **numbers,
        "concurrent_positions": concurrent,
        "add_allowed": False,
        "private_api_scope_ref": private_scope,
        "emergency_stop_receipt_sha256": _sha(raw["emergency_stop_receipt_sha256"], "emergency_stop_receipt_sha256"),
        "rollback_receipt_sha256": _sha(raw["rollback_receipt_sha256"], "rollback_receipt_sha256"),
        "reconciliation_receipt_sha256": _sha(raw["reconciliation_receipt_sha256"], "reconciliation_receipt_sha256"),
        "source_ref": source_ref,
        "fixture_only": False,
        "one_strategy_only": True,
        "one_family_only": True,
        "one_symbol_only": True,
        "capital_scale_allowed": False,
    }
    approval["approval_sha256"] = canonical_sha(approval)
    return approval


def normalize_completion(value: Mapping[str, Any], policy_value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "completion")
    _reject_private(raw)
    policy = normalize_policy(policy_value)
    missing = sorted(COMPLETION_FIELDS - set(raw))
    if missing:
        _fail("COMPLETION_FIELDS_MISSING", ",".join(missing))
    if raw["fixture_only"] is not False:
        _fail("REAL_COMPLETION_EVIDENCE_REQUIRED")
    source_ref = _string(raw["source_ref"], "source_ref")
    if not source_ref.startswith("runtime:"):
        _fail("RUNTIME_SOURCE_REF_REQUIRED")
    started = _int(raw["started_at_ms"], "started_at_ms", 1)
    ended = _int(raw["ended_at_ms"], "ended_at_ms", 1)
    if ended <= started:
        _fail("CANARY_TIME_ORDER_INVALID")
    counts = {
        key: _int(raw[key], key)
        for key in (
            "closed_position_count", "incident_count", "threshold_breach_count",
            "duplicate_order_count", "unreconciled_position_count", "lifecycle_mismatch_count",
            "formal_ledger_mismatch_count", "display_mismatch_count",
        )
    }
    if counts["closed_position_count"] < 1:
        _fail("MICRO_LIVE_CLOSED_POSITION_REQUIRED")
    for key in ("emergency_stop_drill_pass", "rollback_drill_pass", "reconciliation_pass"):
        if raw[key] is not True:
            _fail("COMPLETION_DRILL_OR_RECONCILIATION_REQUIRED", key)
    observed = {
        "minimum_liquidation_buffer_pct_observed": _number(raw["minimum_liquidation_buffer_pct_observed"], "minimum_liquidation_buffer_pct_observed"),
        "maximum_leverage_observed": _number(raw["maximum_leverage_observed"], "maximum_leverage_observed"),
        "maximum_position_pct_observed": _number(raw["maximum_position_pct_observed"], "maximum_position_pct_observed"),
        "maximum_planned_loss_r_observed": _number(raw["maximum_planned_loss_r_observed"], "maximum_planned_loss_r_observed"),
    }
    completion = {
        "schema_version": "zel.micro_live.completion.v1",
        "canary_id": _string(raw["canary_id"], "canary_id"),
        "permit_sha256": _sha(raw["permit_sha256"], "permit_sha256"),
        "source_ref": source_ref,
        "source_sha256": _sha(raw["source_sha256"], "source_sha256"),
        "fixture_only": False,
        "started_at_ms": started,
        "ended_at_ms": ended,
        **counts,
        "emergency_stop_drill_pass": True,
        "rollback_drill_pass": True,
        "reconciliation_pass": True,
        **observed,
    }
    blockers: list[str] = []
    for key in (
        "incident_count", "threshold_breach_count", "duplicate_order_count",
        "unreconciled_position_count", "lifecycle_mismatch_count",
        "formal_ledger_mismatch_count", "display_mismatch_count",
    ):
        if completion[key] != 0:
            blockers.append(f"NONZERO_{key.upper()}")
    if observed["minimum_liquidation_buffer_pct_observed"] < policy["minimum_liquidation_buffer_pct"]:
        blockers.append("LIQUIDATION_BUFFER_BREACH")
    if observed["maximum_leverage_observed"] > policy["maximum_leverage"]:
        blockers.append("LEVERAGE_BREACH")
    if observed["maximum_position_pct_observed"] > policy["maximum_position_pct"]:
        blockers.append("POSITION_PCT_BREACH")
    if observed["maximum_planned_loss_r_observed"] > policy["maximum_planned_loss_r"]:
        blockers.append("PLANNED_LOSS_BREACH")
    completion["blockers"] = sorted(blockers)
    completion["state"] = "PASS_P6_MICRO_LIVE_CANARY_COMPLETE" if not blockers else "HOLD_P6_MICRO_LIVE_CANARY"
    completion["capital_scale_allowed"] = False
    completion["next_activation_requires_new_human_approval"] = True
    completion["completion_sha256"] = canonical_sha(completion)
    return completion
