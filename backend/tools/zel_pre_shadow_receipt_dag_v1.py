from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

STAGES = [
    {
        "id": "DATA_B_TERMINAL",
        "path": "runtime_results/zel/historical_oos_exact25_replay_v1/combined_latest.json",
        "states": ["PASS"],
        "requires": [],
    },
    {
        "id": "RISK_MAIN_EFFECT",
        "path": "runtime_results/zel/data_b_risk_adapter_ablation_v1/latest.json",
        "states": ["PASS_DATA_B_RISK_ADAPTER_ABLATION"],
        "requires": ["DATA_B_TERMINAL"],
    },
    {
        "id": "EXACT25_LIVENESS_AND_REPAIR",
        "path": "runtime_results/zel/exact25_material_upgrade_v1/latest.json",
        "states": ["PASS_EXACT25_MATERIAL_DIAGNOSIS_AND_QUEUE"],
        "requires": ["RISK_MAIN_EFFECT"],
    },
    {
        "id": "TRADE_METHOD_COVERAGE",
        "path": "runtime_results/zel/trade_methods_pre_shadow_v1/latest.json",
        "state_prefixes": ["PASS_"],
        "requires": ["EXACT25_LIVENESS_AND_REPAIR"],
    },
    {
        "id": "COMPONENT_MAIN_EFFECT",
        "path": "runtime_results/zel/component_main_effect_v1/latest.json",
        "states": ["PASS_COMPONENT_MAIN_EFFECT_COMPLETE"],
        "requires": ["TRADE_METHOD_COVERAGE"],
    },
    {
        "id": "SELECTED_INTERACTIONS",
        "path": "runtime_results/zel/selected_interactions_v1/latest.json",
        "states": ["PASS_SELECTED_INTERACTIONS_COMPLETE"],
        "requires": ["COMPONENT_MAIN_EFFECT"],
    },
    {
        "id": "STRATEGY_TOP3_BUNDLES",
        "path": "runtime_results/zel/strategy_top3_bundles_v1/latest.json",
        "states": ["PASS_STRATEGY_TOP3_BUNDLES_COMPLETE"],
        "requires": ["SELECTED_INTERACTIONS"],
    },
    {
        "id": "ALPHA_LAP_CHALLENGERS",
        "path": "runtime_results/zel/alpha_lap_v2/challengers_latest.json",
        "states": ["PASS_ALPHA_LAP_CHALLENGERS_REGISTERED"],
        "requires": ["STRATEGY_TOP3_BUNDLES"],
    },
    {
        "id": "W2_FORWARD",
        "path": "runtime_results/zel/w2_forward_v1/latest.json",
        "states": ["PASS_W2_FORWARD"],
        "requires": ["ALPHA_LAP_CHALLENGERS"],
    },
    {
        "id": "W3_DURABILITY",
        "path": "runtime_results/zel/w3_durability_v1/latest.json",
        "states": ["PASS_W3_DURABILITY"],
        "requires": ["W2_FORWARD"],
    },
    {
        "id": "PORTFOLIO_JOINT_RISK",
        "path": "runtime_results/zel/portfolio_joint_risk_v1/latest.json",
        "states": ["PASS_PORTFOLIO_JOINT_RISK"],
        "requires": ["W3_DURABILITY"],
    },
    {
        "id": "ROLLBACK_REHEARSAL",
        "path": "runtime_results/zel/rollback_rehearsal_v1/latest.json",
        "states": ["PASS_ROLLBACK_REHEARSAL"],
        "requires": ["PORTFOLIO_JOINT_RISK"],
    },
    {
        "id": "PRE_SHADOW_RELEASE",
        "path": "runtime_results/zel/pre_shadow_release_v1/latest.json",
        "states": ["PASS_PRE_SHADOW_RELEASE"],
        "requires": ["ROLLBACK_REHEARSAL"],
    },
]

LINEAGE_ROOT = "runtime_results/zel/pre_shadow_lineage_v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        temp = Path(handle.name)
    temp.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def state_allowed(stage: Mapping[str, Any], state: Any) -> bool:
    if state in stage.get("states", []):
        return True
    text = str(state or "")
    return any(text.startswith(prefix) for prefix in stage.get("state_prefixes", []))


def integrity_ok(payload: Mapping[str, Any]) -> tuple[bool, list[str]]:
    violations: list[str] = []
    if payload.get("execution_authority") not in (None, "NONE"):
        violations.append("EXECUTION_AUTHORITY_NOT_NONE")
    if payload.get("order_authority") not in (None, "BLOCKED"):
        violations.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if payload.get("promotion_authority") is True:
        violations.append("PROMOTION_AUTHORITY_TRUE")
    if payload.get("live_enabled") is True:
        violations.append("LIVE_ENABLED_TRUE")
    return not violations, violations


