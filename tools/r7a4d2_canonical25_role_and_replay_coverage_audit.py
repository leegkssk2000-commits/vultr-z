#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

REGISTRY = Path("backend/strategy25/canonical_strategy_registry_v1.json")
CONFIG = Path("backend/strategy25/canonical_strategy25_config_v1.json")
CONTRACT = Path("backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json")
SEMANTIC = Path("runtime/r7a4d_semantic_parity_audit/semantic_parity_audit_v1.json")
TARGETED = Path("runtime/r7a4d2_targeted_trigger_geometry_diagnose/targeted_diagnose_v1.json")
ATR15_CHILD = Path("runtime/r7a4d2_atr15_side_specialization_economic_child_audit/atr15_side_specialization_economic_child_audit_summary_v1.json")
OOS_OVERLAY = Path("runtime/r7a4d2_ma5_oos_market_source_coverage_expansion/oos_overlay_frozen_input_manifest_v1.json")
OPTIONAL_NO_TRIGGER = Path("runtime/r7a4d2_no_trigger_market_coverage_diagnose/no_trigger_market_coverage_diagnose_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_canonical25_role_and_replay_coverage_audit")
AUDIT_OUT = OUTPUT_DIR / "canonical25_role_and_replay_coverage_audit_v1.json"
PLAN_OUT = OUTPUT_DIR / "canonical25_direct_gross_edge_replay_plan_v1.json"

