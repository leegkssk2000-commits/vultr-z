#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as g5
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "backend/research/prep/rr_exit_robust_geometry_latest.json"
SEAL = ROOT / "backend/research/rebuild/a1_g4_trendrider_broad30_economic_survivor_v1.json"
SCHEMA = "zel.rr_exit.fresh6_observer.v1"
EXPECTED_PREREG_RECEIPT = "7de8b088d67bfa0c1db5f4fe04955214e8f314157e75ed2f24932ad4fc13bba1"
REQUIRED_T = 6
HORIZON_BARS = 48
ONE_HOUR_MS = 3_600_000
EPS = 1e-12


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def finite(value: Any) -> float:
    if value == "INF":
        return 1e300
    if value is None:
        return 0.0
    return float(value)


def verify_prereg(r: Mapping[str, Any]) -> tuple[float, float, int]:
    if str(r.get("schema_version")) != "zel.rr_exit.robust_geometry.v4_prospective":
        raise RuntimeError(f"RR_PREREG_SCHEMA_MISMATCH:{r.get('schema_version')}")
    if str(r.get("state")) != "RR_PLATEAU_PREREGISTERED_WAIT_FRESH6":
        raise RuntimeError(f"RR_PREREG_STATE_MISMATCH:{r.get('state')}")
    if str(r.get("receipt_sha256")) != EXPECTED_PREREG_RECEIPT:
        raise RuntimeError(f"RR_PREREG_RECEIPT_DRIFT:{r.get('receipt_sha256')}")
    if int(r.get("development_T") or 0) != 30 or list(r.get("development_overlap_episode_sizes") or []) != [30]:
        raise RuntimeError("RR_PREREG_DEVELOPMENT_IDENTITY_MISMATCH")
    if bool(r.get("historical_internal_holdout_claimed")) is not False:
        raise RuntimeError("RR_PREREG_HISTORICAL_HOLDOUT_CLAIM_FORBIDDEN")
    if bool(r.get("fresh_candidate_reoptimization_forbidden")) is not True:
        raise RuntimeError("RR_PREREG_REOPTIMIZATION_GUARD_MISSING")
    if int(r.get("required_fresh_T") or 0) != REQUIRED_T:
        raise RuntimeError("RR_PREREG_FRESH_T_MISMATCH")
    selected = r.get("selected")
    if not isinstance(selected, Mapping) or bool(selected.get("plateau_supported")) is not True:
        raise RuntimeError("RR_PREREG_SELECTED_PLATEAU_MISSING")
    if int(selected.get("positive_adjacent_count") or 0) < 2:
        raise RuntimeError("RR_PREREG_LOCAL_PLATEAU_UNSUPPORTED")
    tp_r = float(selected["tp_r"])
    sl_r = float(selected["sl_r"])
    boundary = int(r["development_max_exit_ts"])
    if not (math.isclose(tp_r, 67.0715, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(sl_r, 3.3026, rel_tol=0.0, abs_tol=1e-12)
            and boundary == 1787310000000):
        raise RuntimeError(f"RR_PREREG_FROZEN_GEOMETRY_DRIFT:{tp_r}:{sl_r}:{boundary}")
    return tp_r, sl_r, boundary


def strict_checks(native: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, bool]:
    nwr = float(native.get("win_rate") or 0.0)
    cwr = float(candidate.get("win_rate") or 0.0)
    return {
        "same_trade_count": int(candidate.get("trades") or 0) == int(native.get("trades") or 0) == REQUIRED_T,
        "candidate_economics_nonfail": g5.economics_nonfail(candidate),
        "win_rate_retention_ge_80pct_native": cwr + EPS >= 0.80 * nwr,
        "net_pnl_non_decrease": float(candidate.get("net_pnl_bps") or 0.0) + EPS >= float(native.get("net_pnl_bps") or 0.0),
        "net_expectancy_non_decrease": float(candidate.get("net_expectancy_bps") or 0.0) + EPS >= float(native.get("net_expectancy_bps") or 0.0),
        "profit_factor_non_decrease": finite(candidate.get("profit_factor")) + EPS >= finite(native.get("profit_factor")),
        "payoff_non_decrease": finite(candidate.get("payoff")) + EPS >= finite(native.get("payoff")),
        "drawdown_non_increase": float(candidate.get("drawdown_bps") or 0.0) <= float(native.get("drawdown_bps") or 0.0) + EPS,
    }


def candidate_complete(row: Mapping[str, Any]) -> bool:
    reason = str(row.get("reason") or "")
    if reason in {"TP", "SL"}:
        return True
    if reason != "TIMEOUT":
        return False
    return int(row.get("exit_ts") or 0) >= int(row.get("entry_ts") or 0) + HORIZON_BARS * ONE_HOUR_MS


def run(out: Path) -> dict[str, Any]:
    prereg = read(PREREG)
    seal = read(SEAL)
    g5.validate_seal(seal)
    tp_r, sl_r, boundary_ms = verify_prereg(prereg)
    boundary_utc = datetime.fromtimestamp(boundary_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    receipt = g5.current_policy_replay(out_path=out.parent / "rr_fresh6_current_policy.json", boundary_utc=boundary_utc)
    src = seal["source_authority"]
    if str(receipt.get("policy_sha")) != str(src["policy_sha"]):
        raise RuntimeError("RR_FRESH6_POLICY_DRIFT")
    if str(receipt.get("config_sha")) != str(src["config_sha"]):
        raise RuntimeError("RR_FRESH6_CONFIG_DRIFT")
    if list(receipt.get("integrity_defects") or []):
        raise RuntimeError("RR_FRESH6_INTEGRITY_DEFECT")
    if int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("RR_FRESH6_LOOKAHEAD_DEFECT")

    raw = sorted(
        [dict(x) for x in (receipt.get("trades") or [])
         if int(x.get("signal_ts") or 0) > boundary_ms and int(x.get("exit_ts") or 0) > boundary_ms],
        key=lambda x: (int(x.get("signal_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")),
    )
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in raw:
        dedup[g5.trade_key(row)] = row
    ordered = list(dedup.values())

    symbols = sorted({str(x["symbol"]) for x in ordered})
    bars_by = {s: [dict(x) for x in ev.fetch_bars(s, "1h", 1000)] for s in symbols}
    snaps0 = receipt.get("execution_snapshots")
    if not isinstance(snaps0, Mapping):
        raise RuntimeError("RR_FRESH6_EXECUTION_SNAPSHOTS_MISSING")
    snaps = {str(k): dict(v) for k, v in snaps0.items() if isinstance(v, Mapping)}

    simulated_all = rr.simulate(ordered, tp_r, sl_r, bars_by, snaps) if ordered else []
    if len(simulated_all) != len(ordered):
        raise RuntimeError("RR_FRESH6_SIMULATION_PARITY")

    mature_prefix = 0
    for row in simulated_all:
        if not candidate_complete(row):
            break
        mature_prefix += 1

    validation_n = min(REQUIRED_T, mature_prefix)
    native_rows = ordered[:validation_n]
    candidate_rows = simulated_all[:validation_n]
    native_metrics = g5.metrics(native_rows)
    candidate_metrics = g5.metrics(candidate_rows)
    checks = strict_checks(native_metrics, candidate_metrics) if validation_n == REQUIRED_T else {}
    strict_pass = bool(checks) and all(checks.values())

    if validation_n < REQUIRED_T:
        state = "WAIT_RR_FRESH6"
    elif strict_pass:
        state = "PASS_RR_FRESH6_PROSPECTIVE"
    else:
        state = "HOLD_RR_FRESH6_VALIDATION_FAIL"

    compact = []
    for nrow, crow in zip(native_rows, candidate_rows):
        compact.append({
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
        "preregistered_receipt_sha256": EXPECTED_PREREG_RECEIPT,
        "frozen_tp_r": tp_r,
        "frozen_sl_r": sl_r,
        "frozen_nominal_rr": tp_r / sl_r,
        "development_T": 30,
        "development_max_exit_ts": boundary_ms,
        "prospective_boundary_utc": boundary_utc,
        "required_fresh_T": REQUIRED_T,
        "raw_postboundary_closed_T": len(ordered),
        "candidate_mature_prefix_T": mature_prefix,
        "validation_T": validation_n,
        "first_six_prefix_frozen": True,
        "skip_unresolved_prefix_trade_forbidden": True,
        "fresh_candidate_reoptimization_forbidden": True,
        "fresh_validation_used_to_select_candidate": False,
        "native_control": native_metrics,
        "candidate": candidate_metrics,
        "strict_checks": checks,
        "strict_all_metric_pass": strict_pass,
        "validation_rows": compact,
        "duplicate_count": len(raw) - len(dedup),
        "integrity_defects": list(receipt.get("integrity_defects") or []),
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": (
            "COLLECT_FIRST6_MATURE_PREFIX_NO_RETUNE" if state == "WAIT_RR_FRESH6"
            else "SEAL_RR_FRESH6_EVIDENCE_FOR_NEXT_GATE" if state == "PASS_RR_FRESH6_PROSPECTIVE"
            else "REJECT_FROZEN_RR_KEEP_NATIVE_AND_ROUTE_NEXT_DISTINCT_EXIT_FAMILY"
        ),
    }
    result["receipt_sha256"] = g5.stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    native = {"trades": 6, "win_rate": 0.5, "net_pnl_bps": 100.0, "net_expectancy_bps": 100/6,
              "profit_factor": 2.0, "payoff": 1.5, "drawdown_bps": 40.0}
    better = {"trades": 6, "win_rate": 0.5, "net_pnl_bps": 120.0, "net_expectancy_bps": 20.0,
              "profit_factor": 2.2, "payoff": 1.6, "drawdown_bps": 35.0}
    assert all(strict_checks(native, better).values())
    assert candidate_complete({"reason":"TP","entry_ts":0,"exit_ts":1})
    assert candidate_complete({"reason":"TIMEOUT","entry_ts":1,"exit_ts":1+48*ONE_HOUR_MS})
    assert not candidate_complete({"reason":"TIMEOUT","entry_ts":1,"exit_ts":1+47*ONE_HOUR_MS})
    print("PASS_RR_EXIT_FRESH6_OBSERVER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/rr_exit_fresh6_observer_v1.json"))
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
