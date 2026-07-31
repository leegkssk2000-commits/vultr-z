from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

from backend.research.strategy11_portfolio_governor_v1 import SAFETY, govern

SCHEMA_VERSION = "zel.portfolio_role_engine.v1"
FAMILIES = {"TREND", "MEAN_REVERSION", "BREAKOUT", "HYBRID"}
CLASSIFICATIONS = {"CORE", "SYNTHESIS"}
REQUIRED_CANDIDATE_FIELDS = {
    "material_id", "strategy_id", "strategy_source_sha256", "family", "classification",
    "material_sealed", "net_after_cost", "confidence", "uncertainty", "dd_pct",
    "joint_tail_dd_pct", "cost_pct", "capacity_score", "incumbent_weight",
    "standalone_eligible", "eligible_regimes", "return_series", "signal_event_ids",
    "symbol_weights", "side", "sbot_veto", "lineage_verified",
}
REQUIRED_POLICY_FIELDS = {
    "source_ref", "source_sha256", "current_regime", "minimum_return_points",
    "maximum_pair_correlation", "maximum_signal_overlap", "maximum_family_weight",
    "maximum_symbol_weight", "maximum_side_weight", "maximum_joint_dd_pct",
    "minimum_marginal_score", "active_ensemble_min", "active_ensemble_max",
    "family_ensemble_min", "family_ensemble_max", "standalone_min", "standalone_max",
    "s_material_min", "s_material_max", "edge_weight", "diversification_weight",
    "regime_weight", "total_risk_budget", "max_material_weight", "min_material_weight",
    "max_turnover",
}


class PortfolioRoleError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise PortfolioRoleError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    return result


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INT_REQUIRED", name)
    return value


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "policy")
    missing = sorted(REQUIRED_POLICY_FIELDS - set(raw))
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    integers = {
        key: _integer(raw[key], f"policy.{key}")
        for key in (
            "minimum_return_points", "active_ensemble_min", "active_ensemble_max",
            "family_ensemble_min", "family_ensemble_max", "standalone_min",
            "standalone_max", "s_material_min", "s_material_max",
        )
    }
    numbers = {
        key: _number(raw[key], f"policy.{key}")
        for key in REQUIRED_POLICY_FIELDS
        if key not in integers and key not in {"source_ref", "source_sha256", "current_regime"}
    }
    for key in (
        "maximum_pair_correlation", "maximum_signal_overlap", "maximum_family_weight",
        "maximum_symbol_weight", "maximum_side_weight", "min_material_weight",
        "max_material_weight",
    ):
        if not 0 <= numbers[key] <= 1:
            _fail("POLICY_RATIO_INVALID", key)
    for low, high in (
        ("active_ensemble_min", "active_ensemble_max"),
        ("family_ensemble_min", "family_ensemble_max"),
        ("standalone_min", "standalone_max"),
        ("s_material_min", "s_material_max"),
    ):
        if integers[low] > integers[high]:
            _fail("POLICY_COUNT_RANGE_INVALID", f"{low}>{high}")
    return {
        **integers,
        **numbers,
        "source_ref": _string(raw["source_ref"], "policy.source_ref", maximum=300),
        "source_sha256": _sha(raw["source_sha256"], "policy.source_sha256"),
        "current_regime": _string(raw["current_regime"], "policy.current_regime", maximum=80).upper(),
    }


