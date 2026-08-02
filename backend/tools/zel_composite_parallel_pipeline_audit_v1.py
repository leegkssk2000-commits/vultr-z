from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_COMPOSITE_PARALLEL_PIPELINE_AUDIT_V1"
DEBRIS_SUFFIXES = {".bak", ".old", ".orig", ".rej", ".tmp", ".swp", ".pyc", ".pyo"}
EXCLUDED_PARTS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "quarantine", "archive", "archives", "backup", "backups",
}
REQUIRED_LIGHTWEIGHT = {
    "bingx_contract": "backend/research/zel_bingx_execution_evidence_collector_v1.json",
    "bingx_tool": "backend/tools/zel_bingx_execution_evidence_collector_v1.py",
    "bingx_workflow": ".github/workflows/zel-bingx-execution-evidence-collect-v1.yml",
    "holdout_tool": "backend/tools/zel_holdout_vault_audit_v1.py",
    "holdout_workflow": ".github/workflows/zel-holdout-vault-audit-v1.yml",
    "dag_tool": "backend/tools/zel_pre_shadow_receipt_dag_v1.py",
    "readiness_tool": "backend/tools/zel_parallel_readiness_audit_v1.py",
    "alimi_tool": "backend/tools/zel_alimi_feature_install_audit_v1.py",
    "alimi_workflow": ".github/workflows/zel-alimi-feature-install-audit-v1.yml",
    "composite_contract": "backend/research/zel_composite_module_factory_contract_v1.json",
    "composite_tool": "backend/tools/zel_composite_module_factory_v1.py",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"state": "HOLD_NON_OBJECT_JSON"}
    except Exception as exc:
        return {"state": "HOLD_JSON_PARSE_ERROR", "error": f"{type(exc).__name__}:{exc}"}


def repo_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        yield path, rel


def duplicate_groups(root: Path) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for path, rel in repo_files(root):
        if path.stat().st_size == 0 or path.stat().st_size > 2_000_000:
            continue
        groups.setdefault(file_sha(path), []).append(str(rel))
    rows = []
    for digest, paths in groups.items():
        if len(paths) > 1:
            rows.append({"sha256": digest, "paths": sorted(paths), "count": len(paths)})
    return sorted(rows, key=lambda x: (-x["count"], x["paths"][0]))[:200]


def debris_candidates(root: Path) -> list[str]:
    rows = []
    for path, rel in repo_files(root):
        if path.suffix.lower() in DEBRIS_SUFFIXES or "__pycache__" in rel.parts:
            rows.append(str(rel))
    return sorted(set(rows))[:500]


