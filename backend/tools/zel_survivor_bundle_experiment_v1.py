from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_SURVIVOR_BUNDLE_EXPERIMENT_V1"
MAIN_COMPONENTS = (
    "TRADE_METHODS",
    "BEST_SINGLE_SKILL",
    "TEAM_POLICY",
    "ZBOT_ADVICE",
    "LICO_EXECUTION",
    "ZICO_OMS",
)
PAIR_INTERACTIONS = (
    ("TRADE_METHODS", "BEST_SINGLE_SKILL"),
    ("TRADE_METHODS", "TEAM_POLICY"),
    ("TEAM_POLICY", "ZBOT_ADVICE"),
    ("TRADE_METHODS", "LICO_EXECUTION"),
    ("TEAM_POLICY", "LICO_EXECUTION"),
    ("ZICO_OMS", "LICO_EXECUTION"),
    ("BEST_SINGLE_SKILL", "TEAM_POLICY"),
)
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "shadow_start_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "action": "hold",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def finite(value: Any, default: float = -math.inf) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_survivor(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str) and raw.strip():
        return {"strategy_id": raw.strip()}
    if not isinstance(raw, Mapping):
        return None
    strategy_id = str(raw.get("strategy_id") or raw.get("id") or raw.get("name") or "").strip()
    if not strategy_id:
        return None
    return {"strategy_id": strategy_id, **{str(key): value for key, value in raw.items() if key not in {"strategy_id", "id", "name"}}}


