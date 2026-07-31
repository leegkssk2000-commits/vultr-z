from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.tools import zel_component_autonomy_v2 as core

VERSION = "ZEL_COMPONENT_AUTONOMY_V2_1_SEQUENTIAL_MATERIAL_ONLY"


def _copy_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [deepcopy(dict(row)) for row in rows]


def _stage_decision(
    name: str,
    before: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before_stats = core.stats(before)
    candidate_stats = core.stats(candidate)
    proof = core.evidence(candidate_stats, before_stats, policy)
    apply = bool(proof["material"]) and int(candidate_stats["trade_count"]) > 0
    chosen = _copy_rows(candidate if apply else before)
    return chosen, {
        "stage": name,
        "applied": apply,
        "reason": "APPLY_MATERIAL_POSITIVE" if apply else ("SKIP_NO_CHANGE" if proof.get("no_change") else "SKIP_NOT_MATERIAL"),
        "before": before_stats,
        "candidate": candidate_stats,
        "after": core.stats(chosen),
        "evidence": proof,
    }


def _zbot(rows: Sequence[Mapping[str, Any]], profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    threshold = core.number(profile["disagreement_threshold"])
    return [
        deepcopy(dict(row))
        for row in rows
        if abs(core.number(row["scores"]["trend_score"]) - core.number(row["scores"]["confirm_score"])) <= threshold
    ]


def optimize(
    policy: Mapping[str, Any],
    ledger: Mapping[str, Any],
    summary: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = core.load_events(ledger, summary)
    control = core.stats(rows)
    ledger_sha = core.stable_sha(ledger)
    summary_sha = core.stable_sha(summary)
    fingerprint = core.stable_sha({
        "ledger": ledger_sha,
        "summary": summary_sha,
        "policy": core.stable_sha(policy),
        "version": VERSION,
    })
    same = bool(previous and previous.get("data_fingerprint") == fingerprint)
    epoch = int(previous.get("epoch", 0)) + 1 if same and previous else 1
    prior = dict(previous or {}) if same else {}

    bot_candidates, best_bots = core.optimize_bots(rows, control, policy)
    team_candidates, best_team = core.optimize_teams(rows, control, policy, best_bots)
    skill_candidates, best_skill = core.optimize_skills(rows, control, policy)
    advisor_results, _ = core.optimize_advisors(rows, control, policy)

    stages: dict[str, list[dict[str, Any]]] = {"CONTROL": _copy_rows(rows)}
    decisions: dict[str, dict[str, Any]] = {}

    team_candidate = core.apply_team(stages["CONTROL"], best_team, policy, best_bots)
    stages["TEAM"], decisions["TEAM"] = _stage_decision("TEAM", stages["CONTROL"], team_candidate, policy)

    skill_candidate, skill_meta = core.transform_skill(stages["TEAM"], str(best_skill["skill_id"]))
    stages["SKILL"], decisions["SKILL"] = _stage_decision("SKILL", stages["TEAM"], skill_candidate, policy)
    decisions["SKILL"]["skill_id"] = best_skill["skill_id"]
    decisions["SKILL"]["fidelity"] = skill_meta["fidelity"]
    decisions["SKILL"]["selection_eligible"] = skill_meta["selection_eligible"]

    zbot_profile = advisor_results["ZBOT"]["best"]["profile"]
    stages["ZBOT"], decisions["ZBOT"] = _stage_decision(
        "ZBOT", stages["SKILL"], _zbot(stages["SKILL"], zbot_profile), policy,
    )

    zico_profile = advisor_results["ZICO"]["best"]["profile"]
    stages["ZICO"], decisions["ZICO"] = _stage_decision(
        "ZICO",
        stages["ZBOT"],
        core.apply_cooldown(stages["ZBOT"], int(zico_profile["loss_cooldown_bars"])),
        policy,
    )

    lico_profile = advisor_results["LICO"]["best"]["profile"]
    stages["LICO"], decisions["LICO"] = _stage_decision(
        "LICO", stages["ZICO"], core.apply_lico(stages["ZICO"], lico_profile, policy), policy,
    )

    lineage_valid = all(bool(row.get("lineage_complete")) for row in stages["LICO"])
    if not lineage_valid:
        raise RuntimeError("ZLICE_FULL_STACK_LINEAGE_FAILURE")
    stages["ZLICE"] = _copy_rows(stages["LICO"])
    decisions["ZLICE"] = {
        "stage": "ZLICE",
        "applied": True,
        "reason": "PASS_LINEAGE_VALIDATION_NO_ECONOMIC_MUTATION",
        "lineage_validated": True,
        "required_lineage_coverage_pct": core.number(policy["advisor_search"]["ZLICE"]["required_lineage_coverage_pct"]),
        "before": core.stats(stages["LICO"]),
        "candidate": core.stats(stages["ZLICE"]),
        "after": core.stats(stages["ZLICE"]),
        "evidence": core.evidence(core.stats(stages["ZLICE"]), core.stats(stages["LICO"]), policy),
    }

    stage_stats = {name: core.stats(stage_rows) for name, stage_rows in stages.items()}
    order = ("CONTROL", "TEAM", "SKILL", "ZBOT", "ZICO", "LICO", "ZLICE")
    marginal = {
        order[index]: core.stage_delta(stage_stats[order[index]], stage_stats[order[index - 1]])
        for index in range(1, len(order))
    }
    for stage, decision in decisions.items():
        if stage != "ZLICE" and decision["applied"] and marginal[stage] < -1e-12:
            raise RuntimeError(f"APPLIED_STAGE_NEGATIVE_MARGINAL:{stage}:{marginal[stage]}")
    full = stage_stats["ZLICE"]
    full_evidence = core.evidence(full, control, policy)
    residual = core.stage_delta(full, control) - sum(marginal.values())
    if abs(residual) > 1e-9:
        raise RuntimeError(f"ATTRIBUTION_RESIDUAL_NONZERO:{residual}")

    sample_min = int(policy["epoch_policy"].get("minimum_trade_count_for_performance_claim", 20))
    low_sample = min(int(control["trade_count"]), int(full["trade_count"])) < sample_min
    eligible_axes = {
        "BOT_POLICY": (not low_sample) and any(bool(best_bots[role]["evidence"]["material"]) for role in core.ROLE_ORDER),
        "TEAM_POLICY": (not low_sample) and bool(decisions["TEAM"]["applied"]),
        "SKILL_PROFILE": (not low_sample) and bool(decisions["SKILL"]["applied"]),
        "ADVISOR_PROFILE": (not low_sample) and any(bool(decisions[role]["applied"]) for role in ("ZBOT", "ZICO", "LICO")),
    }

    previous_best = core.number(prior.get("best_full_net"), -1e99)
    improvement = core.number(full["net_return_pct_sum"]) - (
        previous_best if previous_best > -1e98 else core.number(control["net_return_pct_sum"])
    )
    patience = 0 if improvement >= core.number(policy["epoch_policy"]["minimum_material_net_pct_points"]) else int(prior.get("patience", 0)) + 1
    converged = (
        patience >= int(policy["epoch_policy"]["patience_epochs"])
        or epoch >= int(policy["epoch_policy"]["max_epochs_per_data_fingerprint"])
    )
    if low_sample:
        state = "LOW_SAMPLE_HOLD"
    elif converged:
        state = "CONVERGED_HOLD"
    elif full_evidence["material"]:
        state = "PASS_COMPONENT_AUTONOMY_EPOCH"
    else:
        state = "HOLD_NO_MATERIAL_COMPONENT_IMPROVEMENT"

    gemini_required = (not same) or converged
    output = {
        "schema_version": "2.1",
        "version": VERSION,
        "state": state,
        "epoch": min(epoch, int(policy["epoch_policy"]["max_epochs_per_data_fingerprint"])),
        "data_fingerprint": fingerprint,
        "source_authority": {
            "ledger_sha256": ledger_sha,
            "summary_sha256": summary_sha,
            "authority_exact_summary_sha256": summary.get("authority_exact_summary_sha256"),
            "selected_authority_result_sha256": summary.get("selected_authority_result_sha256"),
        },
        "strategy_id": "trend_ma_macd",
        "strategy_variant": "BASE_EXACT_TF_EMA_TRAIL1R_ATR1",
        "execution_fidelity": "CANONICAL_EXACT_LEDGER_PLUS_SEQUENTIAL_ROLE_BOUND_COUNTERFACTUALS",
        "control": {"stats": control, "event_count": len(rows), "event_ledger_sha256": core.stable_sha(rows)},
        "module_results": {
            "bots": {"tested": len(bot_candidates), "best_by_role": best_bots},
            "teams": {"tested": len(team_candidates), "best": best_team},
            "skills": {
                "tested": len(skill_candidates),
                "best": best_skill,
                "observer_only_ids": sorted(core.OBSERVER_ONLY_SKILLS),
            },
            "advisors": advisor_results,
        },
        "pipeline_decisions": decisions,
        "full_stack": {
            "stats": full,
            "evidence": full_evidence,
            "ordered_stage_stats": stage_stats,
            "applied_components": {stage: bool(row["applied"]) for stage, row in decisions.items()},
        },
        "component_attribution": {
            "ordered_marginal_delta_net": marginal,
            "full_stack_delta_net": core.stage_delta(full, control),
            "interaction_residual": residual,
            "method": "SEQUENTIAL_MATERIAL_ONLY_EXACT_SUM",
        },
        "axis_review_eligibility": eligible_axes,
        "convergence": {
            "patience": patience,
            "fingerprint_reset": not same,
            "maximum_epochs": int(policy["epoch_policy"]["max_epochs_per_data_fingerprint"]),
            "minimum_trade_count_for_performance_claim": sample_min,
            "low_sample_hold": low_sample,
            "reopen_on": policy["epoch_policy"]["reopen_on"],
        },
        "ai_usage": {
            "groq_required_axes": [axis for axis, active in eligible_axes.items() if active],
            "workers_ai_required_axes": [axis for axis, active in eligible_axes.items() if active],
            "gemini_required_this_epoch": gemini_required,
            "gemini_trigger_reason": "NEW_EXACT_FINGERPRINT" if not same else ("CONVERGENCE" if converged else "NONE"),
            "gemini_hypothesis_only_when_low_sample": low_sample,
            "same_fingerprint_repeat_forbidden": True,
            "router_policy": policy["ai_policy"],
        },
        "shadow_start_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        **core.SAFE,
    }
    output["result_sha256"] = core.stable_sha(output)
    return output


def _fixture_rows(count: int) -> list[dict[str, Any]]:
    values = [0.30, -0.20, 0.55, -0.35, 0.70, -0.10, 0.42, -0.18, 0.61, 0.12, -0.22, 0.38,
              0.47, -0.16, 0.52, 0.09, -0.24, 0.33, 0.41, -0.12, 0.49, 0.15, -0.19, 0.36]
    rows: list[dict[str, Any]] = []
    for index, net in enumerate(values[:count]):
        day = index + 1
        rows.append({
            "window_id": f"F{1 + index // 4}",
            "symbol": "BTCUSDT" if index % 2 == 0 else "SOLUSDT",
            "entry_ts": f"2026-01-{day:02d}T00:00:00+00:00",
            "exit_ts": f"2026-01-{day:02d}T01:00:00+00:00",
            "net_return_pct": net,
            "mfe_r": max(0.2, net * 4.0 + 1.0),
            "mae_r": max(0.1, -net * 2.0 + 0.2),
            "bars_held": 4 + index,
            "signal_skill": "long_beam" if index % 3 == 0 else "trend_entry",
            "signal_ts": f"2026-01-{day:02d}T00:00:00+00:00",
            "features": {
                "atr_percentile": 20 + (index % 7) * 10,
                "distance_ema20_atr": 0.5 + (index % 5) * 0.1,
                "adx14": 15 + (index % 6) * 3,
                "trend_ema20_50": True,
                "macd_positive": index % 2 == 0,
                "obv_positive": True,
                "directional_close_long": True,
                "body_atr": 0.4 + (index % 4) * 0.1,
                "donchian_break_long": index % 5 == 0,
                "volume_z": -0.5 + (index % 6) * 0.2,
                "atr_pct": 0.4 + (index % 5) * 0.1,
            },
        })
    return rows


def _fixture_input(count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = _fixture_rows(count)
    ledger = {"strategy_id": "trend_ma_macd", "trades": rows}
    baseline = core.stats([core.event(row) for row in rows])
    summary = {
        "strategy_id": "trend_ma_macd",
        "authority": "READ_ONLY_BASELINE_EVIDENCE_NO_EXECUTION",
        "baseline": {"trade_count": count, "net_return_pct_sum": baseline["net_return_pct_sum"]},
        "authority_exact_summary_sha256": "fixture",
        "selected_authority_result_sha256": "fixture",
    }
    return ledger, summary


def fixture(out: str | Path) -> int:
    policy = core.read_json(Path(__file__).resolve().parents[1] / "research" / "zel_component_autonomy_policy_v2.json")
    ledger, summary = _fixture_input(24)
    first = optimize(policy, ledger, summary)
    second = optimize(policy, ledger, summary)
    assert first["result_sha256"] == second["result_sha256"]
    assert set(first["module_results"]["bots"]["best_by_role"]) == set(core.ROLE_ORDER)
    assert first["module_results"]["skills"]["best"]["skill_id"] not in core.OBSERVER_ONLY_SKILLS
    assert abs(core.number(first["component_attribution"]["interaction_residual"])) <= 1e-12
    for stage, decision in first["pipeline_decisions"].items():
        if stage != "ZLICE" and decision["applied"]:
            assert decision["evidence"]["material"] is True
            assert core.number(first["component_attribution"]["ordered_marginal_delta_net"][stage]) >= -1e-12
    low_ledger, low_summary = _fixture_input(5)
    low = optimize(policy, low_ledger, low_summary)
    assert low["state"] == "LOW_SAMPLE_HOLD"
    assert not any(low["axis_review_eligibility"].values())
    assert low["ai_usage"]["gemini_required_this_epoch"] is True
    assert first["order_authority"] == "BLOCKED"
    core.write_json(Path(out) / "fixture_result.json", first)
    core.write_json(Path(out) / "low_sample_fixture_result.json", low)
    print("PASS_COMPONENT_AUTONOMY_V2_1_FIXTURE", first["result_sha256"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--policy", required=True)
    run.add_argument("--ledger", required=True)
    run.add_argument("--summary", required=True)
    run.add_argument("--previous-state")
    run.add_argument("--out", required=True)
    test = subparsers.add_parser("fixture")
    test.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.mode == "fixture":
        return fixture(args.out)
    policy = core.read_json(args.policy)
    previous = core.read_json(args.previous_state) if args.previous_state and Path(args.previous_state).is_file() else None
    result = optimize(policy, core.read_json(args.ledger), core.read_json(args.summary), previous)
    core.write_json(Path(args.out) / "final.json", result)
    core.write_json(Path(args.out) / "state.json", {
        "epoch": result["epoch"],
        "data_fingerprint": result["data_fingerprint"],
        "patience": result["convergence"]["patience"],
        "best_full_net": result["full_stack"]["stats"]["net_return_pct_sum"],
        "result_sha256": result["result_sha256"],
        **core.SAFE,
    })
    print(result["state"], result["result_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
