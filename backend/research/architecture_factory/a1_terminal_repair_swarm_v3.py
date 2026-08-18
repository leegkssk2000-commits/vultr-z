#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_terminal_repair_swarm_v2 import run as run_v2, sha
from backend.research.architecture_factory.a1_strategy_architecture_factory_v2 import corrected_score

NATIVE_SOURCES = {"ohlcv", "volume", "funding", "basis", "open_interest", "l2_order_book", "trade_flow"}


def harden(c: Mapping[str, Any]) -> dict[str, Any]:
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
    row["design_cost_multiple_is_weak_prior_only"] = True
    return row


def run(output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="a1-terminal-v3-") as td:
        tmp = Path(td) / "v2.json"
        base = run_v2(tmp)
    hardened = [harden(x) for x in (base.get("global_queue") or [])]
    hardened.sort(key=lambda x: (-float(x.get("score") or 0.0), str(x.get("candidate_id") or "")))
    lookup = {str(x.get("candidate_id")): x for x in hardened}
    strategies: dict[str, Any] = {}
    for sid, raw in (base.get("strategies") or {}).items():
        entry = dict(raw)
        entry["repair_top3"] = [lookup.get(str(x.get("candidate_id")), harden(x)) for x in (raw.get("repair_top3") or [])]
        entry["new_architecture"] = [lookup.get(str(x.get("candidate_id")), harden(x)) for x in (raw.get("new_architecture") or [])]
        strategies[sid] = entry
    result = dict(base)
    result["schema_version"] = "zel.a1_terminal_repair_swarm.v3"
    result["strategies"] = strategies
    result["global_queue"] = hardened
    result["alpha_proof_required"] = True
    result["preregistration_requires_state"] = "PASS_ALPHA_PROOF_READY_FOR_FRESH_PROSPECTIVE"
    result["preregistration_blocked_without_receipt"] = True
    result["alpha_proof_ready_count"] = sum(1 for x in hardened if x.get("alpha_proof_candidate_ready"))
    result["eligible_count"] = 0
    result["launch"] = {
        "state": "BLOCKED_UNTIL_PASS_ALPHA_PROOF_RECEIPT",
        "candidate": None,
        "reason": "Terminal repair/new-architecture candidates may be generated and reviewed in parallel, but no preregistration or heavy launch is allowed without a candidate-matched PASS_ALPHA_PROOF receipt.",
    }
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = {
        "candidate_id": "x", "mode": "REPAIR", "required_sources": ["ohlcv"],
        "evidence_ids": ["P1"], "expected_move_cost_multiple_target": 2.0,
        "independent_passes": 2, "independent_rejects": 0,
    }
    h = harden(c)
    assert h["alpha_proof_candidate_ready"] is True
    assert h["eligible_for_preregistration"] is False
    assert h["preregistration_blocker"] == "PASS_ALPHA_PROOF_RECEIPT_REQUIRED"
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_terminal_repair_swarm_v3.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "terminal_count": r.get("terminal_count"),
        "queued_repair_count": r.get("queued_repair_count"),
        "queued_new_arch_count": r.get("queued_new_arch_count"),
        "alpha_proof_ready_count": r.get("alpha_proof_ready_count"),
        "eligible_count": r.get("eligible_count"),
        "launch": r.get("launch"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
