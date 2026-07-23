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

AUDIT_PATH = "research/canonical25_source_to_code_wave1_v1.json"
DECISION_PATH = "research/canonical25_wave1_authenticity_decision_v1.json"
RUNTIME_VERIFY = Path("runtime/r7a4d2_canonical25_source_to_code_wave1/canonical25_source_to_code_wave1_verification_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_canonical25_wave1_authenticity_decision_gate")
OUTPUT_JSON = OUTPUT_DIR / "canonical25_wave1_authenticity_decision_gate_v1.json"
EXPECTED_STRATEGIES = {
    "turtle_trend",
    "rbreaker_like",
    "squeeze_break",
    "supertrend_pullback",
    "bb_revert",
}
EXPECTED_CONTRACTS = {
    "BidirectionalIntentContract",
    "NativeExitContract",
    "StrategyStateContract",
    "SessionBoundaryContract",
    "PortfolioHeatContract",
    "StrategySpecificReplayProfile",
}
EXPECTED_COMMON_DEFECTS = {
    "short signals generated but suppressed at LBot adapter",
    "fixed profit targets replace native trend or state exits",
    "fixed long and short sizes replace strategy-native risk sizing",
    "ZEL beam/add/retest/dip logic injected before baseline edge was established",
    "single common replay harness cannot represent session, portfolio, and event-state requirements",
}


def git_show(root: Path, sha: str, path: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{sha}:{path}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"GIT_SHOW_FAILED:{path}:{proc.stderr.decode('utf-8', errors='replace').strip()}")
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


