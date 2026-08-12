from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_source_acquisition.v1"
POLICY_SCHEMA = "zel.production_source_acquisition_policy.v1"
REGISTRY_SCHEMA = "zel.production_source_capability_registry.v1"
PROPOSAL_SCHEMA = "zel.production_ai_proposal_layer.v1"
DEFAULT_POLICY = Path("config/zel_production_source_acquisition_v1.json")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("SOURCE_ACQUISITION_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("SOURCE_ACQUISITION_NON_PAPER_FORBIDDEN")
    for key in ("proposal_state_path", "source_registry_path", "acquisition_state_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"SOURCE_ACQUISITION_PATH_MISSING:{key}")
    if policy.get("auto_resolve_registered_sources") is not True:
        raise RuntimeError("SOURCE_ACQUISITION_AUTO_RESOLUTION_REQUIRED")
    if policy.get("unverified_proposal_policy") != "DROP_STALE_UNVERIFIED":
        raise RuntimeError("SOURCE_ACQUISITION_UNVERIFIED_PROPOSAL_POLICY_INVALID")
    if policy.get("endpoint_discovery_allowed") is not False or policy.get("synthetic_source_allowed") is not False:
        raise RuntimeError("SOURCE_ACQUISITION_UNVERIFIED_SOURCE_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("SOURCE_ACQUISITION_MUTATION_FORBIDDEN")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("SOURCE_ACQUISITION_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("SOURCE_ACQUISITION_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SOURCE_ACQUISITION_LIVE_FORBIDDEN")
    return dict(policy)


def validate_registry(registry: Mapping[str, Any]) -> dict[str, Any]:
    if registry.get("schema_version") != REGISTRY_SCHEMA:
        raise RuntimeError("SOURCE_CAPABILITY_REGISTRY_SCHEMA_INVALID")
    if registry.get("selection_authority") is not False or registry.get("promotion_authority") is not False:
        raise RuntimeError("SOURCE_CAPABILITY_REGISTRY_AUTHORITY_INVALID")
    if registry.get("execution_authority") != "NONE" or registry.get("order_authority") != "BLOCKED":
        raise RuntimeError("SOURCE_CAPABILITY_REGISTRY_EXECUTION_INVALID")
    sources = registry.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        raise RuntimeError("SOURCE_CAPABILITY_REGISTRY_SOURCES_MISSING")
    out = dict(registry)
    normalized: dict[str, dict[str, Any]] = {}
    for source_id, raw in sources.items():
        if not isinstance(raw, Mapping):
            raise RuntimeError(f"SOURCE_CAPABILITY_ROW_INVALID:{source_id}")
        row = dict(raw)
        available = row.get("proposal_available") is True
        native = row.get("native_read_bound") is True
        owner = row.get("owner_path")
        endpoint = row.get("native_endpoint")
        if available and (not native or not str(owner or "").strip() or not str(endpoint or "").strip()):
            raise RuntimeError(f"SOURCE_CAPABILITY_FALSE_BOUND:{source_id}")
        if not available and native:
            raise RuntimeError(f"SOURCE_CAPABILITY_INCONSISTENT:{source_id}")
        normalized[str(source_id)] = row
    out["sources"] = normalized
    return out


def _proposal_contract(proposal: Mapping[str, Any]) -> None:
    if proposal.get("schema_version") != PROPOSAL_SCHEMA:
        raise RuntimeError("SOURCE_ACQUISITION_PROPOSAL_SCHEMA_INVALID")
    if proposal.get("selection_authority") is not False or proposal.get("promotion_authority") is not False:
        raise RuntimeError("SOURCE_ACQUISITION_PROPOSAL_AUTHORITY_INVALID")
    if proposal.get("execution_authority") != "NONE" or proposal.get("order_authority") != "BLOCKED":
        raise RuntimeError("SOURCE_ACQUISITION_PROPOSAL_EXECUTION_INVALID")
    if proposal.get("live_trade_authority") != "BLOCKED" or proposal.get("exchange_order_submitted") is not False:
        raise RuntimeError("SOURCE_ACQUISITION_PROPOSAL_LIVE_INVALID")


def _base(state: str, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "queue": [],
        "resolved_source_count": 0,
        "missing_source_count": 0,
        "dropped_proposal_count": 0,
        "dropped_family_ids": [],
        "proposal_updated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "updated_at_ms": now_ms,
    }


def source_acquisition_tick(
    policy: Mapping[str, Any],
    *,
    proposal: Mapping[str, Any] | None,
    registry: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(proposal, Mapping):
        out = _base("HOLD_SOURCE_ACQUISITION_NO_AI_PROPOSAL", now)
        out["receipt_sha256"] = stable_sha(out)
        return out, None
    _proposal_contract(proposal)
    if not isinstance(registry, Mapping):
        out = _base("HOLD_SOURCE_ACQUISITION_REGISTRY_MISSING", now)
        out["receipt_sha256"] = stable_sha(out)
        return out, None
    reg = validate_registry(registry)
    sources: Mapping[str, Mapping[str, Any]] = reg["sources"]
    raw_proposals = proposal.get("proposals")
    if not isinstance(raw_proposals, list):
        raise RuntimeError("SOURCE_ACQUISITION_PROPOSAL_LIST_INVALID")

    updated_proposal = dict(proposal)
    resolved_rows: list[dict[str, Any]] = []
    changed = False
    resolved_source_ids: set[str] = set()
    dropped_family_ids: list[str] = []

    for raw in raw_proposals:
        if not isinstance(raw, Mapping):
            raise RuntimeError("SOURCE_ACQUISITION_PROPOSAL_ROW_INVALID")
        row = dict(raw)
        required = row.get("required_sources")
        if not isinstance(required, list) or not required:
            raise RuntimeError("SOURCE_ACQUISITION_REQUIRED_SOURCES_INVALID")
        required_ids = sorted(set(map(str, required)))
        unknown = [sid for sid in required_ids if sid not in sources]
        if unknown:
            raise RuntimeError("SOURCE_ACQUISITION_UNKNOWN_SOURCE:" + ",".join(unknown))

        unverified = sorted(
            sid
            for sid in required_ids
            if sources[sid].get("proposal_available") is not True
            or sources[sid].get("native_read_bound") is not True
        )
        if unverified:
            changed = True
            dropped_family_ids.append(str(row.get("family_id") or row.get("proposal_id") or "UNKNOWN"))
            continue

        if sorted(map(str, row.get("missing_sources") or [])) != [] or bool(row.get("source_ready")) is not True:
            changed = True
        row["required_sources"] = required_ids
        row["missing_sources"] = []
        row["source_ready"] = True
        row["state"] = "PASS_AI_PROPOSAL_SOURCE_READY"
        resolved_rows.append(row)
        resolved_source_ids.update(required_ids)

    updated_proposal["proposals"] = resolved_rows
    updated_proposal["proposal_count"] = len(resolved_rows)
    updated_proposal["source_ready_count"] = len(resolved_rows)
    updated_proposal["dropped_unverified_family_ids"] = sorted(dropped_family_ids)
    updated_proposal["dropped_unverified_proposal_count"] = len(dropped_family_ids)
    if resolved_rows:
        updated_proposal["state"] = "PASS_AI_PROPOSAL_SOURCE_READY"
    elif dropped_family_ids:
        updated_proposal["state"] = "HOLD_AI_PROPOSAL_STALE_UNVERIFIED_DROPPED"
    updated_proposal["source_resolution_registry_sha256"] = stable_sha(reg)
    updated_proposal["source_resolution_updated_at_ms"] = now
    updated_proposal["receipt_sha256"] = stable_sha({k: v for k, v in updated_proposal.items() if k != "receipt_sha256"})

    if resolved_rows:
        out = _base("PASS_SOURCE_ACQUISITION_PROPOSALS_SOURCE_READY", now)
        out["next"] = "DETERMINISTIC_EXPLORE_ROUTER_RECHECK"
    elif dropped_family_ids:
        out = _base("HOLD_SOURCE_ACQUISITION_STALE_UNVERIFIED_DROPPED", now)
        out["next"] = "WAIT_NEW_VERIFIED_SOURCE_ONLY_PROPOSAL"
    else:
        out = _base("HOLD_SOURCE_ACQUISITION_NO_CANDIDATES", now)
    out["resolved_source_count"] = len(resolved_source_ids)
    out["missing_source_count"] = 0
    out["dropped_proposal_count"] = len(dropped_family_ids)
    out["dropped_family_ids"] = sorted(dropped_family_ids)
    out["proposal_updated"] = changed
    out["proposal_receipt_sha256"] = updated_proposal["receipt_sha256"]
    out["source_registry_sha256"] = stable_sha(reg)
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, updated_proposal if changed else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args()
    policy = json.loads(ns.policy.read_text(encoding="utf-8"))
    cfg = validate_policy(policy)
    proposal_path = Path(str(cfg["proposal_state_path"]))
    registry_path = Path(str(cfg["source_registry_path"]))
    result, updated = source_acquisition_tick(
        cfg,
        proposal=read_json(proposal_path),
        registry=read_json(registry_path),
    )
    if updated is not None:
        atomic_json_write(proposal_path, updated)
    atomic_json_write(Path(str(cfg["acquisition_state_path"])), result)
    print(json.dumps({
        "state": result["state"],
        "queue_count": len(result.get("queue") or []),
        "missing_source_count": result["missing_source_count"],
        "resolved_source_count": result["resolved_source_count"],
        "dropped_proposal_count": result["dropped_proposal_count"],
        "proposal_updated": result["proposal_updated"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
