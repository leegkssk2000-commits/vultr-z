from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

VERSION = "STRATEGY11_MARKET_DIGITAL_TWIN_CONTRACT_V1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "market_data_mutation_allowed": False,
    "order_submission_allowed": False,
    "capital_allocation_allowed": False,
}


class DigitalTwinContractError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    scenario_type: str
    seed: int
    gross_return_pct: float
    net_return_pct: float
    max_drawdown_pct: float
    fill_ratio: float
    total_cost_bps: float
    pairwise_correlation: Mapping[str, float | None]
    joint_loss_steps: int
    risk_flags: tuple[str, ...]
    scenario_sha: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type,
            "seed": self.seed,
            "gross_return_pct": self.gross_return_pct,
            "net_return_pct": self.net_return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "fill_ratio": self.fill_ratio,
            "total_cost_bps": self.total_cost_bps,
            "pairwise_correlation": dict(self.pairwise_correlation),
            "joint_loss_steps": self.joint_loss_steps,
            "risk_flags": list(self.risk_flags),
            "scenario_sha": self.scenario_sha,
        }


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DigitalTwinContractError(f"INVALID_NUMBER:{name}") from exc
    if not math.isfinite(number):
        raise DigitalTwinContractError(f"NONFINITE_NUMBER:{name}")
    return number


def require_sha(value: Any, name: str) -> str:
    text = str(value or "").lower()
    if not SHA_RE.fullmatch(text):
        raise DigitalTwinContractError(f"INVALID_SHA:{name}")
    return text


