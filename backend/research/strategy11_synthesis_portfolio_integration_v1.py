from __future__ import annotations

import copy
from typing import Any, Mapping

from backend.contracts.strategy11_strategy_proposal_contract_v1 import validate_proposal
from backend.research.strategy11_ensemble_correlation_analyzer_v1 import analyze_candidates
from backend.research.strategy11_global_candidate_classifier_v1 import canonical_sha as classifier_sha
from backend.research.strategy11_portfolio_governor_v1 import govern
from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY, canonical_sha

INPUT_SCHEMA = "strategy11.synthesis_portfolio_integration.input.v1"
OUTPUT_SCHEMA = "strategy11.synthesis_portfolio_integration.output.v1"
PACKAGE_SCHEMA = "strategy11.portfolio_candidate_package.v1"
ELIGIBLE = {"CORE", "SYNTHESIS"}


class SynthesisPortfolioIntegrationError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise SynthesisPortfolioIntegrationError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, 64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def validate_package(value: Mapping[str, Any]) -> dict[str, Any]:
    package = _mapping(value, "candidate_package")
    supplied_sha = _sha(package.get("package_sha"), "candidate_package.package_sha")
    raw = copy.deepcopy(package)
    raw.pop("package_sha", None)
    if canonical_sha(raw) != supplied_sha:
        _fail("PACKAGE_SHA_MISMATCH")
    if package.get("schema_version") != PACKAGE_SCHEMA:
        _fail("PACKAGE_SCHEMA_MISMATCH")
    for key, expected in SAFETY.items():
        if package.get(key) != expected:
            _fail("PACKAGE_AUTHORITY_MISMATCH", key)

    proposal = validate_proposal(_mapping(package.get("proposal"), "package.proposal"))
    classification = _mapping(package.get("classification"), "package.classification")
    classification_name = _string(classification.get("classification"), "classification.classification").upper()
    if classification_name not in ELIGIBLE:
        _fail("PACKAGE_CLASSIFICATION_NOT_ELIGIBLE", classification_name)
    if classification.get("strategy_id") != proposal["strategy_id"]:
        _fail("PACKAGE_STRATEGY_ID_MISMATCH")
    if classification.get("candidate_sha") != proposal["candidate_sha"]:
        _fail("PACKAGE_CANDIDATE_SHA_MISMATCH")
    if classification.get("proposal_sha") != proposal["proposal_sha"]:
        _fail("PACKAGE_PROPOSAL_SHA_MISMATCH")
    classification_sha = _sha(classification.get("classification_sha"), "classification.classification_sha")
    if classifier_sha({key: child for key, child in classification.items() if key != "classification_sha"}) != classification_sha:
        _fail("CLASSIFICATION_SHA_MISMATCH")

    ledger = package.get("source_ledger")
    if not isinstance(ledger, list) or not ledger:
        _fail("SOURCE_LEDGER_REQUIRED")
    normalized_trades: list[dict[str, Any]] = []
    seen_trade_ids: set[str] = set()
    seen_timestamps: set[str] = set()
    for index, raw_trade in enumerate(ledger):
        trade = _mapping(raw_trade, f"source_ledger[{index}]")
        trade_id = _string(trade.get("trade_id"), f"source_ledger[{index}].trade_id")
        timestamp = _string(trade.get("timestamp"), f"source_ledger[{index}].timestamp")
        if trade_id in seen_trade_ids:
            _fail("DUPLICATE_TRADE_ID", trade_id)
        if timestamp in seen_timestamps:
            _fail("DUPLICATE_TRADE_TIMESTAMP", timestamp)
        seen_trade_ids.add(trade_id)
        seen_timestamps.add(timestamp)
        core = {
            "trade_id": trade_id,
            "timestamp": timestamp,
            "net_r": trade.get("net_r"),
            "symbol": _string(trade.get("symbol"), f"source_ledger[{index}].symbol").upper(),
            "regime": _string(trade.get("regime"), f"source_ledger[{index}].regime").upper(),
        }
        supplied_row_sha = _sha(trade.get("source_row_sha"), f"source_ledger[{index}].source_row_sha")
        if canonical_sha(core) != supplied_row_sha:
            _fail("SOURCE_ROW_SHA_MISMATCH", trade_id)
        if isinstance(core["net_r"], bool) or not isinstance(core["net_r"], (int, float)):
            _fail("NET_R_NUMBER_REQUIRED", trade_id)
        normalized_trades.append({**core, "net_r": float(core["net_r"]), "source_row_sha": supplied_row_sha})
    normalized_trades.sort(key=lambda row: row["timestamp"])

    material = _mapping(package.get("material"), "package.material")
    required_material = {
        "material_id", "material_sealed", "material_seal_sha", "net_after_cost",
        "confidence", "uncertainty", "dd_pct", "joint_tail_dd_pct", "cost_pct",
        "capacity_score", "incumbent_weight",
    }
    if set(material) != required_material:
        _fail("MATERIAL_FIELD_SET_MISMATCH")
    if material.get("material_sealed") is not True:
        _fail("MATERIAL_NOT_SEALED")
    material_core = {
        "material_id": _string(material["material_id"], "material.material_id"),
        "classification": classification_name,
        "candidate_sha": proposal["candidate_sha"],
        "proposal_sha": proposal["proposal_sha"],
        "classification_sha": classification_sha,
        "net_after_cost": float(material["net_after_cost"]),
        "confidence": float(material["confidence"]),
        "uncertainty": float(material["uncertainty"]),
        "dd_pct": float(material["dd_pct"]),
        "joint_tail_dd_pct": float(material["joint_tail_dd_pct"]),
        "cost_pct": float(material["cost_pct"]),
        "capacity_score": float(material["capacity_score"]),
        "incumbent_weight": float(material["incumbent_weight"]),
    }
    if _sha(material["material_seal_sha"], "material.material_seal_sha") != canonical_sha(material_core):
        _fail("MATERIAL_SEAL_SHA_MISMATCH", material_core["material_id"])
    return {
        "schema_version": PACKAGE_SCHEMA,
        "strategy_id": proposal["strategy_id"],
        "candidate_sha": proposal["candidate_sha"],
        "proposal": proposal,
        "proposal_sha": proposal["proposal_sha"],
        "classification": classification,
        "classification_name": classification_name,
        "classification_sha": classification_sha,
        "source_ledger": normalized_trades,
        "material": {**material_core, "material_sealed": True, "material_seal_sha": material["material_seal_sha"]},
        "package_sha": supplied_sha,
    }


