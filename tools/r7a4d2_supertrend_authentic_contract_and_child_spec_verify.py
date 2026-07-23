#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

SPEC_PATH = "research/supertrend_flip_authentic_contract_and_child_spec_v1.json"
DECISION_PATH = "research/canonical25_wave1_authenticity_decision_v1.json"
AUDIT_PATH = "research/canonical25_source_to_code_wave1_v1.json"
PARENT_PATH = "backend/strategies/supertrend_pullback.py"
REPAIR_RUNTIME = Path(
    "runtime/r7a4d2_canonical25_wave1_authenticity_decision_gate_repair/"
    "canonical25_wave1_authenticity_decision_gate_repair_v1.json"
)
OUTPUT_DIR = Path("runtime/r7a4d2_supertrend_authentic_contract_and_child_spec")
OUTPUT_JSON = OUTPUT_DIR / "supertrend_authentic_contract_and_child_spec_verification_v1.json"

EXPECTED_INTENTS = {
    "HOLD",
    "ENTER_LONG",
    "ENTER_SHORT",
    "EXIT_LONG",
    "EXIT_SHORT",
    "REVERSE_TO_LONG",
    "REVERSE_TO_SHORT",
}
EXPECTED_FIXTURES = {
    "ATR_WARMUP_AND_RMA_SEED",
    "MONOTONIC_UPTREND",
    "MONOTONIC_DOWNTREND",
    "SINGLE_UP_FLIP",
    "SINGLE_DOWN_FLIP",
    "WHIPSAW_MULTI_FLIP",
    "GAP_ACROSS_BAND",
    "EQUAL_BAND_BOUNDARY",
    "MISSING_OR_NONFINITE_INPUT_FAIL_CLOSED",
}
EXPECTED_TRANSITION_INTENTS = {
    "HOLD",
    "ENTER_LONG",
    "ENTER_SHORT",
    "REVERSE_TO_LONG",
    "REVERSE_TO_SHORT",
}
EXPECTED_PARENT_HASH = "b5398dfce04260422f04a758736d210763dc8c6097eeca953af82a56eb80fe25"


def git_show(root: Path, sha: str, path: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{sha}:{path}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"GIT_SHOW_FAILED:{path}:"
            + proc.stderr.decode("utf-8", errors="replace").strip()
        )
    return proc.stdout