def candidate_lists(payload: Mapping[str, Any]) -> Iterable[Any]:
    for key in (
        "eligible",
        "material_ready_strategies",
        "survivors",
        "selected",
        "active_candidate_queue",
        "strategies",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            yield from value
            return


def survivor_score(row: Mapping[str, Any]) -> tuple[float, float, float, str]:
    expectancy = finite(row.get("expectancy_R") or row.get("expectancy_R_ex_funding"))
    profit_factor = finite(row.get("profit_factor") or row.get("profit_factor_ex_funding"))
    net_r = finite(row.get("net_R") or row.get("net_R_ex_funding"))
    return expectancy, profit_factor, net_r, str(row.get("strategy_id"))


def load_survivors(path: Path, maximum: int) -> list[dict[str, Any]]:
    payload = read_json(path)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in candidate_lists(payload):
        row = normalize_survivor(raw)
        if row is None:
            continue
        strategy_id = row["strategy_id"]
        if strategy_id in seen:
            continue
        seen.add(strategy_id)
        rows.append(row)
    rows.sort(key=survivor_score, reverse=True)
    return rows[:maximum]


def experiment_row(
    strategy_id: str,
    phase: str,
    components: list[str],
    *,
    interaction: bool = False,
    negative_control: bool = False,
    deferred: bool = False,
) -> dict[str, Any]:
    identity = {
        "strategy_id": strategy_id,
        "phase": phase,
        "components": sorted(components),
        "interaction": interaction,
        "negative_control": negative_control,
        "deferred": deferred,
    }
    return {
        "bundle_id": stable_sha(identity)[:16],
        **identity,
        "changed_axes": [] if phase == "BASE" else sorted(components),
        "exact_replay_required": not deferred,
        "data_b_15m_required": not deferred,
        "data_b_1m_required": not deferred,
        "w2_required_after_data_b_pass": not deferred,
        "w3_required_after_w2_pass": not deferred,
        "economic_claim_allowed": False,
        **SAFE,
    }


def build_rows(strategy_id: str) -> list[dict[str, Any]]:
    rows = [experiment_row(strategy_id, "BASE", [])]
    for component in MAIN_COMPONENTS:
        rows.append(experiment_row(strategy_id, "MAIN_EFFECT", [component]))
    rows.append(
        experiment_row(
            strategy_id,
            "NEGATIVE_CONTROL",
            ["ZLICE_LINEAGE"],
            negative_control=True,
        )
    )
    for left, right in PAIR_INTERACTIONS:
        rows.append(
            experiment_row(
                strategy_id,
                "PAIR_INTERACTION_SCREEN",
                [left, right],
                interaction=True,
            )
        )
    rows.extend(
        [
            experiment_row(
                strategy_id,
                "POST_300C_OBSERVER_ONLY",
                ["FAILURE_LEARNING"],
                deferred=True,
            ),
            experiment_row(
                strategy_id,
                "POST_300C_OBSERVER_ONLY",
                ["ML_LIGHT"],
                deferred=True,
            ),
            experiment_row(
                strategy_id,
                "POST_300C_OBSERVER_ONLY",
                ["FAILURE_LEARNING", "ML_LIGHT"],
                interaction=True,
                deferred=True,
            ),
        ]
    )
    return rows


def blocker_state(audit: Mapping[str, Any] | None) -> tuple[list[str], bool]:
    if not audit:
        return ["PRE_SHADOW_AUDIT_NOT_SUPPLIED"], False
    blockers = [str(value) for value in audit.get("blockers", [])]
    ready = not blockers and audit.get("state") == "PASS_TRADE_METHODS_PRE_SHADOW_STRUCTURE"
    return blockers, ready


def strategy_plan(row: Mapping[str, Any], *, audit_ready: bool, blockers: list[str]) -> dict[str, Any]:
    strategy_id = str(row["strategy_id"])
    experiments = build_rows(strategy_id)
    immediate = [item for item in experiments if not item["deferred"]]
    deferred = [item for item in experiments if item["deferred"]]
    result = {
        "strategy_id": strategy_id,
        "source_metrics": {key: value for key, value in row.items() if key != "strategy_id"},
        "state": "READY_FOR_BUNDLE_ADAPTER_REPLAY" if audit_ready else "HOLD_PRE_SHADOW_DEPENDENCY_GAPS",
        "blockers": blockers,
        "experiment_count": len(experiments),
        "immediate_experiment_count": len(immediate),
        "deferred_post_300c_count": len(deferred),
        "experiments": experiments,
        "selection_policy": {
            "main_effects_before_interactions": True,
            "pair_requires_nonnegative_main_effects": True,
            "maximum_top_bundles_for_exact_replay": 3,
            "maximum_active_skills_per_bundle": 2,
            "zlice_nonzero_direct_economic_delta_is_failure": True,
            "failure_learning_ml_light_cannot_promote_pre_shadow": True,
        },
        "required_attribution": [
            "MAIN_EFFECT_DELTA",
            "LEAVE_ONE_COMPONENT_OUT",
            "PAIR_INTERACTION_DELTA",
            "ORDER_STABLE_SHAPLEY_APPROXIMATION",
        ],
        **SAFE,
    }
    result["plan_sha256"] = stable_sha(result)
    return result


def gemini_input(plan: Mapping[str, Any]) -> dict[str, Any]:
    strategy_id = str(plan["strategy_id"])
    return {
        "schema_version": "zel.survivor_bundle.gemini_input.v1",
        "strategy_id": strategy_id,
        "task": "Review the exact per-strategy experiment matrix and propose only falsifiable single-axis hypotheses plus at most two causally plausible pair interactions.",
        "experiment_summary": {
            "state": plan["state"],
            "blockers": plan["blockers"],
            "source_metrics": plan["source_metrics"],
            "experiments": [
                {
                    "bundle_id": row["bundle_id"],
                    "phase": row["phase"],
                    "components": row["components"],
                    "deferred": row["deferred"],
                }
                for row in plan["experiments"]
            ],
        },
        "constraints": {
            "maximum_hypotheses": 4,
            "maximum_interactions": 2,
            "single_axis_hypothesis": True,
            "minimum_two_independent_sources_per_hypothesis": True,
            "no_performance_claim": True,
            "no_promotion": True,
            "failure_learning_ml_light_runtime_deferred_until_post_300c": True,
        },
        "output_schema": {
            "status": "PASS|HOLD",
            "hypotheses": [
                {
                    "axis": "TRADE_METHODS|BEST_SINGLE_SKILL|TEAM_POLICY|ZBOT_ADVICE|LICO_EXECUTION|ZICO_OMS|ZLICE_LINEAGE",
                    "parameter": "one exact parameter",
                    "values": ["bounded values"],
                    "causal_mechanism": "one mechanism",
                    "falsification_test": "one exact replay test",
                    "source_indexes": [1, 2],
                    "overfit_risk": "LOW|MEDIUM|HIGH",
                }
            ],
            "interactions": [
                {
                    "left_axis": "one axis",
                    "right_axis": "one axis",
                    "causal_mechanism": "why the combined delta may differ from additive main effects",
                    "falsification_test": "exact four-cell interaction test",
                    "source_indexes": [1, 2],
                }
            ],
        },
        "plan_sha256": plan["plan_sha256"],
        **SAFE,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    survivors = load_survivors(Path(args.survivors), args.maximum_survivors)
    audit = read_json(Path(args.audit)) if args.audit else None
    blockers, audit_ready = blocker_state(audit)
    generated = now_iso()
    if not survivors:
        return {
            "schema_version": "zel.survivor_bundle_experiment.status.v1",
            "version": VERSION,
            "generated_at": generated,
            "state": "WAIT_SURVIVING_STRATEGY_POOL",
            "survivor_count": 0,
            "strategies": [],
            "blockers": blockers,
            "next": "AUTO_RESUME_AFTER_SYNTHESIS_MATERIAL_POOL_READY",
            **SAFE,
        }

    plans = [strategy_plan(row, audit_ready=audit_ready, blockers=blockers) for row in survivors]
    out = Path(args.out)
    for plan in plans:
        strategy_id = str(plan["strategy_id"])
        write_json(out / "strategies" / strategy_id / "plan.json", plan)
        write_json(out / "gemini_inputs" / f"{strategy_id}.json", gemini_input(plan))
    result = {
        "schema_version": "zel.survivor_bundle_experiment.status.v1",
        "version": VERSION,
        "generated_at": generated,
        "state": "PASS_SURVIVOR_BUNDLE_MATRIX_READY" if audit_ready else "HOLD_SURVIVOR_BUNDLE_MATRIX_DEPENDENCY_GAPS",
        "survivor_count": len(plans),
        "strategy_ids": [plan["strategy_id"] for plan in plans],
        "strategies": plans,
        "pre_shadow_audit_ready": audit_ready,
        "blockers": blockers,
        "gemini_required": True,
        "bundle_adapter_exact_replay_required": True,
        "failure_learning_ml_light_runtime_binding_allowed": False,
        "next": "GEMINI_HYPOTHESIS_GATE_THEN_EXACT_BUNDLE_ADAPTER_REPLAY" if audit_ready else "REPAIR_DEPENDENCY_GAPS_THEN_AUTO_RESUME",
        **SAFE,
    }
    result["result_sha256"] = stable_sha(result)
    return result


def self_test() -> None:
    assert len(MAIN_COMPONENTS) == 6
    assert len(PAIR_INTERACTIONS) == 7
    rows = build_rows("fixture")
    assert len(rows) == 18
    assert sum(row["deferred"] for row in rows) == 3
    assert sum(row["negative_control"] for row in rows) == 1
    assert all(row["promotion_authority"] is False for row in rows)
    fixture = strategy_plan({"strategy_id": "fixture", "expectancy_R": 0.1}, audit_ready=True, blockers=[])
    assert fixture["state"] == "READY_FOR_BUNDLE_ADAPTER_REPLAY"
    assert gemini_input(fixture)["constraints"]["maximum_interactions"] == 2
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--survivors")
    parser.add_argument("--audit")
    parser.add_argument("--out")
    parser.add_argument("--maximum-survivors", type=int, default=5)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.survivors or not args.out:
        parser.error("--survivors and --out are required")
    result = run(args)
    write_json(Path(args.out) / "latest.json", result)
    print(json.dumps({"state": result["state"], "survivor_count": result["survivor_count"], "blockers": result["blockers"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
