from __future__ import annotations

import argparse
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

VERSION = "ZEL_COMPONENT_AUTONOMY_V2_ROLE_BOUND_PIPELINE"
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
OBSERVER_ONLY_SKILLS = {"SK_ENTRY_SHORT_BEAM", "SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD"}
ROLE_ORDER = ("LBot", "MBot", "OBot", "SBot")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def event(row: Mapping[str, Any]) -> dict[str, Any]:
    features = dict(row.get("features") or {})
    atr_rank = number(features.get("atr_percentile"), 50.0) / 100.0
    distance = number(features.get("distance_ema20_atr"), 2.0)
    risk = max(0.0, min(1.0, 0.55 * atr_rank + 0.45 * min(distance / 3.0, 1.0)))
    scores = {
        "trend_score": max(0.0, min(1.0, (number(features.get("adx14")) / 40.0 + 0.5 * bool(features.get("trend_ema20_50"))) / 1.5)),
        "confirm_score": max(0.0, min(1.0, 0.45 * bool(features.get("macd_positive")) + 0.30 * bool(features.get("obv_positive")) + 0.25 * bool(features.get("directional_close_long")))),
        "breakout_score": max(0.0, min(1.0, 0.55 * number(features.get("body_atr")) + 0.45 * bool(features.get("donchian_break_long")))),
        "intuition_score": max(0.0, min(1.0, (number(features.get("volume_z")) + 2.0) / 4.0)),
        "safety_score": 1.0 - risk,
        "risk_score": risk,
    }
    return {
        "window_id": str(row["window_id"]),
        "symbol": str(row["symbol"]),
        "signal_ts": row.get("signal_ts"),
        "entry_ts": str(row["entry_ts"]),
        "exit_ts": str(row["exit_ts"]),
        "net": number(row.get("net_return_pct")),
        "mfe_r": number(row.get("mfe_r")),
        "mae_r": number(row.get("mae_r")),
        "bars_held": int(row.get("bars_held") or 0),
        "beam": row.get("signal_skill") == "long_beam",
        "volume_z": number(features.get("volume_z"), -9.0),
        "atr_pct": number(features.get("atr_pct")),
        "scores": scores,
        "lineage_complete": bool(row.get("signal_ts") and row.get("entry_ts") and row.get("exit_ts") and row.get("features")),
    }


