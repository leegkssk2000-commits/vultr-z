#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

TOL = 1e-9
FIELDS = ("net_pnl_pct", "gross_pnl_pct", "cost_pct", "pnl_r", "entry_index", "exit_index", "exit_reason")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
        rows.append(value)
    return rows


def equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        a, b = float(left), float(right)
        return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= TOL
    return left == right


def compare_trade(prior: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    diffs = []
    for field in FIELDS:
        if not equal(prior.get(field), current.get(field)):
            diffs.append({"field": field, "prior": prior.get(field), "current": current.get(field)})
    return diffs


def audit(
    plan: dict[str, Any],
    closure: dict[str, Any],
    policy_results: list[dict[str, Any]],
    stress: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    if stress.get("state") != "PASS_SHORT_ADMISSION_CANDIDATE_STRESS_66":
        blockers.append("STRESS66_NOT_PASS")
    candidates = [row for row in plan.get("stress_candidates", []) if isinstance(row, dict)]
    cells = [row for row in stress.get("cells", []) if isinstance(row, dict)]
    closure_index = {
        str(row.get("candidate_id") or ""): row
        for row in closure.get("candidate_observations", []) if isinstance(row, dict)
    }
    policy_index = {str(row.get("scenario_id") or ""): row for row in policy_results}
    failures: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        baseline = next((
            row for row in cells
            if row.get("candidate_id") == candidate_id
            and row.get("cost_profile") == "cost_profile_0"
            and row.get("perturbation") == "perturbation_0"
        ), None)
        prior_trade: dict[str, Any] | None = None
        if candidate.get("source") == "closure_observer":
            container = closure_index.get(candidate_id)
            if isinstance(container, dict) and isinstance(container.get("trade"), dict):
                prior_trade = container["trade"]
        else:
            policy_row = policy_index.get(str(candidate.get("scenario_id") or ""))
            trades = policy_row.get("short_trade_detail") if isinstance(policy_row, dict) else None
            if isinstance(trades, list):
                short_trades = [row for row in trades if isinstance(row, dict)]
                if len(short_trades) == 1:
                    prior_trade = short_trades[0]
        if not isinstance(baseline, dict) or not isinstance(baseline.get("trade"), dict):
            failures.append({"candidate_id": candidate_id, "reason": "STRESS_BASELINE_TRADE_MISSING"})
            continue
        if not isinstance(prior_trade, dict):
            failures.append({"candidate_id": candidate_id, "reason": "PRIOR_BASELINE_TRADE_MISSING"})
            continue
        diffs = compare_trade(prior_trade, baseline["trade"])
        if diffs:
            failures.append({"candidate_id": candidate_id, "reason": "BASELINE_TRADE_DIFF", "diffs": diffs})
    if len(candidates) != 11:
        blockers.append(f"CANDIDATE_COUNT_INVALID:{len(candidates)}")
    if failures:
        blockers.append(f"FULL_BASELINE_PARITY_FAILURE:{len(failures)}")
    return failures, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    plan = load_json(root / "runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json")
    closure = load_json(root / "runtime/r7a4d2_short_signal_frequency_admission_closure/admission_closure_v1.json")
    policy_results = load_jsonl(root / "runtime/r7a4d2_short_rr_sidecar_counterfactual/policy_results_600_v1.jsonl")
    stress = load_json(root / "runtime/r7a4d2_short_admission_candidate_stress_66/stress66_proof_v1.json")
    failures, blockers = audit(plan, closure, policy_results, stress)
    state = "PASS_SHORT_STRESS66_FULL_BASELINE_PARITY" if not blockers else "HOLD_SHORT_STRESS66_BASELINE_PARITY"
    proof = {
        "schema": "r7a4d2_short_stress66_full_baseline_parity_v1",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "candidate_count": len(plan.get("stress_candidates", [])),
        "full_baseline_parity_count": 11 - len(failures),
        "baseline_parity_failure_count": len(failures),
        "failures": failures,
    }
    output = root / "runtime/r7a4d2_short_admission_candidate_stress_66/full_baseline_parity_v1.json"
    output.write_text(json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("FULL_BASELINE_PARITY_COUNT=" + str(11 - len(failures)))
    print("BASELINE_PARITY_FAILURE_COUNT=" + str(len(failures)))
    print("FAILURES=" + json.dumps(failures, ensure_ascii=False, sort_keys=True))
    print("PROOF_JSON=" + str(output))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