def _hold_no_synthesis_combo(packages: list[dict[str, Any]], correlation: dict[str, Any]) -> dict[str, Any]:
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": "HOLD_NO_COMPATIBLE_SYNTHESIS_PORTFOLIO",
        "candidate_package_shas": [row["package_sha"] for row in packages],
        "correlation_analysis": correlation,
        "governor_result": None,
        "shadow_targets_ready": False,
        "next": "DROP_CORRELATED_MATERIAL_OR_WAIT_NEW_EVIDENCE",
        "runtime_bound": False,
        **SAFETY,
    }
    result["integration_sha"] = canonical_sha(result)
    return result


def integrate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "integration_input")
    allowed = {"schema_version", "candidate_packages", "correlation_policy", "governor_policy", "authority"}
    if set(payload) != allowed:
        _fail("INPUT_FIELD_SET_MISMATCH")
    if payload.get("schema_version") != INPUT_SCHEMA or payload.get("authority") != SAFETY:
        _fail("INPUT_SCHEMA_OR_AUTHORITY_MISMATCH")
    raw_packages = payload.get("candidate_packages")
    if not isinstance(raw_packages, list) or not 2 <= len(raw_packages) <= 5:
        _fail("CANDIDATE_PACKAGE_COUNT_INVALID")
    packages = [validate_package(row) for row in raw_packages]
    if len({row["strategy_id"] for row in packages}) != len(packages):
        _fail("DUPLICATE_STRATEGY_ID")
    if len({row["candidate_sha"] for row in packages}) != len(packages):
        _fail("DUPLICATE_CANDIDATE_SHA")
    material_ids = [row["material"]["material_id"] for row in packages]
    if len(set(material_ids)) != len(material_ids):
        _fail("DUPLICATE_MATERIAL_ID")
    synthesis_strategy_ids = {
        row["strategy_id"] for row in packages if row["classification_name"] == "SYNTHESIS"
    }
    if not synthesis_strategy_ids:
        _fail("SYNTHESIS_PACKAGE_REQUIRED")

    analyzer_candidates = [
        {
            "strategy_id": row["strategy_id"],
            "candidate_sha": row["candidate_sha"],
            "proposal_sha": row["proposal_sha"],
            "classification_sha": row["classification_sha"],
            "classification": row["classification_name"],
            "trades": [
                {
                    "timestamp": trade["timestamp"],
                    "net_r": trade["net_r"],
                    "symbol": trade["symbol"],
                    "regime": trade["regime"],
                }
                for trade in row["source_ledger"]
            ],
        }
        for row in packages
    ]
    correlation = analyze_candidates(analyzer_candidates, _mapping(payload["correlation_policy"], "correlation_policy"))
    selected = correlation.get("shadow_only_candidate_combinations")
    if not isinstance(selected, list):
        _fail("CORRELATION_COMBINATION_LIST_REQUIRED")
    synthesis_selected = [
        combo for combo in selected
        if synthesis_strategy_ids.intersection(set(combo.get("members", [])))
    ]
    if not synthesis_selected:
        return _hold_no_synthesis_combo(packages, correlation)

    chosen = synthesis_selected[0]
    chosen_members = set(chosen["members"])
    chosen_packages = [row for row in packages if row["strategy_id"] in chosen_members]
    if not any(row["classification_name"] == "SYNTHESIS" for row in chosen_packages):
        _fail("SELECTED_COMBINATION_MISSING_SYNTHESIS")
    chosen_material_ids = [row["material"]["material_id"] for row in chosen_packages]
    if len(set(chosen_material_ids)) != len(chosen_material_ids):
        _fail("SELECTED_COMBINATION_DUPLICATE_MATERIAL_ID")
    candidate_set_sha = chosen["combination_sha"]
    governor_input = {
        "candidate_set_sha": candidate_set_sha,
        "correlation_artifact_sha": correlation["analysis_sha"],
        "materials": [
            {
                "material_id": row["material"]["material_id"],
                "classification": row["classification_name"],
                "material_sealed": True,
                "net_after_cost": row["material"]["net_after_cost"],
                "confidence": row["material"]["confidence"],
                "uncertainty": row["material"]["uncertainty"],
                "dd_pct": row["material"]["dd_pct"],
                "joint_tail_dd_pct": row["material"]["joint_tail_dd_pct"],
                "cost_pct": row["material"]["cost_pct"],
                "capacity_score": row["material"]["capacity_score"],
                "incumbent_weight": row["material"]["incumbent_weight"],
            }
            for row in chosen_packages
        ],
        "policy": copy.deepcopy(payload["governor_policy"]),
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    governor = govern(governor_input)
    pass_governor = governor.get("status") == "PASS_PORTFOLIO_GOVERNOR_SHADOW_TARGETS"
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": "PASS_SYNTHESIS_PORTFOLIO_INTEGRATION" if pass_governor else "HOLD_SYNTHESIS_PORTFOLIO_GOVERNOR",
        "candidate_package_shas": [row["package_sha"] for row in packages],
        "selected_members": chosen["members"],
        "selected_synthesis_members": sorted(synthesis_strategy_ids.intersection(chosen_members)),
        "candidate_set_sha": candidate_set_sha,
        "correlation_analysis": correlation,
        "correlation_analysis_sha": correlation["analysis_sha"],
        "governor_result": governor,
        "shadow_targets_ready": pass_governor,
        "automatic_shadow_start": False,
        "runtime_bound": False,
        "next": "SOURCE_BOUND_MULTICANDIDATE_PREFLIGHT" if pass_governor else "RETAIN_INCUMBENT_WEIGHTS",
        **SAFETY,
    }
    result["integration_sha"] = canonical_sha(result)
    return result
