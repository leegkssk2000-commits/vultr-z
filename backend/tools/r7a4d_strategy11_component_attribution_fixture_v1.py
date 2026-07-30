from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.research.strategy11_component_attribution_v1 import (
    ComponentAttributionError,
    attribute_components,
)
from backend.research.strategy11_synthesis_factorial_replay_v1 import evaluate_factorial
from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY
from backend.tools.r7a4d_strategy11_synthesis_factorial_replay_fixture_v1 import (
    fixture_input,
    reseal,
)


def expect_failure(code: str, fn) -> str:
    try:
        fn()
    except ComponentAttributionError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def policy() -> dict:
    return {
        "policy_id": "fixture-component-attribution-v1",
        "min_leave_one_out_net_r": 0.5,
        "min_shapley_net_r": 0.4,
        "max_leave_one_out_drawdown_penalty_r": 0.0,
        "min_joint_uplift_net_r": 1.0,
        "max_component_share_pct": 80.0,
        "require_both_positive": True,
    }


def attribution_input() -> dict:
    factorial_input = fixture_input()
    factorial_result = evaluate_factorial(factorial_input)
    return {
        "schema_version": "strategy11.component_attribution.input.v1",
        "factorial_input": factorial_input,
        "factorial_result": factorial_result,
        "policy": policy(),
        "authority": dict(SAFETY),
    }


def main() -> int:
    payload = attribution_input()
    result = attribute_components(payload)
    assert result["state"] == "PASS_COMPONENT_ATTRIBUTION"
    assert result["next"] == "SYNTHESIS_SEALER"
    assert abs(result["joint_uplift_net_r"] - 1.2) < 1e-9
    assert abs(result["shapley_sum_net_r"] - result["joint_uplift_net_r"]) < 1e-9
    assert len(result["components"]) == 2
    assert all(row["contribution_pass"] for row in result["components"])
    assert all(row["leave_one_out_net_r"] >= 0.7 for row in result["components"])
    assert all(row["shapley_net_r"] >= 0.55 for row in result["components"])
    for key, expected in SAFETY.items():
        assert result[key] == expected

    dominant = attribution_input()
    dominant["policy"]["max_component_share_pct"] = 50.0
    dominant_result = attribute_components(dominant)
    assert dominant_result["state"] == "HOLD_COMPONENT_ATTRIBUTION"
    assert any("COMPONENT_DOMINANCE_HIGH" in code for code in dominant_result["attribution_blockers"])

    tampered_result = attribution_input()
    tampered_result["factorial_result"]["factorial_sha"] = "f" * 64
    expect_failure("FACTORIAL_RESULT_SHA_MISMATCH", lambda: attribute_components(tampered_result))

    changed_input = attribution_input()
    ab = next(row for row in changed_input["factorial_input"]["cells"] if row["cell_id"] == "BASE_AB")
    ab["metrics"]["net_after_cost_r"] = 2.25
    reseal(ab)
    expect_failure("FACTORIAL_RESULT_SHA_MISMATCH", lambda: attribute_components(changed_input))

    weak = attribution_input()
    weak_ab = next(row for row in weak["factorial_input"]["cells"] if row["cell_id"] == "BASE_AB")
    weak_ab["metrics"]["net_after_cost_r"] = 1.55
    reseal(weak_ab)
    weak["factorial_result"] = evaluate_factorial(weak["factorial_input"])
    expect_failure("PASS_FACTORIAL_RESULT_REQUIRED", lambda: attribute_components(weak))

    out = Path("artifacts/strategy11_component_attribution_v1")
    out.mkdir(parents=True, exist_ok=True)
    (out / "input.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (out / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    status = {
        "state": "PASS_COMPONENT_ATTRIBUTION_FIXTURE",
        "attribution_sha": result["attribution_sha"],
        "fixture_only": True,
        "production_authority": False,
        **SAFETY,
    }
    (out / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
