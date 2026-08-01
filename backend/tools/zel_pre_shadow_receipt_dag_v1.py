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


def evaluate(results_root: Path) -> dict[str, Any]:
    stage_results: list[dict[str, Any]] = []
    passed: set[str] = set()
    first_blocked: str | None = None
    eligible_stage: str | None = None

    for stage in STAGES:
        path = results_root / stage["path"]
        prerequisites = list(stage.get("requires", []))
        prereq_pass = all(item in passed for item in prerequisites)
        row: dict[str, Any] = {
            "stage_id": stage["id"],
            "path": stage["path"],
            "prerequisites": prerequisites,
            "prerequisites_pass": prereq_pass,
            "exists": path.is_file(),
            "receipt_sha256": sha256_path(path) if path.is_file() else None,
            "state": None,
            "integrity_ok": False,
            "violations": [],
            "pass": False,
        }
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("OBJECT_REQUIRED")
                row["state"] = payload.get("state")
                row["integrity_ok"], row["violations"] = integrity_ok(payload)
                row["pass"] = prereq_pass and row["integrity_ok"] and state_allowed(stage, row["state"])
                if stage["id"] == "DATA_B_TERMINAL" and row["pass"]:
                    if payload.get("single_owner_proved") is not True:
                        row["pass"] = False
                        row["violations"].append("DATA_B_SINGLE_OWNER_NOT_PROVED")
                    if payload.get("intervals", {}).get("1m", {}).get("error_count") not in (0, None):
                        row["pass"] = False
                        row["violations"].append("DATA_B_1M_ERRORS_NONZERO")
            except Exception as exc:
                row["violations"].append(f"RECEIPT_PARSE_ERROR:{type(exc).__name__}:{exc}")
        if row["pass"]:
            passed.add(stage["id"])
        elif first_blocked is None:
            first_blocked = stage["id"]
            if prereq_pass and not path.is_file():
                eligible_stage = stage["id"]
        stage_results.append(row)

    complete = len(passed) == len(STAGES)
    state = "PASS_PRE_SHADOW_DAG_COMPLETE" if complete else "HOLD_PRE_SHADOW_DAG_INCOMPLETE"
    return {
        "schema_version": "zel.pre_shadow.receipt_dag.v1",
        "generated_at": now_iso(),
        "state": state,
        "ordered_stage_count": len(STAGES),
        "passed_stage_count": len(passed),
        "passed_stages": [stage["id"] for stage in STAGES if stage["id"] in passed],
        "first_blocked_stage": first_blocked,
        "eligible_next_stage": eligible_stage,
        "dispatch_policy": "ONE_ORDERED_STAGE_AT_A_TIME",
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


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        data_path = root / STAGES[0]["path"]
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(json.dumps({
            "state": "PASS",
            "single_owner_proved": True,
            "intervals": {"1m": {"error_count": 0}},
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_enabled": False,
        }))
        result = evaluate(root)
        assert result["passed_stages"] == ["DATA_B_TERMINAL"]
        assert result["eligible_next_stage"] == "RISK_MAIN_EFFECT"
        risk_path = root / STAGES[1]["path"]
        risk_path.parent.mkdir(parents=True, exist_ok=True)
        risk_path.write_text(json.dumps({
            "state": "PASS_DATA_B_RISK_ADAPTER_ABLATION",
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }))
        result = evaluate(root)
        assert result["passed_stage_count"] == 2
        assert result["eligible_next_stage"] == "EXACT25_LIVENESS_AND_REPAIR"
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
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
