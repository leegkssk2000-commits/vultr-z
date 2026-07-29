from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha

INPUT_SCHEMA = "strategy11.evidence_optimize_closed_loop.input.v1"
OUTPUT_SCHEMA = "strategy11.evidence_optimize_closed_loop.output.v1"

AXIS_ORDER = (
    "ENTRY_CONTEXT_GATE",
    "CANDLE_STRUCTURE_GATE",
    "TREND_REGIME_GATE",
    "VOLATILITY_GATE",
    "VOLUME_FLOW_GATE",
    "MOMENTUM_GATE",
    "SESSION_GATE",
    "SYMBOL_EXCLUSION",
    "STOP",
    "TARGET",
    "BREAKEVEN",
    "PARTIAL",
    "MFE_TRAILING",
    "TIME_STOP",
)

FINGERPRINT_AXIS = {
    "ENTRY_TOO_EARLY": ("ENTRY_CONTEXT_GATE", "CANDLE_STRUCTURE_GATE"),
    "ENTRY_TOO_LATE": ("ENTRY_CONTEXT_GATE", "MOMENTUM_GATE"),
    "REGIME_MISMATCH": ("TREND_REGIME_GATE",),
    "VOLATILITY_MISMATCH": ("VOLATILITY_GATE",),
    "VOLUME_FLOW_MISMATCH": ("VOLUME_FLOW_GATE",),
    "SESSION_CONCENTRATION": ("SESSION_GATE",),
    "SYMBOL_CONCENTRATION": ("SYMBOL_EXCLUSION",),
    "STOP_TOO_TIGHT": ("STOP",),
    "STOP_TOO_WIDE": ("STOP",),
    "BREAKEVEN_MISSED": ("BREAKEVEN",),
    "MFE_GIVEBACK": ("MFE_TRAILING", "BREAKEVEN", "PARTIAL"),
    "TARGET_UNDERSHOOT": ("TARGET", "PARTIAL"),
    "TIME_EXPOSURE": ("TIME_STOP",),
    "NO_SIGNAL": ("ENTRY_CONTEXT_GATE", "CANDLE_STRUCTURE_GATE"),
}

FORBIDDEN_CAPABILITIES = {
    "WRITE_STRATEGY",
    "WRITE_THRESHOLD",
    "WRITE_WEIGHT",
    "WRITE_LEDGER",
    "OPEN_ORDER",
    "CLOSE_ORDER",
    "AMEND_ORDER",
    "ENABLE_PAPER",
    "ENABLE_LIVE",
    "PROMOTE_CANDIDATE",
    "OVERRIDE_SBOT_VETO",
}

ALLOWED_OBSERVER_CAPABILITIES = {
    "READ_EVIDENCE",
    "EMIT_OBSERVATION",
    "EMIT_CALIBRATION",
    "REQUEST_HOLD",
}

RUNTIME_PASS_STATES = {
    "W1": "PASS",
    "W2": "PASS",
    "W3": "PASS",
    "NEW_SEALED": "PASS",
    "SHADOW300": "PASS_SHADOW300_READ_ONLY_COMPLETION",
    "OBSERVER_GATE": "PASS_OBSERVER_ONLY_GATE",
    "HUMAN_GOVERNANCE": "PASS_HUMAN_GOVERNANCE_PREFLIGHT",
}


class OptimizeClosedLoopError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise OptimizeClosedLoopError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("ARRAY_REQUIRED", name)
    return list(value)


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    return value.strip()


