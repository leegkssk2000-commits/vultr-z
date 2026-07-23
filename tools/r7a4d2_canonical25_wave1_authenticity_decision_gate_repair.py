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
PRIOR_GATE = Path("runtime/r7a4d2_canonical25_wave1_authenticity_decision_gate/canonical25_wave1_authenticity_decision_gate_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_canonical25_wave1_authenticity_decision_gate_repair")
OUTPUT_JSON = OUTPUT_DIR / "canonical25_wave1_authenticity_decision_gate_repair_v1.json"

EXPECTED_PRIOR_BLOCKERS = {
    "AUTHENTIC_MATCH_COUNT_NOT_ZERO",
    "WAVE1_RUNTIME_COUNT_INVALID",
    "WAVE1_RUNTIME_AUTHENTIC_COUNT_INVALID",
}
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


def exact_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    runtime_path = root / RUNTIME_VERIFY
    prior_gate_path = root / PRIOR_GATE
    blockers: list[str] = []

    try:
        audit = git_json(root, args.target_sha, AUDIT_PATH)
        decision = git_json(root, args.target_sha, DECISION_PATH)
    except Exception as exc:
        print("STATE=HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR_INPUT")
        print("BLOCKERS=" + json.dumps([f"GIT_OBJECT_INPUT_ERROR:{type(exc).__name__}:{exc}"]))
        print("RC=2")
        return 2

    for label, path in (("WAVE1_RUNTIME", runtime_path), ("PRIOR_GATE", prior_gate_path)):
        if not path.is_file():
            blockers.append(f"{label}_MISSING:{path}")

    if blockers:
        print("STATE=HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR_INPUT")
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    try:
        runtime_verify = local_json(runtime_path)
        prior_gate = local_json(prior_gate_path)
    except Exception as exc:
        print("STATE=HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR_INPUT")
        print("BLOCKERS=" + json.dumps([f"LOCAL_EVIDENCE_INVALID:{type(exc).__name__}:{exc}"]))
        print("RC=2")
        return 2

    protected_paths = [
        root / "backend/strategies/turtle_trend.py",
        root / "backend/strategies/rbreaker_like.py",
        root / "backend/strategies/squeeze_break.py",
        root / "backend/strategies/supertrend_pullback.py",
        root / "backend/strategies/bb_revert.py",
        root / "backend/strategy25/canonical_strategy_registry_v1.json",
        root / "backend/strategy25/canonical_strategy25_config_v1.json",
        runtime_path,
        prior_gate_path,
    ]
    before = snapshot(protected_paths)

    if audit.get("schema") != "canonical25_source_to_code_wave1_v1":
        blockers.append("SOURCE_AUDIT_SCHEMA_INVALID")
    audit_rows = audit.get("strategies") if isinstance(audit.get("strategies"), list) else []
    if len(audit_rows) != 5 or as_id_set(audit_rows, "strategy_id") != EXPECTED_STRATEGIES:
        blockers.append("SOURCE_AUDIT_STRATEGY_SET_INVALID")
    summary = audit.get("wave_summary") if isinstance(audit.get("wave_summary"), dict) else {}
    if exact_int(summary, "authentic_match_count") != 0:
        blockers.append("SOURCE_AUDIT_AUTHENTIC_MATCH_COUNT_INVALID")
    if exact_int(summary, "partial_or_derivative_count") != 2:
        blockers.append("SOURCE_AUDIT_PARTIAL_COUNT_INVALID")
    if exact_int(summary, "critical_heuristic_or_noncanonical_count") != 3:
        blockers.append("SOURCE_AUDIT_CRITICAL_COUNT_INVALID")

    if runtime_verify.get("schema") != "r7a4d2_canonical25_source_to_code_wave1_verification_v1":
        blockers.append("WAVE1_RUNTIME_SCHEMA_INVALID")
    if runtime_verify.get("state") != "PASS_CANONICAL25_SOURCE_TO_CODE_RULE_AUDIT_WAVE1":
        blockers.append("WAVE1_RUNTIME_STATE_NOT_PASS")
    if exact_int(runtime_verify, "strategy_count") != 5:
        blockers.append("WAVE1_RUNTIME_STRATEGY_COUNT_INVALID")
    if exact_int(runtime_verify, "authentic_match_count") != 0:
        blockers.append("WAVE1_RUNTIME_AUTHENTIC_MATCH_COUNT_INVALID")
    if set(str(value) for value in runtime_verify.get("blockers", []) if value):
        blockers.append("WAVE1_RUNTIME_BLOCKERS_NONZERO")

    prior_blockers = set(str(value) for value in prior_gate.get("blockers", []) if value)
    if prior_gate.get("state") != "HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_INPUT":
        blockers.append("PRIOR_GATE_NOT_EXPECTED_HOLD")
    if prior_blockers != EXPECTED_PRIOR_BLOCKERS:
        blockers.append("PRIOR_GATE_BLOCKER_SET_UNEXPECTED:" + json.dumps(sorted(prior_blockers)))
    if exact_int(prior_gate, "source_hash_mismatch_count") != 0:
        blockers.append("PRIOR_GATE_SOURCE_HASH_MISMATCH")
    if exact_int(prior_gate, "input_mutation_count") != 0:
        blockers.append("PRIOR_GATE_INPUT_MUTATION")
    if prior_gate.get("legacy_parent_immutable") is not True:
        blockers.append("PRIOR_GATE_LEGACY_PARENT_NOT_IMMUTABLE")

    if decision.get("schema") != "canonical25_wave1_authenticity_decision_v1":
        blockers.append("DECISION_SCHEMA_INVALID")
    policy = decision.get("decision_policy") if isinstance(decision.get("decision_policy"), dict) else {}
    if policy.get("legacy_parent_immutable") is not True:
        blockers.append("DECISION_LEGACY_PARENT_NOT_IMMUTABLE")
    if policy.get("authentic_baseline_child_only") is not True:
        blockers.append("DECISION_CHILD_ONLY_NOT_TRUE")
    if policy.get("parallel_redesign_allowed") is not False:
        blockers.append("DECISION_PARALLEL_REDESIGN_NOT_FALSE")
    contracts = decision.get("common_contracts") if isinstance(decision.get("common_contracts"), list) else []
    if len(contracts) != 6 or as_id_set(contracts, "contract_id") != EXPECTED_CONTRACTS:
        blockers.append("DECISION_CONTRACT_SET_INVALID")
    rows = decision.get("strategy_decisions") if isinstance(decision.get("strategy_decisions"), list) else []
    if len(rows) != 5 or as_id_set(rows, "strategy_id") != EXPECTED_STRATEGIES:
        blockers.append("DECISION_STRATEGY_SET_INVALID")
    if decision.get("selected_first_child") != "supertrend_flip_authentic":
        blockers.append("DECISION_SELECTED_CHILD_INVALID")
    if decision.get("next_stage") != "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC":
        blockers.append("DECISION_NEXT_STAGE_INVALID")

    after = snapshot(protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append(f"READ_ONLY_INPUT_MUTATION:{len(mutation_paths)}")

    blockers = list(dict.fromkeys(blockers))
    state = (
        "PASS_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR"
        if not blockers
        else "HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR_INPUT"
    )
    next_stage = (
        "R7.A4D2_SUPERTREND_AUTHENTIC_CONTRACT_AND_CHILD_SPEC"
        if not blockers
        else "R7.A4D2_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR"
    )

    result = {
        "schema": "r7a4d2_canonical25_wave1_authenticity_decision_gate_repair_v1",
        "official_stage": "R7.A4D2_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_REPAIR",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "repair_scope": "VALIDATION_SEMANTICS_ONLY",
        "repaired_findings": [
            "zero-valued authentic_match_count must remain zero and not fall through to a missing-value sentinel",
            "runtime verification publishes strategy_count, not wave1_strategy_count",
            "zero-valued runtime authentic_match_count must remain zero and not fall through to a missing-value sentinel",
        ],
        "source_audit_authentic_match_count": exact_int(summary, "authentic_match_count"),
        "runtime_strategy_count": exact_int(runtime_verify, "strategy_count"),
        "runtime_authentic_match_count": exact_int(runtime_verify, "authentic_match_count"),
        "selected_first_strategy": "supertrend_pullback",
        "selected_first_child": decision.get("selected_first_child"),
        "legacy_parent_immutable": True,
        "strategy_mutation_allowed": False,
        "performance_upgrade_allowed": False,
        "promotion_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "input_mutation_count": len(mutation_paths),
        "input_mutation_paths": mutation_paths,
        "next_stage": next_stage,
    }

    output = root / OUTPUT_JSON
    atomic_json(output, result)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("REPAIR_SCOPE=VALIDATION_SEMANTICS_ONLY")
    print("PRIOR_FALSE_BLOCKER_COUNT=" + str(len(EXPECTED_PRIOR_BLOCKERS)))
    print("SOURCE_AUDIT_AUTHENTIC_MATCH_COUNT=" + str(exact_int(summary, "authentic_match_count")))
    print("RUNTIME_STRATEGY_COUNT=" + str(exact_int(runtime_verify, "strategy_count")))
    print("RUNTIME_AUTHENTIC_MATCH_COUNT=" + str(exact_int(runtime_verify, "authentic_match_count")))
    print("SELECTED_FIRST_STRATEGY=supertrend_pullback")
    print("SELECTED_FIRST_CHILD=" + str(decision.get("selected_first_child") or ""))
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