def require_nonempty(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DigitalTwinContractError(f"EMPTY_FIELD:{name}")
    return text


def verify_policy(policy_input: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(policy_input)
    expectations = {
        "fixture_only": True,
        "threshold_authority": False,
        "runtime_activation_allowed": False,
        "market_data_mutation_allowed": False,
        "order_submission_allowed": False,
        "capital_allocation_allowed": False,
    }
    for key, expected in expectations.items():
        if policy.get(key) is not expected:
            raise DigitalTwinContractError(f"POLICY_FAIL_CLOSED_MISMATCH:{key}")
    material = {key: value for key, value in policy.items() if key != "policy_sha"}
    actual = stable_sha(material)
    if policy.get("policy_sha") != actual:
        raise DigitalTwinContractError(f"POLICY_SHA_MISMATCH:{actual}:{policy.get('policy_sha')}")
    required = [str(value) for value in policy.get("required_scenario_types") or []]
    if not required or len(required) != len(set(required)):
        raise DigitalTwinContractError("INVALID_REQUIRED_SCENARIO_TYPES")
    return policy


def verify_binding(binding_input: Mapping[str, Any], policy_sha: str) -> dict[str, str]:
    binding = {
        "source_sha": require_sha(binding_input.get("source_sha"), "source_sha"),
        "data_sha": require_sha(binding_input.get("data_sha"), "data_sha"),
        "portfolio_sha": require_sha(binding_input.get("portfolio_sha"), "portfolio_sha"),
        "policy_sha": require_sha(binding_input.get("policy_sha"), "policy_sha"),
        "run_id": require_nonempty(binding_input.get("run_id"), "run_id"),
        "artifact_id": require_nonempty(binding_input.get("artifact_id"), "artifact_id"),
    }
    if binding["policy_sha"] != policy_sha:
        raise DigitalTwinContractError("REQUEST_POLICY_SHA_MISMATCH")
    return binding


def max_drawdown_pct(step_returns_pct: Sequence[float]) -> float:
    equity = 100.0
    peak = equity
    max_dd = 0.0
    for value in step_returns_pct:
        equity *= 1.0 + value / 100.0
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / max(peak, 1e-12) * 100.0)
    return max_dd


def pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_l = sum(left) / len(left)
    mean_r = sum(right) / len(right)
    numerator = sum((a - mean_l) * (b - mean_r) for a, b in zip(left, right))
    denom_l = math.sqrt(sum((a - mean_l) ** 2 for a in left))
    denom_r = math.sqrt(sum((b - mean_r) ** 2 for b in right))
    if denom_l <= 1e-12 or denom_r <= 1e-12:
        return None
    return numerator / (denom_l * denom_r)


def verify_portfolio(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    if len(rows) < 2:
        raise DigitalTwinContractError("PORTFOLIO_REQUIRES_AT_LEAST_TWO_MATERIALS")
    normalized = []
    weights: dict[str, float] = {}
    for index, row in enumerate(rows):
        strategy_id = require_nonempty(row.get("strategy_id"), f"portfolio[{index}].strategy_id")
        candidate_sha = require_sha(row.get("candidate_sha"), f"portfolio[{index}].candidate_sha")
        material_sha = require_sha(row.get("material_sha"), f"portfolio[{index}].material_sha")
        weight = finite(row.get("weight"), f"portfolio[{index}].weight")
        if weight <= 0 or strategy_id in weights:
            raise DigitalTwinContractError(f"INVALID_PORTFOLIO_WEIGHT_OR_DUPLICATE:{strategy_id}")
        weights[strategy_id] = weight
        normalized.append({
            "strategy_id": strategy_id,
            "candidate_sha": candidate_sha,
            "material_sha": material_sha,
            "weight": weight,
        })
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9:
        raise DigitalTwinContractError(f"PORTFOLIO_WEIGHT_SUM:{total}")
    return normalized, weights


def scenario_material(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "scenario_sha"}


def evaluate_scenario(
    row: Mapping[str, Any],
    weights: Mapping[str, float],
    policy: Mapping[str, Any],
) -> ScenarioResult:
    scenario_id = require_nonempty(row.get("scenario_id"), "scenario_id")
    scenario_type = require_nonempty(row.get("scenario_type"), "scenario_type")
    seed = int(finite(row.get("seed"), f"{scenario_id}.seed"))
    expected_sha = require_sha(row.get("scenario_sha"), f"{scenario_id}.scenario_sha")
    actual_sha = stable_sha(scenario_material(row))
    if expected_sha != actual_sha:
        raise DigitalTwinContractError(f"SCENARIO_SHA_MISMATCH:{scenario_id}:{actual_sha}:{expected_sha}")

    returns_input = row.get("returns_by_strategy") or {}
    if set(returns_input) != set(weights):
        raise DigitalTwinContractError(f"SCENARIO_STRATEGY_SET_MISMATCH:{scenario_id}")
    normalized_returns: dict[str, list[float]] = {}
    lengths: set[int] = set()
    for strategy_id in sorted(weights):
        values = [finite(value, f"{scenario_id}.{strategy_id}.return") for value in returns_input[strategy_id]]
        if not values:
            raise DigitalTwinContractError(f"EMPTY_SCENARIO_PATH:{scenario_id}:{strategy_id}")
        normalized_returns[strategy_id] = values
        lengths.add(len(values))
    if len(lengths) != 1:
        raise DigitalTwinContractError(f"SCENARIO_PATH_LENGTH_MISMATCH:{scenario_id}")
    step_count = next(iter(lengths))

    fill_ratio = finite(row.get("fill_ratio"), f"{scenario_id}.fill_ratio")
    if not 0.0 <= fill_ratio <= 1.0:
        raise DigitalTwinContractError(f"INVALID_FILL_RATIO:{scenario_id}")
    spread_bps = finite(row.get("spread_bps"), f"{scenario_id}.spread_bps")
    slippage_bps = finite(row.get("slippage_bps"), f"{scenario_id}.slippage_bps")
    fee_bps = finite(row.get("fee_bps"), f"{scenario_id}.fee_bps")
    funding_bps = finite(row.get("funding_bps"), f"{scenario_id}.funding_bps")
    latency_ms = finite(row.get("latency_ms"), f"{scenario_id}.latency_ms")
    api_gap_bars = int(finite(row.get("api_gap_bars"), f"{scenario_id}.api_gap_bars"))
    stale_feed_ms = int(finite(row.get("stale_feed_ms"), f"{scenario_id}.stale_feed_ms"))
    liquidity_depth_ratio = finite(row.get("liquidity_depth_ratio"), f"{scenario_id}.liquidity_depth_ratio")
    liquidation_buffer_pct = finite(row.get("liquidation_buffer_pct"), f"{scenario_id}.liquidation_buffer_pct")
    total_cost_bps = spread_bps / 2.0 + slippage_bps + fee_bps + abs(funding_bps)

    portfolio_steps = []
    joint_loss_steps = 0
    for index in range(step_count):
        strategy_values = [normalized_returns[strategy_id][index] for strategy_id in sorted(weights)]
        if all(value < 0 for value in strategy_values):
            joint_loss_steps += 1
        gross = sum(weights[strategy_id] * normalized_returns[strategy_id][index] for strategy_id in weights)
        portfolio_steps.append(gross * fill_ratio)
    gross_return = sum(portfolio_steps)
    net_steps = list(portfolio_steps)
    net_steps[0] -= total_cost_bps / 100.0 * fill_ratio
    net_return = sum(net_steps)
    dd = max_drawdown_pct(net_steps)

    pairwise: dict[str, float | None] = {}
    strategy_ids = sorted(weights)
    for i, left in enumerate(strategy_ids):
        for right in strategy_ids[i + 1:]:
            pairwise[f"{left}|{right}"] = pearson(normalized_returns[left], normalized_returns[right])

    flags: list[str] = []
    if fill_ratio < finite(policy["min_fill_ratio"], "policy.min_fill_ratio"):
        flags.append("LOW_FILL_RATIO")
    if api_gap_bars > int(policy["max_api_gap_bars"]):
        flags.append("API_GAP_BREACH")
    if stale_feed_ms > int(policy["max_stale_feed_ms"]):
        flags.append("STALE_FEED_BREACH")
    if liquidity_depth_ratio < finite(policy["min_liquidity_depth_ratio"], "policy.min_liquidity_depth_ratio"):
        flags.append("LIQUIDITY_DEPTH_COLLAPSE")
    if latency_ms > finite(policy["max_latency_ms"], "policy.max_latency_ms"):
        flags.append("LATENCY_BREACH")
    if total_cost_bps > finite(policy["max_total_cost_bps"], "policy.max_total_cost_bps"):
        flags.append("COST_BREACH")
    if liquidation_buffer_pct < finite(policy["min_liquidation_buffer_pct"], "policy.min_liquidation_buffer_pct"):
        flags.append("LIQUIDATION_BUFFER_BREACH")
    if dd > finite(policy["max_scenario_drawdown_pct"], "policy.max_scenario_drawdown_pct"):
        flags.append("SCENARIO_DRAWDOWN_BREACH")

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type=scenario_type,
        seed=seed,
        gross_return_pct=gross_return,
        net_return_pct=net_return,
        max_drawdown_pct=dd,
        fill_ratio=fill_ratio,
        total_cost_bps=total_cost_bps,
        pairwise_correlation=pairwise,
        joint_loss_steps=joint_loss_steps,
        risk_flags=tuple(sorted(set(flags))),
        scenario_sha=actual_sha,
    )


def evaluate_digital_twin(package: Mapping[str, Any], policy_input: Mapping[str, Any]) -> dict[str, Any]:
    policy = verify_policy(policy_input)
    binding = verify_binding(package.get("source_binding") or {}, str(policy["policy_sha"]))
    portfolio, weights = verify_portfolio(package.get("portfolio") or [])
    computed_portfolio_sha = stable_sha(portfolio)
    if computed_portfolio_sha != binding["portfolio_sha"]:
        raise DigitalTwinContractError("PORTFOLIO_SHA_MISMATCH")

    scenario_rows = package.get("scenarios") or []
    if not isinstance(scenario_rows, Sequence) or isinstance(scenario_rows, (str, bytes)) or not scenario_rows:
        raise DigitalTwinContractError("EMPTY_SCENARIO_SET")
    types = [str(row.get("scenario_type") or "") for row in scenario_rows]
    if len(types) != len(set((str(row.get("scenario_id") or "") for row in scenario_rows))):
        raise DigitalTwinContractError("DUPLICATE_SCENARIO_ID")
    required_types = set(str(value) for value in policy["required_scenario_types"])
    missing_types = sorted(required_types - set(types))
    if missing_types:
        raise DigitalTwinContractError("MISSING_SCENARIO_TYPES:" + ",".join(missing_types))

    results = [evaluate_scenario(row, weights, policy) for row in scenario_rows]
    results.sort(key=lambda value: (value.scenario_type, value.scenario_id))
    rows = [result.as_dict() for result in results]
    risk_scenarios = [row["scenario_id"] for row in rows if row["risk_flags"]]
    worst_dd = max(row["max_drawdown_pct"] for row in rows)
    worst_net = min(row["net_return_pct"] for row in rows)
    liquidity_failure_coverage = {
        "liquidity_shock": any(row["scenario_type"] == "LIQUIDITY_SHOCK" for row in rows),
        "api_gap": any(row["scenario_type"] == "API_GAP" for row in rows),
        "stale_feed": any(
            row["scenario_type"] == "API_GAP" and "STALE_FEED_BREACH" in row["risk_flags"]
            for row in rows
        ),
    }
    if not all(liquidity_failure_coverage.values()):
        raise DigitalTwinContractError("LIQUIDITY_FAILURE_COVERAGE_INCOMPLETE")

    capital_gate = "HOLD_DIGITAL_TWIN_RISK_EXPOSED" if risk_scenarios else "PASS_DIGITAL_TWIN_RISK_ENVELOPE"
    result = {
        "schema_version": "strategy11.market_digital_twin.v1",
        "version": VERSION,
        "state": "PASS_MARKET_DIGITAL_TWIN_SCENARIO_COVERAGE",
        "capital_gate": capital_gate,
        "portfolio": portfolio,
        "scenario_count": len(rows),
        "scenario_types": sorted(set(types)),
        "scenario_results": rows,
        "risk_scenarios": sorted(risk_scenarios),
        "worst_scenario_drawdown_pct": worst_dd,
        "worst_scenario_net_return_pct": worst_net,
        "liquidity_failure_coverage": liquidity_failure_coverage,
        "deterministic_seed_manifest": {
            row["scenario_id"]: row["seed"] for row in rows
        },
        "lineage": {
            **binding,
            "scenario_set_sha": stable_sha([row["scenario_sha"] for row in rows]),
            "package_sha": stable_sha(package),
        },
        **SAFETY,
    }
    result["twin_result_sha"] = stable_sha(result)
    return result
