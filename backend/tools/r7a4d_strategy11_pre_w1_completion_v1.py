from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_PRE_W1_COMPLETION_V1"

SPECS = (
    {
        "stage_id": "GEMINI_ACTIVE_RESEARCH_V3_1",
        "directory": "gemini",
        "pr": 222,
        "run_id": 30302007460,
        "head_sha": "764560062989c58e4c27430e799a78d43c34b997",
        "expected_states": ["PASS"],
        "legacy_protected_field_optional": True,
    },
    {
        "stage_id": "TURTLE_GEMINI_TRAILING_V1_EVIDENCE_ONLY",
        "directory": "turtle",
        "pr": 223,
        "run_id": 30302182624,
        "head_sha": "60b18285a9561732bd669eec1bfd82a7298f5cc3",
        "expected_states": ["RESEARCH_DERIVED_REPAIR_HOLD"],
        "legacy_protected_field_optional": True,
    },
    {
        "stage_id": "ALPHA_EXPECTED_R_FEASIBILITY_V1",
        "directory": "alpha",
        "pr": 230,
        "run_id": 30312526587,
        "head_sha": "cab8dd1827efd3e5bba735d24fb3181f14385465",
        "expected_states": ["RESEARCH_HOLD"],
    },
    {
        "stage_id": "EMA_CAUSAL_HOLD_PACKAGE",
        "directory": "ema",
        "pr": 232,
        "run_id": 30312995588,
        "head_sha": "28944c719d12621f62c14690d83aca2d0d2fdcba",
        "expected_states": ["PASS_HOLD_PACKAGE"],
    },
    {
        "stage_id": "DATA_WAIT_POOL_PRE_DIAGNOSIS_22",
        "directory": "pre_diagnosis",
        "pr": 234,
        "run_id": 30313492251,
        "head_sha": "b095131686ba39460e4bc8e487ca7e25d83650a3",
        "expected_states": ["PASS_PRE_DIAGNOSIS"],
    },
    {
        "stage_id": "W1_PIPELINE_DRY_RUN",
        "directory": "w1_dry_run",
        "pr": 235,
        "run_id": 30314233936,
        "head_sha": "5a34b36e8b537fbf6141f9bd274929a1cff58312",
        "expected_states": ["PASS_PIPELINE_CONTRACT"],
    },
    {
        "stage_id": "EVIDENCE_VISUALIZATION_READY",
        "directory": "visualization",
        "pr": 237,
        "run_id": 30314637231,
        "head_sha": "8e1310cef7bceb7138d3f2d5fca0698347ff06ed",
        "expected_states": ["PASS_VISUALIZATION_READY"],
    },
    {
        "stage_id": "STATISTICAL_POWER_WINDOW_PLAN",
        "directory": "statistical_power",
        "pr": 238,
        "run_id": 30314841419,
        "head_sha": "b4cfe6ff9a5dde82fd54a6c8b209f84706b9f319",
        "expected_states": ["PASS_STATISTICAL_WINDOW_PLAN"],
    },
    {
        "stage_id": "ORCHESTRATION_FAILURE_INJECTION",
        "directory": "failure_injection",
        "pr": 239,
        "run_id": 30314989121,
        "head_sha": "eb3343b60c354747c674423354d846d6eb060e53",
        "expected_states": ["PASS_FAILURE_INJECTION"],
    },
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def false_or_missing(document: Mapping[str, Any], key: str) -> bool:
    return key not in document or document.get(key) is False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    artifacts_root = Path(args.artifacts_root).resolve()
    config_path = Path(args.config).resolve()
    out = Path(args.out).resolve()
    config = load(config_path)
    stage_config = {str(row["stage_id"]): dict(row) for row in config.get("stages", []) if isinstance(row, Mapping)}
    matrix: list[dict[str, Any]] = []
    blockers: list[str] = []

    for spec in SPECS:
        stage_id = str(spec["stage_id"])
        summary_path = artifacts_root / str(spec["directory"]) / "summary.json"
        if not summary_path.exists():
            blockers.append(f"SUMMARY_MISSING:{stage_id}")
            matrix.append({"stage_id": stage_id, "state": "HOLD", "blockers": ["SUMMARY_MISSING"]})
            continue
        document = load(summary_path)
        state = str(document.get("state") or "")
        stage_blockers: list[str] = []
        if state not in set(spec["expected_states"]):
            stage_blockers.append(f"STATE:{state}")
        if document.get("canonical_mutated") is not False:
            stage_blockers.append("CANONICAL_MUTATION_NOT_FALSE")
        if document.get("registry_mutated") is not False:
            stage_blockers.append("REGISTRY_MUTATION_NOT_FALSE")
        if not false_or_missing(document, "execution_allowed"):
            stage_blockers.append("EXECUTION_ALLOWED")
        if document.get("order_authority") not in (None, "BLOCKED"):
            stage_blockers.append("ORDER_AUTHORITY_NOT_BLOCKED")
        protected = document.get("protected_mutations")
        if protected is None and not spec.get("legacy_protected_field_optional"):
            stage_blockers.append("PROTECTED_MUTATIONS_MISSING")
        elif protected is not None and int(protected) != 0:
            stage_blockers.append(f"PROTECTED_MUTATIONS:{protected}")

        configured = stage_config.get(stage_id)
        if not configured:
            stage_blockers.append("ORCHESTRATOR_STAGE_MISSING")
        else:
            if configured.get("implemented") is not True:
                stage_blockers.append("ORCHESTRATOR_NOT_IMPLEMENTED")
            if int(configured.get("pr_number") or 0) != int(spec["pr"]):
                stage_blockers.append("ORCHESTRATOR_PR_MISMATCH")

        if stage_id == "GEMINI_ACTIVE_RESEARCH_V3_1":
            if document.get("GEMINI_USED") is not True or document.get("free_only") is not True:
                stage_blockers.append("GEMINI_USAGE_CONTRACT_FAIL")
            if int(document.get("approved_hypothesis_count") or 0) != 0:
                stage_blockers.append("GEMINI_APPROVAL_AUTHORITY_CHANGED")
        if stage_id == "TURTLE_GEMINI_TRAILING_V1_EVIDENCE_ONLY":
            if document.get("eligible_for_new_sealed"):
                stage_blockers.append("TURTLE_EVIDENCE_HISTORY_PROMOTION")
            if document.get("existing_sealed_reused") is not False or document.get("sealed_holdback_read") is not False:
                stage_blockers.append("SEALED_REUSE_VIOLATION")
        if stage_id == "ALPHA_EXPECTED_R_FEASIBILITY_V1" and document.get("next") != "WAIT_W1_NEW_CAUSAL_EVIDENCE":
            stage_blockers.append("ALPHA_NEXT_MISMATCH")
        if stage_id == "EMA_CAUSAL_HOLD_PACKAGE" and document.get("classification") != "RESEARCH_EXHAUSTED_HOLD":
            stage_blockers.append("EMA_CLASSIFICATION_MISMATCH")
        if stage_id == "DATA_WAIT_POOL_PRE_DIAGNOSIS_22" and int(document.get("pool_size") or 0) != 22:
            stage_blockers.append("POOL_SIZE_MISMATCH")
        if stage_id == "W1_PIPELINE_DRY_RUN" and document.get("performance_claim_allowed") is not False:
            stage_blockers.append("DRY_RUN_PERFORMANCE_CLAIM")
        if stage_id == "EVIDENCE_VISUALIZATION_READY":
            if int(document.get("strategy_count") or 0) != 25 or int(document.get("chart_json_svg_pair_count") or 0) != 100:
                stage_blockers.append("VISUALIZATION_COVERAGE_MISMATCH")
            if document.get("performance_claim_allowed") is not False:
                stage_blockers.append("VISUALIZATION_PERFORMANCE_CLAIM")
        if stage_id == "STATISTICAL_POWER_WINDOW_PLAN" and document.get("performance_claim_allowed") is not False:
            stage_blockers.append("POWER_PLAN_PERFORMANCE_CLAIM")
        if stage_id == "ORCHESTRATION_FAILURE_INJECTION":
            if int(document.get("failed_count") or 0) != 0 or int(document.get("passed_count") or 0) != int(document.get("case_count") or -1):
                stage_blockers.append("FAILURE_INJECTION_MATRIX_FAIL")

        if stage_blockers:
            blockers.extend(f"{stage_id}:{value}" for value in stage_blockers)
        matrix.append({
            "stage_id": stage_id,
            "state": "PASS" if not stage_blockers else "HOLD",
            "authority_state": state,
            "pr": spec["pr"],
            "run_id": spec["run_id"],
            "head_sha": spec["head_sha"],
            "summary_sha256": sha256(summary_path),
            "blockers": stage_blockers,
        })

    completion_stage = stage_config.get("PRE_W1_COMPLETION_AUDIT") or {}
    if completion_stage.get("implemented") is not False:
        blockers.append("PRE_W1_STAGE_EXPECTED_UNIMPLEMENTED_BEFORE_AUDIT")
    w1_stage = stage_config.get("DATA_WAIT_POOL_W1_REPLAY") or {}
    if w1_stage.get("not_before_utc") != "2026-08-01T08:30:00Z":
        blockers.append("W1_NOT_BEFORE_MISMATCH")
    if w1_stage.get("implemented") is not True or int(w1_stage.get("pr_number") or 0) != 219:
        blockers.append("W1_COMPUTE_AUTHORITY_MISMATCH")

    state = "PRE_W1_BACKLOG_COMPLETE" if not blockers else "HOLD"
    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "authority": "READ_ONLY_PRE_W1_COMPLETION_AUDIT",
        "orchestrator_version": config.get("orchestrator_version"),
        "orchestrator_config_sha256": sha256(config_path),
        "required_stage_count": len(SPECS),
        "passed_stage_count": sum(row["state"] == "PASS" for row in matrix),
        "failed_stage_count": sum(row["state"] != "PASS" for row in matrix),
        "stage_matrix": matrix,
        "blockers": blockers,
        "remaining_data_stage": {
            "stage_id": "DATA_WAIT_POOL_W1_REPLAY",
            "pr": 219,
            "not_before_utc": "2026-08-01T08:30:00Z",
            "state": "WAIT_DATA",
        },
        "next": "WAIT_DATA_UNTIL_W1_THEN_RUN_PR219_COMPUTE" if not blockers else "REPAIR_PRE_W1_AUTHORITY",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    write(out / "summary.json", result)
    write(out / "authority_matrix.json", {"rows": matrix})
    print(json.dumps({"state": state, "passed": result["passed_stage_count"], "failed": result["failed_stage_count"], "blockers": len(blockers), "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