def as_id_set(rows: Any, key: str) -> set[str]:
    if not isinstance(rows, list):
        return set()
    return {str(row.get(key) or "") for row in rows if isinstance(row, dict) and row.get(key)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    blockers: list[str] = []

    try:
        audit = git_json(root, args.target_sha, AUDIT_PATH)
        decision = git_json(root, args.target_sha, DECISION_PATH)
    except Exception as exc:
        print("STATE=HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_INPUT")
        print("BLOCKERS=" + json.dumps([f"GIT_OBJECT_INPUT_ERROR:{type(exc).__name__}:{exc}"]))
        print("RC=2")
        return 2

    runtime_path = root / RUNTIME_VERIFY
    if not runtime_path.is_file():
        blockers.append(f"WAVE1_RUNTIME_VERIFICATION_MISSING:{runtime_path}")
        runtime_verify: dict[str, Any] = {}
    else:
        try:
            runtime_verify = local_json(runtime_path)
        except Exception as exc:
            blockers.append(f"WAVE1_RUNTIME_VERIFICATION_INVALID:{type(exc).__name__}")
            runtime_verify = {}

    protected_paths = [
        root / "backend/strategies/turtle_trend.py",
        root / "backend/strategies/rbreaker_like.py",
        root / "backend/strategies/squeeze_break.py",
        root / "backend/strategies/supertrend_pullback.py",
        root / "backend/strategies/bb_revert.py",
        root / "backend/strategy25/canonical_strategy_registry_v1.json",
        root / "backend/strategy25/canonical_strategy25_config_v1.json",
        runtime_path,
    ]
    before = snapshot(protected_paths)

    if audit.get("schema") != "canonical25_source_to_code_wave1_v1":
        blockers.append("SOURCE_AUDIT_SCHEMA_INVALID")
    scope = set(str(value) for value in audit.get("scope", []) if value)
    if scope != EXPECTED_STRATEGIES:
        blockers.append(f"SOURCE_AUDIT_SCOPE_INVALID:{sorted(scope)}")
    audit_rows = audit.get("strategies") if isinstance(audit.get("strategies"), list) else []
    if len(audit_rows) != 5 or as_id_set(audit_rows, "strategy_id") != EXPECTED_STRATEGIES:
        blockers.append("SOURCE_AUDIT_STRATEGY_ROWS_INVALID")
    summary = audit.get("wave_summary") if isinstance(audit.get("wave_summary"), dict) else {}
    if int(summary.get("authentic_match_count") or -1) != 0:
        blockers.append("AUTHENTIC_MATCH_COUNT_NOT_ZERO")
    if int(summary.get("partial_or_derivative_count") or -1) != 2:
        blockers.append("PARTIAL_OR_DERIVATIVE_COUNT_INVALID")
    if int(summary.get("critical_heuristic_or_noncanonical_count") or -1) != 3:
        blockers.append("CRITICAL_COUNT_INVALID")
    common_defects = set(str(value) for value in summary.get("common_defects", []) if value)
    if common_defects != EXPECTED_COMMON_DEFECTS:
        blockers.append("COMMON_DEFECT_SET_INVALID")

    if runtime_verify:
        if runtime_verify.get("state") != "PASS_CANONICAL25_SOURCE_TO_CODE_RULE_AUDIT_WAVE1":
            blockers.append("WAVE1_RUNTIME_STATE_NOT_PASS")
        if int(runtime_verify.get("blocker_count") or 0) != 0:
            blockers.append("WAVE1_RUNTIME_BLOCKERS_NONZERO")
        if int(runtime_verify.get("wave1_strategy_count") or -1) != 5:
            blockers.append("WAVE1_RUNTIME_COUNT_INVALID")
        if int(runtime_verify.get("authentic_match_count") or -1) != 0:
            blockers.append("WAVE1_RUNTIME_AUTHENTIC_COUNT_INVALID")

    if decision.get("schema") != "canonical25_wave1_authenticity_decision_v1":
        blockers.append("DECISION_SCHEMA_INVALID")
    policy = decision.get("decision_policy") if isinstance(decision.get("decision_policy"), dict) else {}
    required_true = [
        "legacy_parent_immutable",
        "authentic_baseline_child_only",
        "zel_extensions_after_authentic_edge_proof_only",
    ]
    required_false = [
        "parameter_optimization_allowed",
        "threshold_relaxation_allowed",
        "parallel_redesign_allowed",
        "performance_upgrade_allowed",
        "promotion_allowed",
        "shadow_start_allowed",
        "paper_live_order_allowed",
    ]
    for key in required_true:
        if policy.get(key) is not True:
            blockers.append(f"DECISION_POLICY_TRUE_REQUIRED:{key}")
    for key in required_false:
        if policy.get(key) is not False:
            blockers.append(f"DECISION_POLICY_FALSE_REQUIRED:{key}")

    contracts = decision.get("common_contracts") if isinstance(decision.get("common_contracts"), list) else []
    contract_ids = as_id_set(contracts, "contract_id")
    if contract_ids != EXPECTED_CONTRACTS or len(contracts) != 6:
        blockers.append(f"CONTRACT_SET_INVALID:{sorted(contract_ids)}")
    for row in contracts:
        if not isinstance(row, dict):
            blockers.append("CONTRACT_ROW_INVALID")
            continue
        if not row.get("purpose"):
            blockers.append(f"CONTRACT_PURPOSE_MISSING:{row.get('contract_id')}")
        if not row.get("fail_closed_rules") and row.get("contract_id") != "StrategyStateContract":
            blockers.append(f"CONTRACT_FAIL_CLOSED_RULES_MISSING:{row.get('contract_id')}")

    decision_rows = decision.get("strategy_decisions") if isinstance(decision.get("strategy_decisions"), list) else []
    if len(decision_rows) != 5 or as_id_set(decision_rows, "strategy_id") != EXPECTED_STRATEGIES:
        blockers.append("STRATEGY_DECISION_SET_INVALID")
    priorities = sorted(int(row.get("priority") or 0) for row in decision_rows if isinstance(row, dict))
    if priorities != [1, 2, 3, 4, 5]:
        blockers.append(f"STRATEGY_PRIORITY_INVALID:{priorities}")
    row_by_id = {str(row.get("strategy_id")): row for row in decision_rows if isinstance(row, dict)}
    supertrend = row_by_id.get("supertrend_pullback", {})
    if decision.get("selected_first_child") != "supertrend_flip_authentic":
        blockers.append("SELECTED_FIRST_CHILD_INVALID")
    if supertrend.get("decision") != "SELECT_FIRST_CONTROL_BASELINE":
        blockers.append("SUPERTREND_CONTROL_DECISION_INVALID")
    if supertrend.get("authentic_child_id") != "supertrend_flip_authentic":
        blockers.append("SUPERTREND_CHILD_ID_INVALID")
    if int(supertrend.get("priority") or -1) != 1:
        blockers.append("SUPERTREND_PRIORITY_INVALID")
    if decision.get("next_stage") != "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC":
        blockers.append("NEXT_STAGE_INVALID")

    for row in decision_rows:
        if not isinstance(row, dict):
            continue
        required = set(str(value) for value in row.get("required_contracts", []) if value)
        unknown = required - EXPECTED_CONTRACTS
        if unknown:
            blockers.append(f"UNKNOWN_REQUIRED_CONTRACT:{row.get('strategy_id')}:{sorted(unknown)}")
        if not required:
            blockers.append(f"REQUIRED_CONTRACTS_EMPTY:{row.get('strategy_id')}")
        if not row.get("authentic_child_rules"):
            blockers.append(f"AUTHENTIC_CHILD_RULES_EMPTY:{row.get('strategy_id')}")

    source_hash_mismatches: list[str] = []
    for row in audit_rows:
        strategy_id = str(row.get("strategy_id") or "")
        source_path = str(row.get("current_source_path") or "")
        expected_sha = str(row.get("current_source_sha256") or "")
        if not strategy_id or not source_path or not expected_sha:
            source_hash_mismatches.append(strategy_id or "UNKNOWN")
            continue
        try:
            actual_sha = hashlib.sha256(git_show(root, args.target_sha, source_path)).hexdigest()
        except Exception:
            source_hash_mismatches.append(strategy_id)
            continue
        if actual_sha != expected_sha:
            source_hash_mismatches.append(strategy_id)
    if source_hash_mismatches:
        blockers.append("SOURCE_HASH_MISMATCH:" + ",".join(sorted(source_hash_mismatches)))

    after = snapshot(protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append(f"READ_ONLY_INPUT_MUTATION:{len(mutation_paths)}")

    blockers = list(dict.fromkeys(blockers))
    state = (
        "PASS_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE"
        if not blockers
        else "HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_INPUT"
    )
    next_stage = (
        "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC"
        if not blockers
        else "R7.A4D2_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR"
    )

    result = {
        "schema": "r7a4d2_canonical25_wave1_authenticity_decision_gate_v1",
        "official_stage": "R7.A4D2_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "wave1_strategy_count": len(decision_rows),
        "common_contract_count": len(contracts),
        "common_contract_ids": sorted(contract_ids),
        "selected_first_strategy": "supertrend_pullback",
        "selected_first_child": decision.get("selected_first_child"),
        "strategy_priority": [
            {"strategy_id": row.get("strategy_id"), "priority": row.get("priority"), "decision": row.get("decision")}
            for row in sorted(decision_rows, key=lambda value: int(value.get("priority") or 999))
            if isinstance(row, dict)
        ],
        "legacy_parent_immutable": policy.get("legacy_parent_immutable") is True,
        "parallel_redesign_allowed": policy.get("parallel_redesign_allowed"),
        "performance_upgrade_allowed": policy.get("performance_upgrade_allowed"),
        "promotion_allowed": policy.get("promotion_allowed"),
        "source_hash_mismatch_count": len(source_hash_mismatches),
        "input_mutation_count": len(mutation_paths),
        "input_mutation_paths": mutation_paths,
        "next_stage": next_stage,
    }

    output = root / OUTPUT_JSON
    atomic_json(output, result)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("WAVE1_STRATEGY_COUNT=" + str(len(decision_rows)))
    print("COMMON_CONTRACT_COUNT=" + str(len(contracts)))
    print("COMMON_CONTRACT_IDS=" + json.dumps(sorted(contract_ids)))
    print("SELECTED_FIRST_STRATEGY=supertrend_pullback")
    print("SELECTED_FIRST_CHILD=" + str(decision.get("selected_first_child") or ""))
    for row in result["strategy_priority"]:
        print(
            "AUTH_DECISION="
            f"{row['priority']}|{row['strategy_id']}|{row['decision']}"
        )
    print("LEGACY_PARENT_IMMUTABLE=" + str(result["legacy_parent_immutable"]).lower())
    print("PARALLEL_REDESIGN_ALLOWED=" + str(result["parallel_redesign_allowed"]).lower())
    print("PERFORMANCE_UPGRADE_ALLOWED=" + str(result["performance_upgrade_allowed"]).lower())
    print("PROMOTION_ALLOWED=" + str(result["promotion_allowed"]).lower())
    print("SOURCE_HASH_MISMATCH_COUNT=" + str(len(source_hash_mismatches)))
    print("INPUT_MUTATION_COUNT=" + str(len(mutation_paths)))
    print("SUMMARY_JSON=" + str(output))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
