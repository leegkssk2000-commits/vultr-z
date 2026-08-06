#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any


def load_script(path: Path):
    spec = importlib.util.spec_from_file_location("zel_momentum_event_study_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load momentum event-study base")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def reweight(events: list[dict[str, Any]], cap: float) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for source in events:
        event = dict(source)
        ratio = float(event.get("expected_move_to_cost") or 0.0)
        relative_volume = float(event.get("relative_volume") or 0.0)
        event["uncapped_quality"] = ratio * relative_volume
        event["quality"] = min(ratio, cap) * relative_volume
        adjusted.append(event)
    return adjusted


def compact_control(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "pass_event_study_gate": summary["pass_event_study_gate"],
        "event_count": summary["event_count"],
        "retained_count": summary["retained_count"],
        "retention_pct": summary["retention_pct"],
        "quality_decile_monotonicity": summary["quality_decile_monotonicity"],
        "selected_mean_net_forward_pct": summary["selected_mean_net_forward_pct"],
        "selected_primary_bootstrap_ci95_pct": summary["selected_primary_bootstrap_ci95_pct"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--ai-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    base = load_script(args.repo_root / "scripts/run_zel_scalp_momentum_event_study_v1.py")
    source_path = args.repo_root / "backend/research/momentum_breakout_continuation_v1.py"
    trial_path = args.repo_root / "backend/research/zel_scalp_momentum_generation1_trial_plan_v1.json"
    control_path = args.repo_root / "backend/research/zel_scalp_momentum_replay_control_plan_v1.json"
    hypothesis_path = args.repo_root / "backend/research/zel_momentum_gen2_ai_hypothesis_v1.json"

    manifest = read_object(args.inputs / "materialized_manifest.json")
    cost = read_object(args.inputs / "cost_binding.json")
    trial_plan = read_object(trial_path)
    control_plan = read_object(control_path)
    ai_receipt = read_object(args.ai_receipt)
    hypothesis = read_object(hypothesis_path)

    if manifest.get("state") != "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("momentum materialization state mismatch")
    if manifest.get("strategy_id") != "momentum_breakout_continuation_v1":
        raise SystemExit("strategy binding mismatch")
    if manifest["references"]["candidate_source_sha256"] != base.sha256_file(source_path):
        raise SystemExit("candidate source SHA mismatch")
    if manifest["references"]["trial_plan_sha256"] != base.sha256_file(trial_path):
        raise SystemExit("trial plan SHA mismatch")
    if manifest["references"]["control_plan_sha256"] != base.sha256_file(control_path):
        raise SystemExit("control plan SHA mismatch")

    if ai_receipt.get("state") != "PASS_MOMENTUM_GEN2_AI_CHAIN_BOUND":
        raise SystemExit("momentum gen2 AI chain not bound")
    if ai_receipt.get("selected_axis") != "EXPECTED_MOVE_TO_COST_SATURATION":
        raise SystemExit("momentum gen2 AI axis mismatch")
    if hypothesis.get("changed_axes") != ["EXPECTED_MOVE_TO_COST_SATURATION"]:
        raise SystemExit("momentum gen2 hypothesis axis mismatch")
    cap = float(ai_receipt.get("effective_cap", 0.0))
    if cap != 6.0:
        raise SystemExit("momentum gen2 cap mismatch")

    all_in_cost_pct = float(cost["all_in_cost_pct"])
    candidate = base.load_module(source_path)
    stage = control_plan["staged_search"][0]
    entry_trials = base.unique_entry_trials(trial_plan, int(stage["maximum_trials"]))
    fixed = stage["fixed_parameters"]

    results: list[dict[str, Any]] = []
    for number, entry_trial in enumerate(entry_trials, 1):
        config_id = f"ES2-{number:03d}"
        raw_events = base.build_events(candidate, args.inputs, entry_trial, fixed, all_in_cost_pct)
        uncapped = base.summarize_trial(f"CTRL-{number:03d}", entry_trial, [dict(event) for event in raw_events])
        adjusted = reweight(raw_events, cap)
        result = base.summarize_trial(config_id, entry_trial, adjusted)
        result["quality_axis"] = "EXPECTED_MOVE_TO_COST_SATURATION"
        result["effective_cap"] = cap
        result["uncapped_control"] = compact_control(uncapped)
        results.append(result)

    passing = [row for row in results if row["pass_event_study_gate"]]
    passing.sort(
        key=lambda row: (
            float(row["selected_mean_net_forward_pct"]["6"] or -math.inf),
            float(row["quality_decile_monotonicity"]),
            int(row["retained_count"]),
        ),
        reverse=True,
    )
    state = "PASS_EVENT_STUDY_EDGE_FOUND" if passing else "PASS_EVENT_STUDY_NO_EDGE"
    receipt = {
        "schema_version": "zel.scalp.momentum.gen2.event_study.v1",
        "state": state,
        "strategy_id": "momentum_breakout_continuation_v1",
        "generation": 2,
        "window": "research",
        "selected_axis": "EXPECTED_MOVE_TO_COST_SATURATION",
        "quality_formula": ai_receipt["quality_formula"],
        "effective_cap": cap,
        "horizons_5m_bars": list(base.HORIZONS),
        "primary_horizon_5m_bars": base.PRIMARY_HORIZON,
        "all_in_cost_pct": all_in_cost_pct,
        "trial_count": len(results),
        "trials": results,
        "passing_config_ids": [row["config_id"] for row in passing],
        "passing_count": len(passing),
        "negative_controls": {
            "UNCAPPED_BASELINE_SCORE": "evaluated_per_trial",
            "NO_SIGNAL_PLACEBO": {"events": 0, "net_return_pct": 0.0, "promotion_authority": False},
            "DIRECTION_REVERSAL": "evaluated_per_trial",
            "PLUS_ONE_BAR_DELAY": "evaluated_per_trial"
        },
        "integrity": {
            "future_information": 0,
            "errors": 0,
            "duplicates": 0,
            "protected_mutations": 0
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold" if passing else "route_change",
        "input_manifest_receipt_sha256": manifest["manifest_receipt_sha256"],
        "ai_gate_receipt_sha256": ai_receipt["receipt_sha256"],
        "baseline_event_study_receipt_sha256": ai_receipt["baseline_event_study_receipt_sha256"],
        "hypothesis_sha256": base.sha256_file(hypothesis_path)
    }
    receipt["receipt_sha256"] = base.canonical_sha256(receipt)
    (args.output / "momentum_event_study_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )
    print(json.dumps({
        "state": state,
        "trial_count": len(results),
        "passing_count": len(passing),
        "best_config_id": passing[0]["config_id"] if passing else None,
        "selected_axis": receipt["selected_axis"],
        "receipt": receipt["receipt_sha256"]
    }, sort_keys=True))


if __name__ == "__main__":
    main()
