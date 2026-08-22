#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as af
from backend.research.architecture_factory.a1_research_depth_retry_guard_v1 import audit as depth_audit

ROOT = Path(__file__).resolve().parents[3]
SUPPLEMENT = ROOT / "backend/research/contracts/a1_high_value_evidence_supplement_v1.json"
SCHEMA = "zel.a1_mechanism_first_research.v1"
COMMON_READY_SOURCES = {"ohlcv", "volume"}
DERIVATIVES_HISTORY_SOURCES = {"funding", "basis", "open_interest"}
MICROSTRUCTURE_HISTORY_SOURCES = {"l2_order_book", "trade_flow"}
COMMON_READY_GENERATION_REQUIREMENT = (
    "COMMON_READY_NEW_ARCHITECTURE_REQUIRED: among the NEW_ARCHITECTURE candidates, generate at least one "
    "candidate whose required_sources are a non-empty subset of [ohlcv, volume] only. It must still be a genuinely "
    "new mechanism/payer/native-horizon architecture, not a renamed legacy repair. Do not add funding, basis, "
    "open_interest, l2_order_book, or trade_flow to that candidate. This is a source-availability constraint only; "
    "do not relax evidence quorum, economics, falsification, cost geometry, or any alpha threshold."
)
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _combined_evidence() -> dict[str, Any]:
    base = _read(af.EVIDENCE)
    supplement = _read(SUPPLEMENT)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(base.get("sources") or []) + list(supplement.get("sources") or []):
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        sid = str(item.get("id") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        item.setdefault("source_type", item.get("tier"))
        item.setdefault("claim", item.get("mechanism"))
        item.setdefault("applicable_families", item.get("applicable_axes") or [])
        rows.append(item)
    out = dict(base)
    out["sources"] = rows
    out["mechanism_first_high_value_supplement_bound"] = True
    out["thresholds_imported_from_sources"] = False
    return out


def _source_preflight(candidate: Mapping[str, Any]) -> tuple[str, list[str]]:
    required = {str(x) for x in (candidate.get("required_sources") or []) if str(x)}
    blockers: list[str] = []
    unknown = required - COMMON_READY_SOURCES - DERIVATIVES_HISTORY_SOURCES - MICROSTRUCTURE_HISTORY_SOURCES
    if unknown:
        blockers.append("UNKNOWN_SOURCE_VOCABULARY:" + ",".join(sorted(unknown)))
    if required & MICROSTRUCTURE_HISTORY_SOURCES:
        blockers.append("TIMESTAMPED_PREENTRY_L2_TRADE_FLOW_HISTORY_REQUIRED")
    if required & DERIVATIVES_HISTORY_SOURCES:
        blockers.append("NATIVE_DERIVATIVES_HISTORY_AUDIT_REQUIRED")
    if blockers:
        return "HOLD_SOURCE_PREFLIGHT", blockers
    if required and required <= COMMON_READY_SOURCES:
        return "READY_COMMON", []
    return "HOLD_SOURCE_PREFLIGHT", ["REQUIRED_SOURCES_EMPTY_OR_UNRESOLVED"]


def _guard(candidate: Mapping[str, Any]) -> tuple[bool, list[str], str, list[str]]:
    reasons: list[str] = []
    if candidate.get("mode") != "NEW_ARCHITECTURE":
        reasons.append("LEGACY_REPAIR_NOT_PRIMARY_LANE")
    if candidate.get("eligible_for_preregistration") is not True:
        reasons.append("INDEPENDENT_REVIEW_NOT_ELIGIBLE")
    if int(candidate.get("independent_passes") or 0) < 2:
        reasons.append("REVIEW_QUORUM_LT2")
    if int(candidate.get("independent_rejects") or 0) > 0:
        reasons.append("EXPLICIT_REVIEW_REJECT")
    if len({str(x) for x in (candidate.get("evidence_ids") or []) if str(x)}) < 3:
        reasons.append("EVIDENCE_SUPPORT_LT3")
    try:
        multiple = float(candidate.get("expected_move_cost_multiple_target") or 0.0)
    except (TypeError, ValueError):
        multiple = 0.0
    if multiple < 2.0:
        reasons.append("DESIGN_MOVE_COST_TARGET_LT2")
    for key in ("mechanism", "payer", "entry_event", "native_horizon", "turnover_cost_budget", "falsification"):
        if not str(candidate.get(key) or "").strip():
            reasons.append(f"MISSING_{key.upper()}")
    source_state, source_blockers = _source_preflight(candidate)
    runnable = not reasons and source_state == "READY_COMMON"
    return runnable, reasons, source_state, source_blockers


def _run_architecture_factory_common_ready(architecture_receipt: Path) -> dict[str, Any]:
    original_prompt = af.generator_prompt

    def source_ready_prompt(context: Mapping[str, Any]) -> str:
        return original_prompt(context) + "\n" + COMMON_READY_GENERATION_REQUIREMENT

    try:
        af.generator_prompt = source_ready_prompt
        return dict(af.run(architecture_receipt))
    finally:
        af.generator_prompt = original_prompt


def run(output: Path) -> dict[str, Any]:
    depth = depth_audit()
    if depth.get("state") != "PASS_RESEARCH_DEPTH_RETRY_GUARD":
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_MECHANISM_FIRST_DEPTH_GUARD",
            "depth_retry_guard": depth,
            "research_direction": "NEW_ARCHITECTURE_PRIMARY",
            **AUTH,
        }
        result["receipt_sha256"] = af.sha(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result

    original_evidence = af.EVIDENCE
    with tempfile.TemporaryDirectory(prefix="a1-mechanism-first-") as td:
        temp = Path(td)
        combined_path = temp / "combined_evidence.json"
        combined_path.write_text(json.dumps(_combined_evidence(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        architecture_receipt = temp / "architecture_factory.json"
        try:
            af.EVIDENCE = combined_path
            architecture = _run_architecture_factory_common_ready(architecture_receipt)
        finally:
            af.EVIDENCE = original_evidence

    diagnostics: list[dict[str, Any]] = []
    runnable: list[dict[str, Any]] = []
    source_wait: list[dict[str, Any]] = []
    legacy_repairs: list[dict[str, Any]] = []
    for raw in architecture.get("all_reviewed_candidates") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        ok, reasons, source_state, source_blockers = _guard(row)
        row["mechanism_first_guard_pass"] = ok
        row["mechanism_first_guard_reasons"] = reasons
        row["source_preflight_state"] = source_state
        row["source_preflight_blockers"] = source_blockers
        diagnostics.append({
            "candidate_id": row.get("candidate_id"),
            "mode": row.get("mode"),
            "architecture_family": row.get("architecture_family"),
            "native_horizon": row.get("native_horizon"),
            "required_sources": row.get("required_sources"),
            "guard_pass": ok,
            "guard_reasons": reasons,
            "source_preflight_state": source_state,
            "source_preflight_blockers": source_blockers,
        })
        if row.get("mode") == "REPAIR":
            legacy_repairs.append(row)
        elif ok:
            runnable.append(row)
        elif not reasons and source_state != "READY_COMMON":
            source_wait.append(row)

    runnable.sort(key=lambda x: (-float(x.get("score") or 0.0), str(x.get("candidate_id") or "")))
    source_wait.sort(key=lambda x: (-float(x.get("score") or 0.0), str(x.get("candidate_id") or "")))
    legacy_repairs.sort(key=lambda x: (-float(x.get("score") or 0.0), str(x.get("candidate_id") or "")))

    state = "PASS_MECHANISM_FIRST_NEW_ARCHITECTURE_READY" if runnable else "HOLD_MECHANISM_FIRST_NO_SOURCE_READY_NEW_ARCHITECTURE"
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "research_direction": "NEW_ARCHITECTURE_PRIMARY",
        "legacy_repair_lane": "SECONDARY_MANUAL_OR_FALLBACK_ONLY",
        "automatic_legacy_a5_repair_primary": False,
        "objective": "Find robust after-cost alpha by mechanism/payer/native-horizon architecture before spending more budget repairing weak legacy parents.",
        "design_rules": {
            "new_architecture_primary": True,
            "legacy_repair_primary": False,
            "minimum_independent_passes": 2,
            "maximum_independent_rejects": 0,
            "minimum_supporting_evidence_documents": 3,
            "minimum_common_ready_new_architectures_requested": 1,
            "expected_move_cost_multiple_target": 2.0,
            "expected_move_cost_multiple_is_design_objective_not_alpha_evidence": True,
            "threshold_sweep": False,
            "best_horizon_cherry_pick": False,
            "sealed_holdout_visibility": False,
            "fee_reduction_rescue": False,
        },
        "source_policy": {
            "common_ready": sorted(COMMON_READY_SOURCES),
            "derivatives_history_requires_native_audit": sorted(DERIVATIVES_HISTORY_SOURCES),
            "microstructure_requires_timestamped_preentry_history": sorted(MICROSTRUCTURE_HISTORY_SOURCES),
            "common_ready_generation_requirement": COMMON_READY_GENERATION_REQUIREMENT,
        },
        "depth_retry_guard": depth,
        "architecture_factory_state": architecture.get("state"),
        "architecture_factory_receipt_sha256": architecture.get("receipt_sha256"),
        "generator_status": architecture.get("generators"),
        "generated_after_dedup": architecture.get("generated_after_dedup"),
        "candidate_guard_diagnostics": diagnostics,
        "new_architecture_ready_queue": runnable[:10],
        "new_architecture_source_wait_queue": source_wait[:10],
        "legacy_repair_backlog": legacy_repairs[:10],
        "new_architecture_ready_count": len(runnable),
        "new_architecture_source_wait_count": len(source_wait),
        "legacy_repair_backlog_count": len(legacy_repairs),
        "next_experiment_candidate": runnable[0] if runnable else None,
        **AUTH,
    }
    result["receipt_sha256"] = af.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    good = {
        "candidate_id": "new-hours",
        "mode": "NEW_ARCHITECTURE",
        "eligible_for_preregistration": True,
        "independent_passes": 2,
        "independent_rejects": 0,
        "evidence_ids": ["A", "B", "C"],
        "expected_move_cost_multiple_target": 2.0,
        "mechanism": "inventory adjustment",
        "payer": "slow inventory rebalancer",
        "entry_event": "completed-bar phase event",
        "native_horizon": "multi-hour",
        "turnover_cost_budget": "natural move is designed to dominate frozen round-trip cost",
        "falsification": "fresh after-cost failure",
        "required_sources": ["ohlcv", "volume"],
    }
    ok, reasons, source_state, blockers = _guard(good)
    assert ok and not reasons and source_state == "READY_COMMON" and not blockers
    repair = dict(good, mode="REPAIR")
    ok, reasons, _, _ = _guard(repair)
    assert not ok and "LEGACY_REPAIR_NOT_PRIMARY_LANE" in reasons
    advanced = dict(good, required_sources=["ohlcv", "funding", "open_interest"])
    ok, reasons, source_state, blockers = _guard(advanced)
    assert not ok and not reasons and source_state == "HOLD_SOURCE_PREFLIGHT"
    assert "NATIVE_DERIVATIVES_HISTORY_AUDIT_REQUIRED" in blockers
    sample_prompt = af.generator_prompt({"available_source_vocabulary": sorted(COMMON_READY_SOURCES)}) + "\n" + COMMON_READY_GENERATION_REQUIREMENT
    assert "COMMON_READY_NEW_ARCHITECTURE_REQUIRED" in sample_prompt
    assert "ohlcv" in sample_prompt and "volume" in sample_prompt
    print("PASS_A1_MECHANISM_FIRST_RESEARCH_V1_SELF_TEST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/a1_mechanism_first_research_v1.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    next_row = result.get("next_experiment_candidate") or {}
    print(json.dumps({
        "state": result.get("state"),
        "direction": result.get("research_direction"),
        "new_ready": result.get("new_architecture_ready_count"),
        "new_source_wait": result.get("new_architecture_source_wait_count"),
        "legacy_backlog": result.get("legacy_repair_backlog_count"),
        "next": next_row.get("candidate_id"),
        "family": next_row.get("architecture_family"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