def validate_candidate(value: Mapping[str, Any], minimum_points: int) -> dict[str, Any]:
    raw = _mapping(value, "candidate")
    missing = sorted(REQUIRED_CANDIDATE_FIELDS - set(raw))
    if missing:
        _fail("CANDIDATE_FIELDS_MISSING", ",".join(missing))
    family = _string(raw["family"], "candidate.family").upper()
    if family not in FAMILIES:
        _fail("FAMILY_INVALID", family)
    classification = _string(raw["classification"], "candidate.classification").upper()
    if classification not in CLASSIFICATIONS:
        _fail("CLASSIFICATION_INVALID", classification)
    for key in ("material_sealed", "standalone_eligible", "sbot_veto", "lineage_verified"):
        if not isinstance(raw[key], bool):
            _fail("BOOL_REQUIRED", f"candidate.{key}")
    series = raw["return_series"]
    if not isinstance(series, Mapping) or len(series) < minimum_points:
        _fail("RETURN_SERIES_INSUFFICIENT", str(raw.get("material_id")))
    normalized_series = {
        _string(timestamp, "return_series.timestamp", maximum=64): _number(result, "return_series.value")
        for timestamp, result in series.items()
    }
    signals = raw["signal_event_ids"]
    if not isinstance(signals, list):
        _fail("SIGNAL_EVENT_IDS_INVALID")
    regimes = raw["eligible_regimes"]
    if not isinstance(regimes, list) or not regimes:
        _fail("ELIGIBLE_REGIMES_REQUIRED")
    symbols = raw["symbol_weights"]
    if not isinstance(symbols, Mapping) or not symbols:
        _fail("SYMBOL_WEIGHTS_REQUIRED")
    normalized_symbols = {
        _string(symbol, "symbol", maximum=30).upper(): _number(weight, "symbol_weight")
        for symbol, weight in symbols.items()
    }
    if any(weight < 0 for weight in normalized_symbols.values()) or sum(normalized_symbols.values()) <= 0:
        _fail("SYMBOL_WEIGHTS_INVALID")
    total_symbol = sum(normalized_symbols.values())
    normalized_symbols = {symbol: weight / total_symbol for symbol, weight in normalized_symbols.items()}
    side = _string(raw["side"], "candidate.side").upper()
    if side not in {"LONG", "SHORT", "BIDIRECTIONAL", "DEFENSIVE"}:
        _fail("SIDE_INVALID", side)
    result = {
        "material_id": _string(raw["material_id"], "candidate.material_id", maximum=120),
        "strategy_id": _string(raw["strategy_id"], "candidate.strategy_id", maximum=120),
        "strategy_source_sha256": _sha(raw["strategy_source_sha256"], "candidate.strategy_source_sha256"),
        "family": family,
        "classification": classification,
        "material_sealed": raw["material_sealed"],
        "net_after_cost": _number(raw["net_after_cost"], "candidate.net_after_cost"),
        "confidence": _number(raw["confidence"], "candidate.confidence"),
        "uncertainty": _number(raw["uncertainty"], "candidate.uncertainty"),
        "dd_pct": _number(raw["dd_pct"], "candidate.dd_pct"),
        "joint_tail_dd_pct": _number(raw["joint_tail_dd_pct"], "candidate.joint_tail_dd_pct"),
        "cost_pct": _number(raw["cost_pct"], "candidate.cost_pct"),
        "capacity_score": _number(raw["capacity_score"], "candidate.capacity_score"),
        "incumbent_weight": _number(raw["incumbent_weight"], "candidate.incumbent_weight"),
        "standalone_eligible": raw["standalone_eligible"],
        "eligible_regimes": sorted({_string(item, "eligible_regime", maximum=80).upper() for item in regimes}),
        "return_series": dict(sorted(normalized_series.items())),
        "signal_event_ids": sorted({_string(item, "signal_event_id", maximum=160) for item in signals}),
        "symbol_weights": dict(sorted(normalized_symbols.items())),
        "side": side,
        "sbot_veto": raw["sbot_veto"],
        "lineage_verified": raw["lineage_verified"],
    }
    if not 0 <= result["confidence"] <= 1 or not 0 <= result["uncertainty"] <= 1:
        _fail("CONFIDENCE_RANGE_INVALID", result["material_id"])
    if not 0 <= result["capacity_score"] <= 1:
        _fail("CAPACITY_RANGE_INVALID", result["material_id"])
    if not result["material_sealed"] or not result["lineage_verified"]:
        _fail("UNSEALED_OR_UNVERIFIED_MATERIAL", result["material_id"])
    return result


