from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

STAGE_PATHS = {
    "DATA_B_TERMINAL": "runtime_results/zel/historical_oos_exact25_replay_v1/combined_latest.json",
    "RISK_MAIN_EFFECT": "runtime_results/zel/data_b_risk_adapter_ablation_v1/latest.json",
    "EXACT25_LIVENESS_AND_REPAIR": "runtime_results/zel/exact25_material_upgrade_v1/latest.json",
    "TRADE_METHOD_COVERAGE": "runtime_results/zel/trade_methods_pre_shadow_v1/latest.json",
    "COMPONENT_MAIN_EFFECT": "runtime_results/zel/component_main_effect_v1/latest.json",
    "SELECTED_INTERACTIONS": "runtime_results/zel/selected_interactions_v1/latest.json",
    "STRATEGY_TOP3_BUNDLES": "runtime_results/zel/strategy_top3_bundles_v1/latest.json",
    "ALPHA_LAP_CHALLENGERS": "runtime_results/zel/alpha_lap_v2/challengers_latest.json",
    "W2_FORWARD": "runtime_results/zel/w2_forward_v1/latest.json",
    "W3_DURABILITY": "runtime_results/zel/w3_durability_v1/latest.json",
    "PORTFOLIO_JOINT_RISK": "runtime_results/zel/portfolio_joint_risk_v1/latest.json",
    "ROLLBACK_REHEARSAL": "runtime_results/zel/rollback_rehearsal_v1/latest.json",
    "PRE_SHADOW_RELEASE": "runtime_results/zel/pre_shadow_release_v1/latest.json",
}

PREDECESSOR = {
    "RISK_MAIN_EFFECT": "DATA_B_TERMINAL",
    "EXACT25_LIVENESS_AND_REPAIR": "RISK_MAIN_EFFECT",
    "TRADE_METHOD_COVERAGE": "EXACT25_LIVENESS_AND_REPAIR",
    "COMPONENT_MAIN_EFFECT": "TRADE_METHOD_COVERAGE",
    "SELECTED_INTERACTIONS": "COMPONENT_MAIN_EFFECT",
    "STRATEGY_TOP3_BUNDLES": "SELECTED_INTERACTIONS",
    "ALPHA_LAP_CHALLENGERS": "STRATEGY_TOP3_BUNDLES",
    "W2_FORWARD": "ALPHA_LAP_CHALLENGERS",
    "W3_DURABILITY": "W2_FORWARD",
    "PORTFOLIO_JOINT_RISK": "W3_DURABILITY",
    "ROLLBACK_REHEARSAL": "PORTFOLIO_JOINT_RISK",
    "PRE_SHADOW_RELEASE": "ROLLBACK_REHEARSAL",
}

WORKFLOW_TO_STAGE = {
    "ZEL Data B Risk Adapter Ablation V1": "RISK_MAIN_EFFECT",
    "ZEL Exact25 Material Upgrade Loop V1": "EXACT25_LIVENESS_AND_REPAIR",
    "ZEL Trade Methods Pre-Shadow Audit V1": "TRADE_METHOD_COVERAGE",
    "ZEL Component Main Effect V1": "COMPONENT_MAIN_EFFECT",
    "ZEL Selected Interactions V1": "SELECTED_INTERACTIONS",
    "ZEL Strategy Top3 Bundles V1": "STRATEGY_TOP3_BUNDLES",
    "ZEL Alpha Lap V2 Challengers V1": "ALPHA_LAP_CHALLENGERS",
    "ZEL W2 Forward V1": "W2_FORWARD",
    "ZEL W3 Durability V1": "W3_DURABILITY",
    "ZEL Portfolio Joint Risk V1": "PORTFOLIO_JOINT_RISK",
    "ZEL Rollback Rehearsal V1": "ROLLBACK_REHEARSAL",
    "ZEL Pre-Shadow Release V1": "PRE_SHADOW_RELEASE",
}

LINEAGE_ROOT = Path("runtime_results/zel/pre_shadow_lineage_v1")
EXPECTATION = LINEAGE_ROOT / "expectation_latest.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        temp = Path(handle.name)
    temp.replace(path)


def stage_path(results_root: Path, stage_id: str) -> Path:
    if stage_id not in STAGE_PATHS:
        raise RuntimeError(f"UNKNOWN_STAGE:{stage_id}")
    return results_root / STAGE_PATHS[stage_id]


