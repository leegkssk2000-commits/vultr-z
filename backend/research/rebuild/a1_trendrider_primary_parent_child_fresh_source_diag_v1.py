#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as loss_diag
from backend.research.rebuild import a1_trend_rider_transition_freshness_frozen_w123_ab_v1 as tr_ab

SCHEMA = "zel.a1.trendrider_primary.parent_child_fresh_source_diag.v1"
BOUNDARY_TS_MS = 1787937985000  # 2026-08-28T17:26:25Z, preregistered CHASE_ATR root-cause boundary
BOUNDARY_UTC = "2026-08-28T17:26:25Z"
AXIS = "SOURCE_OWNER_BEFORE_CHASE_ATR_ONLY"


def _identity(row: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(row.get("symbol") or ""),
        int(row.get("signal_ts") or 0),
        int(row.get("entry_ts") or 0),
        str(row.get("side") or ""),
    )


def _postboundary_closed(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [
        dict(x)
        for x in (receipt.get("trades") or [])
        if isinstance(x, Mapping)
        and int(x.get("signal_ts") or 0) > BOUNDARY_TS_MS
        and int(x.get("exit_ts") or 0) > 0
    ]
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in rows:
        dedup[_identity(row)] = row
    return sorted(dedup.values(), key=lambda x: _identity(x))


def _enrich_preentry(receipt: Mapping[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if rows:
        # Reuse the already-frozen signal-time feature geometry. This reads no
        # exit outcome to decide whether a row is chase-cooling.
        loss_diag._trend_enrichment(receipt, rows)
    return rows


def _quality(receipt: Mapping[str, Any]) -> dict[str, Any]:
    source_gate = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), Mapping) else {}
    return {
        "source_quality_state": source_gate.get("state"),
        "integrity_defects": list(receipt.get("integrity_defects") or []),
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
    }


def _classify(parent_post: int, child_post: int, parent_cooling: int, child_cooling: int, missing_cooling: int) -> tuple[str, str]:
    if parent_post == 0:
        return "WAIT_GENUINE_PRIMARY_PARENT_POSTBOUNDARY_T", "KEEP_CHASE_CHILD_FROZEN;WAIT_FOR_GENUINE_PARENT_FRESH_T"
    if parent_cooling == 0:
        return "WAIT_GENUINE_PRIMARY_PARENT_CHASE_COOLING_T", "KEEP_CHASE_CHILD_FROZEN;NO_ELIGIBLE_PARENT_CHASE_COOLING_T_YET"
    if missing_cooling > 0:
        return "PRIMARY_CHASE_FRESH_SOURCE_PREEMPTED_BY_TRANSITION_CHILD", "PREREGISTER_CANONICAL_PARENT_SOURCE_REPAIR_WITH_NEW_BOUNDARY;DO_NOT_BACKFILL_EXISTING_PARENT_ONLY_TRADES"
    if child_post == 0:
        return "HOLD_PARENT_CHILD_SOURCE_COMPARISON_INCONSISTENT", "NO_CHANGE;INVESTIGATE_IDENTITY_OR_ENRICHMENT"
    if child_cooling > 0:
        return "NO_PRIMARY_CHASE_SOURCE_PREEMPTION", "KEEP_EXISTING_SOURCE;ALLOW_CURRENT_CHASE_EVALUATOR_TO_PROCESS_GENUINE_COOLING_T"
    return "WAIT_GENUINE_CHILD_CHASE_COOLING_T", "KEEP_EXISTING_SOURCE;WAIT_FOR_GENUINE_COOLING_T"


def run(out: Path) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    parent_out = out.parent / "trend_rider_canonical_parent_current.json"
    child_out = out.parent / "trend_rider_transition_child_current.json"

    cache: dict[str, dict[str, Any]] = {}
    original_fetch = tr_ab.exact.v1.fetch_execution_snapshot

    def cached_fetch(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
        if symbol not in cache:
            cache[symbol] = copy.deepcopy(original_fetch(symbol, authority))
        return copy.deepcopy(cache[symbol])

    try:
        tr_ab.exact.v1.fetch_execution_snapshot = cached_fetch
        parent = tr_ab._run_exact(parent_out, child=False)
        child = tr_ab._run_exact(child_out, child=True)
    finally:
        tr_ab.exact.v1.fetch_execution_snapshot = original_fetch

    pq, cq = _quality(parent), _quality(child)
    integrity = {
        "same_source": parent.get("source") == child.get("source"),
        "same_config_sha": parent.get("config_sha") == child.get("config_sha"),
        "same_execution_snapshots": parent.get("execution_snapshots") == child.get("execution_snapshots"),
        "same_cost_authority_sha256": parent.get("cost_authority_sha256") == child.get("cost_authority_sha256"),
        "parent_policy_is_canonical": str(parent.get("policy_path") or "") == "backend/research/rebuild/trend_policy_batch_v1.py",
        "child_policy_is_transition_freshness_only": str(child.get("policy_path") or "") == str(tr_ab.CHILD_POLICY.relative_to(tr_ab.ROOT)),
        "parent_source_quality_pass": pq["source_quality_state"] == "PASS",
        "child_source_quality_pass": cq["source_quality_state"] == "PASS",
        "parent_integrity_defects_empty": pq["integrity_defects"] == [],
        "child_integrity_defects_empty": cq["integrity_defects"] == [],
        "parent_leakage_zero": pq["leakage_lookahead"] == 0,
        "child_leakage_zero": cq["leakage_lookahead"] == 0,
    }
    integrity_ok = all(bool(v) for v in integrity.values())

    parent_rows = _enrich_preentry(parent, _postboundary_closed(parent))
    child_rows = _enrich_preentry(child, _postboundary_closed(child))
    parent_ids = {_identity(x) for x in parent_rows}
    child_ids = {_identity(x) for x in child_rows}
    parent_cooling_ids = {_identity(x) for x in parent_rows if x.get("chase_cooling_or_flat") is True}
    child_cooling_ids = {_identity(x) for x in child_rows if x.get("chase_cooling_or_flat") is True}
    missing_cooling = parent_cooling_ids - child_cooling_ids

    if not integrity_ok:
        state = "HOLD_PARENT_CHILD_FRESH_SOURCE_INTEGRITY"
        next_step = "NO_CHANGE;FIX_READ_ONLY_COMPARISON_INTEGRITY_FIRST"
    else:
        state, next_step = _classify(
            len(parent_rows), len(child_rows), len(parent_cooling_ids), len(child_cooling_ids), len(missing_cooling)
        )

    def compact(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "symbol": str(row.get("symbol") or ""),
            "side": str(row.get("side") or ""),
            "signal_ts": int(row.get("signal_ts") or 0),
            "entry_ts": int(row.get("entry_ts") or 0),
            "exit_ts": int(row.get("exit_ts") or 0),
            "chase_atr": row.get("chase_atr"),
            "prior_chase_atr": row.get("prior_chase_atr"),
            "chase_cooling_or_flat": row.get("chase_cooling_or_flat"),
        }

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "strategy_id": "trend_rider",
        "lane": "PRIMARY_STRICT25_FRESH_PLUS1",
        "changed_axis": AXIS,
        "root_cause_boundary_utc": BOUNDARY_UTC,
        "root_cause_boundary_ts_ms": BOUNDARY_TS_MS,
        "diagnostic_role": "READ_ONLY_SOURCE_OWNER_ATTRIBUTION_BEFORE_CHASE_FILTER",
        "outcome_metrics_read_for_source_decision": False,
        "numeric_threshold_sweep": False,
        "policy_retune": False,
        "old_history_union": False,
        "retroactive_promotion_forbidden": True,
        "existing_parent_only_trades_promotion_eligible_after_source_repair": False,
        "integrity": integrity,
        "parent_quality": pq,
        "child_quality": cq,
        "counts": {
            "canonical_parent_total_completed_T": len(parent.get("trades") or []),
            "transition_child_total_completed_T": len(child.get("trades") or []),
            "canonical_parent_postboundary_closed_T": len(parent_rows),
            "transition_child_postboundary_closed_T": len(child_rows),
            "parent_only_postboundary_closed_T": len(parent_ids - child_ids),
            "child_only_postboundary_closed_T": len(child_ids - parent_ids),
            "canonical_parent_postboundary_chase_cooling_T": len(parent_cooling_ids),
            "transition_child_postboundary_chase_cooling_T": len(child_cooling_ids),
            "parent_chase_cooling_preempted_before_chase_T": len(missing_cooling),
        },
        "parent_postboundary_rows_preentry_only": [compact(x) for x in parent_rows],
        "child_postboundary_rows_preentry_only": [compact(x) for x in child_rows],
        "parent_only_chase_cooling_identities": [list(x) for x in sorted(missing_cooling)],
        "source_owner_preemption_for_chase_confirmed": bool(integrity_ok and missing_cooling),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": next_step,
    }
    result["receipt_sha256"] = loss_diag.sha(result)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert BOUNDARY_TS_MS == 1787937985000
    assert _classify(0, 0, 0, 0, 0)[0] == "WAIT_GENUINE_PRIMARY_PARENT_POSTBOUNDARY_T"
    assert _classify(2, 0, 1, 0, 1)[0] == "PRIMARY_CHASE_FRESH_SOURCE_PREEMPTED_BY_TRANSITION_CHILD"
    assert _classify(2, 1, 0, 0, 0)[0] == "WAIT_GENUINE_PRIMARY_PARENT_CHASE_COOLING_T"
    assert _classify(2, 2, 1, 1, 0)[0] == "NO_PRIMARY_CHASE_SOURCE_PREEMPTION"
    print("PASS_A1_TRENDRIDER_PRIMARY_PARENT_CHILD_FRESH_SOURCE_DIAG_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_primary_parent_child_fresh_source_diag_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "counts": r["counts"],
        "preemption": r["source_owner_preemption_for_chase_confirmed"],
        "next": r["next"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
