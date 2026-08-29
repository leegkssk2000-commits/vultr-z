#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import rr_exit_fresh6_observer_v1 as v1
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr

SCHEMA = "zel.rr_exit.fresh6.observer.v2"


def _full_snapshots(rows: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    authority = rr.read(rr.COST)
    symbols = sorted({str(x["symbol"]) for x in rows})
    snaps = {s: dict(ev.fetch_execution_snapshot(s, authority)) for s in symbols}
    for symbol, snap in snaps.items():
        if not isinstance(snap.get("funding_rows"), list):
            raise RuntimeError(f"RR_FRESH6_FULL_FUNDING_ROWS_MISSING:{symbol}")
        for key in ("fee_bps", "spread_bps", "impact_bps"):
            if key not in snap:
                raise RuntimeError(f"RR_FRESH6_FULL_SNAPSHOT_FIELD_MISSING:{symbol}:{key}")
    return snaps


def run(out: Path) -> dict[str, Any]:
    original_simulate = rr.simulate

    def hydrated_simulate(
        rows: list[Mapping[str, Any]],
        tp_r: float,
        sl_r: float,
        bars_by: Mapping[str, list[Mapping[str, Any]]],
        snaps: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        # The generic policy receipt intentionally persists compact execution
        # snapshots and omits funding_rows. Rehydrate the exact simulator input
        # from the same frozen cost authority used by RR development. Do not
        # alter rows, TP/SL, boundary, or candidate selection.
        full = _full_snapshots([dict(x) for x in rows])
        return original_simulate(rows, tp_r, sl_r, bars_by, full)

    try:
        rr.simulate = hydrated_simulate
        result = v1.run(out)
    finally:
        rr.simulate = original_simulate

    result["schema_version"] = SCHEMA
    result["execution_snapshot_source"] = "a1_top5_fixed_rr_payoff_shadow_v1.COST + ev.fetch_execution_snapshot"
    result["compact_policy_receipt_snapshot_used_for_rr_simulation"] = False
    result["funding_rows_rehydrated_from_same_cost_authority"] = True
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.g5.stable(result)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    # Preserve all v1 gate semantics; this wrapper changes simulator input
    # completeness only.
    assert v1.REQUIRED_T == 6
    assert v1.EXPECTED_PREREG_RECEIPT == "7de8b088d67bfa0c1db5f4fe04955214e8f314157e75ed2f24932ad4fc13bba1"
    native = {"trades": 6, "win_rate": 0.5, "net_pnl_bps": 100.0, "net_expectancy_bps": 100/6,
              "profit_factor": 2.0, "payoff": 1.5, "drawdown_bps": 40.0}
    better = {"trades": 6, "win_rate": 0.5, "net_pnl_bps": 120.0, "net_expectancy_bps": 20.0,
              "profit_factor": 2.2, "payoff": 1.6, "drawdown_bps": 35.0}
    assert all(v1.strict_checks(native, better).values())
    print("PASS_RR_EXIT_FRESH6_OBSERVER_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/rr_exit_fresh6_observer_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "raw_T": r["raw_postboundary_closed_T"],
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
