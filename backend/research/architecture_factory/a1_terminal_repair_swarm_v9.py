#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil
from backend.research.architecture_factory import a1_terminal_repair_swarm_v8 as v8

ROOT = Path(__file__).resolve().parents[3]
V7_RECEIPT = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v7_latest.json"
V8_RECEIPT = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v8_latest.json"
V7_FROZEN_AT = "2026-08-29T20:06:28Z"
V7_FROZEN_AT_MS = int(datetime.fromisoformat(V7_FROZEN_AT.replace("Z", "+00:00")).timestamp() * 1000)
V7_FREEZE_COMMIT = "3c746da48b304cd24a99b47f52c0f325325d6fe8"
V7_RECEIPT_SHA256 = "eb1e16e32e954cb187bfe09c48936dd42d1d24750b1384ed44ce998cee49c15e"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _v7_candidates(v7: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Mapping[str, Any]]]:
    dev = v7.get("development_economics") if isinstance(v7.get("development_economics"), Mapping) else {}
    passed_ids = {str(x.get("candidate_id")) for x in (dev.get("passes") or []) if isinstance(x, Mapping)}
    candidates = [dict(x) for x in (v7.get("ai_candidates") or []) if isinstance(x, Mapping) and str(x.get("candidate_id")) in passed_ids]
    dev_by_id = {str(x.get("candidate_id")): x for x in (dev.get("rows") or []) if isinstance(x, Mapping)}
    return candidates, dev_by_id


def _forward_rows(candidates: list[dict[str, Any]], now_ms: int) -> list[dict[str, Any]]:
    original_boundary = v8.BOUNDARY_MS
    try:
        v8.BOUNDARY_MS = V7_FROZEN_AT_MS
        rows = [v8._evaluate(candidate, now_ms) for candidate in candidates]
    finally:
        v8.BOUNDARY_MS = original_boundary
    for row in rows:
        row["boundary"] = V7_FROZEN_AT
        row["data_scope"] = "TRUE_FORWARD_AFTER_V7_CANDIDATE_FREEZE_CLOSED_BARS_ONLY_WITH_PREFREEZE_WARMUP"
        row["prospective"] = True
        row["temporal_holdout"] = False
        if isinstance(row.get("metrics"), dict):
            row["metrics"]["prospective_elapsed_days"] = max(1e-9, (now_ms - V7_FROZEN_AT_MS) / 86_400_000.0)
    return rows


def _legacy_holdout(v8_receipt: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for raw in v8_receipt.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        row["prospective"] = False
        row["temporal_holdout"] = True
        row["data_scope"] = "TEMPORAL_HOLDOUT_AFTER_GEN1_BOUNDARY_BUT_BEFORE_V7_CANDIDATE_FREEZE"
        rows.append(row)
    return {
        "state": "TEMPORAL_HOLDOUT_INFORMATIONAL_ONLY",
        "boundary": v8_receipt.get("boundary"),
        "candidate_freeze_at": V7_FROZEN_AT,
        "economic_summary": v8_receipt.get("economic_summary") or [],
        "rows": rows,
        "note": "V8 outcomes predate V7 candidate freeze; they are temporal holdout evidence because V7 inputs were pre-GEN1-boundary, but they are not strict forward-prospective evidence.",
    }


def run(output: Path, now_ms: int | None = None) -> dict[str, Any]:
    v7 = _read(V7_RECEIPT)
    v8_receipt = _read(V8_RECEIPT)
    if v7.get("receipt_sha256") != V7_RECEIPT_SHA256:
        raise RuntimeError("V7_RECEIPT_FREEZE_SHA_MISMATCH")
    if v7.get("schema_version") != "zel.a1_terminal_repair_swarm.v7":
        raise RuntimeError("V7_SCHEMA_INVALID")
    candidates, dev_by_id = _v7_candidates(v7)
    if len(candidates) != 4:
        raise RuntimeError(f"V7_FROZEN_CANDIDATE_COUNT_INVALID:{len(candidates)}")
    now_ms = int(now_ms or time.time() * 1000)
    forward = _forward_rows(candidates, now_ms)
    compact = [v8._compact(row, dev_by_id) for row in forward]
    pass_count = sum(1 for x in forward if x.get("state") == "OOS_PASS_EARLY")
    fail_count = sum(1 for x in forward if x.get("state") == "OOS_FAIL_ECONOMICS")
    wait_count = sum(1 for x in forward if x.get("state") == "WAIT_NEW_T")
    reject_count = sum(1 for x in forward if str(x.get("state") or "").startswith("REJECT_"))
    result = {
        "schema_version": "zel.a1_terminal_repair_swarm.v9",
        "objective": "SEPARATE_TEMPORAL_HOLDOUT_FROM_TRUE_FORWARD_PROSPECTIVE_ECONOMICS",
        "candidate_freeze_authority": {
            "v7_receipt_sha256": V7_RECEIPT_SHA256,
            "v7_receipt_commit": V7_FREEZE_COMMIT,
            "candidate_frozen_at": V7_FROZEN_AT,
            "candidate_count": len(candidates),
            "selection_after_freeze": False,
            "retuning_after_freeze": False,
        },
        "temporal_holdout": _legacy_holdout(v8_receipt),
        "forward_prospective": {
            "boundary": V7_FROZEN_AT,
            "evaluated_at": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "candidate_count": len(forward),
            "minimum_events": v8.MIN_OOS_EVENTS,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "wait_new_t_count": wait_count,
            "reject_count": reject_count,
            "economic_summary": compact,
            "rows": forward,
            "next": "REVIEW_FORWARD_PASS_FOR_ALPHA_PROOF_GATE" if pass_count > 0 else ("FALSIFY_FORWARD_FAILED_ARCHITECTURES" if fail_count > 0 else "WAIT_TRUE_FORWARD_CLOSED_T"),
        },
        "truth_correction": {
            "v8_post_gen1_boundary_is_temporal_oos": True,
            "v8_post_gen1_boundary_is_strict_forward_prospective": False,
            "strict_forward_begins_at_v7_candidate_freeze": V7_FROZEN_AT,
            "promotion_from_temporal_holdout_alone_forbidden": True,
        },
        "cost_bps_per_trade": v8.COST_BPS,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert V7_FROZEN_AT_MS > v8.BOUNDARY_MS
    assert v8.MIN_OOS_EVENTS == 12
    assert v8.COST_BPS == 14.0
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V9_FREEZE_CORRECT_FORWARD_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_terminal_repair_swarm_v9_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    f = r["forward_prospective"]
    print(json.dumps({
        "freeze": r["candidate_freeze_authority"],
        "forward_pass": f["pass_count"],
        "forward_fail": f["fail_count"],
        "forward_wait": f["wait_new_t_count"],
        "forward_reject": f["reject_count"],
        "forward_summary": f["economic_summary"],
        "next": f["next"],
        "receipt": r["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