def pearson(left: Mapping[str, float], right: Mapping[str, float], minimum_points: int) -> float:
    keys = sorted(set(left) & set(right))
    if len(keys) < minimum_points:
        _fail("PAIR_RETURN_OVERLAP_INSUFFICIENT", str(len(keys)))
    a = [left[key] for key in keys]
    b = [right[key] for key in keys]
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    denominator = math.sqrt(sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b))
    return 0.0 if denominator == 0 else max(min(numerator / denominator, 1.0), -1.0)


def signal_overlap(left: list[str], right: list[str]) -> float:
    union = set(left) | set(right)
    return 0.0 if not union else len(set(left) & set(right)) / len(union)


def pair_metrics(candidates: list[dict[str, Any]], minimum_points: int) -> tuple[list[dict[str, Any]], dict[str, float]]:
    rows: list[dict[str, Any]] = []
    correlation_sum: dict[str, float] = defaultdict(float)
    counts: Counter[str] = Counter()
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            correlation = pearson(left["return_series"], right["return_series"], minimum_points)
            overlap = signal_overlap(left["signal_event_ids"], right["signal_event_ids"])
            rows.append({
                "left": left["material_id"],
                "right": right["material_id"],
                "correlation": round(correlation, 10),
                "absolute_correlation": round(abs(correlation), 10),
                "signal_overlap": round(overlap, 10),
            })
            correlation_sum[left["material_id"]] += abs(correlation)
            correlation_sum[right["material_id"]] += abs(correlation)
            counts[left["material_id"]] += 1
            counts[right["material_id"]] += 1
    averages = {
        candidate["material_id"]: correlation_sum[candidate["material_id"]] / max(counts[candidate["material_id"]], 1)
        for candidate in candidates
    }
    return rows, averages


def candidate_score(candidate: Mapping[str, Any], average_abs_correlation: float, policy: Mapping[str, Any]) -> float:
    risk = max(candidate["dd_pct"] + candidate["joint_tail_dd_pct"] + candidate["cost_pct"], 0.01)
    edge = max(candidate["net_after_cost"], 0.0) * max(candidate["confidence"] - candidate["uncertainty"], 0.0) * candidate["capacity_score"] / risk
    diversification = max(1.0 - average_abs_correlation, 0.0)
    regime = 1.0 if policy["current_regime"] in candidate["eligible_regimes"] else 0.0
    return (
        policy["edge_weight"] * edge
        + policy["diversification_weight"] * diversification
        + policy["regime_weight"] * regime
    )


