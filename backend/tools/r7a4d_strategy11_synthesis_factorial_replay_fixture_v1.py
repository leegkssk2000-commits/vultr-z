from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.research.strategy11_bounded_synthesis_constructor_v1 import construct_candidate
from backend.research.strategy11_synthesis_factorial_replay_v1 import (
    SynthesisFactorialError,
    evaluate_factorial,
)
from backend.research.strategy11_synthesis_material_registry_v1 import (
    COMPONENT_ROLE,
    SAFETY,
    canonical_sha,
    seal_material,
)


def expect_failure(code: str, fn) -> str:
    try:
        fn()
    except SynthesisFactorialError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def leaf_evidence(seed: int) -> dict:
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
        "net_after_cost_delta": 0.1 + seed / 100.0,
        "max_drawdown_delta": -0.1,
        "worst_loss_r_delta": 0.0,
        "positive_windows_delta": 1,
        "stress_worst_loss_r_delta": 0.0,
    }


def material(material_id: str, component_type: str, axis: str, seed: int) -> dict:
    evidence = leaf_evidence(seed)
    return seal_material(
        {
            "schema_version": "strategy11.synthesis_material.v1",
            "material_id": material_id,
            "base_strategy_id": "turtle_trend",
            "component_type": component_type,
            "component_role": COMPONENT_ROLE[component_type],
            "semantic_axis": axis,
            "parameters": {"fixture_parameter": seed},
            "source_lineage": {
                "source_candidate_sha": f"{seed}" * 64,
                "source_proposal_sha": f"{seed + 1}" * 64,
                "strategy_source_sha": "3" * 64,
                "data_sha": "4" * 64,
                "window_sha": "5" * 64,
                "source_manifest_sha": "6" * 64,
                "evidence_sha": canonical_sha(evidence),
            },
            "evidence": evidence,
            "compatibility": {
                "allowed_base_families": ["TREND"],
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
                "strategy_family": "TREND",
            },
        }
    )


def constructor_policy() -> dict:
    return {
        "policy_id": "fixture-constructor-v1",
        "allowed_templates": ["BASE_PLUS_CONTEXT_EXIT"],
        "max_non_base_components": 2,
        "max_candidates": 5,
        "allow_position_management_pre_shadow": False,
        "require_shared_selection_lineage": True,
        "generic_base_strategy_id": "GENERIC",
    }


def factorial_policy() -> dict:
    return {
        "policy_id": "fixture-factorial-v1",
        "min_retention_pct": 80.0,
        "min_profit_factor": 1.1,
        "min_payoff": 1.0,
        "min_net_after_cost_r": 0.5,
        "max_drawdown_r": 3.0,
        "min_avg_loss_r": -0.75,
        "min_worst_loss_r": -0.75,
        "min_stress_worst_loss_r": -0.75,
        "min_positive_windows": 2,
        "min_interaction_net_r": 0.2,
        "max_interaction_drawdown_r": 0.0,
        "min_marginal_net_r": 0.5,
        "require_ab_parity": True,
        "require_duplicate_zero": True,
    }


def seal_cell(cell_id: str, component_ids: list[str], metrics: dict, *, data_sha: str = "a" * 64) -> dict:
    cell = {
        "schema_version": "strategy11.synthesis_factorial_cell.v1",
        "cell_id": cell_id,
        "component_ids": sorted(component_ids),
        "evaluation_stage": "W2",
        "lineage": {
            "data_sha": data_sha,
            "window_sha": "b" * 64,
            "source_manifest_sha": "c" * 64,
            "replay_run_id": "fixture-w2-run-1",
        },
        "ab_parity_pass": True,
        "duplicate_count": 0,
        "metrics": metrics,
    }
    cell["summary_sha"] = canonical_sha(cell)
    return cell


def metrics(trades: int, net: float, pf: float, payoff: float, dd: float, windows: int) -> dict:
    return {
        "trades": trades,
        "net_after_cost_r": net,
        "profit_factor": pf,
        "payoff": payoff,
        "max_drawdown_r": dd,
        "avg_loss_r": -0.45,
        "worst_loss_r": -0.70,
        "stress_worst_loss_r": -0.74,
        "positive_windows": windows,
        "total_windows": 3,
    }


