from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

VERSION = "STRATEGY11_ADAPTIVE_EXECUTION_CONTRACT_V1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_STATES = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}
ALLOWED_TRANSITIONS = {
    "NEW": {"SENT", "CANCELLED", "REJECTED"},
    "SENT": {"ACK", "PARTIAL", "FILLED", "CANCELLED", "REJECTED", "EXPIRED"},
    "ACK": {"PARTIAL", "FILLED", "CANCELLED", "REJECTED", "EXPIRED"},
    "PARTIAL": {"PARTIAL", "FILLED", "CANCELLED", "EXPIRED"},
    "FILLED": set(),
    "CANCELLED": set(),
    "REJECTED": set(),
    "EXPIRED": set(),
}
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "order_submission_allowed": False,
    "live_enabled": False,
}


class AdaptiveExecutionContractError(ValueError):
    pass


@dataclass(frozen=True)
class Evaluation:
    state: str
    action: str
    blockers: tuple[str, ...]
    metrics: Mapping[str, Any]
    lineage: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "strategy11.adaptive_execution_preview.v1",
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
        raise AdaptiveExecutionContractError(f"INVALID_NUMBER:{name}") from exc
    if not math.isfinite(number):
        raise AdaptiveExecutionContractError(f"NONFINITE_NUMBER:{name}")
    return number


def require_sha(value: Any, name: str) -> str:
    text = str(value or "").lower()
    if not SHA_RE.fullmatch(text):
        raise AdaptiveExecutionContractError(f"INVALID_SHA:{name}")
    return text


