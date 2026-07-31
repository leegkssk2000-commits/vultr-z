from __future__ import annotations

import argparse
import itertools
import json
import random
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from backend.tools import zel_component_autonomy_v2 as core
from backend.tools import zel_component_autonomy_v2_runner as v2

VERSION = "ZEL_COMPONENT_AUTONOMY_V3_CLAIM_GATED"
BONFERRONI = "BONFERRONI_OVER_TESTED_CANDIDATES"


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def identity(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("window_id") or ""),
        str(row.get("symbol") or ""),
        str(row.get("entry_ts") or ""),
        str(row.get("exit_ts") or ""),
    )


def selected_stage_functions(
    result: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Callable[[Sequence[Mapping[str, Any]]], list[dict[str, Any]]]]:
    modules = result["module_results"]
    best_bots = modules["bots"]["best_by_role"]
    best_team = modules["teams"]["best"]
    best_skill = modules["skills"]["best"]
    advisors = modules["advisors"]

    def team(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return core.apply_team(rows, best_team, policy, best_bots)

    def skill(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        transformed, _ = core.transform_skill(rows, str(best_skill["skill_id"]))
        return transformed

    def zbot(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        threshold = core.number(advisors["ZBOT"]["best"]["profile"]["disagreement_threshold"])
        return [
            deepcopy(dict(row)) for row in rows
            if abs(core.number(row["scores"]["trend_score"]) - core.number(row["scores"]["confirm_score"])) <= threshold
        ]

    def zico(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        bars = int(advisors["ZICO"]["best"]["profile"]["loss_cooldown_bars"])
        return core.apply_cooldown(rows, bars)

    def lico(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return core.apply_lico(rows, advisors["LICO"]["best"]["profile"], policy)

    return {"TEAM": team, "SKILL": skill, "ZBOT": zbot, "ZICO": zico, "LICO": lico}


def apply_order(
    rows: Sequence[Mapping[str, Any]],
    order: Sequence[str],
    functions: Mapping[str, Callable[[Sequence[Mapping[str, Any]]], list[dict[str, Any]]]],
    policy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    current = [deepcopy(dict(row)) for row in rows]
    applied: list[str] = []
    for stage in order:
        candidate = functions[stage](current)
        chosen, decision = v2._stage_decision(stage, current, candidate, policy)
        current = chosen
        if decision["applied"]:
            applied.append(stage)
    return current, applied


def order_interaction_audit(
    rows: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    functions = selected_stage_functions(result, policy)
    canonical = [name for name in ("TEAM", "SKILL", "ZBOT", "ZICO", "LICO") if result["pipeline_decisions"][name]["applied"]]
    orders = [tuple(canonical)] if len(canonical) <= 1 else list(itertools.permutations(canonical))
    outcomes = []
    for order in orders:
        final_rows, applied = apply_order(rows, order, functions, policy)
        outcomes.append({"order": list(order), "applied": applied, "stats": core.stats(final_rows)})
    nets = [core.number(row["stats"]["net_return_pct_sum"]) for row in outcomes]
    spread = max(nets) - min(nets) if nets else 0.0
    applied_sets = {frozenset(row["applied"]) for row in outcomes}
    limit = core.number((policy.get("claim_policy") or {}).get("order_spread_max_pct_points"), 0.20)
    order_stable = spread <= limit and len(applied_sets) <= 1
    return {
        "method": "ALL_PERMUTATIONS_OF_APPLIED_COMPONENTS",
        "tested_order_count": len(outcomes),
        "canonical_order": canonical,
        "net_spread_pct_points": spread,
        "applied_set_count": len(applied_sets),
        "order_stable": order_stable,
        "threshold_pct_points": limit,
        "outcomes": outcomes[:20],
    }


def paired_bootstrap(
    control_rows: Sequence[Mapping[str, Any]],
    final_rows: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    control = {identity(row): core.number(row.get("net")) for row in control_rows}
    final = {identity(row): core.number(row.get("net")) for row in final_rows}
    keys = sorted(set(control) | set(final))
    deltas = [final.get(key, 0.0) - control.get(key, 0.0) for key in keys]
    claim = policy.get("claim_policy") or {}
    resamples = int(claim.get("bootstrap_resamples", 2000))
    tested = (
        int(result["module_results"]["bots"]["tested"])
        + int(result["module_results"]["teams"]["tested"])
        + int(result["module_results"]["skills"]["tested"])
        + sum(int(value["tested"]) for value in result["module_results"]["advisors"].values())
    )
    alpha = core.number(claim.get("familywise_alpha"), 0.05)
    corrected_alpha = alpha / max(tested, 1)
    if not deltas:
        return {
            "method": "PAIRED_OPPORTUNITY_BOOTSTRAP",
            "resamples": resamples,
            "tested_candidate_count": tested,
            "adjustment": BONFERRONI,
            "corrected_alpha": corrected_alpha,
            "p_one_sided": 1.0,
            "ci95": [0.0, 0.0],
            "delta_sum": 0.0,
            "pass": False,
        }
    seed = int(str(result["data_fingerprint"])[:16], 16)
    rng = random.Random(seed)
    sums = []
    n = len(deltas)
    for _ in range(resamples):
        sums.append(sum(deltas[rng.randrange(n)] for _ in range(n)))
    sums.sort()
    low = sums[max(0, int(0.025 * resamples) - 1)]
    high = sums[min(resamples - 1, int(0.975 * resamples))]
    p = sum(value <= 0.0 for value in sums) / resamples
    return {
        "method": "PAIRED_OPPORTUNITY_BOOTSTRAP",
        "dependency_warning": "TRADE_LEVEL_APPROXIMATION_REQUIRES_MULTIPLE_INDEPENDENT_WINDOWS",
        "resamples": resamples,
        "tested_candidate_count": tested,
        "adjustment": BONFERRONI,
        "corrected_alpha": corrected_alpha,
        "p_one_sided": p,
        "ci95": [low, high],
        "delta_sum": sum(deltas),
        "pass": p <= corrected_alpha and low > 0.0,
    }


def claim_gate(
    result: dict[str, Any],
    control_rows: Sequence[Mapping[str, Any]],
    final_rows: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    claim = policy.get("claim_policy") or {}
    trade_count = int(result["full_stack"]["stats"]["trade_count"])
    windows = sorted({str(row.get("window_id") or "") for row in control_rows})
    symbols = sorted({str(row.get("symbol") or "") for row in control_rows})
    per_symbol = {symbol: sum(str(row.get("symbol")) == symbol for row in control_rows) for symbol in symbols}
    hypothesis_min = int(claim.get("hypothesis_review_min_trades", 20))
    efficacy_min = int(claim.get("component_efficacy_min_trades", 100))
    integrated_min = int(claim.get("integrated_s_grade_min_trades", 300))
    if trade_count < hypothesis_min:
        tier = "LOW_SAMPLE"
    elif trade_count < efficacy_min:
        tier = "HYPOTHESIS_ONLY"
    elif trade_count < integrated_min:
        tier = "COMPONENT_EFFICACY"
    else:
        tier = "INTEGRATED_S_GRADE_SAMPLE"
    skill = result["pipeline_decisions"]["SKILL"]
    fidelity = str(skill.get("fidelity") or "")
    synthetic = fidelity in set(claim.get("synthetic_skill_fidelities") or [])
    exact_skill_replay_required = bool(skill.get("applied")) and synthetic
    interaction = order_interaction_audit(control_rows, result, policy)
    statistics = paired_bootstrap(control_rows, final_rows, result, policy)
    coverage = {
        "window_count": len(windows),
        "windows": windows,
        "symbol_count": len(symbols),
        "per_symbol_trade_count": per_symbol,
        "multiple_windows_pass": len(windows) >= int(claim.get("minimum_independent_windows", 3)),
        "symbol_count_pass": len(symbols) >= int(claim.get("minimum_symbol_count", 2)),
        "per_symbol_pass": all(value >= int(claim.get("minimum_trades_per_symbol", 10)) for value in per_symbol.values()),
    }
    performance_claim_allowed = (
        trade_count >= efficacy_min
        and coverage["multiple_windows_pass"]
        and coverage["symbol_count_pass"]
        and coverage["per_symbol_pass"]
        and interaction["order_stable"]
        and statistics["pass"]
        and not exact_skill_replay_required
    )
    return {
        "claim_tier": tier,
        "performance_claim_allowed": performance_claim_allowed,
        "exact_skill_replay_required": exact_skill_replay_required,
        "skill_fidelity": fidelity,
        "coverage": coverage,
        "interaction_audit": interaction,
        "statistical_gate": statistics,
    }


def run(args: argparse.Namespace) -> int:
    policy = read_json(args.policy)
    ledger = read_json(args.ledger)
    summary = read_json(args.summary)
    previous = read_json(args.previous_state) if args.previous_state and Path(args.previous_state).is_file() else None
    result = v2.optimize(policy, ledger, summary, previous)
    rows = core.load_events(ledger, summary)
    functions = selected_stage_functions(result, policy)
    applied_order = [name for name in ("TEAM", "SKILL", "ZBOT", "ZICO", "LICO") if result["pipeline_decisions"][name]["applied"]]
    final_rows, _ = apply_order(rows, applied_order, functions, policy)
    gate = claim_gate(result, rows, final_rows, policy)
    result["schema_version"] = "3.0"
    result["version"] = VERSION
    result["claim_gate"] = gate
    result["structure_state"] = "PASS_COMPONENT_STRUCTURE"
    result["economic_state"] = gate["claim_tier"]
    result["performance_claim_allowed"] = gate["performance_claim_allowed"]
    result["shadow_start_allowed"] = False
    result["paper_allowed"] = False
    result["live_allowed"] = False
    if gate["claim_tier"] == "LOW_SAMPLE":
        result["state"] = "LOW_SAMPLE_HOLD"
    elif gate["claim_tier"] == "HYPOTHESIS_ONLY":
        result["state"] = "HYPOTHESIS_ONLY_HOLD"
    elif not gate["interaction_audit"]["order_stable"]:
        result["state"] = "HOLD_COMPONENT_INTERACTION_UNSTABLE"
    elif gate["exact_skill_replay_required"]:
        result["state"] = "HOLD_EXACT_SKILL_REPLAY_REQUIRED"
    elif not gate["statistical_gate"]["pass"]:
        result["state"] = "HOLD_STATISTICAL_GATE"
    result["result_sha256"] = core.stable_sha({key: value for key, value in result.items() if key != "result_sha256"})
    out = Path(args.out)
    write_json(out / "final.json", result)
    write_json(out / "state.json", {
        "state": result["state"],
        "epoch": result["epoch"],
        "data_fingerprint": result["data_fingerprint"],
        "patience": result["convergence"]["patience"],
        "best_full_net": result["full_stack"]["stats"]["net_return_pct_sum"],
        "performance_claim_allowed": result["performance_claim_allowed"],
        "result_sha256": result["result_sha256"],
        **core.SAFE,
    })
    write_json(out / "final_trade_ledger.json", {"trades": final_rows})
    print(result["state"], result["result_sha256"])
    return 0


def fixture(out: Path) -> int:
    policy = read_json(Path(__file__).resolve().parents[1] / "research" / "zel_component_autonomy_policy_v3.json")
    ledger, summary = v2._fixture_input(24)
    result = v2.optimize(policy, ledger, summary)
    rows = core.load_events(ledger, summary)
    functions = selected_stage_functions(result, policy)
    applied_order = [name for name in ("TEAM", "SKILL", "ZBOT", "ZICO", "LICO") if result["pipeline_decisions"][name]["applied"]]
    final_rows, _ = apply_order(rows, applied_order, functions, policy)
    gate = claim_gate(result, rows, final_rows, policy)
    assert gate["claim_tier"] == "HYPOTHESIS_ONLY"
    assert gate["performance_claim_allowed"] is False
    assert gate["interaction_audit"]["tested_order_count"] >= 1
    assert gate["interaction_audit"]["applied_set_count"] == 1

    low_ledger, low_summary = v2._fixture_input(5)
    low_result = v2.optimize(policy, low_ledger, low_summary)
    low_rows = core.load_events(low_ledger, low_summary)
    low_functions = selected_stage_functions(low_result, policy)
    low_order = [name for name in ("TEAM", "SKILL", "ZBOT", "ZICO", "LICO") if low_result["pipeline_decisions"][name]["applied"]]
    low_final, _ = apply_order(low_rows, low_order, low_functions, policy)
    low_gate = claim_gate(low_result, low_rows, low_final, policy)
    assert low_gate["claim_tier"] == "LOW_SAMPLE"
    assert low_gate["performance_claim_allowed"] is False

    write_json(out / "fixture_claim_gate.json", gate)
    write_json(out / "low_sample_claim_gate.json", low_gate)
    print("PASS_COMPONENT_AUTONOMY_V3_CLAIM_GATE_FIXTURE")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--policy", required=True)
    run_parser.add_argument("--ledger", required=True)
    run_parser.add_argument("--summary", required=True)
    run_parser.add_argument("--previous-state")
    run_parser.add_argument("--out", required=True)
    fixture_parser = sub.add_parser("fixture")
    fixture_parser.add_argument("--out", required=True)
    args = parser.parse_args()
    return fixture(Path(args.out)) if args.mode == "fixture" else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