def git_json(root: Path, sha: str, path: str) -> dict[str, Any]:
    value = json.loads(git_show(root, sha, path).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def local_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def exact_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(paths: Iterable[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if item is not None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    blockers: list[str] = []

    try:
        spec = git_json(root, args.target_sha, SPEC_PATH)
        decision = git_json(root, args.target_sha, DECISION_PATH)
        audit = git_json(root, args.target_sha, AUDIT_PATH)
        parent_bytes = git_show(root, args.target_sha, PARENT_PATH)
    except Exception as exc:
        print("STATE=HOLD_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC_INPUT")
        print("BLOCKERS=" + json.dumps([f"GIT_OBJECT_INPUT_ERROR:{type(exc).__name__}:{exc}"]))
        print("RC=2")
        return 2

    repair_path = root / REPAIR_RUNTIME
    if not repair_path.is_file():
        print("STATE=HOLD_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC_INPUT")
        print("BLOCKERS=" + json.dumps([f"REPAIR_RUNTIME_MISSING:{repair_path}"]))
        print("RC=2")
        return 2

    try:
        repair = local_json(repair_path)
    except Exception as exc:
        print("STATE=HOLD_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC_INPUT")
        print("BLOCKERS=" + json.dumps([f"REPAIR_RUNTIME_INVALID:{type(exc).__name__}"]))
        print("RC=2")
        return 2

    protected_paths = [
        root / PARENT_PATH,
        root / "backend/strategy25/canonical_strategy_registry_v1.json",
        root / "backend/strategy25/canonical_strategy25_config_v1.json",
        repair_path,
    ]
    before = snapshot(protected_paths)

    if repair.get("state") != "PASS_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR":
        blockers.append("PRIOR_REPAIR_STATE_NOT_PASS")
    if exact_int(repair, "blocker_count") != 0:
        blockers.append("PRIOR_REPAIR_BLOCKERS_NONZERO")
    if repair.get("selected_first_child") != "supertrend_flip_authentic":
        blockers.append("PRIOR_REPAIR_SELECTED_CHILD_INVALID")
    if repair.get("next_stage") != "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC":
        blockers.append("PRIOR_REPAIR_NEXT_STAGE_INVALID")
    if repair.get("legacy_parent_immutable") is not True:
        blockers.append("PRIOR_REPAIR_PARENT_NOT_IMMUTABLE")

    if decision.get("selected_first_child") != "supertrend_flip_authentic":
        blockers.append("DECISION_SELECTED_CHILD_INVALID")
    if decision.get("selected_first_stage") != "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC":
        blockers.append("DECISION_SELECTED_STAGE_INVALID")

    audit_rows = audit.get("strategies") if isinstance(audit.get("strategies"), list) else []
    supertrend_audit = next(
        (
            row
            for row in audit_rows
            if isinstance(row, dict) and row.get("strategy_id") == "supertrend_pullback"
        ),
        None,
    )
    if not isinstance(supertrend_audit, dict):
        blockers.append("SUPERTREND_SOURCE_AUDIT_MISSING")
        supertrend_audit = {}
    if supertrend_audit.get("current_source_sha256") != EXPECTED_PARENT_HASH:
        blockers.append("SOURCE_AUDIT_PARENT_HASH_INVALID")
    if (
        supertrend_audit.get("authenticity_class")
        != "AUTHENTIC_INDICATOR_FORMULA_SYNTHETIC_PULLBACK_STRATEGY"
    ):
        blockers.append("SOURCE_AUDIT_CLASS_INVALID")

    parent_hash = sha256_bytes(parent_bytes)
    parent_text = parent_bytes.decode("utf-8", errors="replace")
    if parent_hash != EXPECTED_PARENT_HASH:
        blockers.append("PARENT_GIT_OBJECT_HASH_INVALID")
    required_legacy_evidence = {
        "simple_rolling_atr": ".rolling(length, min_periods=length).mean()",
        "ema_filter": "trend_ma",
        "pullback_logic": "pullback_level_long",
        "fixed_rr": "base_rr",
        "beam_logic": "beam_rr",
        "scale_in": "scale_in",
        "dip_add": "dip_add",
        "short_suppression": "short_signal_generated_but_core_is_long_only",
    }
    evidence = {
        key: marker in parent_text for key, marker in required_legacy_evidence.items()
    }
    for key, present in evidence.items():
        if not present:
            blockers.append(f"LEGACY_DEVIATION_EVIDENCE_MISSING:{key}")

    if spec.get("schema") != "r7a4d2_supertrend_flip_authentic_contract_and_child_spec_v1":
        blockers.append("SPEC_SCHEMA_INVALID")
    if spec.get("official_stage") != "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC":
        blockers.append("SPEC_STAGE_INVALID")
    if spec.get("status") != "DESIGN_ONLY_FAIL_CLOSED":
        blockers.append("SPEC_STATUS_INVALID")

    source_authority = spec.get("source_authority") if isinstance(spec.get("source_authority"), dict) else {}
    if (source_authority.get("primary_formula") or {}).get("url") != "https://www.tradingview.com/support/solutions/43000634738-supertrend/":
        blockers.append("PRIMARY_FORMULA_SOURCE_INVALID")
    if (source_authority.get("primary_strategy") or {}).get("url") != "https://www.tradingview.com/support/solutions/43000645068-supertrend-strategy/":
        blockers.append("PRIMARY_STRATEGY_SOURCE_INVALID")
    if (source_authority.get("atr_reference") or {}).get("url") != "https://www.tradingview.com/support/solutions/43000734653-how-are-adr-and-atr-calculated/":
        blockers.append("ATR_REFERENCE_SOURCE_INVALID")
    if source_authority.get("community_sources_performance_authority") is not False:
        blockers.append("COMMUNITY_PERFORMANCE_AUTHORITY_NOT_FALSE")

    parent = spec.get("legacy_parent") if isinstance(spec.get("legacy_parent"), dict) else {}
    child = spec.get("authentic_child") if isinstance(spec.get("authentic_child"), dict) else {}
    if parent.get("strategy_id") != "supertrend_pullback":
        blockers.append("SPEC_PARENT_ID_INVALID")
    if parent.get("source_sha256") != EXPECTED_PARENT_HASH:
        blockers.append("SPEC_PARENT_HASH_INVALID")
    if parent.get("preservation") != "IMMUTABLE_EVIDENCE_PARENT":
        blockers.append("SPEC_PARENT_PRESERVATION_INVALID")
    if child.get("strategy_id") != "supertrend_flip_authentic":
        blockers.append("SPEC_CHILD_ID_INVALID")
    if child.get("implementation_allowed_in_this_stage") is not False:
        blockers.append("CHILD_IMPLEMENTATION_PREMATURELY_ALLOWED")

    formula = spec.get("formula_contract") if isinstance(spec.get("formula_contract"), dict) else {}
    parameters = formula.get("parameters") if isinstance(formula.get("parameters"), dict) else {}
    atr = formula.get("atr") if isinstance(formula.get("atr"), dict) else {}
    direction = formula.get("direction") if isinstance(formula.get("direction"), dict) else {}
    if exact_int(parameters, "atr_length") != 10:
        blockers.append("ATR_LENGTH_INVALID")
    try:
        factor = float(parameters.get("factor"))
    except (TypeError, ValueError):
        factor = float("nan")
    if factor != 3.0:
        blockers.append("SUPERTREND_FACTOR_INVALID")
    if parameters.get("parameter_optimization_allowed") is not False:
        blockers.append("PARAMETER_OPTIMIZATION_NOT_FALSE")
    if parameters.get("threshold_relaxation_allowed") is not False:
        blockers.append("THRESHOLD_RELAXATION_NOT_FALSE")
    if atr.get("method") != "WILDER_RMA":
        blockers.append("ATR_METHOD_NOT_WILDER_RMA")
    if atr.get("legacy_simple_rolling_mean_allowed") is not False:
        blockers.append("LEGACY_SMA_ATR_NOT_FORBIDDEN")
    if direction.get("decision_time") != "CONFIRMED_BAR_CLOSE_ONLY":
        blockers.append("DIRECTION_DECISION_TIME_INVALID")
    if direction.get("warmup_direction") != "DOWN":
        blockers.append("WARMUP_DIRECTION_INVALID")

    intent = spec.get("bidirectional_intent_contract") if isinstance(spec.get("bidirectional_intent_contract"), dict) else {}
    if string_set(intent.get("allowed_intents")) != EXPECTED_INTENTS:
        blockers.append("BIDIRECTIONAL_INTENT_SET_INVALID")
    if intent.get("silent_remap_allowed") is not False:
        blockers.append("SILENT_INTENT_REMAP_NOT_FALSE")
    reversal = intent.get("reversal_accounting") if isinstance(intent.get("reversal_accounting"), dict) else {}
    if reversal.get("ledger_semantics") != "TWO_LEGS_EXIT_THEN_ENTRY_WITH_SAME_SIGNAL_TS":
        blockers.append("REVERSAL_LEDGER_SEMANTICS_INVALID")

    state_contract = spec.get("strategy_state_contract") if isinstance(spec.get("strategy_state_contract"), dict) else {}
    transitions = state_contract.get("transition_table") if isinstance(state_contract.get("transition_table"), list) else []
    transition_intents = {
        str(row.get("intent")) for row in transitions if isinstance(row, dict) and row.get("intent")
    }
    if transition_intents != EXPECTED_TRANSITION_INTENTS:
        blockers.append("STATE_TRANSITION_INTENTS_INVALID")
    if len(transitions) != 6:
        blockers.append("STATE_TRANSITION_COUNT_INVALID")
    initialization_rows = [
        row for row in transitions
        if isinstance(row, dict) and row.get("from") == "WARMUP"
    ]
    if len(initialization_rows) != 1 or initialization_rows[0].get("intent") != "HOLD":
        blockers.append("INITIAL_DIRECTION_ENTRY_BIAS_NOT_BLOCKED")

    native_exit = spec.get("native_exit_contract") if isinstance(spec.get("native_exit_contract"), dict) else {}
    if native_exit.get("native_exit") != "OPPOSITE_CONFIRMED_SUPERTREND_DIRECTION_FLIP":
        blockers.append("NATIVE_EXIT_INVALID")
    if native_exit.get("fixed_target_allowed") is not False:
        blockers.append("FIXED_TARGET_NOT_FALSE")
    if native_exit.get("intrabar_stop_order_allowed") is not False:
        blockers.append("INTRABAR_STOP_NOT_FALSE")
    segment_policy = native_exit.get("segment_end_policy") if isinstance(native_exit.get("segment_end_policy"), dict) else {}
    if segment_policy.get("within_fold") != "CARRY_POSITION_AND_STATE":
        blockers.append("WITHIN_FOLD_STATE_CARRY_INVALID")
    if segment_policy.get("forced_exit_in_native_metrics") is not False:
        blockers.append("FORCED_EXIT_NATIVE_METRIC_NOT_FALSE")

    sizing = spec.get("measurement_sizing_contract") if isinstance(spec.get("measurement_sizing_contract"), dict) else {}
    if sizing.get("strategy_native_sizing_claimed") is not False:
        blockers.append("FALSE_NATIVE_SIZING_CLAIM")
    if sizing.get("position_size_optimization_allowed") is not False:
        blockers.append("POSITION_SIZE_OPTIMIZATION_NOT_FALSE")
    if sizing.get("leverage_allowed") is not False:
        blockers.append("LEVERAGE_NOT_FALSE")

    replay = spec.get("strategy_specific_replay_profile") if isinstance(spec.get("strategy_specific_replay_profile"), dict) else {}
    if string_set(replay.get("native_timeframes")) != {"5m", "15m"}:
        blockers.append("REPLAY_TIMEFRAME_SET_INVALID")
    if replay.get("timeframe_result_pooling_allowed") is not False:
        blockers.append("TIMEFRAME_POOLING_NOT_FALSE")
    if replay.get("best_timeframe_selection_allowed") is not False:
        blockers.append("BEST_TIMEFRAME_SELECTION_NOT_FALSE")
    if replay.get("state_horizon") != "PERSIST_ACROSS_SEGMENTS_WITHIN_FOLD":
        blockers.append("REPLAY_STATE_HORIZON_INVALID")
    if replay.get("segment_end_policy") != "NO_NATIVE_CLOSE":
        blockers.append("REPLAY_SEGMENT_END_POLICY_INVALID")
    if replay.get("gross_edge_first") is not True:
        blockers.append("GROSS_EDGE_FIRST_NOT_TRUE")
    if replay.get("cost_application_stage") != "AFTER_GROSS_EDGE_GATE":
        blockers.append("COST_STAGE_INVALID")
    if replay.get("performance_reselection_allowed") is not False:
        blockers.append("PERFORMANCE_RESELECTION_NOT_FALSE")

    verification = spec.get("verification_plan") if isinstance(spec.get("verification_plan"), dict) else {}
    if string_set(verification.get("formula_fixture_classes")) != EXPECTED_FIXTURES:
        blockers.append("FORMULA_FIXTURE_SET_INVALID")
    if verification.get("economic_test_allowed_in_this_stage") is not False:
        blockers.append("ECONOMIC_TEST_PREMATURELY_ALLOWED")
    try:
        tolerance = float(verification.get("numeric_tolerance"))
    except (TypeError, ValueError):
        tolerance = -1.0
    if tolerance <= 0 or tolerance > 1e-8:
        blockers.append("NUMERIC_TOLERANCE_INVALID")

    authority = spec.get("authority") if isinstance(spec.get("authority"), dict) else {}
    for key in (
        "legacy_parent_mutation_allowed",
        "authentic_child_implementation_allowed",
        "registry_mutation_allowed",
        "config_mutation_allowed",
        "router_mutation_allowed",
        "service_mutation_allowed",
        "shadow_start_allowed",
        "paper_live_order_allowed",
        "promotion_allowed",
        "performance_upgrade_allowed",
    ):
        if authority.get(key) is not False:
            blockers.append(f"AUTHORITY_FALSE_REQUIRED:{key}")

    if spec.get("next_stage") != "R7.A4D2_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES":
        blockers.append("SPEC_NEXT_STAGE_INVALID")

    after = snapshot(protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append(f"READ_ONLY_INPUT_MUTATION:{len(mutation_paths)}")

    blockers = list(dict.fromkeys(blockers))
    state = (
        "PASS_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC"
        if not blockers
        else "HOLD_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC_INPUT"
    )
    next_stage = (
        "R7.A4D2_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES"
        if not blockers
        else "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC_REPAIR"
    )

    result = {
        "schema": "r7a4d2_supertrend_authentic_contract_and_child_spec_verification_v1",
        "official_stage": "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "selected_parent": "supertrend_pullback",
        "selected_child": "supertrend_flip_authentic",
        "parent_git_object_sha256": parent_hash,
        "legacy_deviation_evidence": evidence,
        "legacy_atr_method": "SIMPLE_ROLLING_MEAN",
        "authentic_atr_method": atr.get("method"),
        "formula_parameter_lock": {
            "atr_length": parameters.get("atr_length"),
            "factor": parameters.get("factor"),
        },
        "bidirectional_intent_count": len(string_set(intent.get("allowed_intents"))),
        "state_transition_count": len(transitions),
        "fixture_class_count": len(string_set(verification.get("formula_fixture_classes"))),
        "legacy_parent_immutable": True,
        "strategy_mutation_allowed": False,
        "performance_upgrade_allowed": False,
        "promotion_allowed": False,
        "input_mutation_count": len(mutation_paths),
        "input_mutation_paths": mutation_paths,
        "spec_json": SPEC_PATH,
        "next_stage": next_stage,
    }

    output = root / OUTPUT_JSON
    atomic_json(output, result)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("SELECTED_PARENT=supertrend_pullback")
    print("SELECTED_CHILD=supertrend_flip_authentic")
    print("PARENT_GIT_OBJECT_SHA256=" + parent_hash)
    print("LEGACY_ATR_METHOD=SIMPLE_ROLLING_MEAN")
    print("AUTHENTIC_ATR_METHOD=" + str(atr.get("method") or ""))
    print("ATR_LENGTH=" + str(parameters.get("atr_length")))
    print("SUPERTREND_FACTOR=" + str(parameters.get("factor")))
    print("BIDIRECTIONAL_INTENT_COUNT=" + str(len(string_set(intent.get("allowed_intents")))))
    print("STATE_TRANSITION_COUNT=" + str(len(transitions)))
    print("FORMULA_FIXTURE_CLASS_COUNT=" + str(len(string_set(verification.get("formula_fixture_classes")))))
    print("LEGACY_PARENT_IMMUTABLE=true")
    print("STRATEGY_MUTATION_ALLOWED=false")
    print("PERFORMANCE_UPGRADE_ALLOWED=false")
    print("INPUT_MUTATION_COUNT=" + str(len(mutation_paths)))
    print("SUMMARY_JSON=" + str(output))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
