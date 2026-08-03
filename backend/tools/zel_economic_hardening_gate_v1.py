from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_ECONOMIC_HARDENING_GATE_V1"
SCHEMA = "zel.economic_hardening.receipt.v1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def finite(value: Any) -> float:
    if value is None or isinstance(value, bool):
        raise RuntimeError(f"FINITE_NUMBER_REQUIRED:{value!r}")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RuntimeError(f"FINITE_NUMBER_REQUIRED:{value!r}")
    return parsed


def sha_ok(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "").lower()))


def tokens(value: str) -> Counter[str]:
    return Counter(re.findall(r"[a-z0-9]+", value.lower()))


def cosine_text(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    dot = sum(a[key] * b.get(key, 0) for key in a)
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def safety() -> dict[str, Any]:
    return {
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_mutated": False,
        "paper_mutated": False,
        "live_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def survivor_window_pass(metrics: Mapping[str, Any], gate: Mapping[str, Any]) -> bool:
    return (
        finite(metrics.get("net_R")) > finite(gate["minimum_net_R"])
        and finite(metrics.get("profit_factor")) >= finite(gate["minimum_profit_factor"])
        and finite(metrics.get("expectancy_R")) > finite(gate["minimum_expectancy_R"])
        and finite(metrics.get("payoff_ratio")) >= finite(gate["minimum_payoff_ratio"])
        and finite(metrics.get("retention_pct")) >= finite(gate["minimum_retention_pct"])
    )


def h1_kill_gate(
    row: Mapping[str, Any], policy: Mapping[str, Any], survivor_gate: Mapping[str, Any]
) -> dict[str, Any]:
    approved_axes = [str(value) for value in row.get("approved_axes", [])]
    attempts = [value for value in row.get("axis_attempts", []) if isinstance(value, Mapping)]
    summary = row.get("family_summary") or {}
    max_generations = int(policy["maximum_generations_per_axis_data_sha"])
    generation_by_axis: dict[str, int] = {}
    positive_by_axis: dict[str, bool] = {}
    fingerprints: Counter[str] = Counter()
    for attempt in attempts:
        axis = str(attempt.get("axis_id") or "")
        generation_by_axis[axis] = max(generation_by_axis.get(axis, 0), int(attempt.get("generation") or 0))
        positive = all(
            survivor_window_pass(attempt[window], survivor_gate)
            for window in ("w1", "w2", "w3")
        )
        positive_by_axis[axis] = bool(positive_by_axis.get(axis, False) or positive)
        fingerprint = str(attempt.get("failure_fingerprint") or "")
        if fingerprint:
            fingerprints[fingerprint] += 1
    axes_exhausted = bool(approved_axes) and all(
        generation_by_axis.get(axis, 0) >= max_generations for axis in approved_axes
    )
    two_generation_failure = any(
        generation_by_axis.get(axis, 0) >= max_generations and not positive_by_axis.get(axis, False)
        for axis in approved_axes
    )
    gross_non_positive = finite(summary.get("gross_expectancy_R")) <= 0.0
    cost_non_positive = finite(summary.get("cost_adjusted_expectancy_R")) <= 0.0
    retention_negative = (
        finite(summary.get("retention_pct")) >= finite(survivor_gate["minimum_retention_pct"])
        and cost_non_positive
    )
    neighborhood_negative = finite(summary.get("adjacent_parameter_positive_ratio")) < finite(
        policy["minimum_adjacent_parameter_positive_ratio"]
    )
    repeated_failure = any(
        count >= int(policy["repeated_failure_fingerprint_count"])
        for count in fingerprints.values()
    )
    flags = {
        "approved_axes_exhausted": axes_exhausted,
        "two_generation_failure": two_generation_failure,
        "gross_edge_non_positive": gross_non_positive,
        "cost_adjusted_expectancy_non_positive": cost_non_positive,
        "retention_restores_negative_economics": retention_negative,
        "adjacent_parameter_neighborhood_predominantly_negative": neighborhood_negative,
        "repeated_failure_fingerprint": repeated_failure,
    }
    reject = any(flags.values())
    receipt = {
        "schema_version": "zel.economic_hardening.h1.receipt.v1",
        "control": "H1_STRATEGY_FAMILY_KILL_GATE",
        "state": "REJECT_FAMILY" if reject else "HOLD_FAMILY_REPAIRABLE",
        "strategy_id": row.get("strategy_id"),
        "family_id": row.get("family_id"),
        "data_sha256": row.get("data_sha256"),
        "window_sha256": row.get("window_sha256"),
        "flags": flags,
        "generation_by_axis": generation_by_axis,
        "positive_by_axis": positive_by_axis,
        "failure_fingerprint_counts": dict(fingerprints),
        "further_parameter_tuning_allowed": not reject,
        "requires_new_archetype_and_evidence_id": reject,
        "control_engine_pass": True,
        **safety(),
    }
    if not sha_ok(row.get("data_sha256")) or not sha_ok(row.get("window_sha256")):
        raise RuntimeError("H1_SHA_INVALID")
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def h2_archetype_intake(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    required_text = ("archetype_id", "economic_mechanism", "falsification_rule", "structural_signature")
    missing = [key for key in required_text if not str(row.get(key) or "").strip()]
    features = [str(value) for value in row.get("entry_time_features", []) if str(value).strip()]
    evidence = [str(value) for value in row.get("external_evidence_ids", []) if str(value).strip()]
    for key in policy["required_sha_fields"]:
        if not sha_ok(row.get(key)):
            missing.append(key)
    if not features:
        missing.append("entry_time_features")
    if len(evidence) < int(policy["minimum_external_evidence_count"]):
        missing.append("external_evidence_ids")
    signature = str(row.get("structural_signature") or "")
    similarities = [
        cosine_text(signature, str(existing))
        for existing in row.get("existing_structural_signatures", [])
    ]
    max_similarity = max(similarities, default=0.0)
    parameter_variant = row.get("parameter_variant_of_rejected_family") is True
    structurally_distinct = max_similarity <= finite(policy["maximum_structural_similarity"])
    passed = not missing and not parameter_variant and structurally_distinct
    receipt = {
        "schema_version": "zel.economic_hardening.h2.receipt.v1",
        "control": "H2_NEW_ARCHETYPE_INTAKE_GATE",
        "state": "PASS_ARCHETYPE_INTAKE" if passed else "HOLD_ARCHETYPE_INTAKE_REJECTED",
        "archetype_id": row.get("archetype_id"),
        "missing_requirements": sorted(set(missing)),
        "parameter_variant_of_rejected_family": parameter_variant,
        "maximum_structural_similarity": max_similarity,
        "maximum_allowed_similarity": finite(policy["maximum_structural_similarity"]),
        "structurally_distinct": structurally_distinct,
        "entry_time_feature_count": len(features),
        "external_evidence_ids": evidence,
        "falsification_rule_frozen": bool(str(row.get("falsification_rule") or "").strip()),
        "control_engine_pass": True,
        **safety(),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def h3_bingx_light_calibration(
    row: Mapping[str, Any], policy: Mapping[str, Any], now: datetime
) -> dict[str, Any]:
    observed = parse_time(str(row.get("observed_at") or ""))
    age_hours = max(0.0, (now - observed).total_seconds() / 3600.0)
    floors = [value for value in row.get("slippage_floor_bps_by_notional", []) if isinstance(value, Mapping)]
    reasons: list[str] = []
    if policy.get("require_official_fee_source") and row.get("source_tier") != "official":
        reasons.append("OFFICIAL_FEE_SOURCE_REQUIRED")
    if not str(row.get("source_identifier") or "") or not str(row.get("source_url") or ""):
        reasons.append("SOURCE_IDENTIFIER_OR_URL_MISSING")
    if age_hours > finite(policy["maximum_source_age_hours"]):
        reasons.append("SOURCE_STALE")
    if policy.get("require_account_specific_fee_verification") and row.get("account_specific_verified") is not True:
        reasons.append("ACCOUNT_FEE_TIER_UNVERIFIED")
    maker = finite(row.get("maker_fee_pct"))
    taker = finite(row.get("taker_fee_pct"))
    if maker < 0.0 or taker <= 0.0:
        reasons.append("FEE_RATE_INVALID")
    funding = finite(row.get("funding_p95_abs_pct_8h"))
    if policy.get("require_p95_funding") and funding < 0.0:
        reasons.append("FUNDING_P95_INVALID")
    if policy.get("require_size_aware_slippage_floor") and not floors:
        reasons.append("SLIPPAGE_FLOOR_MISSING")
    last_notional = -math.inf
    for floor in floors:
        notional = finite(floor.get("max_notional_usdt"))
        slippage = finite(floor.get("slippage_bps_one_way"))
        if notional <= last_notional or notional <= 0.0 or slippage < 0.0:
            reasons.append("SLIPPAGE_BUCKET_INVALID")
        last_notional = notional
    latency_p95 = finite(row.get("latency_ms_p95"))
    if policy.get("require_latency_p95") and latency_p95 <= 0.0:
        reasons.append("LATENCY_P95_INVALID")
    if policy.get("require_plus_one_bar_stress") and row.get("plus_one_bar_stress_required") is not True:
        reasons.append("PLUS_ONE_BAR_STRESS_REQUIRED")
    conservative_round_trip_fee_bps = 2.0 * taker * 100.0
    receipt = {
        "schema_version": "zel.economic_hardening.h3.receipt.v1",
        "control": "H3_BINGX_LIGHT_CALIBRATION",
        "state": "PASS_BINGX_LIGHT_CALIBRATION" if not reasons else "HOLD_BINGX_LIGHT_CALIBRATION",
        "observed_at": observed.isoformat(),
        "evaluated_at": now.isoformat(),
        "source_age_hours": age_hours,
        "source_identifier": row.get("source_identifier"),
        "source_url": row.get("source_url"),
        "account_fee_tier": row.get("account_fee_tier"),
        "maker_fee_pct": maker,
        "taker_fee_pct": taker,
        "conservative_round_trip_fee_bps": conservative_round_trip_fee_bps,
        "funding_p95_abs_pct_8h": funding,
        "slippage_floor_bps_by_notional": floors,
        "latency_ms_p50": finite(row.get("latency_ms_p50")),
        "latency_ms_p95": latency_p95,
        "plus_one_bar_stress_required": row.get("plus_one_bar_stress_required") is True,
        "blockers": sorted(set(reasons)),
        "control_engine_pass": True,
        **safety(),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def h4_placebo_controls(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    candidate = row.get("candidate") or {}
    controls = row.get("controls") or {}
    required = [str(value) for value in policy["required_controls"]]
    results: dict[str, Any] = {}
    all_pass = True
    for name in required:
        control = controls.get(name)
        blockers: list[str] = []
        if not isinstance(control, Mapping):
            blockers.append("CONTROL_MISSING")
            control = {}
        if policy.get("require_equal_trade_budget") and int(control.get("trade_count") or -1) != int(candidate.get("trade_count") or -2):
            blockers.append("TRADE_BUDGET_MISMATCH")
        if policy.get("require_identical_window_sha") and control.get("window_sha256") != candidate.get("window_sha256"):
            blockers.append("WINDOW_SHA_MISMATCH")
        if policy.get("require_identical_cost_model_sha") and control.get("cost_model_sha256") != candidate.get("cost_model_sha256"):
            blockers.append("COST_MODEL_SHA_MISMATCH")
        if finite(candidate.get("net_R")) <= finite(control.get("net_R")):
            blockers.append("NET_R_NOT_SUPERIOR")
        if finite(candidate.get("expectancy_R")) <= finite(control.get("expectancy_R")):
            blockers.append("EXPECTANCY_NOT_SUPERIOR")
        if finite(control.get("candidate_minus_control_ci_low_R")) <= finite(policy["minimum_candidate_minus_control_ci_low_R"]):
            blockers.append("CI_LOW_NOT_POSITIVE")
        if finite(control.get("p_value")) > finite(policy["maximum_p_value"]):
            blockers.append("P_VALUE_ABOVE_MAX")
        passed = not blockers
        all_pass = bool(all_pass and passed)
        results[name] = {
            "pass": passed,
            "blockers": blockers,
            "control_net_R": control.get("net_R"),
            "candidate_minus_control_net_R": finite(candidate.get("net_R")) - finite(control.get("net_R")),
            "candidate_minus_control_ci_low_R": control.get("candidate_minus_control_ci_low_R"),
            "p_value": control.get("p_value"),
        }
    if not sha_ok(candidate.get("window_sha256")) or not sha_ok(candidate.get("cost_model_sha256")):
        raise RuntimeError("H4_CANDIDATE_SHA_INVALID")
    receipt = {
        "schema_version": "zel.economic_hardening.h4.receipt.v1",
        "control": "H4_PLACEBO_NEGATIVE_CONTROLS",
        "state": "PASS_PLACEBO_NEGATIVE_CONTROLS" if all_pass else "NO_PROVEN_EDGE",
        "candidate": dict(candidate),
        "control_results": results,
        "required_control_count": len(required),
        "passed_control_count": sum(1 for result in results.values() if result["pass"]),
        "same_windows_costs_trade_budget_required": True,
        "control_engine_pass": True,
        **safety(),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def h5_concentration(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    sealed_at = parse_time(str(row.get("thresholds_sealed_at") or ""))
    holdout_at = parse_time(str(row.get("holdout_opened_at") or ""))
    blockers: list[str] = []
    if policy.get("thresholds_must_be_sealed_before_holdout") and sealed_at > holdout_at:
        blockers.append("THRESHOLDS_NOT_SEALED_BEFORE_HOLDOUT")
    dimensions = row.get("dimensions") or {}

    def max_share(name: str) -> float:
        values = [finite(item.get("profit_share")) for item in dimensions.get(name, []) if isinstance(item, Mapping)]
        return max(values, default=0.0)

    max_symbol = max_share("symbol")
    max_regime = max_share("regime")
    top10 = finite(row.get("top10_trade_profit_share"))
    if max_symbol > finite(policy["maximum_single_symbol_profit_share"]):
        blockers.append("SINGLE_SYMBOL_CONCENTRATION")
    if max_regime > finite(policy["maximum_single_regime_profit_share"]):
        blockers.append("SINGLE_REGIME_CONCENTRATION")
    if top10 > finite(policy["maximum_top10_trade_profit_share"]):
        blockers.append("TOP10_TRADE_CONCENTRATION")
    leave_one = [value for value in row.get("leave_one_group_out", []) if isinstance(value, Mapping)]
    if not leave_one:
        blockers.append("LEAVE_ONE_GROUP_OUT_MISSING")
    failed_leave_one = [
        {"dimension": item.get("dimension"), "group": item.get("group"), "net_R": item.get("net_R")}
        for item in leave_one
        if finite(item.get("net_R")) <= finite(policy["minimum_leave_one_group_out_net_R"])
    ]
    if failed_leave_one:
        blockers.append("LEAVE_ONE_GROUP_OUT_NON_POSITIVE")
    receipt = {
        "schema_version": "zel.economic_hardening.h5.receipt.v1",
        "control": "H5_CONCENTRATION_FRAGILITY_GATE",
        "state": "PASS_CONCENTRATION_FRAGILITY" if not blockers else "HOLD_CONCENTRATION_FRAGILITY",
        "thresholds_sealed_at": sealed_at.isoformat(),
        "holdout_opened_at": holdout_at.isoformat(),
        "maximum_symbol_profit_share": max_symbol,
        "maximum_regime_profit_share": max_regime,
        "top10_trade_profit_share": top10,
        "leave_one_group_out_count": len(leave_one),
        "failed_leave_one_group_out": failed_leave_one,
        "blockers": sorted(set(blockers)),
        "dimensions": dimensions,
        "control_engine_pass": True,
        **safety(),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def evaluate(input_data: Mapping[str, Any], policy: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    controls = {
        "H1": h1_kill_gate(
            input_data["strategy_family"],
            policy["h1_strategy_family_kill_gate"],
            policy["survivor_gate"],
        ),
        "H2": h2_archetype_intake(
            input_data["archetype_candidate"], policy["h2_new_archetype_intake"]
        ),
        "H3": h3_bingx_light_calibration(
            input_data["bingx_light_calibration"],
            policy["h3_bingx_light_calibration"],
            now,
        ),
        "H4": h4_placebo_controls(
            input_data["placebo_negative_controls"],
            policy["h4_placebo_negative_controls"],
        ),
        "H5": h5_concentration(
            input_data["concentration_fragility"],
            policy["h5_concentration_fragility"],
        ),
    }
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": now.isoformat(),
        "state": "PASS_H1_H5_CONTROL_ENGINE_EVALUATION",
        "control_count": len(controls),
        "controls": controls,
        "policy_sha256": stable_sha(policy),
        "input_sha256": stable_sha(input_data),
        "installation_scope": "RESEARCH_CONTROL_PLANE_ONLY",
        "heavy_replay_started": False,
        **safety(),
    }
    if not all(control.get("control_engine_pass") is True for control in controls.values()):
        raise RuntimeError("CONTROL_ENGINE_EVALUATION_FAILED")
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    gate = {
        "minimum_net_R": 0.0,
        "minimum_profit_factor": 1.0,
        "minimum_expectancy_R": 0.0,
        "minimum_payoff_ratio": 1.0,
        "minimum_retention_pct": 60.0,
    }
    assert survivor_window_pass(
        {"net_R": 1, "profit_factor": 1, "expectancy_R": 0.1, "payoff_ratio": 1, "retention_pct": 60},
        gate,
    )
    assert not survivor_window_pass(
        {"net_R": 0, "profit_factor": 1, "expectancy_R": 0.1, "payoff_ratio": 1, "retention_pct": 60},
        gate,
    )
    assert cosine_text("low turnover volatility breakout", "high turnover ema scalp") < 0.85
    assert cosine_text("low turnover volatility breakout", "low turnover volatility breakout") == 1.0
    assert sha_ok("a" * 64)
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--now")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.input or not args.policy or not args.out:
        parser.error("--input, --policy and --out are required")
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    result = evaluate(read_json(args.input), read_json(args.policy), now)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "control_count": result["control_count"], "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
