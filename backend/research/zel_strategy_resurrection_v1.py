from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "zel.strategy_resurrection.v1"
FINGERPRINTS = {
    "SOURCE_OR_LINEAGE_HOLD",
    "DATA_INSUFFICIENT_HOLD",
    "INDICATOR_OR_BASIS_DEAD",
    "ZERO_MARKET_OPPORTUNITY",
    "GATE_OVERFILTER_ZERO_TRADES",
    "LOW_SAMPLE_HOLD",
    "BAD_ENTRY_ECONOMICS",
    "NEAR_PASS_LOSS_SHAPE",
    "NEAR_BREAKEVEN_ECONOMICS",
    "COST_FRAGILE",
    "REGIME_CONCENTRATION",
    "SYMBOL_CONCENTRATION",
    "SHORT_ONLY_EDGE",
    "NO_GENERALIZABLE_EDGE",
    "PASS_CANDIDATE",
}
ALLOWED_AXES = {
    "SOURCE_OR_LINEAGE_HOLD": set(),
    "DATA_INSUFFICIENT_HOLD": set(),
    "INDICATOR_OR_BASIS_DEAD": {"indicator_basis", "indicator_seed", "indicator_state"},
    "ZERO_MARKET_OPPORTUNITY": {"market_universe", "timeframe_eligibility", "new_data_only"},
    "GATE_OVERFILTER_ZERO_TRADES": {"gate_structure", "gate_order", "context_softening", "entry_window_semantics"},
    "LOW_SAMPLE_HOLD": {"new_data_only"},
    "BAD_ENTRY_ECONOMICS": {"entry_trigger", "entry_context", "structural_invalidation"},
    "NEAR_PASS_LOSS_SHAPE": {"stop_shape", "break_even", "time_stop", "reduce25", "loss_cooldown"},
    "NEAR_BREAKEVEN_ECONOMICS": {"exit_capture", "break_even", "time_stop", "cost_filter", "regime_router"},
    "COST_FRAGILE": {"cost_filter", "turnover_control", "holding_time", "liquidity_filter"},
    "REGIME_CONCENTRATION": {"regime_router", "regime_eligibility", "defensive_abstain"},
    "SYMBOL_CONCENTRATION": {"symbol_eligibility", "capacity_filter", "portfolio_role"},
    "SHORT_ONLY_EDGE": {"side_isolation", "short_observer_child", "defensive_sleeve"},
    "NO_GENERALIZABLE_EDGE": {"new_data_only", "new_child_basis"},
    "PASS_CANDIDATE": set(),
}
FORBIDDEN_AXIS_DOMAINS = {
    "INDICATOR_OR_BASIS_DEAD": {"exit", "skill", "sizing"},
    "GATE_OVERFILTER_ZERO_TRADES": {"exit", "stop", "target", "skill", "sizing"},
    "NEAR_PASS_LOSS_SHAPE": {"entry_relaxation", "market_universe"},
    "COST_FRAGILE": {"entry_relaxation", "leverage"},
    "NO_GENERALIZABLE_EDGE": {"same_data_threshold", "same_data_generation"},
}
REQUIRED_EVIDENCE_FIELDS = {
    "strategy_id", "strategy_source_sha256", "source_verified", "lineage_verified",
    "decision_call_count", "indicator_valid_pct", "pre_gate_opportunity_count",
    "gate_block_count", "trade_count", "net_return_pct", "profit_factor",
    "average_loss_r", "control_average_loss_r", "max_drawdown_pct",
    "stress_net_return_pct", "positive_window_count", "window_count",
    "positive_symbol_count", "symbol_count", "largest_symbol_contribution_pct",
    "long_net_return_pct", "short_observer_net_return_pct", "duplicate_trade_count",
    "lookahead_violation_count", "cost_model_mismatch_count", "sample_fingerprint",
}
REQUIRED_POLICY_FIELDS = {
    "minimum_decision_calls", "minimum_indicator_valid_pct", "gate_overfilter_min_block_rate",
    "minimum_performance_trades", "minimum_profit_factor", "minimum_positive_net_pct",
    "negative_edge_max_net_pct", "negative_edge_max_profit_factor",
    "near_breakeven_min_net_pct", "near_breakeven_max_net_pct",
    "near_breakeven_min_profit_factor", "loss_shape_worsening_min_r",
    "minimum_positive_window_ratio", "minimum_positive_symbol_ratio",
    "maximum_single_symbol_contribution_pct", "short_edge_min_delta_pct",
    "material_net_delta_pct", "maximum_shadow_survivors", "minimum_shadow_survivors",
}