def _sha(value: Any, name: str) -> str:
    result = _string(value, name).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _number(value: Any, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    if minimum is not None and result < minimum:
        _fail("NUMBER_BELOW_MIN", name)
    return result


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INT_REQUIRED", name)
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _authority(value: Any, name: str = "authority") -> dict[str, Any]:
    authority = _mapping(value, name)
    for key, expected in SAFETY.items():
        if authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", f"{name}:{key}")
    if authority.get("runtime_bound") is not False:
        _fail("RUNTIME_BOUND_FORBIDDEN", name)
    if authority.get("advisory_enabled") is not False:
        _fail("ADVISORY_PREMATURE", name)
    return {**SAFETY, "runtime_bound": False, "advisory_enabled": False}


def _validate_policy(value: Any) -> dict[str, Any]:
    policy = _mapping(value, "policy")
    required = {
        "policy_id",
        "min_event_sample_count",
        "max_axis_generations_per_data_epoch",
        "required_observer_burnin_cycles",
        "unknown_taxonomy_rate_limit",
        "entry_early_first3_mae_r",
        "entry_late_pre_entry_mfe_r",
        "entry_late_remaining_mfe_r",
        "stop_tight_post_stop_mfe_r",
        "stop_wide_distance_r",
        "breakeven_activation_r",
        "mfe_giveback_activation_r",
        "target_undershoot_post_exit_mfe_r",
        "time_exposure_bars",
        "time_exposure_max_mfe_r",
        "fingerprint_min_count",
        "fingerprint_min_share",
        "fingerprint_priority",
        "candidate_catalog",
    }
    missing = sorted(required - set(policy))
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    priority = [_string(item, "policy.fingerprint_priority[]").upper() for item in _array(policy["fingerprint_priority"], "policy.fingerprint_priority")]
    if len(priority) != len(set(priority)):
        _fail("FINGERPRINT_PRIORITY_DUPLICATE")
    unknown = sorted(set(priority) - set(FINGERPRINT_AXIS))
    if unknown:
        _fail("FINGERPRINT_PRIORITY_UNKNOWN", ",".join(unknown))

    raw_catalog = _mapping(policy["candidate_catalog"], "policy.candidate_catalog")
    catalog: dict[str, list[dict[str, Any]]] = {}
    candidate_ids: set[str] = set()
    for fingerprint, rows in raw_catalog.items():
        key = _string(fingerprint, "policy.candidate_catalog.key").upper()
        if key not in FINGERPRINT_AXIS:
            _fail("CATALOG_FINGERPRINT_UNKNOWN", key)
        normalized_rows = []
        for index, row_value in enumerate(_array(rows, f"policy.candidate_catalog.{key}")):
            row = _mapping(row_value, f"policy.candidate_catalog.{key}[{index}]")
            expected = {"candidate_id", "axis", "parameters", "why"}
            if set(row) != expected:
                _fail("CATALOG_CANDIDATE_SHAPE", f"{key}:{index}")
            candidate_id = _string(row["candidate_id"], f"catalog.{key}.candidate_id")
            if candidate_id in candidate_ids:
                _fail("CATALOG_CANDIDATE_ID_DUPLICATE", candidate_id)
            candidate_ids.add(candidate_id)
            axis = _string(row["axis"], f"catalog.{key}.axis").upper()
            if axis not in AXIS_ORDER or axis not in FINGERPRINT_AXIS[key]:
                _fail("CATALOG_AXIS_INVALID", f"{key}:{axis}")
            parameters = _mapping(row["parameters"], f"catalog.{key}.parameters")
            if not parameters:
                _fail("CATALOG_PARAMETERS_EMPTY", candidate_id)
            normalized_rows.append({
                "candidate_id": candidate_id,
                "axis": axis,
                "parameters": copy.deepcopy(parameters),
                "why": _string(row["why"], f"catalog.{key}.why"),
            })
        catalog[key] = normalized_rows

    normalized = {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "min_event_sample_count": _integer(policy["min_event_sample_count"], "policy.min_event_sample_count", 1),
        "max_axis_generations_per_data_epoch": _integer(policy["max_axis_generations_per_data_epoch"], "policy.max_axis_generations_per_data_epoch", 1),
        "required_observer_burnin_cycles": _integer(policy["required_observer_burnin_cycles"], "policy.required_observer_burnin_cycles", 20),
        "unknown_taxonomy_rate_limit": _number(policy["unknown_taxonomy_rate_limit"], "policy.unknown_taxonomy_rate_limit", 0.0),
        "entry_early_first3_mae_r": _number(policy["entry_early_first3_mae_r"], "policy.entry_early_first3_mae_r", 0.0),
        "entry_late_pre_entry_mfe_r": _number(policy["entry_late_pre_entry_mfe_r"], "policy.entry_late_pre_entry_mfe_r", 0.0),
        "entry_late_remaining_mfe_r": _number(policy["entry_late_remaining_mfe_r"], "policy.entry_late_remaining_mfe_r", 0.0),
        "stop_tight_post_stop_mfe_r": _number(policy["stop_tight_post_stop_mfe_r"], "policy.stop_tight_post_stop_mfe_r", 0.0),
        "stop_wide_distance_r": _number(policy["stop_wide_distance_r"], "policy.stop_wide_distance_r", 0.0),
        "breakeven_activation_r": _number(policy["breakeven_activation_r"], "policy.breakeven_activation_r", 0.0),
        "mfe_giveback_activation_r": _number(policy["mfe_giveback_activation_r"], "policy.mfe_giveback_activation_r", 0.0),
        "target_undershoot_post_exit_mfe_r": _number(policy["target_undershoot_post_exit_mfe_r"], "policy.target_undershoot_post_exit_mfe_r", 0.0),
        "time_exposure_bars": _integer(policy["time_exposure_bars"], "policy.time_exposure_bars", 1),
        "time_exposure_max_mfe_r": _number(policy["time_exposure_max_mfe_r"], "policy.time_exposure_max_mfe_r", 0.0),
        "fingerprint_min_count": _integer(policy["fingerprint_min_count"], "policy.fingerprint_min_count", 1),
        "fingerprint_min_share": _number(policy["fingerprint_min_share"], "policy.fingerprint_min_share", 0.0),
        "fingerprint_priority": priority,
        "candidate_catalog": catalog,
    }
    if normalized["max_axis_generations_per_data_epoch"] > 2:
        _fail("AXIS_GENERATION_LIMIT_ABOVE_TWO")
    if normalized["required_observer_burnin_cycles"] < 100:
        _fail("OBSERVER_BURNIN_BELOW_100")
    if normalized["unknown_taxonomy_rate_limit"] > 0.25 or normalized["fingerprint_min_share"] > 1.0:
        _fail("POLICY_RATE_INVALID")
    normalized["policy_sha"] = canonical_sha(normalized)
    return normalized


def _validate_evidence(value: Any) -> dict[str, Any]:
    evidence = _mapping(value, "evidence")
    stage_states = _mapping(evidence.get("stage_states"), "evidence.stage_states")
    required_stages = {"DISCOVERY", *RUNTIME_PASS_STATES}
    if set(stage_states) != required_stages:
        _fail("STAGE_STATE_KEYS_MISMATCH")
    discovery = _string(stage_states["DISCOVERY"], "evidence.stage_states.DISCOVERY")
    if discovery not in {
        "PASS_F1_F2_F3_IMMUTABLE",
        "PASS_W1_NONOVERLAP",
        "PASS_W2_NONOVERLAP",
        "PASS_W3_NONOVERLAP",
    }:
        _fail("DISCOVERY_STATE_INVALID", discovery)
    normalized = {
        "source_sha": _sha(evidence.get("source_sha"), "evidence.source_sha"),
        "strategy_source_sha": _sha(evidence.get("strategy_source_sha"), "evidence.strategy_source_sha"),
        "data_sha": _sha(evidence.get("data_sha"), "evidence.data_sha"),
        "window_sha": _sha(evidence.get("window_sha"), "evidence.window_sha"),
        "manifest_sha": _sha(evidence.get("manifest_sha"), "evidence.manifest_sha"),
        "head_sha": _sha(evidence.get("head_sha"), "evidence.head_sha"),
        "observer_bundle_sha": _sha(evidence.get("observer_bundle_sha"), "evidence.observer_bundle_sha"),
        "shadow300_completion_sha": _sha(evidence.get("shadow300_completion_sha"), "evidence.shadow300_completion_sha"),
        "human_governance_decision_sha": _sha(evidence.get("human_governance_decision_sha"), "evidence.human_governance_decision_sha"),
        "stage_states": {key: _string(value, f"evidence.stage_states.{key}") for key, value in stage_states.items()},
        "observer_burnin_cycles": _integer(evidence.get("observer_burnin_cycles"), "evidence.observer_burnin_cycles", 0),
        "observer_source_parity_failures": _integer(evidence.get("observer_source_parity_failures"), "evidence.observer_source_parity_failures", 0),
        "observer_drift_breaches": _integer(evidence.get("observer_drift_breaches"), "evidence.observer_drift_breaches", 0),
        "observer_calibration_breaches": _integer(evidence.get("observer_calibration_breaches"), "evidence.observer_calibration_breaches", 0),
        "unknown_taxonomy_rate": _number(evidence.get("unknown_taxonomy_rate"), "evidence.unknown_taxonomy_rate", 0.0),
    }
    normalized["evidence_sha"] = canonical_sha(normalized)
    return normalized


def _validate_ledger(value: Any, evidence: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    ledger = _mapping(value, "search_ledger")
    required = {
        "strategy_id",
        "incumbent_candidate_sha",
        "tested_axes",
        "axis_generation_count",
        "parameter_bounds",
        "tested_combinations",
        "remaining_axes",
        "next_axis",
        "new_data_epoch",
        "W1_epoch",
        "sealed_epoch",
        "input_sha",
        "source_sha",
        "data_sha",
        "window_sha",
        "prompt_sha",
        "response_sha",
        "authority",
    }
    if set(ledger) != required:
        _fail("SEARCH_LEDGER_SHAPE")
    authority = _authority(ledger["authority"], "search_ledger.authority")
    tested_axes = [_string(item, "search_ledger.tested_axes[]").upper() for item in _array(ledger["tested_axes"], "search_ledger.tested_axes")]
    remaining_axes = [_string(item, "search_ledger.remaining_axes[]").upper() for item in _array(ledger["remaining_axes"], "search_ledger.remaining_axes")]
    if any(axis not in AXIS_ORDER for axis in tested_axes + remaining_axes):
        _fail("SEARCH_LEDGER_AXIS_UNKNOWN")
    generation_raw = _mapping(ledger["axis_generation_count"], "search_ledger.axis_generation_count")
    generation = {str(axis).upper(): _integer(count, f"axis_generation_count.{axis}", 0) for axis, count in generation_raw.items()}
    if any(axis not in AXIS_ORDER for axis in generation):
        _fail("SEARCH_LEDGER_GENERATION_AXIS_UNKNOWN")
    if any(count > policy["max_axis_generations_per_data_epoch"] for count in generation.values()):
        _fail("SEARCH_LEDGER_GENERATION_LIMIT_BREACH")
    combinations = []
    seen_combinations: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(_array(ledger["tested_combinations"], "search_ledger.tested_combinations")):
        row = _mapping(raw, f"search_ledger.tested_combinations[{index}]")
        if set(row) != {"axis", "data_sha", "candidate_id", "candidate_sha"}:
            _fail("TESTED_COMBINATION_SHAPE", str(index))
        axis = _string(row["axis"], f"tested_combinations[{index}].axis").upper()
        data_sha = _sha(row["data_sha"], f"tested_combinations[{index}].data_sha")
        candidate_id = _string(row["candidate_id"], f"tested_combinations[{index}].candidate_id")
        candidate_sha = _sha(row["candidate_sha"], f"tested_combinations[{index}].candidate_sha")
        key = (axis, data_sha, candidate_id)
        if key in seen_combinations:
            _fail("TESTED_COMBINATION_DUPLICATE", f"{axis}:{candidate_id}")
        seen_combinations.add(key)
        combinations.append({"axis": axis, "data_sha": data_sha, "candidate_id": candidate_id, "candidate_sha": candidate_sha})
    source_sha = _sha(ledger["source_sha"], "search_ledger.source_sha")
    data_sha = _sha(ledger["data_sha"], "search_ledger.data_sha")
    window_sha = _sha(ledger["window_sha"], "search_ledger.window_sha")
    if source_sha != evidence["source_sha"] or data_sha != evidence["data_sha"] or window_sha != evidence["window_sha"]:
        _fail("SEARCH_LEDGER_EVIDENCE_SHA_MISMATCH")
    normalized = {
        "strategy_id": _string(ledger["strategy_id"], "search_ledger.strategy_id"),
        "incumbent_candidate_sha": _sha(ledger["incumbent_candidate_sha"], "search_ledger.incumbent_candidate_sha"),
        "tested_axes": tested_axes,
        "axis_generation_count": generation,
        "parameter_bounds": copy.deepcopy(_mapping(ledger["parameter_bounds"], "search_ledger.parameter_bounds")),
        "tested_combinations": combinations,
        "remaining_axes": remaining_axes,
        "next_axis": _string(ledger["next_axis"], "search_ledger.next_axis").upper(),
        "new_data_epoch": _integer(ledger["new_data_epoch"], "search_ledger.new_data_epoch", 0),
        "W1_epoch": _integer(ledger["W1_epoch"], "search_ledger.W1_epoch", 0),
        "sealed_epoch": _integer(ledger["sealed_epoch"], "search_ledger.sealed_epoch", 0),
        "input_sha": _sha(ledger["input_sha"], "search_ledger.input_sha"),
        "source_sha": source_sha,
        "data_sha": data_sha,
        "window_sha": window_sha,
        "prompt_sha": _sha(ledger["prompt_sha"], "search_ledger.prompt_sha"),
        "response_sha": _sha(ledger["response_sha"], "search_ledger.response_sha"),
        "authority": authority,
    }
    if normalized["next_axis"] not in AXIS_ORDER:
        _fail("SEARCH_LEDGER_NEXT_AXIS_UNKNOWN")
    normalized["ledger_sha"] = canonical_sha(normalized)
    return normalized


def _validate_observer(value: Any, observer_type: str) -> dict[str, Any]:
    observer = _mapping(value, f"observers.{observer_type}")
    required = {
        "state",
        "observer_type",
        "source_sha",
        "model_sha",
        "config_sha",
        "training_data_sha",
        "feature_lineage_sha",
        "observer_manifest_sha",
        "capabilities",
        "authority",
        "payload",
    }
    if set(observer) != required:
        _fail("OBSERVER_SHAPE", observer_type)
    actual_type = _string(observer["observer_type"], f"observers.{observer_type}.observer_type").upper()
    if actual_type != observer_type:
        _fail("OBSERVER_TYPE_MISMATCH", f"{observer_type}:{actual_type}")
    state = _string(observer["state"], f"observers.{observer_type}.state")
    expected_state = "PASS_ML_LIGHT_OBSERVATION" if observer_type == "ML_LIGHT" else "PASS_FAILURE_LEARNING_OBSERVATION"
    if state != expected_state:
        _fail("OBSERVER_NOT_PASS", f"{observer_type}:{state}")
    authority = _authority(observer["authority"], f"observers.{observer_type}.authority")
    capabilities = sorted({_string(item, "observer.capabilities[]").upper() for item in _array(observer["capabilities"], "observer.capabilities")})
    forbidden = sorted(set(capabilities) & FORBIDDEN_CAPABILITIES)
    if forbidden or set(capabilities) - ALLOWED_OBSERVER_CAPABILITIES:
        _fail("OBSERVER_CAPABILITY_INVALID", f"{observer_type}:{','.join(forbidden)}")
    normalized = {
        "state": state,
        "observer_type": actual_type,
        "source_sha": _sha(observer["source_sha"], f"observers.{observer_type}.source_sha"),
        "model_sha": _sha(observer["model_sha"], f"observers.{observer_type}.model_sha"),
        "config_sha": _sha(observer["config_sha"], f"observers.{observer_type}.config_sha"),
        "training_data_sha": _sha(observer["training_data_sha"], f"observers.{observer_type}.training_data_sha"),
        "feature_lineage_sha": _sha(observer["feature_lineage_sha"], f"observers.{observer_type}.feature_lineage_sha"),
        "observer_manifest_sha": _sha(observer["observer_manifest_sha"], f"observers.{observer_type}.observer_manifest_sha"),
        "capabilities": capabilities,
        "authority": authority,
        "payload": copy.deepcopy(_mapping(observer["payload"], f"observers.{observer_type}.payload")),
    }
    return normalized


def _validate_events(value: Any, strategy_id: str, source_sha: str, min_samples: int) -> list[dict[str, Any]]:
    raw_events = _array(value, "events")
    if len(raw_events) < min_samples:
        _fail("EVENT_SAMPLE_COUNT_LOW", str(len(raw_events)))
    required = {
        "event_id",
        "event_ts",
        "strategy_id",
        "symbol",
        "regime",
        "window_id",
        "side",
        "pnl_r",
        "mfe_r",
        "mae_r",
        "pre_entry_mfe_r",
        "first3_mfe_r",
        "first3_mae_r",
        "stop_distance_r",
        "post_stop_mfe_r",
        "post_exit_mfe_r",
        "bars_to_mfe_peak",
        "bars_held",
        "exit_reason",
        "source_sha",
        "feature_lineage_sha",
    }
    normalized = []
    event_ids: set[str] = set()
    for index, raw in enumerate(raw_events):
        row = _mapping(raw, f"events[{index}]")
        if set(row) != required:
            _fail("EVENT_SHAPE", str(index))
        event_id = _string(row["event_id"], f"events[{index}].event_id")
        if event_id in event_ids:
            _fail("DUPLICATE_EVENT_ID", event_id)
        event_ids.add(event_id)
        row_strategy = _string(row["strategy_id"], f"events[{index}].strategy_id")
        if row_strategy != strategy_id:
            _fail("EVENT_STRATEGY_MISMATCH", event_id)
        row_source_sha = _sha(row["source_sha"], f"events[{index}].source_sha")
        if row_source_sha != source_sha:
            _fail("EVENT_SOURCE_SHA_MISMATCH", event_id)
        normalized.append({
            "event_id": event_id,
            "event_ts": _string(row["event_ts"], f"events[{index}].event_ts"),
            "strategy_id": row_strategy,
            "symbol": _string(row["symbol"], f"events[{index}].symbol").upper(),
            "regime": _string(row["regime"], f"events[{index}].regime").upper(),
            "window_id": _string(row["window_id"], f"events[{index}].window_id").upper(),
            "side": _string(row["side"], f"events[{index}].side").upper(),
            "pnl_r": _number(row["pnl_r"], f"events[{index}].pnl_r"),
            "mfe_r": _number(row["mfe_r"], f"events[{index}].mfe_r", 0.0),
            "mae_r": _number(row["mae_r"], f"events[{index}].mae_r", 0.0),
            "pre_entry_mfe_r": _number(row["pre_entry_mfe_r"], f"events[{index}].pre_entry_mfe_r", 0.0),
            "first3_mfe_r": _number(row["first3_mfe_r"], f"events[{index}].first3_mfe_r", 0.0),
            "first3_mae_r": _number(row["first3_mae_r"], f"events[{index}].first3_mae_r", 0.0),
            "stop_distance_r": _number(row["stop_distance_r"], f"events[{index}].stop_distance_r", 0.0),
            "post_stop_mfe_r": _number(row["post_stop_mfe_r"], f"events[{index}].post_stop_mfe_r", 0.0),
            "post_exit_mfe_r": _number(row["post_exit_mfe_r"], f"events[{index}].post_exit_mfe_r", 0.0),
            "bars_to_mfe_peak": _integer(row["bars_to_mfe_peak"], f"events[{index}].bars_to_mfe_peak", 0),
            "bars_held": _integer(row["bars_held"], f"events[{index}].bars_held", 0),
            "exit_reason": _string(row["exit_reason"], f"events[{index}].exit_reason").upper(),
            "source_sha": row_source_sha,
            "feature_lineage_sha": _sha(row["feature_lineage_sha"], f"events[{index}].feature_lineage_sha"),
        })
    return normalized


def _observer_failure_categories(observer: Mapping[str, Any]) -> Counter[str]:
    payload = observer["payload"]
    hypotheses = payload.get("hypotheses", [])
    if not isinstance(hypotheses, list):
        _fail("FAILURE_HYPOTHESES_ARRAY_REQUIRED")
    counts: Counter[str] = Counter()
    for index, raw in enumerate(hypotheses):
        row = _mapping(raw, f"failure_learning.hypotheses[{index}]")
        category = _string(row.get("category"), f"failure_learning.hypotheses[{index}].category").upper()
        sample_count = _integer(row.get("sample_count"), f"failure_learning.hypotheses[{index}].sample_count", 0)
        counts[category] += sample_count
    return counts


def _fingerprints(events: Sequence[Mapping[str, Any]], failure_categories: Counter[str], policy: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    matched: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    symbols: Counter[str] = Counter(row["symbol"] for row in events if row["pnl_r"] < 0.0)
    regimes: Counter[str] = Counter(row["regime"] for row in events if row["pnl_r"] < 0.0)
    windows: Counter[str] = Counter(row["window_id"] for row in events if row["pnl_r"] < 0.0)

    for row in events:
        if row["pnl_r"] < 0.0 and row["first3_mae_r"] >= policy["entry_early_first3_mae_r"]:
            matched["ENTRY_TOO_EARLY"].append(row)
        if (
            row["pre_entry_mfe_r"] >= policy["entry_late_pre_entry_mfe_r"]
            and max(0.0, row["mfe_r"] - row["pre_entry_mfe_r"]) <= policy["entry_late_remaining_mfe_r"]
        ):
            matched["ENTRY_TOO_LATE"].append(row)
        if row["exit_reason"] == "STOP" and row["post_stop_mfe_r"] >= policy["stop_tight_post_stop_mfe_r"]:
            matched["STOP_TOO_TIGHT"].append(row)
        if row["pnl_r"] < 0.0 and row["stop_distance_r"] >= policy["stop_wide_distance_r"]:
            matched["STOP_TOO_WIDE"].append(row)
        if row["pnl_r"] < 0.0 and row["mfe_r"] >= policy["breakeven_activation_r"]:
            matched["BREAKEVEN_MISSED"].append(row)
        if row["pnl_r"] <= 0.0 and row["mfe_r"] >= policy["mfe_giveback_activation_r"]:
            matched["MFE_GIVEBACK"].append(row)
        if row["exit_reason"] in {"TARGET", "PARTIAL"} and row["post_exit_mfe_r"] >= policy["target_undershoot_post_exit_mfe_r"]:
            matched["TARGET_UNDERSHOOT"].append(row)
        if (
            row["pnl_r"] <= 0.0
            and row["bars_held"] >= policy["time_exposure_bars"]
            and row["mfe_r"] <= policy["time_exposure_max_mfe_r"]
        ):
            matched["TIME_EXPOSURE"].append(row)

    total = len(events)
    loss_count = max(1, sum(row["pnl_r"] < 0.0 for row in events))
    if symbols and symbols.most_common(1)[0][1] / loss_count >= policy["fingerprint_min_share"]:
        dominant = symbols.most_common(1)[0][0]
        matched["SYMBOL_CONCENTRATION"].extend(row for row in events if row["pnl_r"] < 0.0 and row["symbol"] == dominant)
    if windows and windows.most_common(1)[0][1] / loss_count >= policy["fingerprint_min_share"]:
        dominant = windows.most_common(1)[0][0]
        matched["SESSION_CONCENTRATION"].extend(row for row in events if row["pnl_r"] < 0.0 and row["window_id"] == dominant)
    if failure_categories.get("REGIME_MISMATCH", 0) >= policy["fingerprint_min_count"]:
        matched["REGIME_MISMATCH"].extend(row for row in events if row["pnl_r"] < 0.0)
    if failure_categories.get("ENTRY_ABSENCE", 0) >= policy["fingerprint_min_count"]:
        matched["NO_SIGNAL"].extend(row for row in events[: failure_categories["ENTRY_ABSENCE"]])
    if failure_categories.get("EXECUTION_ECONOMICS", 0) >= policy["fingerprint_min_count"]:
        matched["VOLATILITY_MISMATCH"].extend(row for row in events if row["pnl_r"] < 0.0)

    result: dict[str, dict[str, Any]] = {}
    for fingerprint, rows in matched.items():
        unique = {row["event_id"]: row for row in rows}
        selected = list(unique.values())
        count = len(selected)
        share = count / total
        if count < policy["fingerprint_min_count"] or share < policy["fingerprint_min_share"]:
            continue
        loss_r = sum(abs(min(0.0, row["pnl_r"])) for row in selected)
        result[fingerprint] = {
            "fingerprint": fingerprint,
            "event_count": count,
            "event_share": share,
            "loss_r_abs": loss_r,
            "mean_mfe_r": sum(row["mfe_r"] for row in selected) / count,
            "mean_mae_r": sum(row["mae_r"] for row in selected) / count,
            "event_ids": sorted(row["event_id"] for row in selected),
            "support_sha": canonical_sha(sorted(row["event_id"] for row in selected)),
        }
    return result


def _select_fingerprint(rows: Mapping[str, Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any] | None:
    priority_index = {fingerprint: index for index, fingerprint in enumerate(policy["fingerprint_priority"])}
    candidates = list(rows.values())
    if not candidates:
        return None
    candidates.sort(key=lambda row: (
        priority_index.get(row["fingerprint"], len(priority_index)),
        -row["loss_r_abs"],
        -row["event_count"],
        row["fingerprint"],
    ))
    return copy.deepcopy(candidates[0])


def _select_candidate(fingerprint: Mapping[str, Any], ledger: Mapping[str, Any], evidence: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any] | None:
    tested = {(row["axis"], row["data_sha"], row["candidate_id"]) for row in ledger["tested_combinations"]}
    generation = ledger["axis_generation_count"]
    for row in policy["candidate_catalog"].get(fingerprint["fingerprint"], []):
        axis = row["axis"]
        key = (axis, evidence["data_sha"], row["candidate_id"])
        if key in tested:
            continue
        if generation.get(axis, 0) >= policy["max_axis_generations_per_data_epoch"]:
            continue
        if axis not in ledger["remaining_axes"] and axis != ledger["next_axis"]:
            continue
        proposal = {
            "strategy_id": ledger["strategy_id"],
            "incumbent_candidate_sha": ledger["incumbent_candidate_sha"],
            "candidate_id": row["candidate_id"],
            "axis": axis,
            "parameters": copy.deepcopy(row["parameters"]),
            "why": row["why"],
            "failure_fingerprint": fingerprint["fingerprint"],
            "failure_support_sha": fingerprint["support_sha"],
            "source_sha": evidence["source_sha"],
            "strategy_source_sha": evidence["strategy_source_sha"],
            "data_sha": evidence["data_sha"],
            "window_sha": evidence["window_sha"],
            "manifest_sha": evidence["manifest_sha"],
            "single_axis": True,
            "generation": generation.get(axis, 0) + 1,
            "control_required": True,
            "independent_ab_required": True,
            "duplicate_zero_required": True,
            "observed_2x_cost_p95_funding_plus_one_required": True,
            "pareto_and_hard_gates_required": True,
            "replay_required": True,
            "ai_router_plan_required": True,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        }
        proposal["candidate_sha"] = canonical_sha(proposal)
        return proposal
    return None


def _runtime_readiness(evidence: Mapping[str, Any], observers: Mapping[str, Mapping[str, Any]], policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    blockers = []
    for stage, expected in RUNTIME_PASS_STATES.items():
        if evidence["stage_states"].get(stage) != expected:
            blockers.append(f"{stage}_NOT_PASS")
    if evidence["observer_burnin_cycles"] < policy["required_observer_burnin_cycles"]:
        blockers.append("OBSERVER_BURNIN_INCOMPLETE")
    if evidence["observer_source_parity_failures"] != 0:
        blockers.append("OBSERVER_SOURCE_PARITY_FAILURE")
    if evidence["observer_drift_breaches"] != 0:
        blockers.append("OBSERVER_DRIFT_BREACH")
    if evidence["observer_calibration_breaches"] != 0:
        blockers.append("OBSERVER_CALIBRATION_BREACH")
    if evidence["unknown_taxonomy_rate"] > policy["unknown_taxonomy_rate_limit"]:
        blockers.append("UNKNOWN_TAXONOMY_RATE_BREACH")
    if {row["observer_type"] for row in observers.values()} != {"ML_LIGHT", "FAILURE_LEARNING"}:
        blockers.append("OBSERVER_TYPES_INCOMPLETE")
    return not blockers, sorted(set(blockers))


def evaluate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "input")
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    authority = _authority(payload.get("authority"))
    policy = _validate_policy(payload.get("policy"))
    evidence = _validate_evidence(payload.get("evidence"))
    ledger = _validate_ledger(payload.get("search_ledger"), evidence, policy)
    observer_raw = _mapping(payload.get("observers"), "observers")
    if set(observer_raw) != {"ML_LIGHT", "FAILURE_LEARNING"}:
        _fail("OBSERVER_KEYS_MISMATCH")
    observers = {
        "ML_LIGHT": _validate_observer(observer_raw["ML_LIGHT"], "ML_LIGHT"),
        "FAILURE_LEARNING": _validate_observer(observer_raw["FAILURE_LEARNING"], "FAILURE_LEARNING"),
    }
    if any(row["source_sha"] != evidence["source_sha"] for row in observers.values()):
        _fail("OBSERVER_SOURCE_SHA_MISMATCH")
    events = _validate_events(payload.get("events"), ledger["strategy_id"], evidence["source_sha"], policy["min_event_sample_count"])
    failure_categories = _observer_failure_categories(observers["FAILURE_LEARNING"])
    fingerprints = _fingerprints(events, failure_categories, policy)
    selected_fingerprint = _select_fingerprint(fingerprints, policy)
    proposal = _select_candidate(selected_fingerprint, ledger, evidence, policy) if selected_fingerprint else None
    runtime_ready, runtime_blockers = _runtime_readiness(evidence, observers, policy)

    if proposal is None:
        state = "WAIT_NEW_EVIDENCE"
        research_route_action = "hold"
    elif runtime_ready:
        state = "PASS_READ_ONLY_RUNTIME_OBSERVER_BRIDGE_READY"
        research_route_action = "route_change"
    else:
        state = "PASS_RESEARCH_OPTIMIZE_CLOSED_LOOP_PLAN"
        research_route_action = "route_change"

    runtime_bridge = {
        "state": "READY_READ_ONLY_OBSERVER_BRIDGE" if runtime_ready else "WAIT_REAL_SHADOW300_AND_100C_BURNIN",
        "allowed_inputs": [
            "SOURCE_BOUND_MARKET_FEATURES",
            "SOURCE_BOUND_STRATEGY_DECISION_TRACE",
            "SOURCE_BOUND_TRADE_OUTCOME",
            "STATE_LEDGER_PNL_PARITY",
        ],
        "allowed_outputs": ["OBSERVATION", "CALIBRATION", "HOLD_REQUEST"],
        "forbidden_outputs": sorted(FORBIDDEN_CAPABILITIES),
        "runtime_observer_bridge_allowed": runtime_ready,
        "runtime_bound": False,
        "strategy_write_allowed": False,
        "threshold_write_allowed": False,
        "portfolio_weight_write_allowed": False,
        "ledger_write_allowed": False,
        "paper_live_order_allowed": False,
        "external_manual_enable_required": True,
        "blocker_codes": runtime_blockers,
    }
    runtime_bridge["bridge_sha"] = canonical_sha(runtime_bridge)

    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "strategy_id": ledger["strategy_id"],
        "source_binding": {
            "source_sha": evidence["source_sha"],
            "strategy_source_sha": evidence["strategy_source_sha"],
            "data_sha": evidence["data_sha"],
            "window_sha": evidence["window_sha"],
            "manifest_sha": evidence["manifest_sha"],
            "head_sha": evidence["head_sha"],
            "evidence_sha": evidence["evidence_sha"],
            "search_ledger_sha": ledger["ledger_sha"],
            "observer_bundle_sha": evidence["observer_bundle_sha"],
        },
        "failure_category_counts": dict(sorted(failure_categories.items())),
        "fingerprints": [copy.deepcopy(fingerprints[key]) for key in sorted(fingerprints)],
        "selected_fingerprint": selected_fingerprint,
        "next_candidate_proposal": proposal,
        "candidate_count": 1 if proposal else 0,
        "single_axis_only": True,
        "same_strategy_axis_data_duplicate_forbidden": True,
        "max_two_generations_per_axis_data_epoch": policy["max_axis_generations_per_data_epoch"],
        "runtime_bridge": runtime_bridge,
        "research_route_action": research_route_action,
        "requested_action": "hold",
        "automatic_replay_start_allowed": False,
        "replay_requires_existing_orchestrator": proposal is not None,
        "ai_router_execute_required_before_replay": proposal is not None,
        "incumbent_retained": True,
        "rollback_target": ledger["incumbent_candidate_sha"],
        "production_threshold_authority": False,
        "paper_30d_allowed": False,
        "live_activation_allowed": False,
        "order_submission_allowed": False,
        "runtime_bound": False,
        "advisory_enabled": False,
        "policy": policy,
        **authority,
    }
    result["closed_loop_sha"] = canonical_sha(result)
    return result
