from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_pre_survivor_challenger_queue.v1"
POLICY_SCHEMA = "zel.production_pre_survivor_challenger_queue_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_pre_survivor_challenger_queue_v1.json")
PASS_INPUT = "PASS_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_READY"
PASS_QUEUE = "PASS_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_READY"
TERMINAL_REJECT = "REJECT_AI_ADMISSION_ECONOMIC_EDGE"


def _safety() -> dict[str, Any]:
    return {
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "action": "hold",
    }


def _guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")
    if row.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{prefix}_EXCHANGE_ORDER_FORBIDDEN")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("PRE_SURVIVOR_CHALLENGER_QUEUE_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_CHALLENGER_QUEUE_NON_PAPER_FORBIDDEN")
    for key in (
        "input_path", "output_path", "proposal_policy_path", "challenger_evidence_path",
        "reference_feedback_path", "incumbent_path",
    ):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"PRE_SURVIVOR_CHALLENGER_QUEUE_PATH_MISSING:{key}")
    if str(policy["input_path"]) == str(policy["output_path"]):
        raise RuntimeError("PRE_SURVIVOR_CHALLENGER_QUEUE_PATH_COLLISION")
    _guard(policy, "PRE_SURVIVOR_CHALLENGER_QUEUE_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_CHALLENGER_QUEUE_MUTATION_FORBIDDEN")
    return dict(policy)


def _proposal_key(row: Mapping[str, Any]) -> str:
    return stable_sha(
        {
            "family_id": str(row.get("family_id") or ""),
            "template_id": str(row.get("template_id") or ""),
            "economic_mechanism": str(row.get("economic_mechanism") or ""),
            "required_sources": sorted(map(str, row.get("required_sources") or [])),
        }
    )


def _valid_proposals(row: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(row, Mapping):
        return []
    _guard(row, "PRE_SURVIVOR_CHALLENGER_QUEUE_INPUT")
    if row.get("state") != PASS_INPUT:
        return []
    out: list[dict[str, Any]] = []
    for raw in row.get("proposals") or []:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("source_ready") is not True or raw.get("template_ready") is not True:
            continue
        if not str(raw.get("family_id") or "") or not str(raw.get("template_id") or ""):
            continue
        out.append(dict(raw))
    return out


def queue_tick(
    policy: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None,
    reference: Mapping[str, Any] | None,
    incumbent: Mapping[str, Any] | None,
    candidate_budget: int,
    now_ms: int | None = None,
) -> dict[str, Any]:
    validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if candidate_budget <= 0:
        raise RuntimeError("PRE_SURVIVOR_CHALLENGER_QUEUE_BUDGET_INVALID")
    blocked_families: set[str] = set()
    if isinstance(reference, Mapping):
        _guard(reference, "PRE_SURVIVOR_CHALLENGER_QUEUE_REFERENCE")
        if str(reference.get("family_id") or ""):
            blocked_families.add(str(reference.get("family_id")))
    if isinstance(incumbent, Mapping):
        _guard(incumbent, "PRE_SURVIVOR_CHALLENGER_QUEUE_INCUMBENT")
        if str(incumbent.get("family_id") or ""):
            blocked_families.add(str(incumbent.get("family_id")))
    terminal_families: set[str] = set()
    if isinstance(evidence, Mapping):
        _guard(evidence, "PRE_SURVIVOR_CHALLENGER_QUEUE_EVIDENCE")
        for row in evidence.get("challengers") or []:
            if isinstance(row, Mapping) and str(row.get("admission_state") or "") == TERMINAL_REJECT:
                terminal_families.add(str(row.get("family_id") or ""))
    kept: list[dict[str, Any]] = []
    if isinstance(previous, Mapping) and previous.get("schema_version") == SCHEMA:
        _guard(previous, "PRE_SURVIVOR_CHALLENGER_QUEUE_PREVIOUS")
        for row in previous.get("proposals") or []:
            if not isinstance(row, Mapping):
                continue
            family = str(row.get("family_id") or "")
            if family and family not in blocked_families and family not in terminal_families:
                kept.append(dict(row))
    incoming = _valid_proposals(current)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in kept + incoming:
        key = _proposal_key(row)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    selected = merged[:candidate_budget]
    out = {
        "schema_version": SCHEMA,
        "state": PASS_QUEUE if selected else "HOLD_PRE_SURVIVOR_CHALLENGER_QUEUE_EMPTY",
        "role": "PARALLEL_FROZEN_CHALLENGER_QUEUE_NOT_ROUTE",
        "proposal_count": len(selected),
        "source_ready_count": sum(bool(x.get("source_ready")) for x in selected),
        "template_ready_count": sum(bool(x.get("template_ready")) for x in selected),
        "candidate_budget": candidate_budget,
        "proposals": selected,
        "queue_family_ids": [str(x.get("family_id") or "") for x in selected],
        "added_count": max(0, len(selected) - min(len(kept), candidate_budget)),
        "terminal_family_ids_dropped": sorted(x for x in terminal_families if x),
        "reference_family_ids_excluded": sorted(x for x in blocked_families if x),
        "source_next_hypothesis_receipt_sha256": str(current.get("receipt_sha256") or "") if isinstance(current, Mapping) else "",
        "updated_at_ms": now,
        **_safety(),
    }
    out["receipt_sha256"] = stable_sha(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Maintain bounded frozen pre-survivor challenger queue")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    proposal_policy = json.loads(Path(str(cfg["proposal_policy_path"])).read_text(encoding="utf-8"))
    row = queue_tick(
        cfg,
        current=read_json(Path(str(cfg["input_path"]))),
        previous=read_json(Path(str(cfg["output_path"]))),
        evidence=read_json(Path(str(cfg["challenger_evidence_path"]))),
        reference=read_json(Path(str(cfg["reference_feedback_path"]))),
        incumbent=read_json(Path(str(cfg["incumbent_path"]))),
        candidate_budget=int(proposal_policy.get("candidate_budget") or 0),
    )
    atomic_json_write(Path(str(cfg["output_path"])), row)
    print(json.dumps({"state": row["state"], "proposal_count": row["proposal_count"], "queue_family_ids": row["queue_family_ids"], "receipt_sha256": row["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