class StrategyResurrectionError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise StrategyResurrectionError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        _fail("NUMBER_NOT_FINITE", name)
    return result


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INT_REQUIRED", name)
    return value


def _string(value: Any, name: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "policy")
    missing = sorted(REQUIRED_POLICY_FIELDS - set(raw))
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    policy = {key: _number(raw[key], f"policy.{key}") for key in REQUIRED_POLICY_FIELDS}
    for key in ("maximum_shadow_survivors", "minimum_shadow_survivors", "minimum_decision_calls", "minimum_performance_trades"):
        policy[key] = _integer(raw[key], f"policy.{key}")
    if not 0 <= policy["minimum_indicator_valid_pct"] <= 100:
        _fail("POLICY_RANGE_INVALID", "minimum_indicator_valid_pct")
    if not 0 <= policy["gate_overfilter_min_block_rate"] <= 1:
        _fail("POLICY_RANGE_INVALID", "gate_overfilter_min_block_rate")
    if policy["minimum_shadow_survivors"] > policy["maximum_shadow_survivors"]:
        _fail("SURVIVOR_RANGE_INVALID")
    source_ref = _string(raw.get("source_ref"), "policy.source_ref", maximum=300)
    source_sha = _sha(raw.get("source_sha256"), "policy.source_sha256")
    return {**policy, "source_ref": source_ref, "source_sha256": source_sha}


def validate_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "evidence")
    missing = sorted(REQUIRED_EVIDENCE_FIELDS - set(raw))
    if missing:
        _fail("EVIDENCE_FIELDS_MISSING", ",".join(missing))
    for key in ("source_verified", "lineage_verified"):
        if not isinstance(raw[key], bool):
            _fail("BOOL_REQUIRED", key)
    integers = {
        key: _integer(raw[key], key)
        for key in (
            "decision_call_count", "pre_gate_opportunity_count", "gate_block_count",
            "trade_count", "positive_window_count", "window_count",
            "positive_symbol_count", "symbol_count", "duplicate_trade_count",
            "lookahead_violation_count", "cost_model_mismatch_count",
        )
    }
    numbers = {
        key: _number(raw[key], key)
        for key in (
            "indicator_valid_pct", "net_return_pct", "profit_factor", "average_loss_r",
            "control_average_loss_r", "max_drawdown_pct", "stress_net_return_pct",
            "largest_symbol_contribution_pct", "long_net_return_pct", "short_observer_net_return_pct",
        )
    }
    if integers["positive_window_count"] > integers["window_count"]:
        _fail("WINDOW_COUNT_INCONSISTENT")
    if integers["positive_symbol_count"] > integers["symbol_count"]:
        _fail("SYMBOL_COUNT_INCONSISTENT")
    return {
        "strategy_id": _string(raw["strategy_id"], "strategy_id", maximum=120),
        "strategy_source_sha256": _sha(raw["strategy_source_sha256"], "strategy_source_sha256"),
        "source_verified": raw["source_verified"],
        "lineage_verified": raw["lineage_verified"],
        "sample_fingerprint": _sha(raw["sample_fingerprint"], "sample_fingerprint"),
        **integers,
        **numbers,
    }


