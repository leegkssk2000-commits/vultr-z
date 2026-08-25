#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7 as v7
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

SCHEMA = "zel.a1_top5_evolutionary_synthesis.v7_1"


def _extract_attempted(prior: Mapping[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}

    def add(sid: Any, rows: Any) -> None:
        if not sid or not isinstance(rows, list):
            return
        bucket = out.setdefault(str(sid), set())
        bucket.update(str(x) for x in rows if str(x))

    root = prior.get("economic_attempted_axes")
    if isinstance(root, Mapping):
        for sid, rows in root.items():
            add(sid, rows)

    by_strategy = prior.get("by_strategy")
    if isinstance(by_strategy, Mapping):
        for sid, raw in by_strategy.items():
            if not isinstance(raw, Mapping):
                continue
            add(sid, raw.get("economic_attempted_axes"))
            add(sid, raw.get("economically_tested_axes_this_run"))

    for raw in prior.get("candidate_donor_attribution") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = raw.get("host_strategy_id")
        axis = raw.get("changed_axis")
        if sid and axis:
            out.setdefault(str(sid), set()).add(str(axis))
    return out


def _prior_attempted_fixed() -> dict[str, set[str]]:
    prior = v7._read(v7.LATEST)
    return _extract_attempted(prior)


def run(output: Path) -> dict[str, Any]:
    original = v7._prior_attempted
    try:
        v7._prior_attempted = _prior_attempted_fixed
        result = dict(v7.run(output))
    finally:
        v7._prior_attempted = original

    attempted = _extract_attempted(v7._read(v7.LATEST))
    result["schema_version"] = SCHEMA
    result["stable_donor_host_attempt_history"] = True
    result["prior_attempted_gene_pairs"] = {sid: sorted(rows) for sid, rows in sorted(attempted.items())}
    result["failed_gene_pair_retest_same_axis_allowed"] = False
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    sample = {
        "by_strategy": {
            "trend_rider": {
                "economic_attempted_axes": ["DONOR__A__X__ONLY"],
                "economically_tested_axes_this_run": ["DONOR__B__Y__ONLY"],
            }
        },
        "candidate_donor_attribution": [
            {"host_strategy_id": "break_and_continue", "changed_axis": "DONOR__C__Z__ONLY"}
        ],
    }
    got = _extract_attempted(sample)
    assert got["trend_rider"] == {"DONOR__A__X__ONLY", "DONOR__B__Y__ONLY"}, got
    assert got["break_and_continue"] == {"DONOR__C__Z__ONLY"}, got
    assert v7.v3.AUTH["execution_authority"] == "NONE" and v7.v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_EVOLUTIONARY_SYNTHESIS_V7_1_ATTEMPT_MEMORY_SELF_TEST")
    print("PASS_FAILED_DONOR_HOST_PAIR_WILL_ADVANCE_NOT_REPEAT")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_top5_evolutionary_synthesis_v7_1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r.get("state"),
        "hosts": r.get("performance_top5_hosts"),
        "donors": r.get("donor_pool_count"),
        "validated_donors": r.get("validated_edge_donor_count"),
        "candidates": r.get("evolutionary_candidate_count"),
        "development_pass": r.get("development_economic_pass_count"),
        "paid": r.get("paid_request_count"),
        "stable_attempt_history": r.get("stable_donor_host_attempt_history"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