def workflow_noise_candidates(root: Path) -> list[dict[str, Any]]:
    rows = []
    wf_root = root / ".github/workflows"
    if not wf_root.is_dir():
        return rows
    for path in sorted(wf_root.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        automatic = [token for token in ("push:", "pull_request:", "schedule:") if token in text]
        if len(automatic) >= 2 and "workflow_dispatch:" in text:
            rows.append({"path": str(path.relative_to(root)), "automatic_triggers": automatic})
    return rows


def stage_count(root: Path) -> tuple[int | None, str | None]:
    source = root / "backend/tools/zel_pre_shadow_receipt_dag_v1.py"
    if not source.is_file():
        return None, "DAG_TOOL_MISSING"
    spec = importlib.util.spec_from_file_location("zel_dag", source)
    if spec is None or spec.loader is None:
        return None, "DAG_IMPORT_SPEC"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stages = getattr(module, "STAGES", None)
    if not isinstance(stages, list):
        return None, "DAG_STAGES_MISSING"
    return len(stages), None


def result_state(results_root: Path | None, relative: str) -> dict[str, Any]:
    if results_root is None:
        return {"exists": False, "state": None, "reason": "RESULTS_ROOT_NOT_PROVIDED"}
    payload = load_json_optional(results_root / relative)
    if payload is None:
        return {"exists": False, "state": None}
    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    return {
        "exists": True,
        "state": payload.get("state"),
        "action": payload.get("action") or safety.get("action"),
        "execution_authority": payload.get("execution_authority") or safety.get("execution_authority"),
        "order_authority": payload.get("order_authority") or safety.get("order_authority"),
        "errors": payload.get("errors", []),
    }


def build_audit(root: Path, results_root: Path | None) -> dict[str, Any]:
    missing = [name for name, rel in REQUIRED_LIGHTWEIGHT.items() if not (root / rel).is_file()]
    count, dag_error = stage_count(root)
    results = {
        "bingx": result_state(results_root, "runtime_results/zel/bingx_execution_evidence_collector_v1/latest.json"),
        "holdout": result_state(results_root, "runtime_results/zel/holdout_access_rehearsal_v1/latest.json"),
        "readiness": result_state(results_root, "runtime_results/zel/parallel_readiness_audit_v1/latest.json"),
        "alimi": result_state(results_root, "runtime_results/zel/alimi_feature_install_audit_v1/latest.json"),
        "data_b_1m_v2": result_state(results_root, "runtime_results/zel/data_b_1m_v2_watch_v1/latest.json"),
    }
    authority_errors = []
    for name, row in results.items():
        if not row["exists"]:
            continue
        if row.get("execution_authority") not in (None, "NONE"):
            authority_errors.append(f"{name}:EXECUTION_AUTHORITY")
        if row.get("order_authority") not in (None, "BLOCKED"):
            authority_errors.append(f"{name}:ORDER_AUTHORITY")
    duplicate = duplicate_groups(root)
    debris = debris_candidates(root)
    noise = workflow_noise_candidates(root)
    hard_errors = list(missing) + authority_errors
    if count != 13:
        hard_errors.append(f"DAG_STAGE_COUNT:{count}:{dag_error}")
    optimization = {
        "duplicate_exact_content_groups": duplicate,
        "debris_candidates": debris,
        "workflow_noise_candidates": noise,
        "cleanup_performed": False,
        "cleanup_allowed": False,
        "recommended_order": [
            "VERIFY_DUPLICATE_OWNERSHIP_BEFORE_DELETION",
            "QUARANTINE_DEBRIS_CANDIDATES",
            "REMOVE_REDUNDANT_AUTOMATIC_TRIGGERS_ONLY_AFTER_DAG_ROUTE_PROOF",
            "RE_RUN_READINESS_AND_OWNER_POLICY",
        ],
    }
    passed = not hard_errors
    return {
        "schema_version": "zel.composite_parallel_pipeline_audit.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_COMPOSITE_PARALLEL_PIPELINE_AUDIT" if passed else "HOLD_COMPOSITE_PARALLEL_PIPELINE_AUDIT",
        "required_file_count": len(REQUIRED_LIGHTWEIGHT),
        "missing_required_files": missing,
        "dag_stage_count": count,
        "dag_error": dag_error,
        "lightweight_lane_order": [
            "BINGX_VPS_CREDENTIAL_RESOLVER_AND_EXECUTION_EVIDENCE",
            "HOLDOUT_SEAL_ACCESS_REHEARSAL",
            "PRE_SHADOW_13_STAGE_FIXTURE_E2E",
            "ALIMI_BINDING_READ_ONLY_AUDIT",
        ],
        "result_snapshot": results,
        "authority_errors": authority_errors,
        "composite_factory": {
            "static_only": True,
            "factory_enabled": False,
            "activation_enabled": False,
            "rollback_checkpoint_required": True,
            "one_minute_terminal_required_for_economic_evaluation": True,
        },
        "optimization_and_cleanup_audit": optimization,
        "hard_errors": hard_errors,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for rel in REQUIRED_LIGHTWEIGHT.values():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.name == "zel_pre_shadow_receipt_dag_v1.py":
                path.write_text("STAGES=" + repr([{"id": f"S{i}"} for i in range(13)]) + "\n", encoding="utf-8")
            elif path.suffix == ".json":
                path.write_text("{}\n", encoding="utf-8")
            else:
                path.write_text("# fixture\n", encoding="utf-8")
        payload = build_audit(root, None)
        assert payload["state"] == "PASS_COMPOSITE_PARALLEL_PIPELINE_AUDIT", payload
        assert payload["dag_stage_count"] == 13
        assert payload["optimization_and_cleanup_audit"]["cleanup_performed"] is False
        assert payload["execution_authority"] == "NONE"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--results-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.root or not args.out:
        parser.error("root and out are required")
    payload = build_audit(args.root, args.results_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "missing": payload["missing_required_files"],
        "dag_stage_count": payload["dag_stage_count"],
    }, sort_keys=True))
    return 0 if payload["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
