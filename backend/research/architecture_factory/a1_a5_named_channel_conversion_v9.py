#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_a5_economic_improvement_v8 as v8
from backend.research.architecture_factory import a1_a5_economic_improvement_v7 as v7
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

SCHEMA = "zel.a1_a5_named_channel_conversion.v9"


def _strict_named_wrap_attempt(original_factory):
    def factory(original):
        base = original_factory(original)

        def wrapped(provider, prompt, source_ids, axes, readiness):
            effective: dict[str, list[dict[str, Any]]] = {}
            enforced: dict[str, str] = {}
            for sid, raw_rows in axes.items():
                rows = [dict(x) for x in raw_rows if isinstance(x, Mapping)]
                named = [x for x in rows if x.get("named_channel_executable_bridge") is True]
                # TrendRider keeps its frozen original-fresh priority until that lane is exhausted.
                original_fresh_pending = sid == "trend_rider" and any(
                    x.get("origin") == v7.TREND_ORIGIN and x.get("named_channel_executable_bridge") is not True
                    for x in rows
                )
                if named and not original_fresh_pending:
                    chosen = dict(named[0])
                    effective[str(sid)] = [chosen]
                    enforced[str(sid)] = str(chosen.get("axis") or "")
                else:
                    effective[str(sid)] = rows

            rows, meta = base(provider, prompt, source_ids, effective, readiness)
            kept: list[dict[str, Any]] = []
            dropped = 0
            for row in rows:
                sid = str(row.get("strategy_id") or "")
                expected = enforced.get(sid)
                if expected and str(row.get("changed_axis") or "") != expected:
                    dropped += 1
                    continue
                kept.append(row)
            m = dict(meta)
            m["named_channel_strict_enforced_strategy_ids"] = sorted(enforced)
            m["named_channel_strict_expected_axes"] = dict(sorted(enforced.items()))
            m["named_channel_strict_wrong_axis_dropped"] = dropped
            m["candidate_count_after_named_strict_guard"] = len(kept)
            if enforced and not any(str(x.get("strategy_id") or "") in enforced for x in kept):
                m["successful"] = False
            return kept, m

        return wrapped
    return factory


def run(output: Path) -> dict[str, Any]:
    old = v7._wrap_attempt
    try:
        v7._wrap_attempt = _strict_named_wrap_attempt(old)
        result = dict(v8.run(output))
    finally:
        v7._wrap_attempt = old

    bridge = result.get("named_channel_executable_bridge") or {}
    eligible = int(bridge.get("eligible_axis_count") or 0)
    attempted = int(bridge.get("attempted_named_axis_count") or 0)
    by_strategy = bridge.get("eligible_axis_count_by_strategy") or {}
    nontrend_eligible = sum(int(v or 0) for k, v in by_strategy.items() if str(k) != "trend_rider")
    guard_state = "PASS_NAMED_CHANNEL_CONVERSION_NONZERO" if attempted > 0 else "FAIL_NAMED_CHANNEL_CONVERSION_ZERO_ATTEMPT"
    result["named_channel_conversion_guard"] = {
        "state": guard_state,
        "eligible_axis_count": eligible,
        "nontrend_eligible_axis_count": nontrend_eligible,
        "attempted_named_axis_count": attempted,
        "attempted_named_axes_by_strategy": bridge.get("attempted_named_axes_by_strategy") or {},
        "zero_attempt_allowed": False if nontrend_eligible > 0 else True,
        "policy": "ELIGIBLE_NAMED_CHANNEL_AXIS_MUST_REACH_EXECUTABLE_ECONOMIC_REPLAY;TREND_RIDER_ORIGINAL_FRESH_PRIORITY_PRESERVED",
    }
    result["schema_version"] = SCHEMA
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    def fake(provider, prompt, source_ids, axes, readiness):
        rows = []
        for sid, specs in axes.items():
            if specs:
                rows.append({"strategy_id": sid, "changed_axis": specs[0]["axis"], "evidence_ids": specs[0].get("external_evidence_ids", [])})
        return rows, {"successful": True}

    factory = _strict_named_wrap_attempt(lambda original: original)
    wrapped = factory(fake)
    axes = {
        "supertrend_pullback": [
            {"axis": "OLD", "priority": 1},
            {"axis": "YTNAMED_ENTRY_TEST", "named_channel_executable_bridge": True, "external_evidence_ids": ["YTNAMED:x"]},
        ],
        "trend_rider": [
            {"axis": "ORIGINAL_FRESH", "origin": v7.TREND_ORIGIN},
            {"axis": "YTNAMED_ENTRY_TR", "origin": v7.TREND_ORIGIN, "named_channel_executable_bridge": True, "external_evidence_ids": ["YTNAMED:y"]},
        ],
    }
    rows, meta = wrapped("openai", "x", {"YTNAMED:x", "YTNAMED:y"}, axes, {})
    got = {(x["strategy_id"], x["changed_axis"]) for x in rows}
    assert ("supertrend_pullback", "YTNAMED_ENTRY_TEST") in got, got
    assert ("trend_rider", "ORIGINAL_FRESH") in got, got
    assert meta["named_channel_strict_expected_axes"]["supertrend_pullback"] == "YTNAMED_ENTRY_TEST"
    assert "trend_rider" not in meta["named_channel_strict_expected_axes"]
    assert v7.v3.AUTH["execution_authority"] == "NONE" and v7.v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_A5_NAMED_CHANNEL_CONVERSION_V9_SELF_TEST")
    print("PASS_ELIGIBLE_NAMED_CHANNEL_AXIS_CANNOT_SILENTLY_FALL_BACK_TO_OLD_AXIS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_named_channel_conversion_v9.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    b = r.get("named_channel_executable_bridge") or {}
    g = r.get("named_channel_conversion_guard") or {}
    print(json.dumps({
        "state": r.get("state"),
        "conversion_guard": g.get("state"),
        "yt_eligible": b.get("eligible_axis_count"),
        "yt_attempted": b.get("attempted_named_axis_count"),
        "yt_by_strategy": b.get("attempted_named_axes_by_strategy"),
        "development_pass": r.get("development_economic_pass_count"),
        "risk_pass": (r.get("named_channel_risk_sizing_evaluator") or {}).get("economic_pass_count"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