def binding_path(results_root: Path, stage_id: str) -> Path:
    return results_root / LINEAGE_ROOT / f"{stage_id.lower()}.json"


def expectation_path(results_root: Path) -> Path:
    return results_root / EXPECTATION


def create_expectation(
    results_root: Path,
    dag_path: Path,
    stage_id: str,
    workflow_name: str,
    controller_run_id: str,
) -> dict[str, Any]:
    dag = load_json(dag_path)
    if dag.get("eligible_next_stage") != stage_id:
        raise RuntimeError(f"DAG_STAGE_NOT_ELIGIBLE:{dag.get('eligible_next_stage')}!={stage_id}")
    predecessor_id = PREDECESSOR.get(stage_id)
    if not predecessor_id:
        raise RuntimeError(f"STAGE_HAS_NO_PREDECESSOR:{stage_id}")
    predecessor = stage_path(results_root, predecessor_id)
    if not predecessor.is_file():
        raise RuntimeError(f"PREDECESSOR_RECEIPT_MISSING:{predecessor}")
    current = stage_path(results_root, stage_id)
    payload = {
        "schema_version": "zel.pre_shadow.lineage.expectation.v1",
        "generated_at": now_iso(),
        "state": "DISPATCH_INTENT",
        "stage_id": stage_id,
        "workflow_name": workflow_name,
        "controller_run_id": str(controller_run_id),
        "predecessor_stage_id": predecessor_id,
        "predecessor_receipt_sha256": sha256_path(predecessor),
        "previous_stage_receipt_sha256": sha256_path(current) if current.is_file() else None,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    atomic_json(expectation_path(results_root), payload)
    return payload


def bind_completed_event(results_root: Path, event_path: Path) -> dict[str, Any]:
    event = load_json(event_path)
    workflow_run = event.get("workflow_run")
    if not isinstance(workflow_run, dict):
        return {"state": "NOOP_NOT_WORKFLOW_RUN"}
    workflow_name = str(workflow_run.get("name") or "")
    stage_id = WORKFLOW_TO_STAGE.get(workflow_name)
    if not stage_id:
        return {"state": "NOOP_UNMAPPED_WORKFLOW", "workflow_name": workflow_name}
    if workflow_run.get("conclusion") != "success":
        return {
            "state": "HOLD_WORKFLOW_NOT_SUCCESS",
            "workflow_name": workflow_name,
            "stage_id": stage_id,
            "conclusion": workflow_run.get("conclusion"),
        }
    expected_path = expectation_path(results_root)
    if not expected_path.is_file():
        return {"state": "HOLD_EXPECTATION_MISSING", "workflow_name": workflow_name, "stage_id": stage_id}
    expected = load_json(expected_path)
    if expected.get("stage_id") != stage_id or expected.get("workflow_name") != workflow_name:
        return {
            "state": "HOLD_EXPECTATION_MISMATCH",
            "workflow_name": workflow_name,
            "stage_id": stage_id,
            "expected_stage_id": expected.get("stage_id"),
            "expected_workflow_name": expected.get("workflow_name"),
        }
    created_at = parse_time(workflow_run.get("created_at") or workflow_run.get("run_started_at"))
    expected_at = parse_time(expected.get("generated_at"))
    if not created_at or not expected_at or created_at < expected_at:
        return {
            "state": "HOLD_WORKFLOW_PREDATES_EXPECTATION",
            "workflow_name": workflow_name,
            "stage_id": stage_id,
        }

    predecessor_id = PREDECESSOR[stage_id]
    predecessor = stage_path(results_root, predecessor_id)
    receipt = stage_path(results_root, stage_id)
    if not predecessor.is_file() or not receipt.is_file():
        return {
            "state": "HOLD_LINEAGE_RECEIPT_MISSING",
            "workflow_name": workflow_name,
            "stage_id": stage_id,
            "predecessor_exists": predecessor.is_file(),
            "receipt_exists": receipt.is_file(),
        }
    predecessor_sha = sha256_path(predecessor)
    receipt_sha = sha256_path(receipt)
    if predecessor_sha != expected.get("predecessor_receipt_sha256"):
        return {
            "state": "HOLD_PREDECESSOR_CHANGED_DURING_RUN",
            "workflow_name": workflow_name,
            "stage_id": stage_id,
            "expected_predecessor_sha256": expected.get("predecessor_receipt_sha256"),
            "current_predecessor_sha256": predecessor_sha,
        }
    if expected.get("previous_stage_receipt_sha256") == receipt_sha:
        return {
            "state": "HOLD_STAGE_RECEIPT_NOT_REFRESHED",
            "workflow_name": workflow_name,
            "stage_id": stage_id,
            "receipt_sha256": receipt_sha,
        }
    receipt_payload = load_json(receipt)
    receipt_generated_at = parse_time(receipt_payload.get("generated_at"))
    if not receipt_generated_at or receipt_generated_at < expected_at:
        return {
            "state": "HOLD_STAGE_RECEIPT_PREDATES_EXPECTATION",
            "workflow_name": workflow_name,
            "stage_id": stage_id,
        }

    binding = {
        "schema_version": "zel.pre_shadow.lineage.binding.v1",
        "generated_at": now_iso(),
        "state": "PASS_STAGE_LINEAGE_BOUND",
        "stage_id": stage_id,
        "workflow_name": workflow_name,
        "workflow_run_id": str(workflow_run.get("id") or ""),
        "workflow_head_sha": workflow_run.get("head_sha"),
        "controller_run_id": expected.get("controller_run_id"),
        "predecessor_stage_id": predecessor_id,
        "predecessor_receipt_sha256": predecessor_sha,
        "stage_receipt_sha256": receipt_sha,
        "stage_receipt_generated_at": receipt_payload.get("generated_at"),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    atomic_json(binding_path(results_root, stage_id), binding)
    atomic_json(expected_path, {
        **expected,
        "state": "BOUND",
        "bound_at": binding["generated_at"],
        "workflow_run_id": binding["workflow_run_id"],
        "stage_receipt_sha256": receipt_sha,
    })
    return binding


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        data = stage_path(root, "DATA_B_TERMINAL")
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text(json.dumps({"state": "PASS", "generated_at": "2026-01-01T00:00:00+00:00"}))
        dag = root / "dag.json"
        dag.write_text(json.dumps({"eligible_next_stage": "RISK_MAIN_EFFECT"}))
        expectation = create_expectation(root, dag, "RISK_MAIN_EFFECT", "ZEL Data B Risk Adapter Ablation V1", "1")
        assert expectation["predecessor_receipt_sha256"] == sha256_path(data)
        risk = stage_path(root, "RISK_MAIN_EFFECT")
        risk.parent.mkdir(parents=True, exist_ok=True)
        risk.write_text(json.dumps({
            "state": "PASS_DATA_B_RISK_ADAPTER_ABLATION",
            "generated_at": "2026-01-01T00:02:00+00:00",
        }))
        event = root / "event.json"
        event.write_text(json.dumps({"workflow_run": {
            "name": "ZEL Data B Risk Adapter Ablation V1",
            "id": 99,
            "head_sha": "abc",
            "conclusion": "success",
            "created_at": "2026-01-01T00:01:00+00:00",
        }}))
        bound = bind_completed_event(root, event)
        assert bound["state"] == "PASS_STAGE_LINEAGE_BOUND", bound
        assert binding_path(root, "RISK_MAIN_EFFECT").is_file()
    print(json.dumps({"state": "PASS_SELF_TEST"}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("expect", "bind"))
    parser.add_argument("--results-root")
    parser.add_argument("--dag")
    parser.add_argument("--stage-id")
    parser.add_argument("--workflow-name")
    parser.add_argument("--controller-run-id")
    parser.add_argument("--event-path")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.mode or not args.results_root or not args.out:
        parser.error("mode, results-root and out are required")
    root = Path(args.results_root).resolve()
    if args.mode == "expect":
        if not args.dag or not args.stage_id or not args.workflow_name or not args.controller_run_id:
            parser.error("dag, stage-id, workflow-name and controller-run-id are required for expect")
        result = create_expectation(
            root,
            Path(args.dag).resolve(),
            args.stage_id,
            args.workflow_name,
            args.controller_run_id,
        )
    else:
        if not args.event_path:
            parser.error("event-path is required for bind")
        result = bind_completed_event(root, Path(args.event_path).resolve())
    atomic_json(Path(args.out).resolve(), result)
    print(json.dumps({"state": result.get("state"), "stage_id": result.get("stage_id")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
