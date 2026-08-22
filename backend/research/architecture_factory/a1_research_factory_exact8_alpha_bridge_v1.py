from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_external_research_exact8_through_a3_v1 as exact8

ROOT = Path(__file__).resolve().parents[3]
RESEARCH_FACTORY_LATEST = ROOT / "backend/research/architecture_factory/a1_research_factory_latest.json"
EXACT8_SPEC = ROOT / "backend/research/architecture_factory/a1_external_research_exact8_spec_v1.json"
FORWARD_STATE = ROOT / "backend/research/prep/a1_external_research_exact8_forward_state_v1.json"
DEFAULT_OUTPUT = ROOT / "out/a1_research_factory_exact8_alpha_bridge_v1.json"

EXPECTED_PARENT = "range_fade"
EXPECTED_CHILD = "range_fade__liquidity_regime_owner_v1"
EXPECTED_AXIS = "LIQUIDITY_REGIME_OWNER_ONLY"
EXPECTED_SOURCES = {"ohlcv", "volume"}

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


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _candidate_rows(factory: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("experiment_queue", "reviewed_ready_common", "reviewed_ready_common_candidates", "eligible_candidates"):
        value = factory.get(key)
        if isinstance(value, list):
            rows.extend(dict(x) for x in value if isinstance(x, Mapping))
    # V5 receipts may expose strategy rows with nested candidates.
    for row in factory.get("strategies") or []:
        if not isinstance(row, Mapping):
            continue
        for key in ("experiment_queue", "reviewed_ready_common", "eligible_candidates", "candidates"):
            value = row.get(key)
            if isinstance(value, list):
                rows.extend(dict(x) for x in value if isinstance(x, Mapping))
    # Last-resort recursive scan is identity-gated below; it does not widen authority.
    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            if value.get("candidate_id") == "range_fade_repair_1":
                rows.append(dict(value))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(factory)
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = str(row.get("candidate_id") or "")
        if cid:
            dedup[cid] = row
    return list(dedup.values())


def _independent_counts(candidate: Mapping[str, Any]) -> tuple[int, int]:
    if candidate.get("independent_passes") is not None:
        return int(candidate.get("independent_passes") or 0), int(candidate.get("independent_rejects") or 0)
    passes = rejects = 0
    reviews = candidate.get("cross_reviews") or candidate.get("reviews") or {}
    values = reviews.values() if isinstance(reviews, Mapping) else reviews if isinstance(reviews, list) else []
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        state = str(raw.get("state") or raw.get("verdict") or raw.get("decision") or "").upper()
        if "PASS" in state:
            passes += 1
        elif "REJECT" in state or "FAIL" in state:
            rejects += 1
    return passes, rejects


def select_reviewed_repair(factory: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    exact_row = spec.get("specs", {}).get(EXPECTED_PARENT)
    if not isinstance(exact_row, Mapping):
        raise RuntimeError("RANGE_FADE_EXACT8_SPEC_MISSING")
    if str(exact_row.get("child_id")) != EXPECTED_CHILD:
        raise RuntimeError("RANGE_FADE_CHILD_IDENTITY_DRIFT")
    if str(exact_row.get("changed_axis")) != EXPECTED_AXIS:
        raise RuntimeError("RANGE_FADE_AXIS_IDENTITY_DRIFT")

    matches: list[dict[str, Any]] = []
    for row in _candidate_rows(factory):
        if str(row.get("candidate_id")) != "range_fade_repair_1":
            continue
        passes, rejects = _independent_counts(row)
        required_sources = {str(x).lower() for x in (row.get("required_sources") or [])}
        eligible = row.get("eligible_for_experiment_queue") is True or row.get("eligible") is True
        if str(row.get("mode") or "").upper() != "REPAIR":
            raise RuntimeError("RESEARCH_REPAIR_MODE_DRIFT")
        if str(row.get("strategy_id") or row.get("parent_id") or "") != EXPECTED_PARENT:
            raise RuntimeError("RESEARCH_REPAIR_STRATEGY_ID_DRIFT")
        if str(row.get("changed_axis") or "") != EXPECTED_AXIS:
            raise RuntimeError("RESEARCH_REPAIR_CHANGED_AXIS_DRIFT")
        if str(row.get("source_gate") or "") != "READY_COMMON":
            raise RuntimeError("RESEARCH_REPAIR_SOURCE_GATE_NOT_READY_COMMON")
        if required_sources and not required_sources.issubset(EXPECTED_SOURCES):
            raise RuntimeError(f"RESEARCH_REPAIR_SOURCE_SCOPE_WIDENED:{sorted(required_sources)}")
        if not eligible:
            raise RuntimeError("RESEARCH_REPAIR_NOT_ELIGIBLE")
        if passes < 2 or rejects != 0:
            raise RuntimeError(f"RESEARCH_REPAIR_INDEPENDENT_REVIEW_NOT_PASS:{passes}:{rejects}")
        matches.append({**row, "independent_passes": passes, "independent_rejects": rejects})
    if len(matches) != 1:
        raise RuntimeError(f"RESEARCH_REPAIR_IDENTITY_CARDINALITY:{len(matches)}")
    return matches[0]


def build_receipt(factory: Mapping[str, Any], state: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    candidate = select_reviewed_repair(factory, spec)
    replay = exact8.replay_child(EXPECTED_PARENT, state, spec)
    if str(replay.get("child_id")) != EXPECTED_CHILD:
        raise RuntimeError("REPLAY_CHILD_IDENTITY_DRIFT")
    a1 = exact8.evaluate_a1(replay, state)
    a2 = exact8.evaluate_a2(a1, replay, state)
    a3 = exact8.evaluate_a3(a2, replay)

    a1_pass = a1.get("state") == "PASS_EXACT8_A1_CAUSAL_READY_FOR_A2"
    a2_pass = a2.get("state") == "PASS_A2_COST_TURNOVER"
    a3_pass = a3.get("state") == "PASS_A3_GLOBAL_DURABILITY"
    receipt = {
        "schema_version": "zel.a1_research_factory_exact8_alpha_bridge.v1",
        "state": "PASS_RESEARCH_FACTORY_REPAIR_ROUTED_TO_A3" if a3_pass else "PASS_RESEARCH_FACTORY_REPAIR_ROUTED_TO_BOUNDED_REPLAY",
        "research_factory_state": factory.get("state"),
        "candidate_id": candidate.get("candidate_id"),
        "strategy_id": EXPECTED_PARENT,
        "child_id": EXPECTED_CHILD,
        "changed_axis": EXPECTED_AXIS,
        "source_gate": candidate.get("source_gate"),
        "required_sources": candidate.get("required_sources"),
        "evidence_ids": candidate.get("evidence_ids"),
        "independent_passes": candidate.get("independent_passes"),
        "independent_rejects": candidate.get("independent_rejects"),
        "identity_lock": {
            "research_candidate_matches_existing_frozen_adapter": True,
            "ai_prose_translated_into_thresholds": False,
            "new_strategy_logic_created": False,
            "threshold_search": False,
            "holdout_outcomes_accessed": False,
            "synthetic_market_evidence_used": False,
            "parent_pass_inherited": False,
        },
        "bounded_replay": {
            "completed_child_trades": len(replay.get("child_trades") or []),
            "parent_opportunities": len(replay.get("parent_opportunities") or []),
            "integrity_defects": replay.get("integrity_defects") or [],
        },
        "a1_state": a1.get("state"),
        "a2_state": a2.get("state"),
        "a3_state": a3.get("state"),
        "a1_pass": a1_pass,
        "a2_pass": a2_pass,
        "a3_pass": a3_pass,
        "alpha_proof_handoff": "READY_EXISTING_BOUNDED_REPLAY_ALPHA_PATH" if a1_pass else "BLOCKED_UNTIL_PASS_EXACT8_A1_CAUSAL",
        "a1": a1,
        "a2": a2,
        "a3": a3,
        **AUTH,
    }
    receipt["receipt_sha256"] = exact8.stable_sha({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    return receipt


def self_test() -> int:
    spec = read(EXACT8_SPEC)
    row = spec["specs"][EXPECTED_PARENT]
    assert row["child_id"] == EXPECTED_CHILD
    assert row["changed_axis"] == EXPECTED_AXIS
    fixture = {
        "state": "PASS_RESEARCH_FACTORY_V5_REVIEWED_REPAIR_READY",
        "experiment_queue": [{
            "candidate_id": "range_fade_repair_1",
            "strategy_id": EXPECTED_PARENT,
            "changed_axis": EXPECTED_AXIS,
            "mode": "REPAIR",
            "source_gate": "READY_COMMON",
            "required_sources": ["ohlcv", "volume"],
            "eligible_for_experiment_queue": True,
            "independent_passes": 2,
            "independent_rejects": 0,
        }],
    }
    selected = select_reviewed_repair(fixture, spec)
    assert selected["candidate_id"] == "range_fade_repair_1"
    bad = json.loads(json.dumps(fixture))
    bad["experiment_queue"][0]["changed_axis"] = "OTHER_AXIS"
    try:
        select_reviewed_repair(bad, spec)
    except RuntimeError:
        pass
    else:
        raise AssertionError("IDENTITY_MISMATCH_MUST_FAIL_CLOSED")
    print("PASS_RESEARCH_FACTORY_EXACT8_ALPHA_BRIDGE_V1_SELF_TEST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factory", type=Path, default=RESEARCH_FACTORY_LATEST)
    parser.add_argument("--state", type=Path, default=FORWARD_STATE)
    parser.add_argument("--spec", type=Path, default=EXACT8_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    receipt = build_receipt(read(args.factory), read(args.state), read(args.spec))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "candidate_id": receipt["candidate_id"],
        "child_id": receipt["child_id"],
        "completed_child_trades": receipt["bounded_replay"]["completed_child_trades"],
        "a1_state": receipt["a1_state"],
        "a2_state": receipt["a2_state"],
        "a3_state": receipt["a3_state"],
        "alpha_proof_handoff": receipt["alpha_proof_handoff"],
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
