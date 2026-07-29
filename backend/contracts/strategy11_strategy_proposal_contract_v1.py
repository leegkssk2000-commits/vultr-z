from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any, Mapping

SCHEMA_VERSION = "strategy11.strategy_proposal.v1"
TEAM_LANES = {"ALPHA", "BETA", "GAMMA", "DELTA"}
PRODUCER_ROLES = {"LBOT", "MBOT", "OBOT", "SBOT", "RESEARCH"}
SIDES = {"LONG", "SHORT", "BOTH", "NONE"}
STAGES = {"RESEARCH", "SHADOW", "PAPER", "LIVE_READINESS"}
REGIMES = {"UPTREND", "DOWNTREND", "RANGE", "HIGH_VOL", "LOW_VOL", "MIXED", "UNKNOWN"}
PROPOSAL_STATES = {"REQUEST_EVALUATION", "HOLD", "REJECT"}
PRIVATE_KEY_TOKENS = {
    "api_key", "apikey", "secret", "credential", "password", "private_key",
    "account_id", "order_id", "position_id", "exchange_key", "wallet",
}
TOP_LEVEL_KEYS = {
    "schema_version", "proposal_id", "proposal_sha", "strategy_id", "candidate_sha",
    "producer", "market", "edge", "confidence", "cost_envelope", "risk_envelope",
    "lineage", "proposal_state", "reason_codes", "authority", "metadata",
}
REQUIRED_SHA_KEYS = {"strategy_source_sha", "candidate_config_sha", "data_sha", "window_sha", "source_manifest_sha"}


class ProposalContractError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ProposalContractError(f"{code}:{detail}" if detail else code)


def _require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _require_string(value: Any, name: str, *, min_len: int = 1, max_len: int = 256) -> str:
    if not isinstance(value, str):
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if not min_len <= len(result) <= max_len:
        _fail("STRING_LENGTH", name)
    return result


