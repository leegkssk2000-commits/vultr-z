from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_COMPOSITE_PARALLEL_PIPELINE_AUDIT_V2"
EXCLUDED_PARTS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "quarantine", "archive", "archives", "backup", "backups",
}
DEBRIS_SUFFIXES = {".bak", ".old", ".orig", ".rej", ".tmp", ".swp", ".pyc", ".pyo"}
EXPECTED = {
    "composite": {
        "path": "runtime_results/zel/composite_module_factory_v2/latest.json",
        "pass_states": {"PASS_COMPOSITE_FACTORY_V2_STATIC_READY"},
        "hold_states": set(),
        "required": True,
    },
    "bingx": {
        "path": "runtime_results/zel/bingx_execution_evidence_collector_v1/latest.json",
        "pass_states": {"PASS_BINGX_READ_ONLY_EVIDENCE_COLLECTED"},
        "hold_states": {"HOLD_BINGX_READ_ONLY_CREDENTIALS_MISSING"},
        "required": True,
    },
    "holdout": {
        "path": "runtime_results/zel/holdout_access_rehearsal_v2/latest.json",
        "pass_states": {"PASS_HOLDOUT_VAULT_AUDIT_READY_TO_SEAL"},
        "hold_states": set(),
        "required": True,
    },
    "fixture": {
        "path": "runtime_results/zel/pre_shadow_fixture_e2e_v2/latest.json",
        "pass_states": {"PASS_P0_RUNTIME_E2E_CLOSURE"},
        "hold_states": set(),
        "required": True,
    },
    "alimi": {
        "path": "runtime_results/zel/alimi_binding_read_only_audit_v2/latest.json",
        "pass_states": {"PASS_READ_ONLY_ALIMI_BINDING_AUDIT_V2"},
        "hold_states": {"HOLD_ACTIVE_ALIMI_HTML_NOT_FOUND"},
        "required": True,
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "MISSING"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None, "NON_OBJECT_JSON"
        return payload, None
    except Exception as exc:
        return None, f"JSON_PARSE_ERROR:{type(exc).__name__}:{exc}"


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
        size = path.stat().st_size
        if size <= 0 or size > 2_000_000:
            continue
        groups.setdefault(sha_path(path), []).append(str(rel))
    return [
        {"sha256": digest, "count": len(paths), "paths": sorted(paths)}
        for digest, paths in sorted(groups.items())
        if len(paths) > 1
    ][:300]


def debris_candidates(root: Path) -> list[str]:
    return sorted({
        str(rel) for path, rel in repo_files(root)
        if path.suffix.lower() in DEBRIS_SUFFIXES
    })[:1000]


def workflow_noise_candidates(root: Path) -> list[dict[str, Any]]:
    rows = []
    wf_root = root / ".github/workflows"
    if not wf_root.is_dir():
        return rows
    for path in sorted(wf_root.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        header = text.split("\njobs:", 1)[0]
        automatic = [token.rstrip(":") for token in ("push:", "pull_request:", "schedule:") if token in header]
        if len(automatic) >= 2 and "workflow_dispatch:" in header:
            rows.append({"path": str(path.relative_to(root)), "automatic_triggers": automatic})
    return rows


def dag_count(root: Path) -> tuple[int | None, str | None]:
    path = root / "backend/tools/zel_pre_shadow_receipt_dag_v1.py"
    if not path.is_file():
        return None, "DAG_TOOL_MISSING"
    try:
        spec = importlib.util.spec_from_file_location("zel_dag_audit_v2", path)
        if spec is None or spec.loader is None:
            return None, "DAG_IMPORT_SPEC"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stages = getattr(module, "STAGES", None)
        if not isinstance(stages, list):
            return None, "DAG_STAGES_MISSING"
        return len(stages), None
    except Exception as exc:
        return None, f"DAG_IMPORT_ERROR:{type(exc).__name__}:{exc}"


def lane_snapshot(results_root: Path, name: str, contract: dict[str, Any]) -> dict[str, Any]:
    path = results_root / contract["path"]
    payload, parse_error = load_json(path)
    row: dict[str, Any] = {
        "name": name,
        "path": contract["path"],
        "exists": path.is_file(),
        "receipt_sha256": sha_path(path) if path.is_file() else None,
        "parse_error": parse_error,
        "state": payload.get("state") if payload else None,
        "classification": "ERROR",
        "execution_authority": None,
        "order_authority": None,
        "action": None,
        "errors": [],
    }
    if payload is None:
        row["errors"].append(parse_error or "PAYLOAD_MISSING")
        return row
    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    row["execution_authority"] = payload.get("execution_authority") or safety.get("execution_authority")
    row["order_authority"] = payload.get("order_authority") or safety.get("order_authority")
    row["action"] = payload.get("action") or safety.get("action")
    state = row["state"]
    if state in contract["pass_states"]:
        row["classification"] = "PASS"
    elif state in contract["hold_states"]:
        row["classification"] = "HOLD"
    else:
        row["errors"].append(f"UNEXPECTED_STATE:{state}")
    if row["execution_authority"] != "NONE":
        row["errors"].append("EXECUTION_AUTHORITY_NOT_NONE")
    if row["order_authority"] != "BLOCKED":
        row["errors"].append("ORDER_AUTHORITY_NOT_BLOCKED")
    return row


def build(root: Path, results_root: Path) -> dict[str, Any]:
    lanes = {name: lane_snapshot(results_root, name, contract) for name, contract in EXPECTED.items()}
    hard_errors: list[str] = []
    blockers: list[str] = []
    for name, row in lanes.items():
        if row["errors"]:
            hard_errors.extend(f"{name}:{error}" for error in row["errors"])
        elif row["classification"] == "HOLD":
            blockers.append(f"{name}:{row['state']}")
    count, dag_error = dag_count(root)
    if count != 13:
        hard_errors.append(f"DAG_STAGE_COUNT:{count}:{dag_error}")

    composite_path = results_root / EXPECTED["composite"]["path"]
    composite_payload, _ = load_json(composite_path)
    module_optimization = {
        "factory_version": composite_payload.get("version") if composite_payload else None,
        "candidate_count": composite_payload.get("candidate_count") if composite_payload else None,
        "rejected_count": composite_payload.get("rejected_count") if composite_payload else None,
        "invalid_first_child_count": composite_payload.get("invalid_first_child_count") if composite_payload else None,
        "placeholder_source_sha_count": composite_payload.get("placeholder_source_sha_count") if composite_payload else None,
        "source_rebinding_required_before_activation": (
            composite_payload.get("source_rebinding_required_before_activation") if composite_payload else None
        ),
        "activation_allowed": False,
        "economic_evaluation_deferred_until_1m_terminal": True,
    }
    if composite_payload and composite_payload.get("invalid_first_child_count") != 0:
        hard_errors.append("COMPOSITE_INVALID_FIRST_CHILD_NONZERO")

    if hard_errors:
        state = "HOLD_COMPOSITE_PARALLEL_PIPELINE_HARD_ERRORS"
    elif blockers:
        state = "HOLD_COMPOSITE_PARALLEL_PIPELINE_BLOCKED"
    else:
        state = "PASS_COMPOSITE_PARALLEL_PIPELINE_AUDIT_V2"

    return {
        "schema_version": "zel.composite_parallel_pipeline_audit.receipt.v2",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "dag_stage_count": count,
        "dag_error": dag_error,
        "lanes": lanes,
        "blockers": blockers,
        "hard_errors": sorted(set(hard_errors)),
        "module_optimization": module_optimization,
        "cleanup_audit": {
            "exact_duplicate_groups": duplicate_groups(root),
            "debris_candidates": debris_candidates(root),
            "workflow_noise_candidates": workflow_noise_candidates(root),
            "cleanup_performed": False,
            "deletion_authority": False,
            "recommended_action": "QUARANTINE_AFTER_OWNER_AND_ROUTE_VERIFICATION",
        },
        "rollback": {
            "pre_factory_checkpoint_ref": "pre-composite-factory-v1-20260802",
            "available": True,
            "activation_checkpoint_required": True,
            "master_force_reset_forbidden": True,
            "action": "rollback",
        },
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


def fixture_payload(state: str) -> dict[str, Any]:
    return {
        "state": state,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "repo"
        results = Path(temp) / "results"
        root.mkdir()
        dag = root / "backend/tools/zel_pre_shadow_receipt_dag_v1.py"
        dag.parent.mkdir(parents=True)
        dag.write_text("STAGES=" + repr([{"id": f"S{i}"} for i in range(13)]) + "\n", encoding="utf-8")
        states = {
            "composite": "PASS_COMPOSITE_FACTORY_V2_STATIC_READY",
            "bingx": "HOLD_BINGX_READ_ONLY_CREDENTIALS_MISSING",
            "holdout": "PASS_HOLDOUT_VAULT_AUDIT_READY_TO_SEAL",
            "fixture": "PASS_P0_RUNTIME_E2E_CLOSURE",
            "alimi": "HOLD_ACTIVE_ALIMI_HTML_NOT_FOUND",
        }
        for name, contract in EXPECTED.items():
            path = results / contract["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = fixture_payload(states[name])
            if name == "composite":
                payload.update({
                    "version": "fixture", "candidate_count": 2, "rejected_count": 1,
                    "invalid_first_child_count": 0, "placeholder_source_sha_count": 1,
                    "source_rebinding_required_before_activation": True,
                })
            path.write_text(json.dumps(payload), encoding="utf-8")
        receipt = build(root, results)
        assert receipt["state"] == "HOLD_COMPOSITE_PARALLEL_PIPELINE_BLOCKED", receipt
        assert len(receipt["blockers"]) == 2, receipt
        assert receipt["hard_errors"] == [], receipt
        bingx = results / EXPECTED["bingx"]["path"]
        bingx.write_text(json.dumps(fixture_payload("PASS_BINGX_READ_ONLY_EVIDENCE_COLLECTED")))
        alimi = results / EXPECTED["alimi"]["path"]
        alimi.write_text(json.dumps(fixture_payload("PASS_READ_ONLY_ALIMI_BINDING_AUDIT_V2")))
        receipt = build(root, results)
        assert receipt["state"] == "PASS_COMPOSITE_PARALLEL_PIPELINE_AUDIT_V2", receipt
        assert receipt["execution_authority"] == "NONE"
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
    if not args.root or not args.results_root or not args.out:
        parser.error("root, results-root and out are required")
    payload = build(args.root, args.results_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "blockers": payload["blockers"],
        "hard_errors": payload["hard_errors"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