def build_family_ensembles(candidates: list[dict[str, Any]], scores: Mapping[str, float]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate["family"]].append(candidate)
    ensembles: list[dict[str, Any]] = []
    for family, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: (-scores[row["material_id"]], row["material_id"]))
        selected = ordered[:2]
        total_score = sum(max(scores[row["material_id"]], 0.000001) for row in selected)
        member_weights = {
            row["material_id"]: max(scores[row["material_id"]], 0.000001) / total_score for row in selected
        }
        regimes = sorted(set.intersection(*(set(row["eligible_regimes"]) for row in selected))) if selected else []
        if not regimes:
            regimes = sorted(set.union(*(set(row["eligible_regimes"]) for row in selected)))
        ensemble = {
            "material_id": f"family.{family.lower()}",
            "family": family,
            "classification": "SYNTHESIS" if len(selected) > 1 else "CORE",
            "member_ids": [row["material_id"] for row in selected],
            "member_weights": dict(sorted(member_weights.items())),
            "eligible_regimes": regimes,
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
    return ensembles


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
    if any(row["sbot_veto"] for row in candidates):
        vetoed = sorted(row["material_id"] for row in candidates if row["sbot_veto"])
    else:
        vetoed = []
    eligible = [row for row in candidates if not row["sbot_veto"]]
    pairs, average_correlation = pair_metrics(eligible, policy["minimum_return_points"])
    pair_blockers = [
        f"PAIR_CORRELATION:{row['left']}:{row['right']}"
        for row in pairs if row["absolute_correlation"] > policy["maximum_pair_correlation"]
    ] + [
        f"SIGNAL_OVERLAP:{row['left']}:{row['right']}"
        for row in pairs if row["signal_overlap"] > policy["maximum_signal_overlap"]
    ]
    scores = {
        row["material_id"]: candidate_score(row, average_correlation[row["material_id"]], policy)
        for row in eligible
    }
    marginal_rejected = sorted(
        material_id for material_id, score in scores.items() if score < policy["minimum_marginal_score"]
    )
    role_candidates = [row for row in eligible if row["material_id"] not in marginal_rejected]
    ensembles = build_family_ensembles(role_candidates, scores)
    if not policy["family_ensemble_min"] <= len(ensembles) <= policy["family_ensemble_max"]:
        _fail("FAMILY_ENSEMBLE_COUNT_OUT_OF_RANGE", str(len(ensembles)))
    regime_eligible = [row for row in ensembles if policy["current_regime"] in row["eligible_regimes"] and not row["sbot_veto"]]
    ordered = sorted(
        regime_eligible,
        key=lambda row: (-sum(scores[member] for member in row["member_ids"]), row["material_id"]),
    )
    active_count = min(policy["active_ensemble_max"], len(ordered))
    if active_count < policy["active_ensemble_min"]:
        _fail("ACTIVE_ENSEMBLE_COUNT_INSUFFICIENT", str(active_count))
    active = ordered[:active_count]
    governor_payload = {
        "candidate_set_sha": canonical_sha(candidates),
        "correlation_artifact_sha": canonical_sha(pairs),
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
    weights = governed.get("target_risk_weights", {})
    family_weights = {row["family"]: weights.get(row["material_id"], 0.0) for row in active}
    side_weights: dict[str, float] = defaultdict(float)
    symbol_weights: dict[str, float] = defaultdict(float)
    member_lookup = {row["material_id"]: row for row in candidates}
    for ensemble in active:
        ensemble_weight = weights.get(ensemble["material_id"], 0.0)
        for member_id, member_weight in ensemble["member_weights"].items():
            member = member_lookup[member_id]
            effective = ensemble_weight * member_weight
            side_weights[member["side"]] += effective
            for symbol, symbol_weight in member["symbol_weights"].items():
                symbol_weights[symbol] += effective * symbol_weight
    blockers = list(pair_blockers) + list(governed.get("blockers", []))
    if any(weight > policy["maximum_family_weight"] for weight in family_weights.values()):
        blockers.append("FAMILY_WEIGHT_LIMIT")
    if any(weight > policy["maximum_symbol_weight"] for weight in symbol_weights.values()):
        blockers.append("SYMBOL_WEIGHT_LIMIT")
    if any(weight > policy["maximum_side_weight"] for weight in side_weights.values()):
        blockers.append("SIDE_WEIGHT_LIMIT")
    if any(row["joint_tail_dd_pct"] > policy["maximum_joint_dd_pct"] for row in active):
        blockers.append("JOINT_DD_LIMIT")
    status = "PASS_P3_SHADOW_PORTFOLIO_TARGETS" if not blockers else "HOLD_P3_PORTFOLIO_GAPS"
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "s_material_count": len(candidates),
        "standalone_strategy_count": len(standalone),
        "family_ensemble_count": len(ensembles),
        "active_ensemble_count": len(active),
        "vetoed_material_ids": vetoed,
        "marginal_rejected_material_ids": marginal_rejected,
        "pair_metrics": pairs,
        "candidate_scores": dict(sorted((key, round(value, 10)) for key, value in scores.items())),
        "family_ensembles": ensembles,
        "active_ensemble_ids": [row["material_id"] for row in active],
        "target_risk_weights": weights,
        "family_weights": dict(sorted(family_weights.items())),
        "side_weights": dict(sorted(side_weights.items())),
        "symbol_weights": dict(sorted(symbol_weights.items())),
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
