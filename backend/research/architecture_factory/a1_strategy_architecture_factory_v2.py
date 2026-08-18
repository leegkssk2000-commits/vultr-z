#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import run as run_v1, sha

NATIVE_SOURCES = {"ohlcv", "volume", "funding", "basis", "open_interest", "l2_order_book", "trade_flow"}


def corrected_score(c: Mapping[str, Any]) -> float:
    passes = int(c.get("independent_passes") or 0)
    rejects = int(c.get("independent_rejects") or 0)
    evidence_count = len(c.get("evidence_ids") or [])
    required = [str(x) for x in (c.get("required_sources") or [])]
    source_ready = bool(required) and set(required).issubset(NATIVE_SOURCES)
    weak_design_prior = min(max(float(c.get("expected_move_cost_multiple_target") or 0.0) - 1.0, 0.0), 3.0) * 0.25
    score = passes * 3.0 - rejects * 5.0
    score += min(evidence_count, 4) * 0.75
    score += 1.5 if c.get("mode") == "NEW_ARCHITECTURE" else 0.75
    score += 0.75 if source_ready else -3.0
    score += weak_design_prior
    return round(score, 4)


def harden_candidate(c: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(c)
    required = [str(x) for x in (row.get("required_sources") or [])]
    source_ready = bool(required) and set(required).issubset(NATIVE_SOURCES)
    passes = int(row.get("independent_passes") or 0)
    rejects = int(row.get("independent_rejects") or 0)
    row["source_ready"] = source_ready
    row["score"] = corrected_score(row)
    row["alpha_proof_candidate_ready"] = source_ready and passes >= 2 and rejects == 0
    row["alpha_proof_state"] = "REQUIRED_NOT_RUN"
    row["alpha_proof_receipt_sha256"] = None
    row["eligible_for_preregistration"] = False
    row["preregistration_blocker"] = "PASS_ALPHA_PROOF_RECEIPT_REQUIRED"
    row["ranking_economic_feasibility"] = "UNMEASURED_ALPHA_PROOF_REQUIRED"
    row["design_cost_multiple_is_weak_prior_only"] = True
    return row


def run(output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="a1-factory-v2-") as td:
        tmp = Path(td) / "v1.json"
        base = run_v1(tmp)
    reviewed = [harden_candidate(x) for x in (base.get("all_reviewed_candidates") or [])]
    reviewed.sort(key=lambda x: (-float(x.get("score") or 0.0), str(x.get("candidate_id") or "")))
    top3 = reviewed[:3]
    result = dict(base)
    result["schema_version"] = "zel.a1_strategy_architecture_factory.v2"
    result["all_reviewed_candidates"] = reviewed
    result["top3"] = top3
    result["alpha_proof_required"] = True
    result["preregistration_requires_state"] = "PASS_ALPHA_PROOF_READY_FOR_FRESH_PROSPECTIVE"
    result["preregistration_blocked_without_receipt"] = True
    result["alpha_proof_ready_count"] = sum(1 for x in reviewed if x.get("alpha_proof_candidate_ready"))
    result["eligible_for_preregistration_count"] = 0
    result["state"] = (
        "PASS_ARCHITECTURE_FACTORY_TOP3_READY_FOR_ALPHA_PROOF"
        if any(x.get("alpha_proof_candidate_ready") for x in top3)
        else "HOLD_ARCHITECTURE_FACTORY_NO_ALPHA_PROOF_CANDIDATE"
    )
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = {
        "candidate_id": "x", "mode": "NEW_ARCHITECTURE", "required_sources": ["ohlcv", "basis"],
        "evidence_ids": ["P1", "P2"], "expected_move_cost_multiple_target": 4.0,
        "independent_passes": 2, "independent_rejects": 0,
    }
    h = harden_candidate(c)
    assert h["alpha_proof_candidate_ready"] is True
    assert h["eligible_for_preregistration"] is False
    assert h["preregistration_blocker"] == "PASS_ALPHA_PROOF_RECEIPT_REQUIRED"
    c2 = dict(c); c2["independent_rejects"] = 1
    assert harden_candidate(c2)["alpha_proof_candidate_ready"] is False
    print("PASS_A1_STRATEGY_ARCHITECTURE_FACTORY_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_strategy_architecture_factory_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r["state"],
        "generated_after_dedup": r.get("generated_after_dedup"),
        "alpha_proof_ready_count": r["alpha_proof_ready_count"],
        "eligible_for_preregistration_count": r["eligible_for_preregistration_count"],
        "top3": [{"id": x.get("candidate_id"), "mode": x.get("mode"), "family": x.get("architecture_family"), "score": x.get("score"), "alpha_proof_ready": x.get("alpha_proof_candidate_ready"), "prereg_eligible": x.get("eligible_for_preregistration")} for x in r.get("top3") or []],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