def classify(value: Mapping[str, Any], policy_value: Mapping[str, Any]) -> dict[str, Any]:
    evidence = validate_evidence(value)
    policy = validate_policy(policy_value)
    secondary: list[str] = []
    trade_count = evidence["trade_count"]
    window_ratio = evidence["positive_window_count"] / max(evidence["window_count"], 1)
    symbol_ratio = evidence["positive_symbol_count"] / max(evidence["symbol_count"], 1)
    block_rate = evidence["gate_block_count"] / max(evidence["pre_gate_opportunity_count"], 1)

    if not evidence["source_verified"] or not evidence["lineage_verified"]:
        primary = "SOURCE_OR_LINEAGE_HOLD"
    elif evidence["duplicate_trade_count"] or evidence["lookahead_violation_count"] or evidence["cost_model_mismatch_count"]:
        primary = "SOURCE_OR_LINEAGE_HOLD"
    elif evidence["decision_call_count"] < policy["minimum_decision_calls"]:
        primary = "DATA_INSUFFICIENT_HOLD"
    elif evidence["indicator_valid_pct"] < policy["minimum_indicator_valid_pct"]:
        primary = "INDICATOR_OR_BASIS_DEAD"
    elif evidence["pre_gate_opportunity_count"] == 0:
        primary = "ZERO_MARKET_OPPORTUNITY"
    elif trade_count == 0 and block_rate >= policy["gate_overfilter_min_block_rate"]:
        primary = "GATE_OVERFILTER_ZERO_TRADES"
    elif trade_count < policy["minimum_performance_trades"]:
        primary = "LOW_SAMPLE_HOLD"
    else:
        loss_worsening = abs(evidence["average_loss_r"]) - abs(evidence["control_average_loss_r"])
        short_delta = evidence["short_observer_net_return_pct"] - evidence["long_net_return_pct"]
        if evidence["long_net_return_pct"] < 0 and short_delta >= policy["short_edge_min_delta_pct"] and evidence["short_observer_net_return_pct"] > 0:
            primary = "SHORT_ONLY_EDGE"
        elif evidence["net_return_pct"] > 0 and evidence["profit_factor"] >= policy["minimum_profit_factor"] and loss_worsening >= policy["loss_shape_worsening_min_r"]:
            primary = "NEAR_PASS_LOSS_SHAPE"
        elif (
            policy["near_breakeven_min_net_pct"] <= evidence["net_return_pct"] <= policy["near_breakeven_max_net_pct"]
            and evidence["profit_factor"] >= policy["near_breakeven_min_profit_factor"]
        ):
            primary = "NEAR_BREAKEVEN_ECONOMICS"
        elif evidence["net_return_pct"] > policy["minimum_positive_net_pct"] and evidence["stress_net_return_pct"] < 0:
            primary = "COST_FRAGILE"
        elif window_ratio < policy["minimum_positive_window_ratio"]:
            primary = "REGIME_CONCENTRATION"
        elif symbol_ratio < policy["minimum_positive_symbol_ratio"] or evidence["largest_symbol_contribution_pct"] > policy["maximum_single_symbol_contribution_pct"]:
            primary = "SYMBOL_CONCENTRATION"
        elif evidence["net_return_pct"] <= policy["negative_edge_max_net_pct"] and evidence["profit_factor"] <= policy["negative_edge_max_profit_factor"]:
            primary = "NO_GENERALIZABLE_EDGE"
        elif evidence["net_return_pct"] < policy["minimum_positive_net_pct"] or evidence["profit_factor"] < policy["minimum_profit_factor"]:
            primary = "BAD_ENTRY_ECONOMICS"
        else:
            primary = "PASS_CANDIDATE"

        if evidence["stress_net_return_pct"] < 0 and evidence["net_return_pct"] > 0:
            secondary.append("COST_FRAGILE")
        if window_ratio < policy["minimum_positive_window_ratio"]:
            secondary.append("REGIME_CONCENTRATION")
        if symbol_ratio < policy["minimum_positive_symbol_ratio"] or evidence["largest_symbol_contribution_pct"] > policy["maximum_single_symbol_contribution_pct"]:
            secondary.append("SYMBOL_CONCENTRATION")

    if primary not in FINGERPRINTS:
        _fail("FINGERPRINT_INTERNAL_ERROR", primary)
    result = {
        "schema_version": SCHEMA_VERSION,
        "strategy_id": evidence["strategy_id"],
        "strategy_source_sha256": evidence["strategy_source_sha256"],
        "sample_fingerprint": evidence["sample_fingerprint"],
        "primary_fingerprint": primary,
        "secondary_fingerprints": sorted(set(secondary) - {primary}),
        "allowed_axes": sorted(ALLOWED_AXES[primary]),
        "forbidden_axis_domains": sorted(FORBIDDEN_AXIS_DOMAINS.get(primary, set())),
        "same_data_auto_promotion_allowed": False,
        "parent_mutation_allowed": False,
        "shadow_activation_allowed": False,
        "needs_new_data": primary in {"DATA_INSUFFICIENT_HOLD", "ZERO_MARKET_OPPORTUNITY", "LOW_SAMPLE_HOLD", "NO_GENERALIZABLE_EDGE"},
        "evidence_sha256": canonical_sha(evidence),
        "policy_sha256": canonical_sha(policy),
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    result["result_sha256"] = canonical_sha(result)
    return result


def plan_child(
    classification: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    result = _mapping(classification, "classification")
    proposed = _mapping(proposal, "proposal")
    fingerprint = _string(result.get("primary_fingerprint"), "primary_fingerprint")
    if fingerprint not in FINGERPRINTS:
        _fail("FINGERPRINT_INVALID", fingerprint)
    axis = _string(proposed.get("axis"), "proposal.axis", maximum=120)
    if axis not in ALLOWED_AXES[fingerprint]:
        _fail("AXIS_NOT_ALLOWED_FOR_FINGERPRINT", f"{fingerprint}:{axis}")
    parent_sha = _sha(proposed.get("parent_sha256"), "proposal.parent_sha256")
    if parent_sha != result.get("strategy_source_sha256"):
        _fail("PARENT_SHA_MISMATCH")
    child_sha = _sha(proposed.get("child_sha256"), "proposal.child_sha256")
    if child_sha == parent_sha:
        _fail("CHILD_MUST_DIFFER_FROM_PARENT")
    parameters = proposed.get("parameters")
    if not isinstance(parameters, Mapping) or len(parameters) != 1:
        _fail("EXACTLY_ONE_PARAMETER_REQUIRED")
    parameter, values = next(iter(parameters.items()))
    parameter = _string(parameter, "proposal.parameter", maximum=120)
    if not isinstance(values, list) or not 1 <= len(values) <= 8:
        _fail("PARAMETER_VALUES_INVALID")
    source_sample = _sha(proposed.get("sample_fingerprint"), "proposal.sample_fingerprint")
    if source_sample != result.get("sample_fingerprint"):
        _fail("SAMPLE_FINGERPRINT_MISMATCH")
    plan = {
        "schema_version": "zel.strategy_child_plan.v1",
        "strategy_id": result["strategy_id"],
        "failure_fingerprint": fingerprint,
        "axis": axis,
        "parameter": parameter,
        "values": values,
        "parent_sha256": parent_sha,
        "child_sha256": child_sha,
        "sample_fingerprint": source_sample,
        "change_count": 1,
        "parent_immutable": True,
        "same_sample_promotion_allowed": False,
        "runtime_binding_allowed": False,
        "shadow_activation_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    plan["plan_sha256"] = canonical_sha(plan)
    return plan


def audit_exact25(
    evidence_rows: list[Mapping[str, Any]],
    policy: Mapping[str, Any],
    expected_sources: Mapping[str, str],
) -> dict[str, Any]:
    if len(evidence_rows) != 25:
        _fail("EXACT25_EVIDENCE_COUNT_REQUIRED", str(len(evidence_rows)))
    sources = {str(key): _sha(value, f"expected_sources.{key}") for key, value in expected_sources.items()}
    if len(sources) != 25:
        _fail("EXACT25_SOURCE_COUNT_REQUIRED", str(len(sources)))
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in evidence_rows:
        classified = classify(row, policy)
        strategy_id = classified["strategy_id"]
        if strategy_id in seen:
            _fail("DUPLICATE_STRATEGY_EVIDENCE", strategy_id)
        seen.add(strategy_id)
        if sources.get(strategy_id) != classified["strategy_source_sha256"]:
            _fail("STRATEGY_SOURCE_MISMATCH", strategy_id)
        results.append(classified)
    if seen != set(sources):
        _fail("STRATEGY_SET_MISMATCH")
    counts = Counter(row["primary_fingerprint"] for row in results)
    actionable = [row for row in results if row["allowed_axes"]]
    direct_pass = [row for row in results if row["primary_fingerprint"] == "PASS_CANDIDATE"]
    return {
        "schema_version": "zel.strategy_resurrection.audit.v1",
        "state": "PASS_EXACT25_FAILURE_FINGERPRINT_COVERAGE",
        "strategy_count": 25,
        "failure_fingerprint_coverage_pct": 100.0,
        "fingerprint_counts": dict(sorted(counts.items())),
        "direct_pass_count": len(direct_pass),
        "actionable_rescue_count": len(actionable),
        "results": sorted(results, key=lambda row: row["strategy_id"]),
        "p2_complete": False,
        "p2_complete_reason": "REAL_SHADOW_SURVIVOR_RECEIPTS_REQUIRED",
        "parent_strategy_mutation_count": 0,
        "same_sample_auto_promotion_count": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