def _require_enum(value: Any, name: str, allowed: set[str]) -> str:
    result = _require_string(value, name).upper()
    if result not in allowed:
        _fail("ENUM_INVALID", f"{name}={result}")
    return result


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _require_number(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
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


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    return value


def _require_sha(value: Any, name: str) -> str:
    result = _require_string(value, name, min_len=64, max_len=64).lower()
    if any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _reject_private_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in PRIVATE_KEY_TOKENS):
                _fail("PRIVATE_FIELD_FORBIDDEN", f"{path}.{key}")
            _reject_private_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private_fields(child, f"{path}[{index}]")


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def proposal_sha(value: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(value))
    payload.pop("proposal_sha", None)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def validate_proposal(value: Mapping[str, Any], *, require_sealed_sha: bool = True) -> dict[str, Any]:
    proposal = _require_dict(value, "proposal")
    _reject_private_fields(proposal)

    extra = sorted(set(proposal) - TOP_LEVEL_KEYS)
    missing = sorted((TOP_LEVEL_KEYS - {"proposal_sha", "metadata"}) - set(proposal))
    if extra:
        _fail("TOP_LEVEL_EXTRA_FIELDS", ",".join(extra))
    if missing:
        _fail("TOP_LEVEL_MISSING_FIELDS", ",".join(missing))

    normalized: dict[str, Any] = {
        "schema_version": _require_enum(proposal.get("schema_version"), "schema_version", {SCHEMA_VERSION.upper()}).lower(),
        "proposal_id": _require_string(proposal.get("proposal_id"), "proposal_id", max_len=160),
        "strategy_id": _require_string(proposal.get("strategy_id"), "strategy_id", max_len=120),
        "candidate_sha": _require_sha(proposal.get("candidate_sha"), "candidate_sha"),
    }

    producer = _require_dict(proposal.get("producer"), "producer")
    normalized["producer"] = {
        "team_lane": _require_enum(producer.get("team_lane"), "producer.team_lane", TEAM_LANES),
        "role": _require_enum(producer.get("role"), "producer.role", PRODUCER_ROLES),
        "independent_proposal": _require_bool(producer.get("independent_proposal"), "producer.independent_proposal"),
    }
    if normalized["producer"]["independent_proposal"] is not True:
        _fail("TEAM_INDEPENDENCE_REQUIRED")

    market = _require_dict(proposal.get("market"), "market")
    symbols = market.get("symbols")
    if not isinstance(symbols, list) or not symbols or len(symbols) > 20:
        _fail("SYMBOL_LIST_INVALID")
    normalized["market"] = {
        "symbols": sorted({_require_string(item, "market.symbols[]", max_len=30).upper() for item in symbols}),
        "timeframe": _require_string(market.get("timeframe"), "market.timeframe", max_len=20),
        "side": _require_enum(market.get("side"), "market.side", SIDES),
        "regime": _require_enum(market.get("regime"), "market.regime", REGIMES),
        "session": _require_string(market.get("session"), "market.session", max_len=40),
    }

    edge = _require_dict(proposal.get("edge"), "edge")
    normalized["edge"] = {
        "trades": _require_int(edge.get("trades"), "edge.trades", minimum=0),
        "win_rate_pct": _require_number(edge.get("win_rate_pct"), "edge.win_rate_pct", minimum=0.0, maximum=100.0),
        "net_pct": _require_number(edge.get("net_pct"), "edge.net_pct"),
        "profit_factor": _require_number(edge.get("profit_factor"), "edge.profit_factor", minimum=0.0),
        "payoff": _require_number(edge.get("payoff"), "edge.payoff", minimum=0.0),
        "positive_windows": _require_int(edge.get("positive_windows"), "edge.positive_windows", minimum=0),
        "total_windows": _require_int(edge.get("total_windows"), "edge.total_windows", minimum=1),
        "retention_pct": _require_number(edge.get("retention_pct"), "edge.retention_pct", minimum=0.0, maximum=100.0),
    }
    if normalized["edge"]["positive_windows"] > normalized["edge"]["total_windows"]:
        _fail("POSITIVE_WINDOWS_EXCEED_TOTAL")

    confidence = _require_dict(proposal.get("confidence"), "confidence")
    normalized["confidence"] = {
        "score": _require_number(confidence.get("score"), "confidence.score", minimum=0.0, maximum=1.0),
        "uncertainty": _require_number(confidence.get("uncertainty"), "confidence.uncertainty", minimum=0.0, maximum=1.0),
        "sample_quality": _require_enum(confidence.get("sample_quality"), "confidence.sample_quality", {"LOW", "MEDIUM", "HIGH"}),
        "oos_windows": _require_int(confidence.get("oos_windows"), "confidence.oos_windows", minimum=0),
    }

    cost = _require_dict(proposal.get("cost_envelope"), "cost_envelope")
    normalized["cost_envelope"] = {
        "fee_bps": _require_number(cost.get("fee_bps"), "cost_envelope.fee_bps", minimum=0.0),
        "slippage_bps": _require_number(cost.get("slippage_bps"), "cost_envelope.slippage_bps", minimum=0.0),
        "funding_8h_pct": _require_number(cost.get("funding_8h_pct"), "cost_envelope.funding_8h_pct"),
        "latency_ms": _require_number(cost.get("latency_ms"), "cost_envelope.latency_ms", minimum=0.0),
        "stress_multiplier": _require_number(cost.get("stress_multiplier"), "cost_envelope.stress_multiplier", minimum=1.0),
        "capacity_notional_usdt": _require_number(cost.get("capacity_notional_usdt"), "cost_envelope.capacity_notional_usdt", minimum=0.0),
    }

    risk = _require_dict(proposal.get("risk_envelope"), "risk_envelope")
    normalized["risk_envelope"] = {
        "max_drawdown_pct": _require_number(risk.get("max_drawdown_pct"), "risk_envelope.max_drawdown_pct", minimum=0.0),
        "avg_loss_r": _require_number(risk.get("avg_loss_r"), "risk_envelope.avg_loss_r", maximum=0.0),
        "worst_loss_r": _require_number(risk.get("worst_loss_r"), "risk_envelope.worst_loss_r", maximum=0.0),
        "stress_worst_loss_r": _require_number(risk.get("stress_worst_loss_r"), "risk_envelope.stress_worst_loss_r", maximum=0.0),
        "joint_tail_budget_pct": _require_number(risk.get("joint_tail_budget_pct"), "risk_envelope.joint_tail_budget_pct", minimum=0.0),
        "max_exposure_pct": _require_number(risk.get("max_exposure_pct"), "risk_envelope.max_exposure_pct", minimum=0.0, maximum=100.0),
    }

    lineage = _require_dict(proposal.get("lineage"), "lineage")
    normalized_lineage = {key: _require_sha(lineage.get(key), f"lineage.{key}") for key in sorted(REQUIRED_SHA_KEYS)}
    normalized_lineage.update({
        "run_id": _require_string(lineage.get("run_id"), "lineage.run_id", max_len=40),
        "artifact": _require_string(lineage.get("artifact"), "lineage.artifact", max_len=240),
        "data_epoch": _require_string(lineage.get("data_epoch"), "lineage.data_epoch", max_len=80),
    })
    normalized["lineage"] = normalized_lineage

    normalized["proposal_state"] = _require_enum(proposal.get("proposal_state"), "proposal_state", PROPOSAL_STATES)
    reason_codes = proposal.get("reason_codes")
    if not isinstance(reason_codes, list) or len(reason_codes) > 20:
        _fail("REASON_CODES_INVALID")
    normalized["reason_codes"] = sorted({_require_string(item, "reason_codes[]", max_len=100).upper() for item in reason_codes})

    authority = _require_dict(proposal.get("authority"), "authority")
    normalized["authority"] = {
        "stage": _require_enum(authority.get("stage"), "authority.stage", STAGES),
        "research_only": _require_bool(authority.get("research_only"), "authority.research_only"),
        "promotion_authority": _require_bool(authority.get("promotion_authority"), "authority.promotion_authority"),
        "execution_allowed": _require_bool(authority.get("execution_allowed"), "authority.execution_allowed"),
        "order_authority": _require_enum(authority.get("order_authority"), "authority.order_authority", {"BLOCKED"}),
        "protected_mutations": _require_int(authority.get("protected_mutations"), "authority.protected_mutations", minimum=0),
    }
    if normalized["authority"]["research_only"] is not True:
        _fail("RESEARCH_ONLY_REQUIRED")
    if normalized["authority"]["promotion_authority"] is not False:
        _fail("PROMOTION_AUTHORITY_FORBIDDEN")
    if normalized["authority"]["execution_allowed"] is not False:
        _fail("EXECUTION_FORBIDDEN")
    if normalized["authority"]["protected_mutations"] != 0:
        _fail("PROTECTED_MUTATION_FORBIDDEN")

    metadata = proposal.get("metadata", {})
    if not isinstance(metadata, Mapping):
        _fail("OBJECT_REQUIRED", "metadata")
    normalized["metadata"] = dict(metadata)
    _reject_private_fields(normalized["metadata"], "$.metadata")

    computed_sha = proposal_sha(normalized)
    if require_sealed_sha:
        supplied_sha = _require_sha(proposal.get("proposal_sha"), "proposal_sha")
        if supplied_sha != computed_sha:
            _fail("PROPOSAL_SHA_MISMATCH")
    normalized["proposal_sha"] = computed_sha
    return normalized


def seal_proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(value))
    payload.pop("proposal_sha", None)
    normalized = validate_proposal(payload, require_sealed_sha=False)
    return validate_proposal(normalized, require_sealed_sha=True)


def contract_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Normalize independent strategy proposals before classification, ensemble analysis and portfolio governance.",
        "producer_lanes": sorted(TEAM_LANES),
        "producer_roles": sorted(PRODUCER_ROLES),
        "proposal_states": sorted(PROPOSAL_STATES),
        "required_lineage_sha": sorted(REQUIRED_SHA_KEYS),
        "private_field_tokens": sorted(PRIVATE_KEY_TOKENS),
        "authority": {
            "research_only": True,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "protected_mutations": 0,
        },
    }
