from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from backend.research.strategy11_portfolio_governor_v1 import SAFETY, govern
from backend.research.zel_portfolio_role_engine_v1 import (
    PortfolioRoleError,
    _fail,
    candidate_score,
    canonical_sha,
    pair_metrics,
    validate_candidate,
    validate_policy,
)

SCHEMA_VERSION = "zel.portfolio_role_engine.v1.1"


def pair_lookup(rows: list[dict[str, Any]]) -> dict[frozenset[str], dict[str, Any]]:
    return {frozenset((row["left"], row["right"])): row for row in rows}


def compatible(
    left: str,
    right: str,
    lookup: Mapping[frozenset[str], Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> bool:
    row = lookup.get(frozenset((left, right)))
    if row is None:
        return True
    return (
        float(row["absolute_correlation"]) <= float(policy["maximum_pair_correlation"])
        and float(row["signal_overlap"]) <= float(policy["maximum_signal_overlap"])
    )


def weighted_series(rows: list[dict[str, Any]], weights: Mapping[str, float]) -> dict[str, float]:
    common = set(rows[0]["return_series"])
    for row in rows[1:]:
        common &= set(row["return_series"])
    return {
        timestamp: sum(row["return_series"][timestamp] * weights[row["material_id"]] for row in rows)
        for timestamp in sorted(common)
    }


def build_family_ensembles_safe(
    candidates: list[dict[str, Any]],
    scores: Mapping[str, float],
    candidate_pairs: list[dict[str, Any]],
    policy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lookup = pair_lookup(candidate_pairs)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate["family"]].append(candidate)
    ensembles: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    for family, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: (-scores[row["material_id"]], row["material_id"]))
        selected = [ordered[0]]
        for candidate in ordered[1:]:
            if compatible(selected[0]["material_id"], candidate["material_id"], lookup, policy):
                selected.append(candidate)
                break
            pruned.append({
                "material_id": candidate["material_id"],
                "reason": "HIGH_CORRELATION_OR_SIGNAL_OVERLAP_WITH_FAMILY_PRIMARY",
                "retained_as_observer_control": True,
            })
        total_score = sum(max(scores[row["material_id"]], 0.000001) for row in selected)
        member_weights = {
            row["material_id"]: max(scores[row["material_id"]], 0.000001) / total_score
            for row in selected
        }
        intersections = set(selected[0]["eligible_regimes"])
        for row in selected[1:]:
            intersections &= set(row["eligible_regimes"])
        regimes = sorted(intersections)
        if not regimes:
            regimes = sorted(set().union(*(set(row["eligible_regimes"]) for row in selected)))
        signals = sorted(set().union(*(set(row["signal_event_ids"]) for row in selected)))
        series = weighted_series(selected, member_weights)
        ensemble = {
            "material_id": f"family.{family.lower()}",
            "family": family,
            "classification": "SYNTHESIS" if len(selected) > 1 else "CORE",
            "member_ids": [row["material_id"] for row in selected],
            "member_weights": dict(sorted(member_weights.items())),
            "eligible_regimes": regimes,
            "return_series": series,
            "signal_event_ids": signals,
            "material_sealed": True,
            "net_after_cost": sum(row["net_after_cost"] * member_weights[row["material_id"]] for row in selected),
            "confidence": sum(row["confidence"] * member_weights[row["material_id"]] for row in selected),
            "uncertainty": sum(row["uncertainty"] * member_weights[row["material_id"]] for row in selected),
            "dd_pct": sum(row["dd_pct"] * member_weights[row["material_id"]] for row in selected),
            "joint_tail_dd_pct": max(row["joint_tail_dd_pct"] for row in selected),
            "cost_pct": sum(row["cost_pct"] * member_weights[row["material_id"]] for row in selected),
            "capacity_score": min(row["capacity_score"] for row in selected),
            "incumbent_weight": sum(row["incumbent_weight"] for row in selected),
            "sbot_veto": any(row["sbot_veto"] for row in selected),
        }
        ensemble["ensemble_sha256"] = canonical_sha(ensemble)
        ensembles.append(ensemble)
    return ensembles, pruned


def normalized_exposures(
    active: list[dict[str, Any]],
    weights: Mapping[str, float],
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    total = sum(float(value) for value in weights.values())
    if total <= 0:
        _fail("TARGET_WEIGHT_TOTAL_INVALID")
    lookup = {row["material_id"]: row for row in candidates}
    family: dict[str, float] = defaultdict(float)
    side: dict[str, float] = defaultdict(float)
    symbol: dict[str, float] = defaultdict(float)
    for ensemble in active:
        ensemble_ratio = float(weights.get(ensemble["material_id"], 0.0)) / total
        family[ensemble["family"]] += ensemble_ratio
        for member_id, member_weight in ensemble["member_weights"].items():
            member = lookup[member_id]
            effective = ensemble_ratio * float(member_weight)
            side[member["side"]] += effective
            for symbol_id, symbol_weight in member["symbol_weights"].items():
                symbol[symbol_id] += effective * float(symbol_weight)
    return dict(family), dict(side), dict(symbol)


def evaluate(candidates_value: list[Mapping[str, Any]], policy_value: Mapping[str, Any]) -> dict[str, Any]:
    policy = validate_policy(policy_value)
    if not isinstance(candidates_value, list):
        _fail("CANDIDATE_LIST_REQUIRED")
    candidates = [validate_candidate(row, policy["minimum_return_points"]) for row in candidates_value]
    if len({row["material_id"] for row in candidates}) != len(candidates):
        _fail("DUPLICATE_MATERIAL_ID")
    if not policy["s_material_min"] <= len(candidates) <= policy["s_material_max"]:
        _fail("S_MATERIAL_COUNT_OUT_OF_RANGE", str(len(candidates)))
    standalone = [row for row in candidates if row["standalone_eligible"]]
    if not policy["standalone_min"] <= len(standalone) <= policy["standalone_max"]:
        _fail("STANDALONE_COUNT_OUT_OF_RANGE", str(len(standalone)))

    vetoed = sorted(row["material_id"] for row in candidates if row["sbot_veto"])
    eligible = [row for row in candidates if not row["sbot_veto"]]
    candidate_pairs, average_correlation = pair_metrics(eligible, policy["minimum_return_points"])
    scores = {
        row["material_id"]: candidate_score(row, average_correlation[row["material_id"]], policy)
        for row in eligible
    }
    marginal_rejected = sorted(
        material_id for material_id, score in scores.items()
        if score < policy["minimum_marginal_score"]
    )
    role_candidates = [row for row in eligible if row["material_id"] not in marginal_rejected]
    ensembles, pruned = build_family_ensembles_safe(role_candidates, scores, candidate_pairs, policy)
    if not policy["family_ensemble_min"] <= len(ensembles) <= policy["family_ensemble_max"]:
        _fail("FAMILY_ENSEMBLE_COUNT_OUT_OF_RANGE", str(len(ensembles)))

    regime_eligible = [
        row for row in ensembles
        if policy["current_regime"] in row["eligible_regimes"] and not row["sbot_veto"]
    ]
    ordered = sorted(
        regime_eligible,
        key=lambda row: (-sum(scores[member] for member in row["member_ids"]), row["material_id"]),
    )
    active_count = min(policy["active_ensemble_max"], len(ordered))
    if active_count < policy["active_ensemble_min"]:
        _fail("ACTIVE_ENSEMBLE_COUNT_INSUFFICIENT", str(active_count))
    active = ordered[:active_count]
    active_pairs, _ = pair_metrics(active, policy["minimum_return_points"])
    blockers = [
        f"ACTIVE_PAIR_CORRELATION:{row['left']}:{row['right']}"
        for row in active_pairs
        if row["absolute_correlation"] > policy["maximum_pair_correlation"]
    ] + [
        f"ACTIVE_SIGNAL_OVERLAP:{row['left']}:{row['right']}"
        for row in active_pairs
        if row["signal_overlap"] > policy["maximum_signal_overlap"]
    ]

    governor_payload = {
        "candidate_set_sha": canonical_sha(candidates),
        "correlation_artifact_sha": canonical_sha(active_pairs),
        "materials": [
            {
                "material_id": row["material_id"],
                "classification": row["classification"],
                "material_sealed": row["material_sealed"],
                "net_after_cost": row["net_after_cost"],
                "confidence": row["confidence"],
                "uncertainty": row["uncertainty"],
                "dd_pct": row["dd_pct"],
                "joint_tail_dd_pct": row["joint_tail_dd_pct"],
                "cost_pct": row["cost_pct"],
                "capacity_score": row["capacity_score"],
                "incumbent_weight": row["incumbent_weight"],
            }
            for row in active
        ],
        "policy": {
            "total_risk_budget": policy["total_risk_budget"],
            "max_material_weight": policy["max_material_weight"],
            "min_material_weight": policy["min_material_weight"],
            "max_turnover": policy["max_turnover"],
        },
        **SAFETY,
    }
    governed = govern(governor_payload)
    blockers.extend(governed.get("blockers", []))
    weights = governed.get("target_risk_weights", {})
    family_weights, side_weights, symbol_weights = normalized_exposures(active, weights, candidates)
    if any(weight > policy["maximum_family_weight"] for weight in family_weights.values()):
        blockers.append("FAMILY_WEIGHT_LIMIT")
    if any(weight > policy["maximum_symbol_weight"] for weight in symbol_weights.values()):
        blockers.append("SYMBOL_WEIGHT_LIMIT")
    if any(weight > policy["maximum_side_weight"] for weight in side_weights.values()):
        blockers.append("SIDE_WEIGHT_LIMIT")
    if any(row["joint_tail_dd_pct"] > policy["maximum_joint_dd_pct"] for row in active):
        blockers.append("JOINT_DD_LIMIT")

    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_P3_SHADOW_PORTFOLIO_TARGETS" if not blockers else "HOLD_P3_PORTFOLIO_GAPS",
        "s_material_count": len(candidates),
        "standalone_strategy_count": len(standalone),
        "family_ensemble_count": len(ensembles),
        "active_ensemble_count": len(active),
        "vetoed_material_ids": vetoed,
        "marginal_rejected_material_ids": marginal_rejected,
        "correlation_pruned_rows": pruned,
        "candidate_pair_metrics": candidate_pairs,
        "active_pair_metrics": active_pairs,
        "candidate_scores": dict(sorted((key, round(value, 10)) for key, value in scores.items())),
        "family_ensembles": ensembles,
        "active_ensemble_ids": [row["material_id"] for row in active],
        "target_risk_weights": weights,
        "family_weight_ratios": dict(sorted(family_weights.items())),
        "side_weight_ratios": dict(sorted(side_weights.items())),
        "symbol_weight_ratios": dict(sorted(symbol_weights.items())),
        "blockers": sorted(set(blockers)),
        "observer_control_ids": sorted(row["material_id"] for row in candidates),
        "capital_activation_allowed": False,
        "shadow_only": True,
        "parent_strategy_mutation_count": 0,
        "sbot_veto_override_count": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "policy_sha256": canonical_sha(policy),
        "input_sha256": canonical_sha(candidates),
    }
    result["result_sha256"] = canonical_sha(result)
    return result


__all__ = ["PortfolioRoleError", "evaluate"]
