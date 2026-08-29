#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as g5
from backend.research.prep import rr_exit_fresh6_observer_v1 as base
from backend.research.prep import rr_exit_fresh6_observer_v2 as hydrated
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr

SCHEMA = "zel.rr_exit.true_fresh6.observer.v1"
REQUIRED_T = 6
TRUE_BOUNDARY_UTC = hydrated.PREREG_FREEZE_UTC
TRUE_BOUNDARY_TS_MS = hydrated.PREREG_FREEZE_TS_MS
TRUE_BOUNDARY_COMMIT = hydrated.PREREG_FREEZE_COMMIT


def run(out: Path) -> dict[str, Any]:
    prereg = hydrated.v1.read(hydrated.v1.PREREG)
    seal = hydrated.v1.read(hydrated.v1.SEAL)
    g5.validate_seal(seal)
    tp_r, sl_r, development_boundary = base.verify_prereg(prereg)
    if TRUE_BOUNDARY_TS_MS <= development_boundary:
        raise RuntimeError("RR_TRUE_BOUNDARY_NOT_AFTER_DEVELOPMENT")

    receipt = g5.current_policy_replay(
        out_path=out.parent / "rr_true_fresh6_current_policy.json",
        boundary_utc=TRUE_BOUNDARY_UTC,
    )
    src = seal["source_authority"]
    if str(receipt.get("policy_sha")) != str(src["policy_sha"]):
        raise RuntimeError("RR_TRUE_FRESH6_POLICY_DRIFT")
    if str(receipt.get("config_sha")) != str(src["config_sha"]):
        raise RuntimeError("RR_TRUE_FRESH6_CONFIG_DRIFT")
    if list(receipt.get("integrity_defects") or []):
        raise RuntimeError("RR_TRUE_FRESH6_INTEGRITY_DEFECT")
    if int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("RR_TRUE_FRESH6_LOOKAHEAD_DEFECT")

    raw = sorted(
        [dict(x) for x in (receipt.get("trades") or [])
         if int(x.get("signal_ts") or 0) > TRUE_BOUNDARY_TS_MS
         and int(x.get("exit_ts") or 0) > TRUE_BOUNDARY_TS_MS],
        key=lambda x: (int(x.get("signal_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")),
    )
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in raw:
        dedup[g5.trade_key(row)] = row
    ordered = list(dedup.values())

    symbols = sorted({str(x["symbol"]) for x in ordered})
    bars_by = {s: [dict(x) for x in ev.fetch_bars(s, "1h", 1000)] for s in symbols}
    full_snaps = hydrated._full_snapshots(ordered) if ordered else {}
    simulated = rr.simulate(ordered, tp_r, sl_r, bars_by, full_snaps) if ordered else []
    if len(simulated) != len(ordered):
        raise RuntimeError("RR_TRUE_FRESH6_SIMULATION_PARITY")

    mature_prefix = 0
    for row in simulated:
        if not base.candidate_complete(row):
            break
        mature_prefix += 1

    validation_n = min(REQUIRED_T, mature_prefix)
    native_rows = ordered[:validation_n]
    candidate_rows = simulated[:validation_n]
    native_metrics = g5.metrics(native_rows)
    candidate_metrics = g5.metrics(candidate_rows)
    checks = base.strict_checks(native_metrics, candidate_metrics) if validation_n == REQUIRED_T else {}
    strict_pass = bool(checks) and all(checks.values())

    if validation_n < REQUIRED_T:
        state = "WAIT_RR_TRUE_PROSPECTIVE_FRESH6"
    elif strict_pass:
        state = "PASS_RR_TRUE_PROSPECTIVE_FRESH6"
    else:
        state = "HOLD_RR_TRUE_PROSPECTIVE_FRESH6_FAIL"

    rows_compact = []
    for nrow, crow in zip(native_rows, candidate_rows):
        rows_compact.append({
            "symbol": nrow.get("symbol"),
            "signal_ts": int(nrow.get("signal_ts") or 0),
            "side": nrow.get("side"),
            "native_net_bps": float(nrow.get("net_bps") or 0.0),
            "candidate_net_bps": float(crow.get("net_bps") or 0.0),
            "candidate_reason": crow.get("reason"),
            "candidate_exit_ts": int(crow.get("exit_ts") or 0),
        })

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "preregistered_receipt_sha256": base.EXPECTED_PREREG_RECEIPT,
        "preregister_freeze_commit": TRUE_BOUNDARY_COMMIT,
        "true_prospective_boundary_utc": TRUE_BOUNDARY_UTC,
        "true_prospective_boundary_ts_ms": TRUE_BOUNDARY_TS_MS,
        "development_max_exit_ts": development_boundary,
        "boundary_after_candidate_freeze": True,
        "frozen_tp_r": tp_r,
        "frozen_sl_r": sl_r,
        "frozen_nominal_rr": tp_r / sl_r,
        "required_fresh_T": REQUIRED_T,
        "raw_postfreeze_closed_T": len(ordered),
        "candidate_mature_prefix_T": mature_prefix,
        "validation_T": validation_n,
        "first_six_prefix_frozen": True,
        "skip_unresolved_prefix_trade_forbidden": True,
        "candidate_reoptimization_forbidden": True,
        "validation_used_to_select_candidate": False,
        "old_history_union": False,
        "pre_prereg_trade_use_for_true_proof": False,
        "native_control": native_metrics,
        "candidate": candidate_metrics,
        "strict_checks": checks,
        "strict_all_metric_pass": strict_pass,
        "validation_rows": rows_compact,
        "duplicate_count": len(raw) - len(dedup),
        "integrity_defects": list(receipt.get("integrity_defects") or []),
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
        "execution_snapshot_source": "a1_top5_fixed_rr_payoff_shadow_v1.COST + ev.fetch_execution_snapshot",
        "funding_rows_rehydrated_from_same_cost_authority": True,
        "true_prospective_proof_complete": strict_pass,
        "promotion_evidence_eligible": strict_pass,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": (
            "COLLECT_FIRST6_MATURE_POST_PREREG_PREFIX_NO_RETUNE" if state == "WAIT_RR_TRUE_PROSPECTIVE_FRESH6"
            else "SEAL_TRUE_PROSPECTIVE_RR_EVIDENCE_FOR_NEXT_GATE" if state == "PASS_RR_TRUE_PROSPECTIVE_FRESH6"
            else "REJECT_FROZEN_RR_KEEP_NATIVE_AND_ROUTE_NEXT_DISTINCT_EXIT_FAMILY"
        ),
    }
    result["receipt_sha256"] = g5.stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert TRUE_BOUNDARY_COMMIT == "c36f6d6c8abea0ec2657ad3b5fa6c7ef8a745f1c"
    assert TRUE_BOUNDARY_UTC == "2026-08-29T00:52:04Z"
    assert TRUE_BOUNDARY_TS_MS == 1787964724000
    assert TRUE_BOUNDARY_TS_MS > 1787310000000
    assert REQUIRED_T == 6
    print("PASS_RR_EXIT_TRUE_FRESH6_OBSERVER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/rr_exit_true_fresh6_observer_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "raw_T": r["raw_postfreeze_closed_T"],
        "mature_prefix_T": r["candidate_mature_prefix_T"],
        "validation_T": r["validation_T"],
        "native": r["native_control"],
        "candidate": r["candidate"],
        "checks": r["strict_checks"],
        "next": r["next"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
