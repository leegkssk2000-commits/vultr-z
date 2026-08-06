#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PATH = ROOT / "backend/research/zel_scalp_momentum_replay_control_plan_v1.json"
TRIAL_PATH = ROOT / "backend/research/zel_scalp_momentum_generation1_trial_plan_v1.json"


def main() -> None:
    control = json.loads(CONTROL_PATH.read_text())
    trial = json.loads(TRIAL_PATH.read_text())

    assert control["schema_version"] == "zel.scalp.momentum.replay_control_plan.v1"
    assert control["strategy_id"] == "momentum_breakout_continuation_v1"
    assert control["state"] == "PASS_STRATEGY_KERNEL_BOUND_REPLAY_BLOCKED_PENDING_FEATURE_CONTRIBUTION"
    assert control["legacy_trial_plan_disposition"] == "DIAGNOSTIC_COVERAGE_ONLY_NOT_SELECTION_AUTHORITY"
    assert control["legacy_adapters_disposition"] == "BLOCKED_NO_SELECTION_OR_ECONOMIC_AUTHORITY"
    assert control["next_gate"] == "FEATURE_ECONOMIC_CONTRIBUTION"

    kernel = control["strategy_kernel"]
    assert kernel["feature_policy_ssot"] == "backend/research/zel_feature_strategy_ssot_v1.py"
    assert kernel["intent_adapters"] == "backend/research/zel_strategy_intent_adapters_v1.py"
    assert kernel["boundary_audit"] == "backend/research/zel_strategy_kernel_boundary_audit_v1.json"
    assert kernel["feature_validator"] == "scripts/validate_zel_feature_strategy_ssot_v1.py"
    assert kernel["parity_validator"] == "scripts/validate_zel_strategy_kernel_parity_v1.py"
    assert kernel["required_gate_order"] == [
        "BOUNDARY_OWNERSHIP",
        "FEATURE_CORRECTNESS",
        "REPLAY_PAPER_DECISION_INTENT_PARITY",
        "FEATURE_ECONOMIC_CONTRIBUTION",
        "INTEGRATED_ECONOMIC_REPLAY",
    ]

    assert trial["strategy_id"] == control["strategy_id"]
    assert trial["trial_count"] == 48
    assert len(trial["trials"]) == 48

    stages = control["staged_search"]
    assert [stage["stage_id"] for stage in stages] == ["S1_ENTRY_STRUCTURE", "S2_RISK_EXIT"]
    assert stages[0]["maximum_trials"] <= 24
    assert stages[1]["maximum_trials"] <= 12
    assert stages[1]["inherits_frozen_stage"] == "S1_ENTRY_STRUCTURE"

    all_parameters = set(trial["bounds"])
    stage_parameters = set(stages[0]["parameters"]) | set(stages[1]["parameters"])
    assert stage_parameters == all_parameters
    assert set(stages[0]["parameters"]).isdisjoint(stages[1]["parameters"])
    assert set(stages[0]["fixed_parameters"]) == set(stages[1]["parameters"])

    controls = {row["control_id"] for row in control["negative_controls"] if row["required"]}
    assert controls == {"NO_SIGNAL_PLACEBO", "DIRECTION_REVERSAL", "PLUS_ONE_BAR_DELAY"}

    cutoff = control["marginal_expectancy_cutoff"]
    assert cutoff["selected_on"] == "W1_ONLY"
    assert cutoff["frozen_unchanged_on"] == ["W2", "W3"]
    assert cutoff["minimum_opportunity_retention_pct"] >= 60.0

    policy = control["selection_policy"]
    assert policy["window"] == "W1_ONLY"
    assert policy["freeze_through"] == ["W2", "W3"]
    assert policy["minimum_trades_per_window"] >= 60

    assert control["promotion_authority"] is False
    assert control["selection_authority"] is False
    assert control["execution_authority"] == "NONE"
    assert control["order_authority"] == "BLOCKED"
    assert control["protected_mutations"] == 0
    assert control["action"] == "hold"

    print(json.dumps({
        "state": control["state"],
        "legacy_trials": trial["trial_count"],
        "stages": [stage["stage_id"] for stage in stages],
        "controls": sorted(controls),
        "heavy_replay": "BLOCKED_PENDING_FEATURE_CONTRIBUTION",
        "next_gate": control["next_gate"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