def load_events(ledger: Mapping[str, Any], summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    if ledger.get("strategy_id") != "trend_ma_macd" or summary.get("strategy_id") != "trend_ma_macd":
        raise RuntimeError("STRATEGY_ID_MISMATCH")
    if summary.get("authority") != "READ_ONLY_BASELINE_EVIDENCE_NO_EXECUTION":
        raise RuntimeError("EVIDENCE_AUTHORITY_INVALID")
    rows = [event(row) for row in ledger.get("trades", [])]
    baseline = summary.get("baseline") or {}
    if len(rows) != int(baseline.get("trade_count", -1)):
        raise RuntimeError("TRADE_COUNT_MISMATCH")
    if abs(sum(number(row["net"]) for row in rows) - number(baseline.get("net_return_pct_sum"))) > 1e-9:
        raise RuntimeError("NET_SUM_MISMATCH")
    if not rows or not all(row["lineage_complete"] for row in rows):
        raise RuntimeError("LINEAGE_INCOMPLETE")
    return sorted(rows, key=lambda row: (pd.Timestamp(row["entry_ts"]), row["symbol"]))


def stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    ordered = sorted(rows, key=lambda row: (pd.Timestamp(row["entry_ts"]), str(row["symbol"])))
    returns = [number(row.get("net")) for row in ordered]
    wins = [value for value in returns if value > 0.0]
    losses = [value for value in returns if value < 0.0]
    equity = peak = drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gross_loss = abs(sum(losses))
    profit_factor = sum(wins) / gross_loss if gross_loss > 1e-12 else (999.0 if wins else 0.0)
    count = len(ordered)
    return {
        "trade_count": count,
        "win_rate_pct": 100.0 * len(wins) / count if count else 0.0,
        "net_return_pct_sum": sum(returns),
        "profit_factor": profit_factor,
        "max_drawdown_pct": drawdown,
        "average_mfe_r": sum(number(row.get("mfe_r")) for row in ordered) / count if count else 0.0,
        "average_mae_r": sum(number(row.get("mae_r")) for row in ordered) / count if count else 0.0,
    }


def evidence(candidate: Mapping[str, Any], control: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    delta = {
        "net": number(candidate.get("net_return_pct_sum")) - number(control.get("net_return_pct_sum")),
        "pf": number(candidate.get("profit_factor")) - number(control.get("profit_factor")),
        "dd_reduction": number(control.get("max_drawdown_pct")) - number(candidate.get("max_drawdown_pct")),
        "retention": number(candidate.get("trade_count")) / max(number(control.get("trade_count")), 1.0),
    }
    epoch = policy["epoch_policy"]
    material = (
        delta["net"] >= number(epoch["minimum_material_net_pct_points"])
        and delta["retention"] >= number(epoch["minimum_trade_retention"])
        and (delta["pf"] >= number(epoch["minimum_material_pf"]) or delta["dd_reduction"] >= number(epoch["minimum_material_dd_pct_points"]))
    )
    no_change = all(abs(delta[name]) <= 1e-12 for name in ("net", "pf", "dd_reduction")) and abs(delta["retention"] - 1.0) <= 1e-12
    return {"deltas": delta, "material": material, "no_change": no_change}


def role_score(row: Mapping[str, Any], role: str, weight: float, warning_cap: float) -> float:
    scores = row["scores"]
    mapping = {
        "LBot": ("trend_score", "confirm_score"),
        "MBot": ("confirm_score", "intuition_score"),
        "OBot": ("breakout_score", "trend_score"),
        "SBot": ("safety_score", "safety_score"),
    }
    primary, secondary = mapping[role]
    value = weight * number(scores[primary]) + (1.0 - weight) * number(scores[secondary])
    if number(scores["risk_score"]) >= 0.85:
        value = min(value, warning_cap)
    return value


def select_best(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not candidates:
        raise RuntimeError("CANDIDATE_SET_EMPTY")
    return dict(max(candidates, key=lambda row: (
        1 if (row.get("evidence") or {}).get("material") else 0,
        number((row.get("stats") or {}).get("net_return_pct_sum")),
        number((row.get("stats") or {}).get("profit_factor")),
        -number((row.get("stats") or {}).get("max_drawdown_pct")),
        number((row.get("stats") or {}).get("trade_count")),
    )))


def optimize_bots(rows: Sequence[Mapping[str, Any]], base: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    best_by_role: dict[str, dict[str, Any]] = {}
    for role in ROLE_ORDER:
        role_rows: list[dict[str, Any]] = []
        for weight in policy["bot_search"]["primary_weights"]:
            for threshold in policy["bot_search"]["helper_thresholds"]:
                for cap in policy["bot_search"]["warning_caps"]:
                    selected = [row for row in rows if role_score(row, role, number(weight), number(cap)) >= number(threshold)]
                    candidate_stats = stats(selected)
                    row = {
                        "bot": role,
                        "weight": number(weight),
                        "threshold": number(threshold),
                        "warning_cap": number(cap),
                        "stats": candidate_stats,
                        "evidence": evidence(candidate_stats, base, policy),
                    }
                    role_rows.append(row)
                    candidates.append(row)
        best_by_role[role] = select_best(role_rows)
    return candidates, best_by_role


def bot_scores(row: Mapping[str, Any], profiles: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    return {
        role: role_score(row, role, number(profile["weight"]), number(profile["warning_cap"]))
        for role, profile in profiles.items()
    }


def team_accepts(row: Mapping[str, Any], team: Mapping[str, Any], profiles: Mapping[str, Mapping[str, Any]], support: float, watcher_floor: float, veto: float) -> bool:
    values = bot_scores(row, profiles)
    if values[team["main"]] < number(profiles[team["main"]]["threshold"]):
        return False
    if values[team["support"]] < support:
        return False
    for watcher in team.get("watchers", []):
        if watcher == "SBot":
            if values[watcher] < 1.0 - veto:
                return False
        elif values[watcher] < watcher_floor:
            return False
    return True


def optimize_teams(rows: Sequence[Mapping[str, Any]], base: Mapping[str, Any], policy: Mapping[str, Any], profiles: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    watcher_floors = policy["team_search"].get("watcher_confirmation_thresholds", [0.35, 0.45, 0.55])
    for name, team in policy["team_search"]["teams"].items():
        for support in policy["team_search"]["support_thresholds"]:
            for watcher_floor in watcher_floors:
                for veto in policy["team_search"]["watcher_veto_thresholds"]:
                    selected = [row for row in rows if team_accepts(row, team, profiles, number(support), number(watcher_floor), number(veto))]
                    candidate_stats = stats(selected)
                    candidates.append({
                        "team": name,
                        "support_threshold": number(support),
                        "watcher_confirmation_threshold": number(watcher_floor),
                        "watcher_veto_threshold": number(veto),
                        "stats": candidate_stats,
                        "evidence": evidence(candidate_stats, base, policy),
                    })
    return candidates, select_best(candidates)


def apply_team(rows: Sequence[Mapping[str, Any]], best: Mapping[str, Any], policy: Mapping[str, Any], profiles: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    team = policy["team_search"]["teams"][best["team"]]
    return [
        deepcopy(row) for row in rows
        if team_accepts(
            row, team, profiles, number(best["support_threshold"]),
            number(best["watcher_confirmation_threshold"]), number(best["watcher_veto_threshold"]),
        )
    ]


def transform_skill(rows: Sequence[Mapping[str, Any]], skill_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    transformed: list[dict[str, Any]] = []
    observer_count = 0
    fidelity = "EVENT_LEVEL_COUNTERFACTUAL"
    selection_eligible = True
    if skill_id == "BASE_NO_SKILL":
        return [deepcopy(row) for row in rows], {"fidelity": "CONTROL", "selection_eligible": False, "observer_count": 0}
    if skill_id == "SK_ENTRY_LONG_BEAM":
        fidelity = "EXACT_LEDGER_SUBSET_LONG_BEAM_ONLY"
        return [deepcopy(row) for row in rows if row.get("beam")], {"fidelity": fidelity, "selection_eligible": True, "observer_count": 0}
    if skill_id == "SK_ENTRY_SHORT_BEAM":
        return [deepcopy(row) for row in rows], {"fidelity": "OBSERVER_ONLY_NO_SHORT_LEDGER", "selection_eligible": False, "observer_count": 0}
    for original in rows:
        row = deepcopy(original)
        net = number(row["net"])
        mfe = number(row["mfe_r"])
        mae = number(row["mae_r"])
        if skill_id in {"SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD"}:
            observer_count += int(mae >= 0.25)
            selection_eligible = False
            fidelity = "OBSERVER_ONLY_LOSS_DIRECTION_ADD"
        elif skill_id == "SK_ADD_PYRAMIDING" and mfe >= 0.35 and net > 0.0:
            row["net"] = net * 1.14
        elif skill_id == "SK_ADD_PROFITABLE_SCALE_IN" and mfe >= 0.35 and net > 0.0:
            row["net"] = net * 1.28
        elif skill_id == "SK_EXIT_PARTIAL_30" and mfe >= 1.0:
            row["net"] = 0.3 * max(net, 0.5) + 0.7 * net
        elif skill_id == "SK_EXIT_TRAILING_STOP" and mfe >= 1.0:
            row["net"] = max(net, (mfe - 1.0) * 0.25)
        elif skill_id == "SK_EXIT_MFE_RUNNER" and mfe >= 1.0:
            row["net"] = max(net, 0.15 + 0.35 * min(mfe, 3.0))
        elif skill_id == "SK_EXIT_RUNNER_HOLD" and mfe >= 2.0:
            row["net"] = max(net, 0.5 * min(mfe, 3.0))
        elif skill_id == "SK_EXIT_TIME_STOP" and int(row["bars_held"]) > 48:
            row["net"] = net * 48.0 / max(int(row["bars_held"]), 1)
        elif skill_id == "SK_EXIT_BREAK_EVEN_SHIFT" and mfe >= 1.0 and net < 0.0:
            row["net"] = -0.04
        elif skill_id == "SK_RISK_REDUCE_25" and mfe >= 0.75:
            row["net"] = 0.09375 + 0.75 * net
        transformed.append(row)
    return transformed, {"fidelity": fidelity, "selection_eligible": selection_eligible, "observer_count": observer_count}


def optimize_skills(rows: Sequence[Mapping[str, Any]], base: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    skill_ids = ["BASE_NO_SKILL", *policy["skill_search"]["entry_ablations"], *policy["skill_search"]["management_candidates"]]
    candidates: list[dict[str, Any]] = []
    for skill_id in skill_ids:
        transformed, meta = transform_skill(rows, skill_id)
        candidate_stats = stats(transformed)
        candidates.append({
            "skill_id": skill_id,
            "fidelity": meta["fidelity"],
            "selection_eligible": meta["selection_eligible"],
            "observer_count": meta["observer_count"],
            "loss_direction_observer_only": skill_id in OBSERVER_ONLY_SKILLS,
            "stats": candidate_stats,
            "evidence": evidence(candidate_stats, base, policy),
        })
    eligible = [row for row in candidates if row["selection_eligible"] and row["skill_id"] != "BASE_NO_SKILL"]
    return candidates, select_best(eligible)


def apply_cooldown(rows: Sequence[Mapping[str, Any]], bars: int) -> list[dict[str, Any]]:
    if bars <= 0:
        return [deepcopy(row) for row in rows]
    result: list[dict[str, Any]] = []
    last_loss_exit: dict[str, pd.Timestamp] = {}
    for original in sorted(rows, key=lambda row: (pd.Timestamp(row["entry_ts"]), row["symbol"])):
        row = deepcopy(original)
        symbol = str(row["symbol"])
        entry = pd.Timestamp(row["entry_ts"])
        previous = last_loss_exit.get(symbol)
        if previous is not None and entry < previous + pd.Timedelta(minutes=15 * bars):
            continue
        result.append(row)
        if number(row["net"]) < 0.0:
            last_loss_exit[symbol] = pd.Timestamp(row["exit_ts"])
    return result


def optimize_simple_role(
    rows: Sequence[Mapping[str, Any]], base: Mapping[str, Any], policy: Mapping[str, Any],
    role: str, configs: Sequence[Mapping[str, Any]], apply: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for config in configs:
        selected = apply(rows, config)
        candidate_stats = stats(selected)
        candidates.append({"role": role, "profile": dict(config), "stats": candidate_stats, "evidence": evidence(candidate_stats, base, policy)})
    return candidates, select_best(candidates)


def apply_lico(rows: Sequence[Mapping[str, Any]], profile: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    base_cost = number(policy["risk_contract"]["cost_bps_per_side"])
    cost = number(profile["cost_bps_per_side"])
    incremental_round_trip_pct = 2.0 * max(cost - base_cost, 0.0) / 100.0
    latency_bars = int(profile["latency_bars"])
    result: list[dict[str, Any]] = []
    for original in rows:
        if number(original.get("volume_z"), -9.0) < number(profile["minimum_volume_z"]):
            continue
        if number(original.get("atr_pct")) > number(profile["maximum_atr_pct"]):
            continue
        row = deepcopy(original)
        latency_penalty = 0.01 * latency_bars * min(number(row.get("mae_r")), 2.0)
        row["net"] = number(row["net"]) - incremental_round_trip_pct - latency_penalty
        result.append(row)
    return result


def optimize_advisors(rows: Sequence[Mapping[str, Any]], base: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    zbot_configs = [{"disagreement_threshold": number(value)} for value in policy["advisor_search"]["ZBOT"]["disagreement_thresholds"]]
    zbot, best_zbot = optimize_simple_role(
        rows, base, policy, "ZBOT", zbot_configs,
        lambda source, config: [deepcopy(row) for row in source if abs(number(row["scores"]["trend_score"]) - number(row["scores"]["confirm_score"])) <= number(config["disagreement_threshold"])],
    )
    zico_configs = [{"loss_cooldown_bars": int(value)} for value in policy["advisor_search"]["ZICO"]["loss_cooldown_bars"]]
    zico, best_zico = optimize_simple_role(rows, base, policy, "ZICO", zico_configs, lambda source, config: apply_cooldown(source, int(config["loss_cooldown_bars"])))
    lico_configs = [
        {
            "minimum_volume_z": number(volume), "maximum_atr_pct": number(atr),
            "cost_bps_per_side": number(cost), "latency_bars": int(latency),
        }
        for volume in policy["advisor_search"]["LICO"]["minimum_volume_z"]
        for atr in policy["advisor_search"]["LICO"]["maximum_atr_pct"]
        for cost in policy["advisor_search"]["LICO"].get("cost_bps_per_side", [policy["risk_contract"]["cost_bps_per_side"]])
        for latency in policy["advisor_search"]["LICO"].get("latency_bars", [0])
    ]
    lico, best_lico = optimize_simple_role(rows, base, policy, "LICO", lico_configs, lambda source, config: apply_lico(source, config, policy))
    zlice = {
        "role": "ZLICE",
        "profile": {"required_lineage_coverage_pct": number(policy["advisor_search"]["ZLICE"]["required_lineage_coverage_pct"])},
        "lineage_validated": all(row.get("lineage_complete") for row in rows),
        "selection_eligible": False,
        "stats": stats(rows),
        "evidence": evidence(stats(rows), base, policy),
    }
    if not zlice["lineage_validated"]:
        raise RuntimeError("ZLICE_LINEAGE_VALIDATION_FAILED")
    results = {
        "ZBOT": {"tested": len(zbot), "candidates": zbot, "best": best_zbot},
        "ZICO": {"tested": len(zico), "candidates": zico, "best": best_zico},
        "LICO": {"tested": len(lico), "candidates": lico, "best": best_lico},
        "ZLICE": {"tested": 1, "best": zlice},
    }
    combined_material = any(results[role]["best"]["evidence"]["material"] for role in ("ZBOT", "ZICO", "LICO"))
    return results, {"material": combined_material, "best_profiles": {role: results[role]["best"] for role in results}}


def stage_delta(after: Mapping[str, Any], before: Mapping[str, Any]) -> float:
    return number(after.get("net_return_pct_sum")) - number(before.get("net_return_pct_sum"))


def optimize(policy: Mapping[str, Any], ledger: Mapping[str, Any], summary: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rows = load_events(ledger, summary)
    base = stats(rows)
    ledger_sha = stable_sha(ledger)
    summary_sha = stable_sha(summary)
    fingerprint = stable_sha({"ledger": ledger_sha, "summary": summary_sha, "policy": stable_sha(policy), "version": VERSION})
    same = bool(previous and previous.get("data_fingerprint") == fingerprint)
    epoch = int(previous.get("epoch", 0)) + 1 if same and previous else 1
    prior = dict(previous or {}) if same else {}

    bot_candidates, best_bots = optimize_bots(rows, base, policy)
    team_candidates, best_team = optimize_teams(rows, base, policy, best_bots)
    skill_candidates, best_skill = optimize_skills(rows, base, policy)
    advisor_results, advisor_summary = optimize_advisors(rows, base, policy)

    applied_components = {
        "TEAM": bool(best_team["evidence"]["material"]),
        "SKILL": bool(best_skill["evidence"]["material"]),
        "ZBOT": bool(advisor_results["ZBOT"]["best"]["evidence"]["material"]),
        "ZICO": bool(advisor_results["ZICO"]["best"]["evidence"]["material"]),
        "LICO": bool(advisor_results["LICO"]["best"]["evidence"]["material"]),
        "ZLICE": True,
    }
    stage_rows: dict[str, list[dict[str, Any]]] = {"CONTROL": [deepcopy(row) for row in rows]}
    stage_rows["TEAM"] = apply_team(stage_rows["CONTROL"], best_team, policy, best_bots) if applied_components["TEAM"] else [deepcopy(row) for row in stage_rows["CONTROL"]]
    stage_rows["SKILL"], _ = transform_skill(stage_rows["TEAM"], best_skill["skill_id"]) if applied_components["SKILL"] else ([deepcopy(row) for row in stage_rows["TEAM"]], {"fidelity": "SKIP_NO_MATERIAL", "selection_eligible": False, "observer_count": 0})
    zbot_profile = advisor_results["ZBOT"]["best"]["profile"]
    stage_rows["ZBOT"] = [deepcopy(row) for row in stage_rows["SKILL"] if abs(number(row["scores"]["trend_score"]) - number(row["scores"]["confirm_score"])) <= number(zbot_profile["disagreement_threshold"])] if applied_components["ZBOT"] else [deepcopy(row) for row in stage_rows["SKILL"]]
    zico_profile = advisor_results["ZICO"]["best"]["profile"]
    stage_rows["ZICO"] = apply_cooldown(stage_rows["ZBOT"], int(zico_profile["loss_cooldown_bars"])) if applied_components["ZICO"] else [deepcopy(row) for row in stage_rows["ZBOT"]]
    lico_profile = advisor_results["LICO"]["best"]["profile"]
    stage_rows["LICO"] = apply_lico(stage_rows["ZICO"], lico_profile, policy) if applied_components["LICO"] else [deepcopy(row) for row in stage_rows["ZICO"]]
    if not all(row.get("lineage_complete") for row in stage_rows["LICO"]):
        raise RuntimeError("ZLICE_FULL_STACK_LINEAGE_FAILURE")
    stage_rows["ZLICE"] = [deepcopy(row) for row in stage_rows["LICO"]]
    stage_stats = {name: stats(value) for name, value in stage_rows.items()}
    order = ("CONTROL", "TEAM", "SKILL", "ZBOT", "ZICO", "LICO", "ZLICE")
    marginal = {
        order[index]: stage_delta(stage_stats[order[index]], stage_stats[order[index - 1]])
        for index in range(1, len(order))
    }
    full = stage_stats["ZLICE"]
    full_evidence = evidence(full, base, policy)
    residual = stage_delta(full, base) - sum(marginal.values())
    if abs(residual) > 1e-9:
        raise RuntimeError(f"ATTRIBUTION_RESIDUAL_NONZERO:{residual}")

    eligible_axes = {
        "BOT_POLICY": any(best_bots[role]["evidence"]["material"] for role in ROLE_ORDER),
        "TEAM_POLICY": bool(best_team["evidence"]["material"]),
        "SKILL_PROFILE": bool(best_skill["evidence"]["material"]),
        "ADVISOR_PROFILE": bool(advisor_summary["material"]),
    }
    sample_min = int(policy["epoch_policy"].get("minimum_trade_count_for_performance_claim", 20))
    low_sample = min(int(base["trade_count"]), int(full["trade_count"])) < sample_min
    previous_best = number(prior.get("best_full_net"), -1e99)
    improvement = number(full["net_return_pct_sum"]) - (previous_best if previous_best > -1e98 else number(base["net_return_pct_sum"]))
    patience = 0 if improvement >= number(policy["epoch_policy"]["minimum_material_net_pct_points"]) else int(prior.get("patience", 0)) + 1
    converged = patience >= int(policy["epoch_policy"]["patience_epochs"]) or epoch >= int(policy["epoch_policy"]["max_epochs_per_data_fingerprint"])
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
        "schema_version": "2.0",
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
        "execution_fidelity": "CANONICAL_EXACT_LEDGER_PLUS_ROLE_BOUND_COUNTERFACTUAL_COMPONENTS",
        "control": {"stats": base, "event_count": len(rows), "event_ledger_sha256": stable_sha(rows)},
        "module_results": {
            "bots": {"tested": len(bot_candidates), "best_by_role": best_bots},
            "teams": {"tested": len(team_candidates), "best": best_team},
            "skills": {"tested": len(skill_candidates), "best": best_skill, "observer_only_ids": sorted(OBSERVER_ONLY_SKILLS)},
            "advisors": advisor_results,
        },
        "full_stack": {"stats": full, "evidence": full_evidence, "ordered_stage_stats": stage_stats, "applied_components": applied_components},
        "component_attribution": {
            "ordered_marginal_delta_net": marginal,
            "full_stack_delta_net": stage_delta(full, base),
            "interaction_residual": residual,
            "method": "ORDERED_MARGINAL_EXACT_SUM",
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
            "same_fingerprint_repeat_forbidden": True,
            "router_policy": policy["ai_policy"],
        },
        "shadow_start_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        **SAFE,
    }
    output["result_sha256"] = stable_sha(output)
    return output


def fixture(out: str | Path) -> int:
    rows = []
    for index, net in enumerate([0.30, -0.20, 0.55, -0.35, 0.70, -0.10, 0.42, -0.18, 0.61, 0.12, -0.22, 0.38, 0.47, -0.16, 0.52, 0.09, -0.24, 0.33, 0.41, -0.12, 0.49, 0.15, -0.19, 0.36]):
        day = 1 + index
        rows.append({
            "window_id": f"F{1 + index // 4}", "symbol": "BTCUSDT" if index % 2 == 0 else "SOLUSDT",
            "entry_ts": f"2026-01-{day:02d}T00:00:00+00:00", "exit_ts": f"2026-01-{day:02d}T01:00:00+00:00",
            "net_return_pct": net, "mfe_r": max(0.2, net * 4.0 + 1.0), "mae_r": max(0.1, -net * 2.0 + 0.2),
            "bars_held": 4 + index, "signal_skill": "long_beam" if index % 3 == 0 else "trend_entry",
            "signal_ts": f"2026-01-{day:02d}T00:00:00+00:00",
            "features": {
                "atr_percentile": 20 + (index % 7) * 10, "distance_ema20_atr": 0.5 + (index % 5) * 0.1,
                "adx14": 15 + (index % 6) * 3, "trend_ema20_50": True, "macd_positive": index % 2 == 0,
                "obv_positive": True, "directional_close_long": True, "body_atr": 0.4 + (index % 4) * 0.1,
                "donchian_break_long": index % 5 == 0, "volume_z": -0.5 + (index % 6) * 0.2, "atr_pct": 0.4 + (index % 5) * 0.1,
            },
        })
    ledger = {"strategy_id": "trend_ma_macd", "trades": rows}
    baseline = stats([event(row) for row in rows])
    summary = {
        "strategy_id": "trend_ma_macd", "authority": "READ_ONLY_BASELINE_EVIDENCE_NO_EXECUTION",
        "baseline": {"trade_count": len(rows), "net_return_pct_sum": baseline["net_return_pct_sum"]},
        "authority_exact_summary_sha256": "fixture", "selected_authority_result_sha256": "fixture",
    }
    policy = read_json(Path(__file__).resolve().parents[1] / "research" / "zel_component_autonomy_policy_v2.json")
    first = optimize(policy, ledger, summary)
    second = optimize(policy, ledger, summary)
    assert first["result_sha256"] == second["result_sha256"]
    assert set(first["module_results"]["bots"]["best_by_role"]) == set(ROLE_ORDER)
    assert first["module_results"]["skills"]["best"]["skill_id"] not in OBSERVER_ONLY_SKILLS
    assert first["module_results"]["skills"]["observer_only_ids"] == sorted(OBSERVER_ONLY_SKILLS)
    assert abs(number(first["component_attribution"]["interaction_residual"])) <= 1e-12
    assert first["convergence"]["low_sample_hold"] is False
    low_rows = rows[:5]
    low_ledger = {"strategy_id": "trend_ma_macd", "trades": low_rows}
    low_baseline = stats([event(row) for row in low_rows])
    low_summary = dict(summary)
    low_summary["baseline"] = {"trade_count": len(low_rows), "net_return_pct_sum": low_baseline["net_return_pct_sum"]}
    low = optimize(policy, low_ledger, low_summary)
    assert low["state"] == "LOW_SAMPLE_HOLD"
    assert low["convergence"]["low_sample_hold"] is True
    assert first["order_authority"] == "BLOCKED"
    write_json(Path(out) / "fixture_result.json", first)
    write_json(Path(out) / "low_sample_fixture_result.json", low)
    print("PASS_COMPONENT_AUTONOMY_V2_FIXTURE", first["result_sha256"])
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
    policy = read_json(args.policy)
    previous = read_json(args.previous_state) if args.previous_state and Path(args.previous_state).is_file() else None
    result = optimize(policy, read_json(args.ledger), read_json(args.summary), previous)
    write_json(Path(args.out) / "final.json", result)
    write_json(Path(args.out) / "state.json", {
        "epoch": result["epoch"], "data_fingerprint": result["data_fingerprint"],
        "patience": result["convergence"]["patience"], "best_full_net": result["full_stack"]["stats"]["net_return_pct_sum"],
        "result_sha256": result["result_sha256"], **SAFE,
    })
    print(result["state"], result["result_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