def require_nonempty(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AdaptiveExecutionContractError(f"EMPTY_FIELD:{name}")
    return text


def verify_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    required_false = (
        "runtime_activation_allowed",
        "order_submission_allowed",
        "automatic_live_enable",
        "threshold_authority",
    )
    for key in required_false:
        if policy.get(key) is not False:
            raise AdaptiveExecutionContractError(f"POLICY_NOT_FAIL_CLOSED:{key}")
    if policy.get("fixture_only") is not True:
        raise AdaptiveExecutionContractError("POLICY_NOT_FIXTURE_ONLY")
    expected = str(policy.get("policy_sha") or "")
    material = {key: value for key, value in policy.items() if key != "policy_sha"}
    actual = stable_sha(material)
    if expected != actual:
        raise AdaptiveExecutionContractError(f"POLICY_SHA_MISMATCH:{actual}:{expected}")
    return dict(policy)


def verify_source_binding(binding: Mapping[str, Any]) -> dict[str, str]:
    result = {
        "source_sha": require_sha(binding.get("source_sha"), "source_sha"),
        "data_sha": require_sha(binding.get("data_sha"), "data_sha"),
        "candidate_sha": require_sha(binding.get("candidate_sha"), "candidate_sha"),
        "policy_sha": require_sha(binding.get("policy_sha"), "policy_sha"),
        "run_id": require_nonempty(binding.get("run_id"), "run_id"),
        "artifact_id": require_nonempty(binding.get("artifact_id"), "artifact_id"),
    }
    return result


def verify_fill_history(history: Sequence[Mapping[str, Any]], requested_qty: float) -> dict[str, Any]:
    if not history:
        raise AdaptiveExecutionContractError("EMPTY_FILL_HISTORY")
    previous_state: str | None = None
    previous_filled = 0.0
    timestamps: list[int] = []
    for index, row in enumerate(history):
        state = str(row.get("state") or "").upper()
        if state not in ALLOWED_TRANSITIONS:
            raise AdaptiveExecutionContractError(f"UNKNOWN_FILL_STATE:{index}:{state}")
        filled = finite(row.get("filled_qty"), f"fill_history[{index}].filled_qty")
        ts_ms = int(finite(row.get("ts_ms"), f"fill_history[{index}].ts_ms"))
        if filled < previous_filled or filled < 0 or filled > requested_qty:
            raise AdaptiveExecutionContractError(f"INVALID_FILLED_QTY:{index}")
        if timestamps and ts_ms <= timestamps[-1]:
            raise AdaptiveExecutionContractError(f"NON_MONOTONIC_FILL_TS:{index}")
        if previous_state is not None and state != previous_state and state not in ALLOWED_TRANSITIONS[previous_state]:
            raise AdaptiveExecutionContractError(f"INVALID_FILL_TRANSITION:{previous_state}->{state}")
        if previous_state in TERMINAL_STATES:
            raise AdaptiveExecutionContractError(f"EVENT_AFTER_TERMINAL:{previous_state}")
        previous_state = state
        previous_filled = filled
        timestamps.append(ts_ms)
    assert previous_state is not None
    if previous_state == "FILLED" and abs(previous_filled - requested_qty) > 1e-12:
        raise AdaptiveExecutionContractError("FILLED_STATE_QTY_MISMATCH")
    if previous_state == "PARTIAL" and not (0 < previous_filled < requested_qty):
        raise AdaptiveExecutionContractError("PARTIAL_STATE_QTY_MISMATCH")
    return {
        "state": previous_state,
        "filled_qty": previous_filled,
        "filled_ratio": previous_filled / max(requested_qty, 1e-12),
        "last_ts_ms": timestamps[-1],
        "event_count": len(history),
        "history_sha": stable_sha(list(history)),
    }


def evaluate_preview(
    request: Mapping[str, Any],
    policy_input: Mapping[str, Any],
    seen_intent_ids: set[str] | frozenset[str] | None = None,
    seen_client_order_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    policy = verify_policy(policy_input)
    binding = verify_source_binding(request.get("source_binding") or {})
    if binding["policy_sha"] != policy["policy_sha"]:
        raise AdaptiveExecutionContractError("REQUEST_POLICY_SHA_MISMATCH")

    intent_id = require_nonempty(request.get("intent_id"), "intent_id")
    client_order_id = require_nonempty(request.get("client_order_id"), "client_order_id")
    symbol = require_nonempty(request.get("symbol"), "symbol").upper()
    exchange = require_nonempty(request.get("exchange"), "exchange").upper()
    side = require_nonempty(request.get("side"), "side").lower()
    if side not in {"long", "short"}:
        raise AdaptiveExecutionContractError("INVALID_SIDE")
    stop_owner = require_nonempty(request.get("stop_owner"), "stop_owner")

    requested_qty = finite(request.get("requested_qty"), "requested_qty")
    requested_notional = finite(request.get("requested_notional"), "requested_notional")
    equity = finite(request.get("equity"), "equity")
    leverage = finite(request.get("leverage"), "leverage")
    current_exposure_pct = finite(request.get("current_exposure_pct"), "current_exposure_pct")
    requested_exposure_pct = finite(request.get("requested_exposure_pct"), "requested_exposure_pct")
    liq_buffer_pct = finite(request.get("liq_buffer_pct"), "liq_buffer_pct")
    spread_bps = finite(request.get("spread_bps"), "spread_bps")
    slippage_bps = finite(request.get("slippage_bps"), "slippage_bps")
    fee_bps = finite(request.get("fee_bps"), "fee_bps")
    funding_8h_pct = finite(request.get("funding_8h_pct"), "funding_8h_pct")
    latency_ms = finite(request.get("latency_ms"), "latency_ms")
    data_age_ms = finite(request.get("data_age_ms"), "data_age_ms")
    depth_notional = finite(request.get("depth_notional"), "depth_notional")
    now_ms = int(finite(request.get("now_ms"), "now_ms"))

    if min(requested_qty, requested_notional, equity, depth_notional) <= 0:
        raise AdaptiveExecutionContractError("NONPOSITIVE_REQUEST_OR_CAPACITY")
    if current_exposure_pct < 0 or requested_exposure_pct <= 0 or liq_buffer_pct < 0:
        raise AdaptiveExecutionContractError("INVALID_RISK_METRIC")

    fill = verify_fill_history(request.get("fill_history") or [], requested_qty)
    total_cost_bps = spread_bps / 2.0 + slippage_bps + fee_bps + abs(funding_8h_pct) * 100.0
    participation_pct = requested_notional / max(depth_notional, 1e-12) * 100.0
    projected_exposure_pct = current_exposure_pct + requested_exposure_pct
    ack_age_ms = max(0, now_ms - int(fill["last_ts_ms"]))

    blockers: list[str] = []
    if intent_id in set(seen_intent_ids or set()):
        blockers.append("DUPLICATE_INTENT_ID")
    if client_order_id in set(seen_client_order_ids or set()):
        blockers.append("DUPLICATE_CLIENT_ORDER_ID")
    if exchange not in {str(value).upper() for value in policy["allowed_exchanges"]}:
        blockers.append("EXCHANGE_NOT_ALLOWED")
    if symbol not in {str(value).upper() for value in policy["allowed_symbols"]}:
        blockers.append("SYMBOL_NOT_ALLOWED")
    if leverage > finite(policy["max_leverage"], "policy.max_leverage"):
        blockers.append("LEVERAGE_LIMIT")
    if projected_exposure_pct > finite(policy["max_total_exposure_pct"], "policy.max_total_exposure_pct"):
        blockers.append("EXPOSURE_LIMIT")
    if liq_buffer_pct < finite(policy["min_liq_buffer_pct"], "policy.min_liq_buffer_pct"):
        blockers.append("LIQ_BUFFER_LIMIT")
    if spread_bps > finite(policy["max_spread_bps"], "policy.max_spread_bps"):
        blockers.append("SPREAD_LIMIT")
    if slippage_bps > finite(policy["max_slippage_bps"], "policy.max_slippage_bps"):
        blockers.append("SLIPPAGE_LIMIT")
    if latency_ms > finite(policy["max_latency_ms"], "policy.max_latency_ms"):
        blockers.append("LATENCY_LIMIT")
    if data_age_ms > finite(policy["max_data_age_ms"], "policy.max_data_age_ms"):
        blockers.append("STALE_DATA")
    if participation_pct > finite(policy["max_depth_participation_pct"], "policy.max_depth_participation_pct"):
        blockers.append("LIQUIDITY_CAPACITY_LIMIT")
    if total_cost_bps > finite(policy["max_total_cost_bps"], "policy.max_total_cost_bps"):
        blockers.append("TOTAL_COST_LIMIT")
    if stop_owner not in set(policy["allowed_stop_owners"]):
        blockers.append("STOP_OWNER_INVALID")
    if request.get("reduce_only") is not False:
        blockers.append("NEW_ENTRY_REDUCE_ONLY_SHAPE_INVALID")
    if fill["state"] in {"PARTIAL", "SENT", "ACK"} and ack_age_ms > int(policy["fill_heartbeat_timeout_ms"]):
        blockers.append("FILL_HEARTBEAT_STALE")
    if fill["state"] == "PARTIAL":
        blockers.append("PARTIAL_FILL_RECONCILIATION_REQUIRED")
    if fill["state"] in TERMINAL_STATES:
        blockers.append(f"TERMINAL_FILL_STATE_{fill['state']}")

    blockers = sorted(set(blockers))
    if blockers:
        state = "HOLD_ADAPTIVE_EXECUTION_PREVIEW"
        action = "hold"
        next_step = "RECONCILE_OR_REJECT_PREVIEW"
    else:
        state = "PASS_ADAPTIVE_EXECUTION_PREVIEW"
        action = "hold"
        next_step = "SHADOW_EXECUTION_SIMULATION_ONLY"

    metrics = {
        "requested_notional": requested_notional,
        "equity": equity,
        "leverage": leverage,
        "current_exposure_pct": current_exposure_pct,
        "requested_exposure_pct": requested_exposure_pct,
        "projected_exposure_pct": projected_exposure_pct,
        "liq_buffer_pct": liq_buffer_pct,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "fee_bps": fee_bps,
        "funding_8h_pct": funding_8h_pct,
        "total_cost_bps": total_cost_bps,
        "latency_ms": latency_ms,
        "data_age_ms": data_age_ms,
        "depth_notional": depth_notional,
        "depth_participation_pct": participation_pct,
        "fill_state": fill["state"],
        "filled_ratio": fill["filled_ratio"],
        "fill_heartbeat_age_ms": ack_age_ms,
        "stop_owner": stop_owner,
        "next_step": next_step,
    }
    lineage = {
        **binding,
        "intent_id": intent_id,
        "client_order_id": client_order_id,
        "symbol": symbol,
        "exchange": exchange,
        "side": side,
        "fill_history_sha": fill["history_sha"],
        "request_sha": stable_sha(request),
    }
    result = Evaluation(state, action, tuple(blockers), metrics, lineage).as_dict()
    result["decision_sha"] = stable_sha(result)
    return result