def fixture_input() -> dict:
    base = material("turtle.base.v1", "BASE_ENGINE", "TURTLE_BASE", 1)
    context = material("turtle.context.low_vol.v1", "CONTEXT_GATE", "LOW_VOL_GATE", 2)
    exit_skill = material("turtle.exit.mfe.v1", "EXIT_SKILL", "MFE_TRAILING", 3)
    candidate = construct_candidate(base, [context, exit_skill], constructor_policy())
    a_id, b_id = sorted(row["material_id"] for row in candidate["components"])
    cells = [
        seal_cell("BASE", [], metrics(20, 1.0, 1.20, 1.10, 2.0, 2)),
        seal_cell("BASE_A", [a_id], metrics(18, 1.5, 1.35, 1.20, 1.8, 3)),
        seal_cell("BASE_B", [b_id], metrics(19, 1.4, 1.30, 1.18, 1.7, 3)),
        seal_cell("BASE_AB", [a_id, b_id], metrics(17, 2.2, 1.55, 1.35, 1.4, 3)),
    ]
    return {
        "schema_version": "strategy11.synthesis_factorial_replay.input.v1",
        "candidate": candidate,
        "cells": cells,
        "policy": factorial_policy(),
        "authority": dict(SAFETY),
    }


def reseal(cell: dict) -> None:
    cell.pop("summary_sha", None)
    cell["summary_sha"] = canonical_sha(cell)


def main() -> int:
    payload = fixture_input()
    result = evaluate_factorial(payload)
    assert result["state"] == "PASS_SYNTHESIS_FACTORIAL_W2_CANDIDATE"
    assert abs(result["interaction"]["net_after_cost_r"] - 0.3) < 1e-9
    assert result["interaction"]["max_drawdown_r"] < 0.0
    assert abs(result["interaction"]["marginal_net_r_vs_best_single"] - 0.7) < 1e-9
    assert result["selection_data_reused"] is False
    assert result["next"] == "COMPONENT_ATTRIBUTION"
    for key, expected in SAFETY.items():
        assert result[key] == expected

    weak = fixture_input()
    weak_ab = next(row for row in weak["cells"] if row["cell_id"] == "BASE_AB")
    weak_ab["metrics"]["net_after_cost_r"] = 1.55
    reseal(weak_ab)
    weak_result = evaluate_factorial(weak)
    assert weak_result["state"] == "HOLD_SYNTHESIS_FACTORIAL"
    assert "INTERACTION_NET_LOW" in weak_result["synergy_blockers"]
    assert "MARGINAL_NET_LOW" in weak_result["synergy_blockers"]

    reused = fixture_input()
    selection_data_sha = reused["candidate"]["selection_lineage"]["data_sha"]
    for cell in reused["cells"]:
        cell["lineage"]["data_sha"] = selection_data_sha
        reseal(cell)
    expect_failure("SELECTION_DATA_REUSE_FORBIDDEN", lambda: evaluate_factorial(reused))

    duplicated = fixture_input()
    duplicate_cell = next(row for row in duplicated["cells"] if row["cell_id"] == "BASE_AB")
    duplicate_cell["duplicate_count"] = 1
    reseal(duplicate_cell)
    expect_failure("DUPLICATE_ZERO_REQUIRED", lambda: evaluate_factorial(duplicated))

    wrong_mapping = fixture_input()
    mapped = next(row for row in wrong_mapping["cells"] if row["cell_id"] == "BASE_A")
    mapped["component_ids"] = ["wrong-material"]
    reseal(mapped)
    expect_failure("CELL_COMPONENT_MAPPING_MISMATCH", lambda: evaluate_factorial(wrong_mapping))

    tampered = fixture_input()
    tampered["cells"][0]["metrics"]["net_after_cost_r"] = 99.0
    expect_failure("CELL_SUMMARY_SHA_MISMATCH", lambda: evaluate_factorial(tampered))

    out = Path("artifacts/strategy11_synthesis_factorial_replay_v1")
    out.mkdir(parents=True, exist_ok=True)
    (out / "input.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (out / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    status = {
        "state": "PASS_SYNTHESIS_FACTORIAL_REPLAY_FIXTURE",
        "factorial_sha": result["factorial_sha"],
        "fixture_only": True,
        "production_authority": False,
        **SAFETY,
    }
    (out / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
