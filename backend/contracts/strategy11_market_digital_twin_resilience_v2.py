from __future__ import annotations

import json
from typing import Any, Mapping

from backend.contracts.strategy11_market_digital_twin_contract_v1 import (
    DigitalTwinContractError,
    evaluate_digital_twin,
    stable_sha,
)

VERSION = "STRATEGY11_MARKET_DIGITAL_TWIN_RESILIENCE_V2"


def evaluate_digital_twin_resilience_v2(package: Mapping[str, Any], policy_input: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(policy_input)
    allowed_map = policy.get("allowed_expected_flags_by_type")
    dd_map = policy.get("max_resilience_drawdown_pct_by_type")
    net_map = policy.get("min_resilience_net_return_pct_by_type")
    if not isinstance(allowed_map, Mapping) or not isinstance(dd_map, Mapping) or not isinstance(net_map, Mapping):
        raise DigitalTwinContractError("RESILIENCE_POLICY_MAPS_MISSING")

    base = evaluate_digital_twin(package, policy)
    scenario_types = set(base["scenario_types"])
    if set(allowed_map) != scenario_types or set(dd_map) != scenario_types or set(net_map) != scenario_types:
        raise DigitalTwinContractError("RESILIENCE_POLICY_SCENARIO_SET_MISMATCH")

    rows = []
    blocking_scenarios: list[str] = []
    for scenario in base["scenario_results"]:
        scenario_type = scenario["scenario_type"]
        flags = set(str(value) for value in scenario["risk_flags"])
        allowed = set(str(value) for value in allowed_map[scenario_type])
        unexpected = sorted(flags - allowed)
        missing_expected = sorted(allowed - flags)
        dd_limit = float(dd_map[scenario_type])
        net_floor = float(net_map[scenario_type])
        blockers = []
        if unexpected:
            blockers.extend(f"UNEXPECTED_RISK_FLAG:{value}" for value in unexpected)
        if scenario["max_drawdown_pct"] > dd_limit:
            blockers.append("RESILIENCE_DRAWDOWN_BREACH")
        if scenario["net_return_pct"] < net_floor:
            blockers.append("RESILIENCE_NET_FLOOR_BREACH")
        # Expected stress flags must actually be observed; otherwise the scenario label is not evidence.
        if missing_expected:
            blockers.extend(f"EXPECTED_STRESS_NOT_OBSERVED:{value}" for value in missing_expected)
        if blockers:
            blocking_scenarios.append(scenario["scenario_id"])
        rows.append({
            "scenario_id": scenario["scenario_id"],
            "scenario_type": scenario_type,
            "observed_risk_flags": sorted(flags),
            "allowed_expected_flags": sorted(allowed),
            "unexpected_risk_flags": unexpected,
            "missing_expected_flags": missing_expected,
            "max_drawdown_pct": scenario["max_drawdown_pct"],
            "max_drawdown_limit_pct": dd_limit,
            "net_return_pct": scenario["net_return_pct"],
            "net_return_floor_pct": net_floor,
            "blockers": sorted(blockers),
            "resilience_pass": not blockers,
        })

    result = dict(base)
    result["schema_version"] = "strategy11.market_digital_twin_resilience.v2"
    result["version"] = VERSION
    result["v1_twin_result_sha"] = base["twin_result_sha"]
    result["resilience_rows"] = rows
    result["blocking_scenarios"] = sorted(blocking_scenarios)
    result["capital_gate"] = (
        "PASS_DIGITAL_TWIN_RISK_ENVELOPE"
        if not blocking_scenarios
        else "HOLD_DIGITAL_TWIN_RISK_EXPOSED"
    )
    result["resilience_policy_sha"] = str(policy["policy_sha"])
    result["twin_result_sha"] = stable_sha({key: value for key, value in result.items() if key != "twin_result_sha"})
    return result
