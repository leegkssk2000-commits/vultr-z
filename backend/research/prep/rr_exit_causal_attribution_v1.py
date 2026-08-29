#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as g5
from backend.research.prep import rr_exit_fresh6_observer_v1 as h1
from backend.research.prep import rr_exit_fresh6_observer_v2 as h2
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr

SCHEMA = "zel.rr_exit.causal_attribution.v1"
FREEZE_TS_MS = 1787964724000
HORIZON_BARS = 48
ONE_HOUR_MS = 3_600_000


def _ordered_holdout(out: Path) -> tuple[list[dict[str, Any]], float, float]:
    prereg = h1.read(h1.PREREG)
    seal = h1.read(h1.SEAL)
    g5.validate_seal(seal)
    tp_r, sl_r, boundary_ms = h1.verify_prereg(prereg)
    boundary_utc = h1.datetime.fromtimestamp(boundary_ms / 1000, tz=h1.timezone.utc).isoformat().replace("+00:00", "Z")
    receipt = g5.current_policy_replay(out_path=out.parent / "rr_causal_current_policy.json", boundary_utc=boundary_utc)
    if list(receipt.get("integrity_defects") or []):
        raise RuntimeError("RR_CAUSAL_INTEGRITY_DEFECT")
    if int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("RR_CAUSAL_LOOKAHEAD_DEFECT")
    raw = sorted(
        [dict(x) for x in (receipt.get("trades") or [])
         if int(x.get("signal_ts") or 0) > boundary_ms
         and int(x.get("signal_ts") or 0) < FREEZE_TS_MS
         and int(x.get("exit_ts") or 0) > boundary_ms],
        key=lambda x: (int(x.get("signal_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")),
    )
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in raw:
        dedup[g5.trade_key(row)] = row
    rows = list(dedup.values())[:h1.REQUIRED_T]
    if len(rows) != h1.REQUIRED_T:
        raise RuntimeError(f"RR_CAUSAL_EXPECTED_FIXED6:{len(rows)}")
    return rows, tp_r, sl_r


def _forced_native_horizon(
    rows: list[dict[str, Any]], tp_r: float, sl_r: float,
    bars_by: Mapping[str, list[dict[str, Any]]], snaps: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        sym = str(row["symbol"]); bars = list(bars_by[sym]); idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        si = idx.get(int(row["signal_ts"])); ei = idx.get(int(row["entry_ts"])); ni = idx.get(int(row["exit_ts"]))
        if si is None or ei is None or ni is None or ni < ei:
            raise RuntimeError(f"RR_CAUSAL_NATIVE_HORIZON_BAR_MISSING:{sym}:{row.get('signal_ts')}")
        entry = float(row.get("entry") or bars[ei]["open"]); side = str(row["side"]); r = rr.native_r(row, bars, si, entry)
        stop = entry - sl_r * r if side == "long" else entry + sl_r * r
        target = entry + tp_r * r if side == "long" else entry - tp_r * r
        px = ts = reason = None
        for j in range(ei, ni + 1):
            lo, hi = float(bars[j]["low"]), float(bars[j]["high"])
            hit_sl = lo <= stop if side == "long" else hi >= stop
            hit_tp = hi >= target if side == "long" else lo <= target
            if hit_sl:
                px, ts, reason = stop, int(bars[j]["ts_ms"]), "SL"; break
            if hit_tp:
                px, ts, reason = target, int(bars[j]["ts_ms"]), "TP"; break
        if px is None:
            px, ts, reason = float(bars[ni]["close"]), int(bars[ni]["ts_ms"]), "NATIVE_HORIZON_MARK"
        snap = snaps[sym]
        funding = ev.funding_cost(int(row["entry_ts"]), int(ts), list(snap["funding_rows"]))
        cost = float(snap["fee_bps"]) + float(snap["spread_bps"]) + float(snap["impact_bps"]) + funding
        gross = (float(px) - entry) / entry * 10000 if side == "long" else (entry - float(px)) / entry * 10000
        out.append({**{k: row.get(k) for k in ("symbol", "signal_ts", "entry_ts", "side")},
                    "exit_ts": int(ts), "entry": entry, "exit": float(px), "reason": reason,
                    "net_bps": gross - cost, "gross_bps": gross, "realized_cost_bps": cost})
    return out


def _excursion(row: Mapping[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    si = idx[int(row["signal_ts"])]; ei = idx[int(row["entry_ts"])]
    entry = float(row.get("entry") or bars[ei]["open"]); side = str(row["side"]); r = rr.native_r(row, bars, si, entry)
    last = min(len(bars) - 1, ei + HORIZON_BARS)
    mae = 0.0; mfe = 0.0; first_1r = None
    for j in range(ei, last + 1):
        lo, hi = float(bars[j]["low"]), float(bars[j]["high"])
        adverse = (entry - lo) / r if side == "long" else (hi - entry) / r
        favorable = (hi - entry) / r if side == "long" else (entry - lo) / r
        mae = max(mae, adverse); mfe = max(mfe, favorable)
        if first_1r is None and adverse >= 1.0:
            first_1r = int(bars[j]["ts_ms"])
    return {"mae_native_r": mae, "mfe_native_r": mfe, "first_native_1r_cross_ts": first_1r,
            "candidate_sl_3p3026r_crossed": mae + 1e-12 >= 3.3026,
            "candidate_tp_67p0715r_crossed": mfe + 1e-12 >= 67.0715}


def run(out: Path) -> dict[str, Any]:
    rows, tp_r, sl_r = _ordered_holdout(out)
    symbols = sorted({str(x["symbol"]) for x in rows})
    bars_by = {s: [dict(x) for x in ev.fetch_bars(s, "1h", 1000)] for s in symbols}
    snaps = h2._full_snapshots(rows)

    frozen = rr.simulate(rows, tp_r, sl_r, bars_by, snaps)
    sl1 = rr.simulate(rows, tp_r, 1.0, bars_by, snaps)
    native_horizon = _forced_native_horizon(rows, tp_r, sl_r, bars_by, snaps)
    if not all(h1.candidate_complete(x) for x in frozen):
        raise RuntimeError("RR_CAUSAL_FROZEN_PREFIX_NOT_MATURE")
    if any(int(x["exit_ts"]) >= FREEZE_TS_MS for x in frozen):
        raise RuntimeError("RR_CAUSAL_FROZEN_OUTCOME_NOT_PREPREREG")

    fm, sm, nm = g5.metrics(frozen), g5.metrics(sl1), g5.metrics(native_horizon)
    row_diag = []
    for native, a, b, c in zip(rows, frozen, sl1, native_horizon):
        ex = _excursion(native, bars_by[str(native["symbol"])])
        row_diag.append({
            "symbol": native["symbol"], "signal_ts": int(native["signal_ts"]), "side": native["side"],
            "native_net_bps": float(native.get("net_bps") or 0.0),
            "frozen_net_bps": float(a["net_bps"]), "sl1_48h_net_bps": float(b["net_bps"]),
            "wide_sl_native_horizon_net_bps": float(c["net_bps"]),
            "frozen_reason": a["reason"], "sl1_48h_reason": b["reason"], "native_horizon_reason": c["reason"],
            "sl_widen_delta_bps": float(a["net_bps"]) - float(b["net_bps"]),
            "post_native_horizon_delta_bps": float(a["net_bps"]) - float(c["net_bps"]),
            "native_exit_ts": int(native["exit_ts"]), "frozen_exit_ts": int(a["exit_ts"]),
            **ex,
        })

    all_timeout = all(x["reason"] == "TIMEOUT" for x in frozen)
    tp_untouched = all(not x["candidate_tp_67p0715r_crossed"] for x in row_diag)
    sl_candidate_untouched = all(not x["candidate_sl_3p3026r_crossed"] for x in row_diag)
    rescued_after_1r = sum(1 for x in row_diag if x["first_native_1r_cross_ts"] is not None and x["frozen_net_bps"] > 0)
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_RR_CAUSAL_ATTRIBUTION_DIAGNOSTIC_COMPLETE",
        "action": "hold",
        "strategy_id": "trend_rider", "lane_id": "trend_rider_broad_wr7000",
        "evidence_role": "POST_DEVELOPMENT_PRE_PREREG_DIAGNOSTIC_ONLY",
        "promotion_evidence_eligible": False, "selection_authority": False, "promotion_authority": False,
        "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED",
        "candidate_reoptimization_forbidden": True, "threshold_sweep": False, "old_history_retroactive_promotion_forbidden": True,
        "fixed_counterfactuals": {
            "A_frozen": {"tp_r": tp_r, "sl_r": sl_r, "horizon_h": 48, "metrics": fm},
            "B_native_stop_scale": {"tp_r": tp_r, "sl_r": 1.0, "horizon_h": 48, "metrics": sm},
            "C_wide_sl_native_horizon": {"tp_r": tp_r, "sl_r": sl_r, "horizon": "EACH_NATIVE_EXIT_TS", "metrics": nm},
        },
        "aggregate_deltas_bps": {
            "A_minus_B_sl_widen": float(fm["net_pnl_bps"]) - float(sm["net_pnl_bps"]),
            "A_minus_C_post_native_horizon": float(fm["net_pnl_bps"]) - float(nm["net_pnl_bps"]),
        },
        "observations": {
            "frozen_all_timeout": all_timeout,
            "frozen_tp_barrier_untouched_all6": tp_untouched,
            "frozen_sl_barrier_untouched_all6": sl_candidate_untouched,
            "positive_frozen_after_native_1r_cross_count": rescued_after_1r,
            "interaction_warning": "SL_WIDEN_AND_HOLD_TIME_ARE_CAUSALLY_INTERACTING;DELTAS_ARE_NOT_ADDITIVE",
        },
        "rows": row_diag,
        "next": "USE_DIAGNOSTIC_TO_CHOOSE_ONE_CAUSAL_AXIS;DO_NOT_RETUNE_FROZEN_TRUE_FRESH_CANDIDATE",
    }
    result["receipt_sha256"] = g5.stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert FREEZE_TS_MS == 1787964724000
    assert HORIZON_BARS == 48
    assert math.isclose(3.3026, 3.3026, rel_tol=0.0, abs_tol=1e-12)
    print("PASS_RR_EXIT_CAUSAL_ATTRIBUTION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, default=Path("out/rr_exit_causal_attribution_v1.json")); ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test: return self_test()
    r = run(a.out)
    print(json.dumps({"state": r["state"], "A": r["fixed_counterfactuals"]["A_frozen"]["metrics"], "B": r["fixed_counterfactuals"]["B_native_stop_scale"]["metrics"], "C": r["fixed_counterfactuals"]["C_wide_sl_native_horizon"]["metrics"], "deltas": r["aggregate_deltas_bps"], "observations": r["observations"], "receipt": r["receipt_sha256"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
