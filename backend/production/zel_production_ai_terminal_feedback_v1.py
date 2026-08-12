from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_ai_terminal_feedback.v1"
POLICY_SCHEMA = "zel.production_ai_terminal_feedback_policy.v1"
CATALOG_SCHEMA = "zel.production_ai_terminal_family_catalog.v1"
ECONOMIC_SCHEMA = "zel.production_ai_admission_executor.v1"
PROPOSAL_SCHEMA = "zel.production_ai_proposal_layer.v1"
CONTRACT_STATE_SCHEMA = "zel.production_ai_admission_materializer.v1"
FACTORY_SCHEMA = "zel.production_alpha_factory.v1"
DEFAULT_POLICY = Path("config/zel_production_ai_terminal_feedback_v1.json")
REJECT_STATE = "REJECT_AI_ADMISSION_ECONOMIC_EDGE"


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("AI_TERMINAL_FEEDBACK_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("AI_TERMINAL_FEEDBACK_NON_PAPER_FORBIDDEN")
    for key in (
        "economic_result_path", "proposal_state_path", "contract_state_path",
        "terminal_catalog_path", "factory_path", "proposal_policy_path",
        "augmented_factory_path", "augmented_proposal_policy_path",
    ):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"AI_TERMINAL_FEEDBACK_PATH_MISSING:{key}")
    _authority_guard(policy, "AI_TERMINAL_FEEDBACK_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("AI_TERMINAL_FEEDBACK_MUTATION_FORBIDDEN")
    return dict(policy)


def _empty_catalog(now_ms: int) -> dict[str, Any]:
    row = {
        "schema_version": CATALOG_SCHEMA,
        "state": "PASS_AI_TERMINAL_CATALOG_EMPTY",
        "entries": [],
        "terminal_family_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now_ms,
    }
    row["receipt_sha256"] = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    return row


def _validate_catalog(catalog: Mapping[str, Any] | None, now_ms: int) -> dict[str, Any]:
    if not isinstance(catalog, Mapping):
        return _empty_catalog(now_ms)
    if catalog.get("schema_version") != CATALOG_SCHEMA:
        raise RuntimeError("AI_TERMINAL_FEEDBACK_CATALOG_SCHEMA_INVALID")
    _authority_guard(catalog, "AI_TERMINAL_FEEDBACK_CATALOG")
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError("AI_TERMINAL_FEEDBACK_CATALOG_ENTRIES_INVALID")
    return dict(catalog)


def _rejected_results(economic: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(economic, Mapping):
        return []
    if economic.get("schema_version") != ECONOMIC_SCHEMA:
        raise RuntimeError("AI_TERMINAL_FEEDBACK_ECONOMIC_SCHEMA_INVALID")
    _authority_guard(economic, "AI_TERMINAL_FEEDBACK_ECONOMIC")
    out: list[dict[str, Any]] = []
    for raw in economic.get("results") or []:
        if not isinstance(raw, Mapping) or raw.get("state") != REJECT_STATE:
            continue
        family_id = str(raw.get("family_id") or "").strip()
        if not family_id:
            raise RuntimeError("AI_TERMINAL_FEEDBACK_REJECT_FAMILY_MISSING")
        out.append(dict(raw))
    return out


def _proposal_mechanisms(proposal: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(proposal, Mapping) or proposal.get("schema_version") != PROPOSAL_SCHEMA:
        return {}
    _authority_guard(proposal, "AI_TERMINAL_FEEDBACK_PROPOSAL")
    out: dict[str, str] = {}
    for raw in proposal.get("proposals") or []:
        if isinstance(raw, Mapping):
            family_id = str(raw.get("family_id") or "").strip()
            if family_id:
                out[family_id] = str(raw.get("economic_mechanism") or "").strip()
    return out


def _merge_catalog(
    catalog: Mapping[str, Any] | None,
    rejected: list[dict[str, Any]],
    economic: Mapping[str, Any] | None,
    proposal: Mapping[str, Any] | None,
    now_ms: int,
) -> tuple[dict[str, Any], list[str]]:
    out = _validate_catalog(catalog, now_ms)
    entries = [dict(x) for x in out.get("entries") or [] if isinstance(x, Mapping)]
    by_id = {str(x.get("family_id") or ""): x for x in entries if str(x.get("family_id") or "")}
    mechanisms = _proposal_mechanisms(proposal)
    added: list[str] = []
    economic_receipt = str((economic or {}).get("receipt_sha256") or "")
    for row in rejected:
        family_id = str(row["family_id"])
        if family_id in by_id:
            continue
        entry = {
            "family_id": family_id,
            "state": "TERMINAL_REJECT_AI_ADMISSION_DO_NOT_REACTIVATE",
            "economic_mechanism": mechanisms.get(family_id, ""),
            "contract_id": str(row.get("contract_id") or ""),
            "template_id": str(row.get("template_id") or ""),
            "economic_result_receipt_sha256": str(row.get("receipt_sha256") or ""),
            "economic_batch_receipt_sha256": economic_receipt,
            "rejected_at_ms": now_ms,
            "reactivation_allowed": False,
        }
        entries.append(entry)
        by_id[family_id] = entry
        added.append(family_id)
    entries.sort(key=lambda x: str(x.get("family_id") or ""))
    out.update(
        {
            "state": "PASS_AI_TERMINAL_CATALOG_BOUND" if entries else "PASS_AI_TERMINAL_CATALOG_EMPTY",
            "entries": entries,
            "terminal_family_count": len(entries),
            "updated_at_ms": now_ms,
        }
    )
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, sorted(added)


def _sanitize_proposal(proposal: Mapping[str, Any] | None, terminal_ids: set[str], catalog_sha: str) -> tuple[dict[str, Any] | None, int]:
    if not isinstance(proposal, Mapping):
        return None, 0
    if proposal.get("schema_version") != PROPOSAL_SCHEMA:
        raise RuntimeError("AI_TERMINAL_FEEDBACK_PROPOSAL_SCHEMA_INVALID")
    _authority_guard(proposal, "AI_TERMINAL_FEEDBACK_PROPOSAL")
    rows = proposal.get("proposals")
    if not isinstance(rows, list):
        raise RuntimeError("AI_TERMINAL_FEEDBACK_PROPOSAL_LIST_INVALID")
    kept = [dict(x) for x in rows if isinstance(x, Mapping) and str(x.get("family_id") or "") not in terminal_ids]
    dropped = len(rows) - len(kept)
    if dropped == 0:
        return dict(proposal), 0
    out = dict(proposal)
    out["proposals"] = kept
    out["proposal_count"] = len(kept)
    out["source_ready_count"] = sum(bool(x.get("source_ready")) for x in kept)
    if kept:
        out["state"] = "PASS_AI_PROPOSAL_SOURCE_READY" if out["source_ready_count"] else "HOLD_AI_PROPOSAL_SOURCE_BINDING_REQUIRED"
    else:
        out["state"] = "HOLD_AI_PROPOSAL_NO_CANDIDATE"
        out["ai_call_succeeded"] = False
        out["retry_after_ms"] = 0
        out["reused"] = False
    out["terminal_feedback_catalog_sha256"] = catalog_sha
    out["terminal_feedback_dropped_count"] = dropped
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, dropped


def _sanitize_contracts(contracts: Mapping[str, Any] | None, terminal_ids: set[str], catalog_sha: str) -> tuple[dict[str, Any] | None, int]:
    if not isinstance(contracts, Mapping):
        return None, 0
    if contracts.get("schema_version") != CONTRACT_STATE_SCHEMA:
        raise RuntimeError("AI_TERMINAL_FEEDBACK_CONTRACT_SCHEMA_INVALID")
    _authority_guard(contracts, "AI_TERMINAL_FEEDBACK_CONTRACT")
    rows = contracts.get("contracts")
    if not isinstance(rows, list):
        raise RuntimeError("AI_TERMINAL_FEEDBACK_CONTRACT_LIST_INVALID")
    kept = [dict(x) for x in rows if isinstance(x, Mapping) and str(x.get("family_id") or "") not in terminal_ids]
    dropped = len(rows) - len(kept)
    if dropped == 0:
        return dict(contracts), 0
    out = dict(contracts)
    out["contracts"] = kept
    out["contract_count"] = len(kept)
    if kept:
        out["state"] = "PASS_AI_ADMISSION_CONTRACTS_FROZEN"
    else:
        out["state"] = "HOLD_AI_ADMISSION_NO_SOURCE_READY_PROPOSAL"
        out["next"] = "RETURN_TO_EDGE_ACQUISITION"
    out["terminal_feedback_catalog_sha256"] = catalog_sha
    out["terminal_feedback_dropped_count"] = dropped
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, dropped


def _augment_factory(factory: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    if factory.get("schema_version") != FACTORY_SCHEMA:
        raise RuntimeError("AI_TERMINAL_FEEDBACK_FACTORY_SCHEMA_INVALID")
    families = factory.get("families")
    if not isinstance(families, Mapping):
        raise RuntimeError("AI_TERMINAL_FEEDBACK_FACTORY_FAMILIES_MISSING")
    out = copy.deepcopy(dict(factory))
    augmented = dict(out["families"])
    for entry in catalog.get("entries") or []:
        if not isinstance(entry, Mapping):
            continue
        family_id = str(entry.get("family_id") or "")
        if not family_id:
            continue
        if family_id in augmented:
            raise RuntimeError(f"AI_TERMINAL_FEEDBACK_FACTORY_ID_COLLISION:{family_id}")
        augmented[family_id] = {
            "strategy_id": f"terminal_ai_{family_id}",
            "status": "TERMINAL_REJECT_AI_ADMISSION_DO_NOT_REACTIVATE",
            "mechanism": entry.get("economic_mechanism"),
            "symbols": [],
            "reactivation_allowed": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }
    out["families"] = augmented
    out["terminal_feedback_catalog_sha256"] = catalog.get("receipt_sha256")
    return out


def feedback_tick(
    policy: Mapping[str, Any],
    *,
    economic: Mapping[str, Any] | None,
    proposal: Mapping[str, Any] | None,
    contracts: Mapping[str, Any] | None,
    catalog: Mapping[str, Any] | None,
    factory: Mapping[str, Any],
    proposal_policy: Mapping[str, Any],
    now_ms: int | None = None,
) -> dict[str, Any]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    rejected = _rejected_results(economic)
    merged_catalog, added = _merge_catalog(catalog, rejected, economic, proposal, now)
    terminal_ids = {str(x.get("family_id") or "") for x in merged_catalog.get("entries") or [] if isinstance(x, Mapping)}
    sanitized_proposal, dropped_proposals = _sanitize_proposal(proposal, terminal_ids, str(merged_catalog["receipt_sha256"]))
    sanitized_contracts, dropped_contracts = _sanitize_contracts(contracts, terminal_ids, str(merged_catalog["receipt_sha256"]))
    augmented_factory = _augment_factory(factory, merged_catalog)
    augmented_policy = dict(proposal_policy)
    augmented_policy["factory_path"] = str(cfg["augmented_factory_path"])
    augmented_policy["terminal_feedback_catalog_sha256"] = merged_catalog["receipt_sha256"]
    out = {
        "schema_version": SCHEMA,
        "state": "PASS_AI_TERMINAL_REJECT_FEEDBACK_APPLIED" if (added or dropped_proposals or dropped_contracts) else "HOLD_AI_TERMINAL_FEEDBACK_NO_NEW_REJECT",
        "action": "hold",
        "new_terminal_family_ids": added,
        "terminal_family_count": len(terminal_ids),
        "dropped_proposal_count": dropped_proposals,
        "dropped_contract_count": dropped_contracts,
        "terminal_catalog": merged_catalog,
        "sanitized_proposal": sanitized_proposal,
        "sanitized_contracts": sanitized_contracts,
        "augmented_factory": augmented_factory,
        "augmented_proposal_policy": augmented_policy,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    }
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Feed terminal AI economic rejects back into Explore")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    result = feedback_tick(
        cfg,
        economic=read_json(Path(str(cfg["economic_result_path"]))),
        proposal=read_json(Path(str(cfg["proposal_state_path"]))),
        contracts=read_json(Path(str(cfg["contract_state_path"]))),
        catalog=read_json(Path(str(cfg["terminal_catalog_path"]))),
        factory=read_json(Path(str(cfg["factory_path"]))) or {},
        proposal_policy=read_json(Path(str(cfg["proposal_policy_path"]))) or {},
    )
    atomic_json_write(Path(str(cfg["terminal_catalog_path"])), result["terminal_catalog"])
    if isinstance(result.get("sanitized_proposal"), Mapping):
        atomic_json_write(Path(str(cfg["proposal_state_path"])), result["sanitized_proposal"])
    if isinstance(result.get("sanitized_contracts"), Mapping):
        atomic_json_write(Path(str(cfg["contract_state_path"])), result["sanitized_contracts"])
    atomic_json_write(Path(str(cfg["augmented_factory_path"])), result["augmented_factory"])
    atomic_json_write(Path(str(cfg["augmented_proposal_policy_path"])), result["augmented_proposal_policy"])
    print(json.dumps({
        "state": result["state"],
        "new_terminal_family_ids": result["new_terminal_family_ids"],
        "terminal_family_count": result["terminal_family_count"],
        "dropped_proposal_count": result["dropped_proposal_count"],
        "dropped_contract_count": result["dropped_contract_count"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
