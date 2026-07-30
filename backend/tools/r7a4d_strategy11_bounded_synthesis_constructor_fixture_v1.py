from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.research.strategy11_bounded_synthesis_constructor_v1 import (
    BoundedSynthesisError,
    construct_candidate,
    construct_plan,
)
from backend.research.strategy11_synthesis_material_registry_v1 import (
    COMPONENT_ROLE,
    SAFETY,
    build_registry,
    canonical_sha,
    seal_material,
)


def expect_failure(code: str, fn) -> str:
    try:
        fn()
    except BoundedSynthesisError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def evidence(seed: int) -> dict:
    return {
        "ab_replay_pass": True,
        "duplicate_count": 0,
        "baseline_trades": 20,
        "candidate_trades": 18,
        "retention_pct": 90.0,
        "normal_loss_cap_pass": True,
        "stress_loss_cap_pass": True,
        "economic_gate_pass": True,
        "window_gate_pass": True,
        "pareto_non_dominated": True,
        "net_after_cost_delta": 0.20 + seed / 100.0,
        "max_drawdown_delta": -0.10,
        "worst_loss_r_delta": 0.0,
        "positive_windows_delta": 1,
        "stress_worst_loss_r_delta": 0.0,
    }


def material(
    material_id: str,
    component_type: str,
    axis: str,
    *,
    base_strategy_id: str = "turtle_trend",
    family: str = "TREND",
    seed: int = 1,
    data_sha: str = "4" * 64,
) -> dict:
    row_evidence = evidence(seed)
    parameters = {"fixture_parameter": seed}
    if component_type == "BASE_ENGINE":
        parameters = {"strategy_version": "fixture-v1"}
    return seal_material(
        {
            "schema_version": "strategy11.synthesis_material.v1",
            "material_id": material_id,
            "base_strategy_id": base_strategy_id,
            "component_type": component_type,
            "component_role": COMPONENT_ROLE[component_type],
            "semantic_axis": axis,
            "parameters": parameters,
            "source_lineage": {
                "source_candidate_sha": f"{seed % 10}" * 64,
                "source_proposal_sha": f"{(seed + 1) % 10}" * 64,
                "strategy_source_sha": "3" * 64,
                "data_sha": data_sha,
                "window_sha": "5" * 64,
                "source_manifest_sha": "6" * 64,
                "evidence_sha": canonical_sha(row_evidence),
            },
            "evidence": row_evidence,
            "compatibility": {
                "allowed_base_families": [family],
                "incompatible_component_types": ["ADVISOR", "RISK_CONSTRAINT"],
                "incompatible_axes": [],
                "same_axis_allowed": False,
                "maximum_generation_per_axis_data": 2,
            },
            "state": "PASS_LEAF",
            "authority": dict(SAFETY),
            "metadata": {
                "fixture_only": True,
                "production_authority": False,
                "strategy_family": family,
            },
        }
    )


def policy() -> dict:
    return {
        "policy_id": "fixture-bounded-synthesis-v1",
        "allowed_templates": [
            "BASE_PLUS_CONTEXT",
            "BASE_PLUS_EXIT",
            "BASE_PLUS_CONTEXT_EXIT",
        ],
        "max_non_base_components": 2,
        "max_candidates": 10,
        "allow_position_management_pre_shadow": False,
        "require_shared_selection_lineage": True,
        "generic_base_strategy_id": "GENERIC",
    }


def main() -> int:
    base = material("turtle.base.v1", "BASE_ENGINE", "TURTLE_BASE", seed=1)
    context = material("turtle.context.low_vol.v1", "CONTEXT_GATE", "LOW_VOL_GATE", seed=2)
    exit_skill = material("turtle.exit.mfe.v1", "EXIT_SKILL", "MFE_TRAILING", seed=3)
    registry = build_registry([base, context, exit_skill])
    plan = construct_plan(
        {
            "schema_version": "strategy11.bounded_synthesis_constructor.input.v1",
            "registry": registry,
            "policy": policy(),
            "authority": dict(SAFETY),
        }
    )
    assert plan["state"] == "PASS_BOUNDED_SYNTHESIS_PLAN"
    assert plan["candidate_count"] == 3
    assert {row["template"] for row in plan["candidates"]} == {
        "BASE_PLUS_CONTEXT",
        "BASE_PLUS_EXIT",
        "BASE_PLUS_CONTEXT_EXIT",
    }
    assert all(row["selection_data_role"] == "DESIGN_SELECTION_ONLY" for row in plan["candidates"])
    assert all(row["first_oos_required"] == "W2" for row in plan["candidates"])
    assert all(row["confirmation_required"] == ["W2", "W3", "NEW_SEALED"] for row in plan["candidates"])
    for key, expected in SAFETY.items():
        assert plan[key] == expected

    bad_registry = copy.deepcopy(registry)
    bad_registry["registry_sha"] = "f" * 64
    expect_failure(
        "REGISTRY_SHA_MISMATCH",
        lambda: construct_plan(
            {
                "schema_version": "strategy11.bounded_synthesis_constructor.input.v1",
                "registry": bad_registry,
                "policy": policy(),
                "authority": dict(SAFETY),
            }
        ),
    )

    mismatched_exit = material(
        "turtle.exit.mfe.other_data.v1",
        "EXIT_SKILL",
        "MFE_TRAILING_2",
        seed=4,
        data_sha="a" * 64,
    )
    expect_failure(
        "SELECTION_LINEAGE_MISMATCH",
        lambda: construct_candidate(base, [context, mismatched_exit], policy()),
    )

    position = material("turtle.position.scale.v1", "POSITION_MANAGEMENT", "SCALE_IN", seed=5)
    expect_failure(
        "POSITION_MANAGEMENT_PRE_SHADOW_FORBIDDEN",
        lambda: construct_candidate(base, [position], policy()),
    )

    advisor = material("turtle.advisor.zbot.v1", "ADVISOR", "ZBOT_ADVICE", seed=6)
    expect_failure(
        "NON_ALPHA_COMPONENT_FORBIDDEN",
        lambda: construct_candidate(base, [advisor], policy()),
    )

    same_axis = material("turtle.confirm.low_vol.v1", "ENTRY_CONFIRM", "LOW_VOL_GATE", seed=7)
    expect_failure(
        "DUPLICATE_SEMANTIC_AXIS",
        lambda: construct_candidate(base, [context, same_axis], policy()),
    )

    unsupported = material("turtle.confirm.volume.v1", "ENTRY_CONFIRM", "VOLUME_CONFIRM", seed=8)
    permissive = policy()
    permissive["allowed_templates"].append("BASE_PLUS_CONFIRM")
    expect_failure(
        "COMPONENT_TEMPLATE_NOT_SUPPORTED",
        lambda: construct_candidate(base, [context, unsupported], permissive),
    )

    wrong_family = material(
        "turtle.context.range_only.v1",
        "CONTEXT_GATE",
        "RANGE_ONLY",
        family="RANGE",
        seed=9,
    )
    expect_failure(
        "BASE_FAMILY_NOT_ALLOWED",
        lambda: construct_candidate(base, [wrong_family], policy()),
    )

    out = Path("artifacts/strategy11_bounded_synthesis_constructor_v1")
    out.mkdir(parents=True, exist_ok=True)
    (out / "registry.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    (out / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    status = {
        "state": "PASS_BOUNDED_SYNTHESIS_CONSTRUCTOR_FIXTURE",
        "plan_sha": plan["plan_sha"],
        "candidate_count": plan["candidate_count"],
        "fixture_only": True,
        "production_authority": False,
        **SAFETY,
    }
    (out / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