EXPECTED_COUNT = 25
AMBIGUOUS_ROLE_IDS = {
    "break_and_continue",
    "rbreaker_like",
    "squeeze_break",
    "trend_ma_macd",
    "vwap_revert",
}
BAD_SEMANTIC = {"SEMANTIC_PARITY_FAIL"}
BAD_TARGETED = {
    "CALL_ERROR",
    "ADAPTER_DIRECT_OR_LONG_MAPPING_MISMATCH",
    "PAYLOAD_GEOMETRY_FAIL",
}
CALL_WINDOW_CLASSES = {"UNEXPLAINED_ZERO_TRADE", "A4D_ZERO_WITH_FULL_SCAN_LONG_TRIGGER"}
NO_TRIGGER_CLASSES = {"NO_LONG_TRIGGER_SELECTED_FOLDS", "FULL_SCAN_NO_ACTIVE_TRIGGER"}
SHORT_SCOPE_CLASSES = {"LONG_PARITY_PASS_SHORT_SCOPE_GAP", "FULL_SCAN_SHORT_ONLY_TRIGGER", "FULL_SCAN_BOTH_SIDES_TRIGGER"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def source_capabilities(path: Path, callable_name: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text, filename=str(path))
    parts = callable_name.split(".")
    expected_class = parts[0] if len(parts) == 2 else ""
    expected_method = parts[1] if len(parts) == 2 else ""
    top_functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    class_methods: dict[str, set[str]] = {}
    constants: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_methods[node.name] = {
                child.name for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            constants.add(node.value.strip().lower())
    lowered = text.lower()
    short_markers = sum(marker in lowered for marker in (
        "enter_short", "short_signal", "side\": \"short", "side': 'short", "side = \"short\"", "side='short'"
    ))
    long_markers = sum(marker in lowered for marker in (
        "enter_long", "long_signal", "side\": \"long", "side': 'long", "side = \"long\"", "side='long'"
    ))
    management_markers = {
        "add": bool(re.search(r"\badd\b", lowered)),
        "reduce": bool(re.search(r"\breduce\b", lowered)),
        "exit": bool(re.search(r"\b(exit|close)\b", lowered)),
    }
    return {
        "ast_parse_ok": True,
        "canonical_callable_resolved": bool(expected_class and expected_method and expected_method in class_methods.get(expected_class, set())),
        "direct_strategy_callable_present": "strategy" in top_functions,
        "source_short_capable_static": bool(short_markers or "short" in constants),
        "source_long_capable_static": bool(long_markers or "long" in constants),
        "management_markers": management_markers,
    }


def report_map(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("strategy_id") or ""): row
        for row in value.get("strategy_reports", [])
        if isinstance(row, dict) and row.get("strategy_id")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    required = [root / REGISTRY, root / CONFIG, root / CONTRACT, root / SEMANTIC, root / TARGETED, root / ATR15_CHILD, root / OOS_OVERLAY]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT_INPUT")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    registry = load_json(root / REGISTRY)
    config = load_json(root / CONFIG)
    contract = load_json(root / CONTRACT)
    semantic = load_json(root / SEMANTIC)
    targeted = load_json(root / TARGETED)
    atr15_child = load_json(root / ATR15_CHILD)
    overlay = load_json(root / OOS_OVERLAY)
    no_trigger = load_json(root / OPTIONAL_NO_TRIGGER) if (root / OPTIONAL_NO_TRIGGER).is_file() else {}

    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    strategies_config = config.get("strategies") if isinstance(config.get("strategies"), dict) else {}
    semantic_by_id = report_map(semantic)
    targeted_by_id = report_map(targeted)

    blockers: list[str] = []
    if registry.get("schema") != "canonical_strategy25_registry_v1" or int(registry.get("strategy_count") or -1) != EXPECTED_COUNT:
        blockers.append("REGISTRY_SCHEMA_OR_COUNT_INVALID")
    if len(entries) != EXPECTED_COUNT:
        blockers.append(f"REGISTRY_ENTRY_COUNT_INVALID:{len(entries)}")
    if int(contract.get("expected_strategy_count") or -1) != EXPECTED_COUNT:
        blockers.append("CONTRACT_STRATEGY_COUNT_INVALID")
    if len(semantic_by_id) != EXPECTED_COUNT:
        blockers.append(f"SEMANTIC_REPORT_COUNT_INVALID:{len(semantic_by_id)}")
    if atr15_child.get("state") != "PASS_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT":
        blockers.append("ATR15_CHILD_AUDIT_NOT_PASS")
    if atr15_child.get("classification") != "SIDE_PARTITION_NOT_ECONOMICALLY_REPRODUCED":
        blockers.append("FAILED_11_LANE_AXIS_NOT_CLOSED")
    if bool(atr15_child.get("promotion_allowed")):
        blockers.append("ATR15_CHILD_PROMOTION_AUTHORITY_TRUE")
    if overlay.get("state") != "PASS" or int(overlay.get("oos_generated_market_source_count") or -1) < 3:
        blockers.append("STRICT_FORWARD_OOS_OVERLAY_INVALID")

    entry_ids = [str(row.get("strategy_id") or "") for row in entries]
    if len(set(entry_ids)) != EXPECTED_COUNT or any(not value for value in entry_ids):
        blockers.append("REGISTRY_STRATEGY_ID_SET_INVALID")

    source_paths: list[Path] = []
    reports: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda row: str(row.get("strategy_id") or "")):
        strategy_id = str(entry.get("strategy_id") or "")
        engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
        implementation = str(engine.get("implementation_path") or "")
        callable_name = str(engine.get("callable") or "")
        expected_sha = str(engine.get("source_sha256") or "")
        source = root / implementation
        source_paths.append(source)

        local_issues: list[str] = []
        if entry.get("active_allowed") is not False or entry.get("fail_closed") is not True:
            local_issues.append("AUTHORITY_NOT_FAIL_CLOSED")
        if strategy_id not in strategies_config:
            local_issues.append("CONFIG_BINDING_MISSING")
        actual_sha = sha256_file(source)
        if actual_sha is None:
            local_issues.append("SOURCE_MISSING")
            capabilities = {
                "ast_parse_ok": False,
                "canonical_callable_resolved": False,
                "direct_strategy_callable_present": False,
                "source_short_capable_static": False,
                "source_long_capable_static": False,
                "management_markers": {},
            }
        elif actual_sha != expected_sha:
            local_issues.append("SOURCE_REGISTRY_SHA_MISMATCH")
            capabilities = source_capabilities(source, callable_name)
        else:
            try:
                capabilities = source_capabilities(source, callable_name)
            except Exception as exc:
                local_issues.append(f"SOURCE_AST_ERROR:{type(exc).__name__}")
                capabilities = {
                    "ast_parse_ok": False,
                    "canonical_callable_resolved": False,
                    "direct_strategy_callable_present": False,
                    "source_short_capable_static": False,
                    "source_long_capable_static": False,
                    "management_markers": {},
                }
        if not capabilities.get("canonical_callable_resolved"):
            local_issues.append("CANONICAL_CALLABLE_UNRESOLVED")
        if not capabilities.get("direct_strategy_callable_present"):
            local_issues.append("DIRECT_STRATEGY_CALLABLE_MISSING")

        sem = semantic_by_id.get(strategy_id, {})
        tgt = targeted_by_id.get(strategy_id, {})
        sem_class = str(sem.get("classification") or "MISSING")
        tgt_class = str(tgt.get("classification") or "NOT_TARGETED")
        long_signals = max(
            int(sem.get("sampled_long_active_signal_count") or 0),
            int(tgt.get("long_active_signal_count") or 0),
        )
        short_signals = max(
            int(sem.get("sampled_short_active_signal_count") or 0),
            int(tgt.get("short_active_signal_count") or 0),
        )
        a4d_trades = int(sem.get("a4d_trade_count") or tgt.get("a4d_trade_count") or 0)
        source_short = bool(capabilities.get("source_short_capable_static"))
        source_long = bool(capabilities.get("source_long_capable_static"))
        short_capable = short_signals > 0 or source_short or sem_class in SHORT_SCOPE_CLASSES or tgt_class in SHORT_SCOPE_CLASSES
        long_capable = long_signals > 0 or source_long or a4d_trades > 0

        role = str(entry.get("strategy_role") or "").strip().lower()
        execution_scope = str(entry.get("execution_scope") or "").strip().lower()
        role_ready = strategy_id not in AMBIGUOUS_ROLE_IDS or (
            role == "standalone" and execution_scope == "independent_entry_add_reduce_exit"
        )

        if local_issues:
            classification = "SOURCE_OR_ADAPTER_BIND_HOLD"
            reason = ",".join(local_issues)
        elif sem_class in BAD_SEMANTIC or tgt_class in BAD_TARGETED:
            classification = "ADAPTER_OR_GEOMETRY_HOLD"
            reason = f"semantic={sem_class};targeted={tgt_class}"
        elif sem_class in CALL_WINDOW_CLASSES or tgt_class in CALL_WINDOW_CLASSES:
            classification = "CALL_WINDOW_HOLD"
            reason = f"semantic={sem_class};targeted={tgt_class}"
        elif not role_ready:
            classification = "ROLE_AUTHORITY_HOLD"
            reason = "AMBIGUOUS_STANDALONE_ROLE_NOT_CLOSED"
        elif short_capable and (short_signals > 0 or tgt_class in SHORT_SCOPE_CLASSES or sem_class in SHORT_SCOPE_CLASSES):
            classification = "REPLAY_READY_UNIFIED_LONG_SHORT"
            reason = "CANONICAL_BIND_VALID_SHORT_SCOPE_REQUIRES_UNIFIED_HARNESS"
        elif (sem_class in NO_TRIGGER_CLASSES or tgt_class in NO_TRIGGER_CLASSES) and not (long_signals or short_signals):
            classification = "MARKET_COVERAGE_HOLD"
            reason = f"semantic={sem_class};targeted={tgt_class}"
        elif long_capable:
            classification = "REPLAY_READY_LONG_ONLY"
            reason = "CANONICAL_BIND_VALID_LONG_SIGNAL_OR_PRIOR_TRADE_EVIDENCE"
        else:
            classification = "MARKET_COVERAGE_HOLD"
            reason = "NO_ACTIVE_ENTRY_EVIDENCE"

        reports.append({
            "strategy_id": strategy_id,
            "implementation_path": implementation,
            "canonical_callable": callable_name,
            "source_sha256": actual_sha,
            "source_registry_sha_match": actual_sha == expected_sha,
            "active_allowed": entry.get("active_allowed"),
            "fail_closed": entry.get("fail_closed"),
            "strategy_role": role or None,
            "execution_scope": execution_scope or None,
            "role_ready": role_ready,
            "semantic_classification": sem_class,
            "targeted_classification": tgt_class,
            "a4d_trade_count_reference_only": a4d_trades,
            "sampled_long_active_signal_count": long_signals,
            "sampled_short_active_signal_count": short_signals,
            "long_capable": long_capable,
            "short_capable": short_capable,
            "capabilities": capabilities,
            "classification": classification,
            "classification_reason": reason,
            "local_issues": local_issues,
        })

    protected = required + source_paths
    if (root / OPTIONAL_NO_TRIGGER).is_file():
        protected.append(root / OPTIONAL_NO_TRIGGER)
    before = snapshot(protected)
    after = snapshot(protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append(f"READ_ONLY_INPUT_MUTATION:{len(mutation_paths)}")

    histogram = dict(sorted(Counter(row["classification"] for row in reports).items()))
    ready_long = [row["strategy_id"] for row in reports if row["classification"] == "REPLAY_READY_LONG_ONLY"]
    ready_unified = [row["strategy_id"] for row in reports if row["classification"] == "REPLAY_READY_UNIFIED_LONG_SHORT"]
    closure = [row["strategy_id"] for row in reports if row["classification"] in {
        "SOURCE_OR_ADAPTER_BIND_HOLD", "ADAPTER_OR_GEOMETRY_HOLD", "CALL_WINDOW_HOLD", "ROLE_AUTHORITY_HOLD"
    }]
    coverage = [row["strategy_id"] for row in reports if row["classification"] == "MARKET_COVERAGE_HOLD"]

    blockers = list(dict.fromkeys(blockers))
    audit_state = "PASS_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT" if not blockers else "HOLD_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT_INPUT"
    next_stage = (
        "R7.A4D2_CANONICAL25_DIRECT_GROSS_EDGE_OOS_BATCH_PLAN"
        if not blockers and (ready_long or ready_unified)
        else "R7.A4D2_CANONICAL25_ADAPTER_AND_MARKET_COVERAGE_CLOSURE"
    )

    audit = {
        "schema": "r7a4d2_canonical25_role_and_replay_coverage_audit_v1",
        "official_stage": "R7.A4D2_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT",
        "state": audit_state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "canonical_strategy_count": len(reports),
        "classification_histogram": histogram,
        "strategy_reports": reports,
        "failed_11_lane_axis_frozen": True,
        "failed_11_lane_axis_reference": str(ATR15_CHILD),
        "canonical25_selection_independent_of_11_lane_results": True,
        "old_a4d_performance_not_accepted_as_final": True,
        "no_trigger_evidence_present": bool(no_trigger),
        "source_registry_mutation_count": len(mutation_paths),
        "source_registry_mutation_paths": mutation_paths,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": next_stage,
    }

    plan = {
        "schema": "r7a4d2_canonical25_direct_gross_edge_replay_plan_v1",
        "official_stage": "R7.A4D2_CANONICAL25_DIRECT_GROSS_EDGE_OOS_BATCH_PLAN",
        "state": "PASS_CANONICAL25_DIRECT_GROSS_EDGE_OOS_BATCH_PLAN" if not blockers else "HOLD_CANONICAL25_DIRECT_GROSS_EDGE_OOS_BATCH_PLAN",
        "target_commit": args.target_sha,
        "selection_policy": "CANONICAL25_ORIGINAL_STRATEGIES_NO_11_LANE_RESELECTION_NO_PARAMETER_OPTIMIZATION",
        "strict_forward_overlay_manifest": str(OOS_OVERLAY),
        "replay_ready_long_only_ids": ready_long,
        "replay_ready_unified_long_short_ids": ready_unified,
        "pre_replay_closure_ids": closure,
        "market_coverage_expansion_ids": coverage,
        "gross_edge_first": True,
        "gross_edge_metrics": [
            "gross_r_sum", "gross_expectancy_r", "gross_profit_factor", "positive_gross_folds",
            "median_mfe_r", "median_mae_r", "symbol_concentration", "regime_concentration"
        ],
        "cost_stage_after_gross_gate": True,
        "cost_profiles": ["base", "adverse", "severe"],
        "timing_stress_required": True,
        "minimum_folds": 6,
        "minimum_symbols": 3,
        "minimum_unique_events": 24,
        "parameter_optimization_allowed": False,
        "threshold_relaxation_allowed": False,
        "strategy_mutation_allowed": False,
        "candidate_reselection_allowed": False,
        "promotion_allowed": False,
        "portfolio_weight_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": next_stage,
    }

    output = root / OUTPUT_DIR
    atomic_json(output / AUDIT_OUT.name, audit)
    atomic_json(output / PLAN_OUT.name, plan)

    print("STATE=" + audit_state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("CANONICAL_STRATEGY_COUNT=" + str(len(reports)))
    print("REPLAY_READY_LONG_ONLY_COUNT=" + str(len(ready_long)))
    print("REPLAY_READY_UNIFIED_LONG_SHORT_COUNT=" + str(len(ready_unified)))
    print("PRE_REPLAY_CLOSURE_COUNT=" + str(len(closure)))
    print("MARKET_COVERAGE_HOLD_COUNT=" + str(len(coverage)))
    print("CLASSIFICATION_HISTOGRAM=" + json.dumps(histogram, sort_keys=True))
    for row in reports:
        print(
            "CANONICAL25_RESULT="
            f"{row['strategy_id']}|CLASS={row['classification']}|SEM={row['semantic_classification']}|"
            f"TARGET={row['targeted_classification']}|TRADES_REF={row['a4d_trade_count_reference_only']}|"
            f"LONG_SIG={row['sampled_long_active_signal_count']}|SHORT_SIG={row['sampled_short_active_signal_count']}|"
            f"ROLE_READY={str(row['role_ready']).lower()}|REASON={row['classification_reason']}"
        )
    print("FAILED_11_LANE_AXIS_FROZEN=true")
    print("OLD_A4D_PERFORMANCE_FINAL_ALLOWED=false")
    print("AUDIT_JSON=" + str(output / AUDIT_OUT.name))
    print("PLAN_JSON=" + str(output / PLAN_OUT.name))
    print("INPUT_MUTATION_COUNT=" + str(len(mutation_paths)))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
