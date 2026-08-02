from __future__ import annotations

import argparse
import ast
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_PARALLEL_READINESS_AUDIT_V1"

STATUS_PATHS = {
    "data_b_1m": "runtime_results/zel/data_b_1m_progress_probe_v2/latest.json",
    "stage_broker": "runtime_results/zel/ai_stage_authorization_broker_v1/latest.json",
    "holdout_audit": "runtime_results/zel/holdout_vault_audit_v1/latest.json",
    "pre_shadow_dag": "runtime_results/zel/pre_shadow_receipt_dag_v1/latest.json",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def load_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return load_json(path)
    except Exception as exc:
        return {
            "state": "HOLD_STATUS_PARSE_ERROR",
            "parse_error": f"{type(exc).__name__}:{exc}",
        }


def load_stages(stage_source: Path) -> list[dict[str, Any]]:
    tree = ast.parse(stage_source.read_text(encoding="utf-8"), filename=str(stage_source))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "STAGES" for target in targets):
                value = ast.literal_eval(node.value)
                if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
                    raise ValueError("STAGES_LIST_OF_OBJECTS_REQUIRED")
                return [dict(row) for row in value]
    raise ValueError("STAGES_ASSIGNMENT_NOT_FOUND")


def workflow_sources(workflows_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(workflows_root.glob("*.y*ml")):
        result[path.name] = path.read_text(encoding="utf-8", errors="replace")
    return result


def dispatch_mapping_present(controller_text: str, stage_id: str) -> bool:
    pattern = re.compile(
        rf"['\"]{re.escape(stage_id)}['\"]\s*:\s*\{{.*?['\"]workflow_file['\"]\s*:",
        re.DOTALL,
    )
    return bool(pattern.search(controller_text))


def producer_like_reference(text: str, expected_path: str) -> bool:
    parent = str(Path(expected_path).parent)
    if expected_path not in text and parent not in text:
        return False
    markers = (
        "git add",
        "write_text(",
        "cp out/",
        "mkdir -p",
        "atomic_json(",
    )
    return any(marker in text for marker in markers)


def receipt_reference_audit(
    stages: list[dict[str, Any]],
    workflows: Mapping[str, str],
    controller_text: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, stage in enumerate(stages):
        stage_id = str(stage["id"])
        expected_path = str(stage["path"])
        parent = str(Path(expected_path).parent)
        references = sorted(
            name for name, text in workflows.items()
            if expected_path in text or parent in text
        )
        producer_like = sorted(
            name for name, text in workflows.items()
            if producer_like_reference(text, expected_path)
        )
        dispatch_required = index > 0
        mapped = (not dispatch_required) or dispatch_mapping_present(controller_text, stage_id)
        violations: list[str] = []
        if not references:
            violations.append("EXPECTED_RECEIPT_PATH_UNREFERENCED")
        if not producer_like:
            violations.append("EXPECTED_RECEIPT_PRODUCER_NOT_PROVED")
        if dispatch_required and not mapped:
            violations.append("DAG_DISPATCH_MAPPING_MISSING")
        rows.append({
            "stage_index": index,
            "stage_id": stage_id,
            "expected_receipt_path": expected_path,
            "prerequisites": list(stage.get("requires", [])),
            "reference_workflows": references,
            "producer_like_workflows": producer_like,
            "dispatch_mapping_required": dispatch_required,
            "dispatch_mapping_present": mapped,
            "implementation_ready": not violations,
            "violations": violations,
        })
    return rows


def status_summary(results_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, relative in STATUS_PATHS.items():
        payload = load_json_optional(results_root / relative)
        result[key] = {
            "path": relative,
            "exists": payload is not None,
            "state": payload.get("state") if payload else None,
            "action": payload.get("action") if payload else None,
            "execution_authority": payload.get("execution_authority") if payload else None,
            "order_authority": payload.get("order_authority") if payload else None,
        }
        if key == "holdout_audit" and payload:
            result[key]["missing_config_names"] = list(payload.get("missing_config_names", []))
            result[key]["holdout_bytes_read"] = payload.get("holdout_bytes_read")
            result[key]["permissions_mutated"] = payload.get("permissions_mutated")
        if key == "data_b_1m" and payload:
            latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else {}
            integrity = payload.get("integrity") if isinstance(payload.get("integrity"), dict) else {}
            result[key]["process_count"] = latest.get("process_count")
            result[key]["single_owner"] = integrity.get("single_owner")
            result[key]["terminal_complete"] = integrity.get("terminal_complete")
            result[key]["cpu_delta_sec"] = payload.get("cpu_delta_sec")
    return result


def build_audit(control_root: Path, results_root: Path) -> dict[str, Any]:
    stage_source = control_root / "backend/tools/zel_pre_shadow_receipt_dag_v1.py"
    workflows_root = control_root / ".github/workflows"
    controller_path = workflows_root / "zel-pre-shadow-dag-controller-v1.yml"
    stages = load_stages(stage_source)
    workflows = workflow_sources(workflows_root)
    controller_text = controller_path.read_text(encoding="utf-8")
    stage_rows = receipt_reference_audit(stages, workflows, controller_text)
    statuses = status_summary(results_root)

    missing_dispatch = [row["stage_id"] for row in stage_rows if "DAG_DISPATCH_MAPPING_MISSING" in row["violations"]]
    unproved_producers = [row["stage_id"] for row in stage_rows if "EXPECTED_RECEIPT_PRODUCER_NOT_PROVED" in row["violations"]]
    unreferenced_paths = [row["stage_id"] for row in stage_rows if "EXPECTED_RECEIPT_PATH_UNREFERENCED" in row["violations"]]
    first_gap = next((row["stage_id"] for row in stage_rows if row["violations"]), None)
    holdout_missing = list(statuses.get("holdout_audit", {}).get("missing_config_names", []))

    parallel_work: list[dict[str, Any]] = []
    if missing_dispatch or unproved_producers or unreferenced_paths:
        parallel_work.append({
            "lane": "DOWNSTREAM_DAG_IMPLEMENTATION",
            "safe_now": True,
            "scope": "STATIC_CONTROL_PLANE_ONLY",
            "targets": list(dict.fromkeys(missing_dispatch + unproved_producers + unreferenced_paths))[:5],
            "next": "READ_ONLY_DIAGNOSIS_THEN_ONE_STAGE_MINIMAL_IMPLEMENTATION",
        })
    if holdout_missing:
        parallel_work.append({
            "lane": "HOLDOUT_CONFIGURATION_PREFLIGHT",
            "safe_now": True,
            "scope": "CONFIG_NAMES_AND_EXTERNAL_PATH_METADATA_ONLY",
            "targets": holdout_missing,
            "next": "CONFIGURE_VARIABLES_AND_SECRET_THEN_RUN_READ_ONLY_AUDIT",
        })
    parallel_work.append({
        "lane": "DATA_B_TERMINAL_WATCH",
        "safe_now": True,
        "scope": "READ_ONLY_RECEIPT_MONITORING",
        "targets": ["DATA_B_TERMINAL"],
        "next": "DO_NOT_RESTART_OR_DUPLICATE_OWNER",
    })

    complete = not (missing_dispatch or unproved_producers or unreferenced_paths or holdout_missing)
    return {
        "schema_version": "zel.parallel_readiness.audit.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_PARALLEL_READINESS_COMPLETE" if complete else "HOLD_PARALLEL_READINESS_GAPS",
        "ordered_stage_count": len(stage_rows),
        "implementation_ready_count": sum(1 for row in stage_rows if row["implementation_ready"]),
        "first_static_gap": first_gap,
        "missing_dispatch_stage_ids": missing_dispatch,
        "unproved_producer_stage_ids": unproved_producers,
        "unreferenced_receipt_stage_ids": unreferenced_paths,
        "stage_results": stage_rows,
        "status_snapshot": statuses,
        "parallel_work_available": parallel_work,
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
        control = root / "control"
        results = root / "results"
        workflows = control / ".github/workflows"
        tools = control / "backend/tools"
        workflows.mkdir(parents=True)
        tools.mkdir(parents=True)
        results.mkdir()
        (tools / "zel_pre_shadow_receipt_dag_v1.py").write_text(
            "STAGES=["
            "{'id':'DATA_B_TERMINAL','path':'runtime_results/a/latest.json','requires':[]},"
            "{'id':'RISK_MAIN_EFFECT','path':'runtime_results/b/latest.json','requires':['DATA_B_TERMINAL']},"
            "{'id':'COMPONENT_MAIN_EFFECT','path':'runtime_results/c/latest.json','requires':['RISK_MAIN_EFFECT']}"
            "]\n",
            encoding="utf-8",
        )
        (workflows / "zel-pre-shadow-dag-controller-v1.yml").write_text(
            "mapping={'RISK_MAIN_EFFECT':{'workflow_file':'risk.yml'}}\n",
            encoding="utf-8",
        )
        (workflows / "risk.yml").write_text(
            "root=results/runtime_results/b\nmkdir -p $root\ngit add runtime_results/b\n",
            encoding="utf-8",
        )
        audit = build_audit(control, results)
        assert audit["state"] == "HOLD_PARALLEL_READINESS_GAPS", audit
        assert "COMPONENT_MAIN_EFFECT" in audit["missing_dispatch_stage_ids"], audit
        assert "COMPONENT_MAIN_EFFECT" in audit["unreferenced_receipt_stage_ids"], audit
        assert audit["execution_authority"] == "NONE"
        assert audit["order_authority"] == "BLOCKED"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-root", type=Path)
    parser.add_argument("--results-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.control_root or not args.results_root or not args.out:
        parser.error("control-root, results-root and out are required")
    payload = build_audit(args.control_root, args.results_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "ready": payload["implementation_ready_count"],
        "total": payload["ordered_stage_count"],
        "first_gap": payload["first_static_gap"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