def binding_path(results_root: Path, stage_id: str) -> Path:
    return results_root / LINEAGE_ROOT / f"{stage_id.lower()}.json"


def validate_lineage(
    results_root: Path,
    stage: Mapping[str, Any],
    row: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, dict[str, Any], list[str]]:
    prerequisites = list(stage.get("requires", []))
    if not prerequisites:
        return True, {"required": False}, []
    predecessor_id = prerequisites[-1]
    predecessor = rows_by_id.get(predecessor_id)
    violations: list[str] = []
    info: dict[str, Any] = {
        "required": True,
        "predecessor_stage_id": predecessor_id,
        "binding_path": str(binding_path(results_root, str(stage["id"])).relative_to(results_root)),
        "binding_exists": False,
        "binding_sha256": None,
        "binding_state": None,
    }
    if not predecessor or not predecessor.get("pass"):
        violations.append("PREDECESSOR_NOT_PASSED")
        return False, info, violations
    path = binding_path(results_root, str(stage["id"]))
    if not path.is_file():
        violations.append("LINEAGE_BINDING_MISSING")
        return False, info, violations
    info["binding_exists"] = True
    info["binding_sha256"] = sha256_path(path)
    try:
        binding = load_json(path)
    except Exception as exc:
        violations.append(f"LINEAGE_BINDING_PARSE_ERROR:{type(exc).__name__}:{exc}")
        return False, info, violations
    info["binding_state"] = binding.get("state")
    expected = {
        "state": "PASS_STAGE_LINEAGE_BOUND",
        "stage_id": stage["id"],
        "predecessor_stage_id": predecessor_id,
        "predecessor_receipt_sha256": predecessor.get("receipt_sha256"),
        "stage_receipt_sha256": row.get("receipt_sha256"),
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            violations.append(f"LINEAGE_{key.upper()}_MISMATCH")
    binding_integrity, binding_violations = integrity_ok(binding)
    if not binding_integrity:
        violations.extend(f"BINDING_{item}" for item in binding_violations)
    return not violations, info, violations


def evaluate(results_root: Path) -> dict[str, Any]:
    stage_results: list[dict[str, Any]] = []
    rows_by_id: dict[str, dict[str, Any]] = {}
    passed: set[str] = set()
    first_blocked: str | None = None
    eligible_stage: str | None = None
    retry_reason: str | None = None

    for stage in STAGES:
        stage_id = str(stage["id"])
        path = results_root / str(stage["path"])
        prerequisites = list(stage.get("requires", []))
        prereq_pass = all(item in passed for item in prerequisites)
        row: dict[str, Any] = {
            "stage_id": stage_id,
            "path": stage["path"],
            "prerequisites": prerequisites,
            "prerequisites_pass": prereq_pass,
            "exists": path.is_file(),
            "receipt_sha256": sha256_path(path) if path.is_file() else None,
            "state": None,
            "parse_ok": False,
            "integrity_ok": False,
            "state_allowed": False,
            "lineage_ok": not prerequisites,
            "lineage": {"required": bool(prerequisites)},
            "violations": [],
            "pass": False,
            "retry_eligible": False,
        }
        if path.is_file():
            try:
                payload = load_json(path)
                row["parse_ok"] = True
                row["state"] = payload.get("state")
                row["integrity_ok"], integrity_violations = integrity_ok(payload)
                row["violations"].extend(integrity_violations)
                row["state_allowed"] = state_allowed(stage, row["state"])
                basic_pass = prereq_pass and row["integrity_ok"] and row["state_allowed"]
                if stage_id == "DATA_B_TERMINAL" and basic_pass:
                    if payload.get("single_owner_proved") is not True:
                        basic_pass = False
                        row["violations"].append("DATA_B_SINGLE_OWNER_NOT_PROVED")
                    if payload.get("intervals", {}).get("1m", {}).get("error_count") not in (0, None):
                        basic_pass = False
                        row["violations"].append("DATA_B_1M_ERRORS_NONZERO")
                if basic_pass:
                    lineage_ok, lineage_info, lineage_violations = validate_lineage(
                        results_root, stage, row, rows_by_id
                    )
                    row["lineage_ok"] = lineage_ok
                    row["lineage"] = lineage_info
                    row["violations"].extend(lineage_violations)
                row["pass"] = basic_pass and row["lineage_ok"]
                row["retry_eligible"] = (
                    prereq_pass
                    and row["parse_ok"]
                    and row["integrity_ok"]
                    and not row["pass"]
                )
            except Exception as exc:
                row["violations"].append(f"RECEIPT_PARSE_ERROR:{type(exc).__name__}:{exc}")
        else:
            row["retry_eligible"] = prereq_pass

        if row["pass"]:
            passed.add(stage_id)
        elif first_blocked is None:
            first_blocked = stage_id
            if row["retry_eligible"]:
                eligible_stage = stage_id
                if not row["exists"]:
                    retry_reason = "MISSING_RECEIPT"
                elif not row["state_allowed"]:
                    retry_reason = "SAFE_NON_PASSING_RECEIPT"
                elif not row["lineage_ok"]:
                    retry_reason = "MISSING_OR_STALE_LINEAGE_BINDING"
                else:
                    retry_reason = "SAFE_RETRY_REQUIRED"
        stage_results.append(row)
        rows_by_id[stage_id] = row

    complete = len(passed) == len(STAGES)
    state = "PASS_PRE_SHADOW_DAG_COMPLETE" if complete else "HOLD_PRE_SHADOW_DAG_INCOMPLETE"
    return {
        "schema_version": "zel.pre_shadow.receipt_dag.v2",
        "generated_at": now_iso(),
        "state": state,
        "ordered_stage_count": len(STAGES),
        "passed_stage_count": len(passed),
        "passed_stages": [stage["id"] for stage in STAGES if stage["id"] in passed],
        "first_blocked_stage": first_blocked,
        "eligible_next_stage": eligible_stage,
        "eligible_reason": retry_reason,
        "dispatch_policy": "ONE_ORDERED_STAGE_AT_A_TIME",
        "lineage_policy": "CURRENT_PREDECESSOR_AND_STAGE_RECEIPT_SHA_REQUIRED",
        "safe_non_passing_receipt_retry": True,
        "parallelism_scope": "INTERNAL_TO_COMPONENT_MAIN_EFFECT_ONLY",
        "stage_results": stage_results,
        "shadow_start_allowed": complete,
        "paper_start_allowed": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), sort_keys=True) + "\n", encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        data_path = root / STAGES[0]["path"]
        write_receipt(data_path, {
            "state": "PASS",
            "single_owner_proved": True,
            "intervals": {"1m": {"error_count": 0}},
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_enabled": False,
        })
        result = evaluate(root)
        assert result["passed_stages"] == ["DATA_B_TERMINAL"]
        assert result["eligible_next_stage"] == "RISK_MAIN_EFFECT"
        assert result["eligible_reason"] == "MISSING_RECEIPT"

        risk_path = root / STAGES[1]["path"]
        write_receipt(risk_path, {
            "state": "WAIT_RISK_RETRY",
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        })
        result = evaluate(root)
        assert result["eligible_next_stage"] == "RISK_MAIN_EFFECT"
        assert result["eligible_reason"] == "SAFE_NON_PASSING_RECEIPT"

        write_receipt(risk_path, {
            "state": "PASS_DATA_B_RISK_ADAPTER_ABLATION",
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        })
        result = evaluate(root)
        assert result["passed_stage_count"] == 1
        assert result["eligible_next_stage"] == "RISK_MAIN_EFFECT"
        assert result["eligible_reason"] == "MISSING_OR_STALE_LINEAGE_BINDING"

        lineage = binding_path(root, "RISK_MAIN_EFFECT")
        write_receipt(lineage, {
            "state": "PASS_STAGE_LINEAGE_BOUND",
            "stage_id": "RISK_MAIN_EFFECT",
            "predecessor_stage_id": "DATA_B_TERMINAL",
            "predecessor_receipt_sha256": sha256_path(data_path),
            "stage_receipt_sha256": sha256_path(risk_path),
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        })
        result = evaluate(root)
        assert result["passed_stage_count"] == 2
        assert result["eligible_next_stage"] == "EXACT25_LIVENESS_AND_REPAIR"

        write_receipt(data_path, {
            "state": "PASS",
            "single_owner_proved": True,
            "intervals": {"1m": {"error_count": 0}, "generation": 2},
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_enabled": False,
        })
        result = evaluate(root)
        assert result["passed_stage_count"] == 1
        assert result["eligible_next_stage"] == "RISK_MAIN_EFFECT"
        assert result["eligible_reason"] == "MISSING_OR_STALE_LINEAGE_BINDING"
    print(json.dumps({"state": "PASS_SELF_TEST", "stage_count": len(STAGES)}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.results_root or not args.out:
        parser.error("results-root and out are required")
    result = evaluate(Path(args.results_root).resolve())
    atomic_json(Path(args.out).resolve(), result)
    print(json.dumps({
        "state": result["state"],
        "passed_stage_count": result["passed_stage_count"],
        "first_blocked_stage": result["first_blocked_stage"],
        "eligible_next_stage": result["eligible_next_stage"],
        "eligible_reason": result["eligible_reason"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
