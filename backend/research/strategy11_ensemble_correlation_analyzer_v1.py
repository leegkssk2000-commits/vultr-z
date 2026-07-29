from __future__ import annotations

import hashlib
import itertools
import json
import math
import statistics
from typing import Any, Iterable, Mapping, Sequence

ALLOWED_CLASSIFICATIONS = {"CORE", "SYNTHESIS"}


class CorrelationAnalyzerError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise CorrelationAnalyzerError(f"{code}:{detail}" if detail else code)


def canonical_sha(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _number(value: Any, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    if minimum is not None and result < minimum:
        _fail("NUMBER_BELOW_MIN", name)
    if maximum is not None and result > maximum:
        _fail("NUMBER_ABOVE_MAX", name)
    return result


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    return value.strip()


def _sha(value: Any, name: str) -> str:
    result = _string(value, name).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    mean_a = statistics.fmean(a)
    mean_b = statistics.fmean(b)
    da = [x - mean_a for x in a]
    db = [x - mean_b for x in b]
    denominator = math.sqrt(sum(x * x for x in da) * sum(x * x for x in db))
    if denominator == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(da, db)) / denominator


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _max_drawdown(values: Sequence[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return abs(worst)


def _drawdown_flags(values: Sequence[float]) -> list[bool]:
    cumulative = 0.0
    peak = 0.0
    flags: list[bool] = []
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        flags.append(cumulative < peak)
    return flags


def _rolling_corr(a: Sequence[float], b: Sequence[float], window: int) -> list[float]:
    if len(a) < window:
        return []
    return [_pearson(a[index - window:index], b[index - window:index]) for index in range(window, len(a) + 1)]


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(value)
    result = {
        "policy_id": _string(policy.get("policy_id"), "policy.policy_id"),
        "max_cosine_similarity": _number(policy.get("max_cosine_similarity"), "policy.max_cosine_similarity", 0.0, 1.0),
        "max_abs_pnl_correlation": _number(policy.get("max_abs_pnl_correlation"), "policy.max_abs_pnl_correlation", 0.0, 1.0),
        "max_loss_concurrence": _number(policy.get("max_loss_concurrence"), "policy.max_loss_concurrence", 0.0, 1.0),
        "max_drawdown_concurrence": _number(policy.get("max_drawdown_concurrence"), "policy.max_drawdown_concurrence", 0.0, 1.0),
        "rolling_window": _integer(policy.get("rolling_window"), "policy.rolling_window", 3),
        "min_combination_size": _integer(policy.get("min_combination_size"), "policy.min_combination_size", 2),
        "max_combination_size": _integer(policy.get("max_combination_size"), "policy.max_combination_size", 2),
        "max_candidate_combinations": _integer(policy.get("max_candidate_combinations"), "policy.max_candidate_combinations", 1),
    }
    if result["min_combination_size"] > result["max_combination_size"]:
        _fail("COMBINATION_SIZE_ORDER_INVALID")
    if result["max_combination_size"] > 5:
        _fail("COMBINATION_SIZE_ABOVE_FIVE")
    return result


def validate_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(value)
    classification = _string(candidate.get("classification"), "candidate.classification").upper()
    if classification not in ALLOWED_CLASSIFICATIONS:
        _fail("CLASSIFICATION_NOT_ENSEMBLE_ELIGIBLE", classification)
    trades = candidate.get("trades")
    if not isinstance(trades, list) or not trades:
        _fail("TRADES_REQUIRED")
    normalized_trades: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, trade in enumerate(trades):
        if not isinstance(trade, Mapping):
            _fail("TRADE_OBJECT_REQUIRED", str(index))
        timestamp = _string(trade.get("timestamp"), f"trades[{index}].timestamp")
        if timestamp in seen:
            _fail("DUPLICATE_TIMESTAMP", timestamp)
        seen.add(timestamp)
        normalized_trades.append({
            "timestamp": timestamp,
            "net_r": _number(trade.get("net_r"), f"trades[{index}].net_r"),
            "symbol": _string(trade.get("symbol"), f"trades[{index}].symbol").upper(),
            "regime": _string(trade.get("regime"), f"trades[{index}].regime").upper(),
        })
    normalized_trades.sort(key=lambda row: row["timestamp"])
    return {
        "strategy_id": _string(candidate.get("strategy_id"), "candidate.strategy_id"),
        "candidate_sha": _sha(candidate.get("candidate_sha"), "candidate.candidate_sha"),
        "proposal_sha": _sha(candidate.get("proposal_sha"), "candidate.proposal_sha"),
        "classification_sha": _sha(candidate.get("classification_sha"), "candidate.classification_sha"),
        "classification": classification,
        "trades": normalized_trades,
    }


def _aligned(candidates: Sequence[dict[str, Any]]) -> tuple[list[str], dict[str, list[float]]]:
    timestamps = sorted({trade["timestamp"] for candidate in candidates for trade in candidate["trades"]})
    values: dict[str, list[float]] = {}
    for candidate in candidates:
        lookup = {trade["timestamp"]: trade["net_r"] for trade in candidate["trades"]}
        values[candidate["strategy_id"]] = [lookup.get(timestamp, 0.0) for timestamp in timestamps]
    return timestamps, values


def _pair_metrics(a: dict[str, Any], b: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    timestamps, values = _aligned([a, b])
    av = values[a["strategy_id"]]
    bv = values[b["strategy_id"]]
    active_a = {index for index, value in enumerate(av) if value != 0.0}
    active_b = {index for index, value in enumerate(bv) if value != 0.0}
    overlap = len(active_a & active_b) / len(active_a | active_b) if active_a | active_b else 0.0
    cosine_denominator = math.sqrt(len(active_a) * len(active_b))
    cosine = len(active_a & active_b) / cosine_denominator if cosine_denominator else 0.0
    losses_a = {index for index, value in enumerate(av) if value < 0.0}
    losses_b = {index for index, value in enumerate(bv) if value < 0.0}
    min_losses = min(len(losses_a), len(losses_b))
    loss_concurrence = len(losses_a & losses_b) / min_losses if min_losses else 0.0
    dda = _drawdown_flags(av)
    ddb = _drawdown_flags(bv)
    dd_a_count = sum(dda)
    dd_b_count = sum(ddb)
    min_dd = min(dd_a_count, dd_b_count)
    dd_concurrence = sum(x and y for x, y in zip(dda, ddb)) / min_dd if min_dd else 0.0
    rolling = _rolling_corr(av, bv, policy["rolling_window"])
    pnl_corr = _pearson(av, bv)
    joint = [(x + y) / 2.0 for x, y in zip(av, bv)]
    symbols_a = {trade["symbol"] for trade in a["trades"]}
    symbols_b = {trade["symbol"] for trade in b["trades"]}
    regimes_a = {trade["regime"] for trade in a["trades"]}
    regimes_b = {trade["regime"] for trade in b["trades"]}

    blockers: list[str] = []
    if cosine > policy["max_cosine_similarity"]:
        blockers.append("COSINE_SIMILARITY_HIGH")
    if abs(pnl_corr) > policy["max_abs_pnl_correlation"] and loss_concurrence > policy["max_loss_concurrence"]:
        blockers.append("PNL_AND_LOSS_CONCURRENCE_HIGH")
    if dd_concurrence > policy["max_drawdown_concurrence"]:
        blockers.append("DRAWDOWN_CONCURRENCE_HIGH")

    return {
        "pair": sorted([a["strategy_id"], b["strategy_id"]]),
        "timestamp_count": len(timestamps),
        "signal_overlap_jaccard": overlap,
        "signal_cosine_similarity": cosine,
        "pnl_correlation": pnl_corr,
        "rolling_correlation_mean": statistics.fmean(rolling) if rolling else 0.0,
        "rolling_correlation_max_abs": max((abs(value) for value in rolling), default=0.0),
        "loss_concurrence": loss_concurrence,
        "drawdown_concurrence": dd_concurrence,
        "symbol_exposure_jaccard": _jaccard(symbols_a, symbols_b),
        "regime_exposure_jaccard": _jaccard(regimes_a, regimes_b),
        "equal_weight_joint_net_r": sum(joint),
        "equal_weight_worst_joint_drawdown_r": _max_drawdown(joint),
        "equal_weight_marginal_net_r": {
            a["strategy_id"]: 0.5 * sum(av),
            b["strategy_id"]: 0.5 * sum(bv),
        },
        "compatible": not blockers,
        "blocker_codes": blockers,
    }


def _combination_metrics(combo: Sequence[dict[str, Any]], pair_lookup: Mapping[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    names = sorted(candidate["strategy_id"] for candidate in combo)
    pairs = [pair_lookup[tuple(sorted(pair))] for pair in itertools.combinations(names, 2)]
    timestamps, values = _aligned(list(combo))
    weight = 1.0 / len(combo)
    joint = [sum(values[name][index] * weight for name in names) for index in range(len(timestamps))]
    symbols = {trade["symbol"] for candidate in combo for trade in candidate["trades"]}
    regimes = {trade["regime"] for candidate in combo for trade in candidate["trades"]}
    return {
        "members": names,
        "member_count": len(names),
        "pairwise_compatible": all(pair["compatible"] for pair in pairs),
        "equal_weight_only": True,
        "equal_weight_net_r": sum(joint),
        "equal_weight_worst_joint_drawdown_r": _max_drawdown(joint),
        "symbol_coverage": sorted(symbols),
        "regime_coverage": sorted(regimes),
        "max_pair_cosine": max((pair["signal_cosine_similarity"] for pair in pairs), default=0.0),
        "max_pair_loss_concurrence": max((pair["loss_concurrence"] for pair in pairs), default=0.0),
        "max_pair_drawdown_concurrence": max((pair["drawdown_concurrence"] for pair in pairs), default=0.0),
        "combination_sha": canonical_sha({"members": names, "diagnostic_equal_weight": True}),
    }


def analyze_candidates(candidate_values: Iterable[Mapping[str, Any]], policy_value: Mapping[str, Any]) -> dict[str, Any]:
    policy = validate_policy(policy_value)
    candidates = [validate_candidate(candidate) for candidate in candidate_values]
    if len(candidates) < 2:
        _fail("AT_LEAST_TWO_CANDIDATES_REQUIRED")
    strategy_ids = [candidate["strategy_id"] for candidate in candidates]
    if len(set(strategy_ids)) != len(strategy_ids):
        _fail("DUPLICATE_STRATEGY_ID")

    pair_rows = [_pair_metrics(a, b, policy) for a, b in itertools.combinations(candidates, 2)]
    pair_lookup = {tuple(row["pair"]): row for row in pair_rows}
    combinations: list[dict[str, Any]] = []
    max_size = min(policy["max_combination_size"], len(candidates))
    for size in range(policy["min_combination_size"], max_size + 1):
        for combo in itertools.combinations(candidates, size):
            row = _combination_metrics(combo, pair_lookup)
            if row["pairwise_compatible"]:
                combinations.append(row)

    combinations.sort(key=lambda row: (
        row["equal_weight_worst_joint_drawdown_r"],
        -row["equal_weight_net_r"],
        -len(row["regime_coverage"]),
        -len(row["symbol_coverage"]),
        row["members"],
    ))
    selected = combinations[:policy["max_candidate_combinations"]]
    blocked_pairs = [row for row in pair_rows if not row["compatible"]]
    result = {
        "schema_version": "strategy11.ensemble_correlation_analysis.v1",
        "candidate_count": len(candidates),
        "candidate_lineage": [
            {
                "strategy_id": candidate["strategy_id"],
                "candidate_sha": candidate["candidate_sha"],
                "proposal_sha": candidate["proposal_sha"],
                "classification_sha": candidate["classification_sha"],
                "classification": candidate["classification"],
            }
            for candidate in candidates
        ],
        "policy": policy,
        "policy_sha": canonical_sha(policy),
        "pair_matrix": pair_rows,
        "blocked_pair_count": len(blocked_pairs),
        "compatible_combination_count": len(combinations),
        "shadow_only_candidate_combinations": selected,
        "diagnostic_equal_weight_only": True,
        "target_weights_created": False,
        "selection_order": ["MIN_WORST_JOINT_DD", "MAX_NET_AFTER_PAIR_FILTER", "MAX_REGIME_COVERAGE", "MAX_SYMBOL_COVERAGE"],
        "single_score_used": False,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    result["analysis_sha"] = canonical_sha(result)
    return result
