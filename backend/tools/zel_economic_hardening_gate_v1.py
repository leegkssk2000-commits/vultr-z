from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_ECONOMIC_HARDENING_GATE_V2"
SCHEMA = "zel.economic_hardening.receipt.v2"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PROTECTED_TOKENS = (
    "canonical",
    "registry/runtime",
    "formal_ledger",
    "shadow",
    "paper",
    "live",
    "order",
)


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
    if not value:
        raise RuntimeError("TIME_REQUIRED")
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


def positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"POSITIVE_INTEGER_REQUIRED:{field}:{value!r}")
    return value


def sha_ok(value: Any) -> bool:
    return bool(SHA_RE.fullmatch(str(value or "").lower()))


def require_sha(value: Any, field: str) -> str:
    text = str(value or "").lower()
    if not sha_ok(text):
        raise RuntimeError(f"SHA256_REQUIRED:{field}")
    return text


def receipt_material(receipt: Mapping[str, Any]) -> dict[str, Any]:
    material = dict(receipt)
    material.pop("receipt_sha256", None)
    return material


def verify_embedded_receipt(
    receipt: Any,
    *,
    field: str,
    expected_state: str | None = None,
    fixture_allowed: bool = True,
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise RuntimeError(f"RECEIPT_OBJECT_REQUIRED:{field}")
    row = dict(receipt)
    supplied = require_sha(row.get("receipt_sha256"), f"{field}.receipt_sha256")
    actual = stable_sha(receipt_material(row))
    if supplied != actual:
        raise RuntimeError(f"RECEIPT_SHA_MISMATCH:{field}")
    if expected_state is not None and row.get("state") != expected_state:
        raise RuntimeError(f"RECEIPT_STATE_MISMATCH:{field}:{row.get('state')}")
    if not fixture_allowed and row.get("fixture_only") is True:
        raise RuntimeError(f"FIXTURE_RECEIPT_FORBIDDEN:{field}")
    return row


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
    data_sha = require_sha(row.get("data_sha256"), "H1.data_sha256")
    window_sha = require_sha(row.get("window_sha256"), "H1.window_sha256")
    approved_axes = [str(value).strip() for value in row.get("approved_axes", []) if str(value).strip()]
    if not approved_axes or len(set(approved_axes)) != len(approved_axes):
        raise RuntimeError("H1_APPROVED_AXES_INVALID")
    attempts = [value for value in row.get("axis_attempts", []) if isinstance(value, Mapping)]
    if len(attempts) != len(row.get("axis_attempts", [])):
        raise RuntimeError("H1_ATTEMPT_OBJECT_REQUIRED")
    summary = row.get("family_summary")
    if not isinstance(summary, Mapping):
        raise RuntimeError("H1_FAMILY_SUMMARY_REQUIRED")
    max_generations = positive_int(
        policy["maximum_generations_per_axis_data_sha"],
        "H1.maximum_generations_per_axis_data_sha",
    )
    generations_by_axis: dict[str, set[int]] = defaultdict(set)
    positive_by_axis: dict[str, bool] = {}
    fingerprints: Counter[str] = Counter()
    duplicate_generation_keys: list[str] = []
    seen_generation_keys: set[tuple[str, int]] = set()
    for attempt in attempts:
        axis = str(attempt.get("axis_id") or "").strip()
        if axis not in approved_axes:
            raise RuntimeError(f"H1_UNAPPROVED_AXIS:{axis}")
        generation = positive_int(attempt.get("generation"), f"H1.{axis}.generation")
        if generation > max_generations:
            raise RuntimeError(f"H1_GENERATION_ABOVE_BUDGET:{axis}:{generation}")
        key = (axis, generation)
        if key in seen_generation_keys:
            duplicate_generation_keys.append(f"{axis}:{generation}")
        seen_generation_keys.add(key)
        generations_by_axis[axis].add(generation)
        positive = all(
            survivor_window_pass(attempt[window], survivor_gate)
            for window in ("w1", "w2", "w3")
        )
        positive_by_axis[axis] = bool(positive_by_axis.get(axis, False) or positive)
        fingerprint = str(attempt.get("failure_fingerprint") or "").strip()
        if fingerprint:
            fingerprints[fingerprint] += 1
    if duplicate_generation_keys:
        raise RuntimeError("H1_DUPLICATE_AXIS_GENERATION:" + ",".join(sorted(duplicate_generation_keys)))
    required_sequence = set(range(1, max_generations + 1))
    sequence_complete_by_axis = {
        axis: generations_by_axis.get(axis, set()) == required_sequence for axis in approved_axes
    }
    generation_count_by_axis = {
        axis: len(generations_by_axis.get(axis, set())) for axis in approved_axes
    }
    axes_exhausted = all(sequence_complete_by_axis.values())
    completed_generation_failure = any(
        sequence_complete_by_axis[axis] and not positive_by_axis.get(axis, False)
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
        count >= positive_int(
            policy["repeated_failure_fingerprint_count"],
            "H1.repeated_failure_fingerprint_count",
        )
        for count in fingerprints.values()
    )
    flags = {
        "approved_axes_exhausted": axes_exhausted,
        "completed_generation_failure": completed_generation_failure,
        "gross_edge_non_positive": gross_non_positive,
        "cost_adjusted_expectancy_non_positive": cost_non_positive,
        "retention_restores_negative_economics": retention_negative,
        "adjacent_parameter_neighborhood_predominantly_negative": neighborhood_negative,
        "repeated_failure_fingerprint": repeated_failure,
    }
    reject = any(flags.values())
    receipt = {
        "schema_version": "zel.economic_hardening.h1.receipt.v2",
        "control": "H1_STRATEGY_FAMILY_KILL_GATE",
        "state": "REJECT_FAMILY" if reject else "HOLD_FAMILY_REPAIRABLE",
        "strategy_id": row.get("strategy_id"),
        "family_id": row.get("family_id"),
        "data_sha256": data_sha,
        "window_sha256": window_sha,
        "flags": flags,
        "generation_count_by_axis": generation_count_by_axis,
        "generation_sequence_complete_by_axis": sequence_complete_by_axis,
        "positive_by_axis": positive_by_axis,
        "failure_fingerprint_counts": dict(fingerprints),
        "further_parameter_tuning_allowed": not reject,
        "requires_new_archetype_and_evidence_id": reject,
        "control_engine_pass": True,
        **safety(),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def h2_archetype_intake(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    required_text = (
        "archetype_id",
        "economic_mechanism",
        "falsification_rule",
        "structural_signature",
    )
    missing = [key for key in required_text if not str(row.get(key) or "").strip()]
    features = [str(value).strip() for value in row.get("entry_time_features", []) if str(value).strip()]
    evidence = [str(value).strip() for value in row.get("external_evidence_ids", []) if str(value).strip()]
    for key in policy["required_sha_fields"]:
        if not sha_ok(row.get(key)):
            missing.append(key)
    if not features:
        missing.append("entry_time_features")
    if len(evidence) < positive_int(
        policy["minimum_external_evidence_count"], "H2.minimum_external_evidence_count"
    ):
        missing.append("external_evidence_ids")
    registry = verify_embedded_receipt(
        row.get("registry_snapshot_receipt"),
        field="H2.registry_snapshot_receipt",
        expected_state="PASS_ARCHETYPE_REGISTRY_SNAPSHOT",
    )
    registry_count = int(registry.get("registry_count") or 0)
    verified_empty = registry.get("verified_empty") is True
    require_sha(registry.get("registry_sha256"), "H2.registry_snapshot_receipt.registry_sha256")
    signature = str(row.get("structural_signature") or "")
    corpus = [str(value).strip() for value in row.get("existing_structural_signatures", []) if str(value).strip()]
    corpus_valid = (
        (corpus and registry_count == len(corpus) and not verified_empty)
        or (not corpus and registry_count == 0 and verified_empty)
    )
    similarities = [cosine_text(signature, existing) for existing in corpus]
    max_similarity = max(similarities, default=0.0)
    parameter_variant = row.get("parameter_variant_of_rejected_family") is True
    structurally_distinct = corpus_valid and max_similarity <= finite(
        policy["maximum_structural_similarity"]
    )
    if not corpus_valid:
        missing.append("verified_registry_corpus")
    passed = not missing and not parameter_variant and structurally_distinct
    receipt = {
        "schema_version": "zel.economic_hardening.h2.receipt.v2",
        "control": "H2_NEW_ARCHETYPE_INTAKE_GATE",
        "state": "PASS_ARCHETYPE_INTAKE" if passed else "HOLD_ARCHETYPE_INTAKE_REJECTED",
        "archetype_id": row.get("archetype_id"),
        "missing_requirements": sorted(set(missing)),
        "parameter_variant_of_rejected_family": parameter_variant,
        "registry_snapshot_receipt_sha256": registry["receipt_sha256"],
        "registry_count": registry_count,
        "verified_empty_registry": verified_empty,
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
    mode = str(row.get("calibration_mode") or "").strip().lower()
    if mode not in {"fixture", "real"}:
        raise RuntimeError("H3_CALIBRATION_MODE_INVALID")
    observed = parse_time(str(row.get("observed_at") or ""))
    raw_age_seconds = (now - observed).total_seconds()
    tolerance = finite(policy.get("maximum_future_clock_skew_seconds", 0.0))
    reasons: list[str] = []
    if raw_age_seconds < -tolerance:
        reasons.append("SOURCE_FUTURE_DATED")
    age_hours = max(0.0, raw_age_seconds / 3600.0)
    if age_hours > finite(policy["maximum_source_age_hours"]):
        reasons.append("SOURCE_STALE")
    if policy.get("require_official_fee_source") and row.get("source_tier") != "official":
        reasons.append("OFFICIAL_FEE_SOURCE_REQUIRED")
    if not str(row.get("source_identifier") or "").strip() or not str(row.get("source_url") or "").strip():
        reasons.append("SOURCE_IDENTIFIER_OR_URL_MISSING")
    account = verify_embedded_receipt(
        row.get("account_commission_receipt"),
        field="H3.account_commission_receipt",
        expected_state="PASS_BINGX_READ_ONLY_ACCOUNT_COMMISSION",
        fixture_allowed=(mode == "fixture"),
    )
    account_tier = str(row.get("account_fee_tier") or "").strip()
    if not account_tier:
        reasons.append("ACCOUNT_FEE_TIER_MISSING")
    if account.get("account_fee_tier") != account_tier:
        reasons.append("ACCOUNT_FEE_TIER_RECEIPT_MISMATCH")
    if account.get("source") != "BINGX_READ_ONLY_ACCOUNT_COMMISSION":
        reasons.append("ACCOUNT_RECEIPT_SOURCE_INVALID")
    require_sha(account.get("payload_sha256"), "H3.account_commission_receipt.payload_sha256")
    maker = finite(row.get("maker_fee_pct"))
    taker = finite(row.get("taker_fee_pct"))
    if abs(maker - finite(account.get("maker_fee_pct"))) > 1e-12:
        reasons.append("MAKER_FEE_RECEIPT_MISMATCH")
    if abs(taker - finite(account.get("taker_fee_pct"))) > 1e-12:
        reasons.append("TAKER_FEE_RECEIPT_MISMATCH")
    if maker < 0.0 or taker <= 0.0:
        reasons.append("FEE_RATE_INVALID")
    funding = finite(row.get("funding_p95_abs_pct_8h"))
    if policy.get("require_p95_funding") and funding < 0.0:
        reasons.append("FUNDING_P95_INVALID")
    floors = [
        value
        for value in row.get("slippage_floor_bps_by_notional", [])
        if isinstance(value, Mapping)
    ]
    if policy.get("require_size_aware_slippage_floor") and not floors:
        reasons.append("SLIPPAGE_FLOOR_MISSING")
    last_notional = -math.inf
    normalized_floors: list[dict[str, float]] = []
    for floor in floors:
        notional = finite(floor.get("max_notional_usdt"))
        slippage = finite(floor.get("slippage_bps_one_way"))
        if notional <= last_notional or notional <= 0.0 or slippage < 0.0:
            reasons.append("SLIPPAGE_BUCKET_INVALID")
        last_notional = notional
        normalized_floors.append(
            {"max_notional_usdt": notional, "slippage_bps_one_way": slippage}
        )
    latency_p50 = finite(row.get("latency_ms_p50"))
    latency_p95 = finite(row.get("latency_ms_p95"))
    if latency_p50 <= 0.0 or latency_p95 < latency_p50:
        reasons.append("LATENCY_DISTRIBUTION_INVALID")
    stress = verify_embedded_receipt(
        row.get("plus_one_bar_stress_receipt"),
        field="H3.plus_one_bar_stress_receipt",
        expected_state="PASS_PLUS_ONE_BAR_STRESS",
        fixture_allowed=(mode == "fixture"),
    )
    require_sha(stress.get("result_sha256"), "H3.plus_one_bar_stress_receipt.result_sha256")
    require_sha(stress.get("window_sha256"), "H3.plus_one_bar_stress_receipt.window_sha256")
    require_sha(stress.get("cost_model_sha256"), "H3.plus_one_bar_stress_receipt.cost_model_sha256")
    positive_int(stress.get("trade_count"), "H3.plus_one_bar_stress_receipt.trade_count")
    stressed_expectancy = finite(stress.get("stressed_expectancy_R"))
    finite(stress.get("baseline_expectancy_R"))
    if policy.get("require_plus_one_bar_stress") and stress.get("state") != "PASS_PLUS_ONE_BAR_STRESS":
        reasons.append("PLUS_ONE_BAR_STRESS_NOT_RUN")
    if mode == "real" and (
        account.get("fixture_only") is True or stress.get("fixture_only") is True
    ):
        reasons.append("FIXTURE_RECEIPT_USED_FOR_REAL_CALIBRATION")
    operational_pass = mode == "real" and not reasons
    state = (
        "PASS_BINGX_LIGHT_CALIBRATION"
        if operational_pass
        else "PASS_H3_ENGINE_FIXTURE_ONLY"
        if mode == "fixture" and not reasons
        else "HOLD_BINGX_LIGHT_CALIBRATION"
    )
    receipt = {
        "schema_version": "zel.economic_hardening.h3.receipt.v2",
        "control": "H3_BINGX_LIGHT_CALIBRATION",
        "state": state,
        "calibration_mode": mode,
        "operational_calibration_pass": operational_pass,
        "observed_at": observed.isoformat(),
        "evaluated_at": now.isoformat(),
        "source_age_hours": age_hours,
        "source_identifier": row.get("source_identifier"),
        "source_url": row.get("source_url"),
        "account_fee_tier": account_tier,
        "account_commission_receipt_sha256": account["receipt_sha256"],
        "maker_fee_pct": maker,
        "taker_fee_pct": taker,
        "conservative_round_trip_fee_bps": 2.0 * taker * 100.0,
        "funding_p95_abs_pct_8h": funding,
        "slippage_floor_bps_by_notional": normalized_floors,
        "latency_ms_p50": latency_p50,
        "latency_ms_p95": latency_p95,
        "plus_one_bar_stress_receipt_sha256": stress["receipt_sha256"],
        "plus_one_bar_stressed_expectancy_R": stressed_expectancy,
        "blockers": sorted(set(reasons)),
        "control_engine_pass": True,
        **safety(),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def validate_replay_result(
    receipt: Any,
    *,
    field: str,
    expected_control_type: str,
    expected_state: str,
) -> dict[str, Any]:
    row = verify_embedded_receipt(
        receipt, field=field, expected_state=expected_state
    )
    if row.get("control_type") != expected_control_type:
        raise RuntimeError(f"H4_CONTROL_TYPE_MISMATCH:{field}")
    for key in (
        "source_sha256",
        "data_sha256",
        "config_sha256",
        "window_sha256",
        "cost_model_sha256",
    ):
        require_sha(row.get(key), f"{field}.{key}")
    positive_int(row.get("trade_count"), f"{field}.trade_count")
    finite(row.get("net_R"))
    finite(row.get("expectancy_R"))
    return row


def h4_placebo_controls(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    required = [str(value) for value in policy["required_controls"]]
    candidate = validate_replay_result(
        row.get("candidate_receipt"),
        field="H4.candidate_receipt",
        expected_control_type="candidate",
        expected_state=str(policy["required_source_receipt_state"]),
    )
    controls = row.get("control_receipts")
    if not isinstance(controls, Mapping):
        raise RuntimeError("H4_CONTROL_RECEIPTS_REQUIRED")
    if set(controls) != set(required):
        raise RuntimeError(
            "H4_CONTROL_SET_MISMATCH:"
            + json.dumps({"expected": sorted(required), "actual": sorted(controls)})
        )
    candidate_count = positive_int(candidate["trade_count"], "H4.candidate.trade_count")
    results: dict[str, Any] = {}
    all_pass = True
    for name in required:
        control = validate_replay_result(
            controls[name],
            field=f"H4.control_receipts.{name}",
            expected_control_type=name,
            expected_state=str(policy["required_source_receipt_state"]),
        )
        blockers: list[str] = []
        control_count = positive_int(control["trade_count"], f"H4.{name}.trade_count")
        if policy.get("require_equal_trade_budget") and control_count != candidate_count:
            blockers.append("TRADE_BUDGET_MISMATCH")
        if policy.get("require_identical_window_sha") and control["window_sha256"] != candidate["window_sha256"]:
            blockers.append("WINDOW_SHA_MISMATCH")
        if policy.get("require_identical_cost_model_sha") and control["cost_model_sha256"] != candidate["cost_model_sha256"]:
            blockers.append("COST_MODEL_SHA_MISMATCH")
        if control["source_sha256"] != candidate["source_sha256"]:
            blockers.append("SOURCE_SHA_MISMATCH")
        if control["data_sha256"] != candidate["data_sha256"]:
            blockers.append("DATA_SHA_MISMATCH")
        if finite(candidate["net_R"]) <= finite(control["net_R"]):
            blockers.append("NET_R_NOT_SUPERIOR")
        if finite(candidate["expectancy_R"]) <= finite(control["expectancy_R"]):
            blockers.append("EXPECTANCY_NOT_SUPERIOR")
        ci_low = finite(control.get("candidate_minus_control_ci_low_R"))
        p_value = finite(control.get("p_value"))
        if ci_low <= finite(policy["minimum_candidate_minus_control_ci_low_R"]):
            blockers.append("CI_LOW_NOT_POSITIVE")
        if not (0.0 <= p_value <= finite(policy["maximum_p_value"])):
            blockers.append("P_VALUE_ABOVE_MAX_OR_INVALID")
        passed = not blockers
        all_pass = all_pass and passed
        results[name] = {
            "pass": passed,
            "blockers": blockers,
            "source_receipt_sha256": control["receipt_sha256"],
            "control_net_R": control["net_R"],
            "candidate_minus_control_net_R": finite(candidate["net_R"]) - finite(control["net_R"]),
            "candidate_minus_control_ci_low_R": ci_low,
            "p_value": p_value,
        }
    receipt = {
        "schema_version": "zel.economic_hardening.h4.receipt.v2",
        "control": "H4_PLACEBO_NEGATIVE_CONTROLS",
        "state": "PASS_PLACEBO_NEGATIVE_CONTROLS" if all_pass else "NO_PROVEN_EDGE",
        "candidate_source_receipt_sha256": candidate["receipt_sha256"],
        "candidate_trade_count": candidate_count,
        "window_sha256": candidate["window_sha256"],
        "cost_model_sha256": candidate["cost_model_sha256"],
        "control_results": results,
        "required_control_count": len(required),
        "passed_control_count": sum(1 for result in results.values() if result["pass"]),
        "same_windows_costs_trade_budget_verified": all_pass,
        "control_engine_pass": True,
        **safety(),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def h5_concentration(
    row: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    policy_sha256: str,
) -> dict[str, Any]:
    seal = verify_embedded_receipt(
        row.get("threshold_seal_receipt"),
        field="H5.threshold_seal_receipt",
        expected_state="PASS_THRESHOLD_SEAL",
    )
    if seal.get("policy_sha256") != policy_sha256:
        raise RuntimeError("H5_THRESHOLD_SEAL_POLICY_SHA_MISMATCH")
    holdout_window_sha = require_sha(
        row.get("holdout_window_sha256"), "H5.holdout_window_sha256"
    )
    if seal.get("holdout_window_sha256") != holdout_window_sha:
        raise RuntimeError("H5_THRESHOLD_SEAL_WINDOW_SHA_MISMATCH")
    thresholds_material = {
        "maximum_single_symbol_profit_share": finite(
            policy["maximum_single_symbol_profit_share"]
        ),
        "maximum_single_regime_profit_share": finite(
            policy["maximum_single_regime_profit_share"]
        ),
        "maximum_top10_trade_profit_share": finite(
            policy["maximum_top10_trade_profit_share"]
        ),
        "minimum_leave_one_group_out_net_R": finite(
            policy["minimum_leave_one_group_out_net_R"]
        ),
    }
    if seal.get("thresholds_sha256") != stable_sha(thresholds_material):
        raise RuntimeError("H5_THRESHOLD_SEAL_VALUES_MISMATCH")
    sealed_at = parse_time(str(seal.get("sealed_at") or ""))
    holdout_at = parse_time(str(row.get("holdout_opened_at") or ""))
    blockers: list[str] = []
    if (
        policy.get("thresholds_must_be_sealed_before_holdout")
        and sealed_at >= holdout_at
    ):
        blockers.append("THRESHOLDS_NOT_STRICTLY_SEALED_BEFORE_HOLDOUT")
    dimensions = row.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise RuntimeError("H5_DIMENSIONS_REQUIRED")
    required_dimensions = [str(value) for value in policy["required_dimensions"]]
    if set(dimensions) != set(required_dimensions):
        raise RuntimeError("H5_DIMENSION_SET_MISMATCH")
    expected_pairs: set[tuple[str, str]] = set()
    max_shares: dict[str, float] = {}
    normalized_dimensions: dict[str, list[dict[str, Any]]] = {}
    for dimension in required_dimensions:
        raw_rows = dimensions.get(dimension)
        if not isinstance(raw_rows, list) or not raw_rows:
            raise RuntimeError(f"H5_DIMENSION_ROWS_REQUIRED:{dimension}")
        groups: set[str] = set()
        normalized: list[dict[str, Any]] = []
        shares: list[float] = []
        for item in raw_rows:
            if not isinstance(item, Mapping):
                raise RuntimeError(f"H5_DIMENSION_ROW_OBJECT_REQUIRED:{dimension}")
            group = str(item.get("group") or "").strip()
            if not group or group in groups:
                raise RuntimeError(f"H5_GROUP_INVALID_OR_DUPLICATE:{dimension}:{group}")
            groups.add(group)
            share = finite(item.get("profit_share"))
            net_r = finite(item.get("net_R"))
            if not (0.0 <= share <= 1.0):
                raise RuntimeError(f"H5_PROFIT_SHARE_OUT_OF_RANGE:{dimension}:{group}")
            expected_pairs.add((dimension, group))
            shares.append(share)
            normalized.append({"group": group, "profit_share": share, "net_R": net_r})
        max_shares[dimension] = max(shares)
        normalized_dimensions[dimension] = normalized
    top10 = finite(row.get("top10_trade_profit_share"))
    if not (0.0 <= top10 <= 1.0):
        raise RuntimeError("H5_TOP10_SHARE_OUT_OF_RANGE")
    if max_shares["symbol"] > finite(policy["maximum_single_symbol_profit_share"]):
        blockers.append("SINGLE_SYMBOL_CONCENTRATION")
    if max_shares["regime"] > finite(policy["maximum_single_regime_profit_share"]):
        blockers.append("SINGLE_REGIME_CONCENTRATION")
    if top10 > finite(policy["maximum_top10_trade_profit_share"]):
        blockers.append("TOP10_TRADE_CONCENTRATION")
    leave_one_raw = row.get("leave_one_group_out")
    if not isinstance(leave_one_raw, list):
        raise RuntimeError("H5_LEAVE_ONE_GROUP_OUT_REQUIRED")
    observed_pairs: set[tuple[str, str]] = set()
    failed_leave_one: list[dict[str, Any]] = []
    normalized_leave_one: list[dict[str, Any]] = []
    for item in leave_one_raw:
        if not isinstance(item, Mapping):
            raise RuntimeError("H5_LEAVE_ONE_ROW_OBJECT_REQUIRED")
        pair = (
            str(item.get("dimension") or "").strip(),
            str(item.get("group") or "").strip(),
        )
        if pair in observed_pairs:
            raise RuntimeError(f"H5_DUPLICATE_LEAVE_ONE_PAIR:{pair}")
        observed_pairs.add(pair)
        net_r = finite(item.get("net_R"))
        normalized_leave_one.append(
            {"dimension": pair[0], "group": pair[1], "net_R": net_r}
        )
        if net_r <= finite(policy["minimum_leave_one_group_out_net_R"]):
            failed_leave_one.append(
                {"dimension": pair[0], "group": pair[1], "net_R": net_r}
            )
    missing_pairs = sorted(expected_pairs - observed_pairs)
    extra_pairs = sorted(observed_pairs - expected_pairs)
    if missing_pairs:
        blockers.append("LEAVE_ONE_GROUP_OUT_COVERAGE_MISSING")
    if extra_pairs:
        blockers.append("LEAVE_ONE_GROUP_OUT_UNKNOWN_PAIR")
    if failed_leave_one:
        blockers.append("LEAVE_ONE_GROUP_OUT_NON_POSITIVE")
    receipt = {
        "schema_version": "zel.economic_hardening.h5.receipt.v2",
        "control": "H5_CONCENTRATION_FRAGILITY_GATE",
        "state": "PASS_CONCENTRATION_FRAGILITY" if not blockers else "HOLD_CONCENTRATION_FRAGILITY",
        "threshold_seal_receipt_sha256": seal["receipt_sha256"],
        "threshold_policy_sha256": policy_sha256,
        "thresholds_sealed_at": sealed_at.isoformat(),
        "holdout_opened_at": holdout_at.isoformat(),
        "holdout_window_sha256": holdout_window_sha,
        "maximum_profit_share_by_dimension": max_shares,
        "top10_trade_profit_share": top10,
        "expected_leave_one_group_out_count": len(expected_pairs),
        "observed_leave_one_group_out_count": len(observed_pairs),
        "missing_leave_one_group_out_pairs": missing_pairs,
        "extra_leave_one_group_out_pairs": extra_pairs,
        "failed_leave_one_group_out": failed_leave_one,
        "blockers": sorted(set(blockers)),
        "dimensions": normalized_dimensions,
        "leave_one_group_out": normalized_leave_one,
        "control_engine_pass": True,
        **safety(),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def evaluate(input_data: Mapping[str, Any], policy: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    policy_sha = stable_sha(policy)
    controls = {
        "H1": h1_kill_gate(
            input_data["strategy_family"],
            policy["h1_strategy_family_kill_gate"],
            policy["survivor_gate"],
        ),
        "H2": h2_archetype_intake(
            input_data["archetype_candidate"],
            policy["h2_new_archetype_intake"],
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
            policy_sha256=policy_sha,
        ),
    }
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": now.isoformat(),
        "state": "PASS_H1_H5_CONTROL_ENGINE_EVALUATION",
        "control_count": len(controls),
        "controls": controls,
        "policy_sha256": policy_sha,
        "input_sha256": stable_sha(input_data),
        "installation_scope": "RESEARCH_CONTROL_PLANE_ONLY",
        "heavy_replay_started": False,
        **safety(),
    }
    if not all(control.get("control_engine_pass") is True for control in controls.values()):
        raise RuntimeError("CONTROL_ENGINE_EVALUATION_FAILED")
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def ensure_safe_output(artifact_root: Path, relative_out: Path) -> Path:
    if relative_out.is_absolute() or ".." in relative_out.parts:
        raise RuntimeError("OUTPUT_MUST_BE_RELATIVE_WITHOUT_PARENT_TRAVERSAL")
    root = artifact_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    cursor = root
    for part in relative_out.parent.parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise RuntimeError(f"OUTPUT_PARENT_SYMLINK_FORBIDDEN:{cursor}")
    output = (root / relative_out).resolve(strict=False)
    if os.path.commonpath([str(root), str(output)]) != str(root):
        raise RuntimeError("OUTPUT_OUTSIDE_ARTIFACT_ROOT")
    if output.exists() and output.is_symlink():
        raise RuntimeError("OUTPUT_SYMLINK_FORBIDDEN")
    lowered = output.as_posix().lower()
    if any(token in lowered for token in PROTECTED_TOKENS):
        raise RuntimeError("OUTPUT_PROTECTED_PATH_FORBIDDEN")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def self_test() -> int:
    gate = {
        "minimum_net_R": 0.0,
        "minimum_profit_factor": 1.0,
        "minimum_expectancy_R": 0.0,
        "minimum_payoff_ratio": 1.0,
        "minimum_retention_pct": 60.0,
    }
    assert survivor_window_pass(
        {
            "net_R": 1,
            "profit_factor": 1,
            "expectancy_R": 0.1,
            "payoff_ratio": 1,
            "retention_pct": 60,
        },
        gate,
    )
    assert not survivor_window_pass(
        {
            "net_R": 0,
            "profit_factor": 1,
            "expectancy_R": 0.1,
            "payoff_ratio": 1,
            "retention_pct": 60,
        },
        gate,
    )
    assert cosine_text("low turnover volatility breakout", "high turnover ema scalp") < 0.85
    assert cosine_text("low turnover volatility breakout", "low turnover volatility breakout") == 1.0
    assert sha_ok("a" * 64)
    try:
        positive_int(100.9, "trade_count")
    except RuntimeError:
        pass
    else:
        raise AssertionError("fractional trade count accepted")
    try:
        ensure_safe_output(Path("/tmp/zel-artifacts"), Path("../runtime/state.json"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("unsafe output accepted")
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--now")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.input or not args.policy or not args.artifact_root or not args.out:
        parser.error("--input, --policy, --artifact-root and --out are required")
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    result = evaluate(read_json(args.input), read_json(args.policy), now)
    output = ensure_safe_output(args.artifact_root, args.out)
    atomic_write_json(output, result)
    print(
        json.dumps(
            {
                "state": result["state"],
                "control_count": result["control_count"],
                "receipt_sha256": result["receipt_sha256"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
