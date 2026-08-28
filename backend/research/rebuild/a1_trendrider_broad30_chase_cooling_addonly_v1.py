#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as tr_policy
from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import metrics, payoff, strict, trade_key

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "backend/research/rebuild/a1_top5_structure_authority_lock_v1.json"
SCHEMA = "zel.a1.trendrider.broad30_chase_cooling_addonly.v1"
AXIS = "CHASE_COOLING_OR_FLAT_ONLY"
EPS = 1e-12


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def avg_loss(rows: list[Mapping[str, Any]]) -> float | None:
    vals = [-float(x["net_bps"]) for x in rows if float(x.get("net_bps") or 0) < 0]
    return sum(vals) / len(vals) if vals else None


def compact(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in (
        "symbol", "signal_ts", "entry_ts", "exit_ts", "side", "net_bps", "reason",
        "prior_chase_atr", "chase_atr", "chase_state", "chase_cooling_or_flat",
    )}


def enrich(receipt: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    interval = str((receipt.get("source") or {}).get("interval") or "1h")
    if interval != "1h":
        raise RuntimeError(f"SOURCE_INTERVAL_MISMATCH:{interval}")
    cfg = tr_policy.TrendRiderTransitionFreshnessConfig()
    bars_by: dict[str, list[dict[str, Any]]] = {}
    idx_by: dict[str, dict[int, int]] = {}
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, interval, 1000)]
        bars_by[symbol] = bars
        idx_by[symbol] = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
    for row in rows:
        symbol = str(row["symbol"])
        signal_ts = int(row["signal_ts"])
        idx = idx_by[symbol].get(signal_ts)
        if idx is None or idx < 65:
            row["feature_missing"] = True
            continue
        current = tr_policy.compute_trend_rider_feature(
            bars_by[symbol][:idx + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg
        )
        previous = tr_policy.compute_trend_rider_feature(
            bars_by[symbol][:idx], symbol=symbol,
            now_ts_ms=int(bars_by[symbol][idx - 1]["ts_ms"]), config=cfg
        )
        chase = float(current.values["chase_atr"])
        prior = float(previous.values["chase_atr"])
        cooling = chase <= prior
        row.update({
            "prior_chase_atr": prior,
            "chase_atr": chase,
            "chase_state": "COOLING_OR_FLAT" if cooling else "EXPANDING",
            "chase_cooling_or_flat": cooling,
            "feature_missing": False,
        })


def profile_checks(parent: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, bool]:
    pm, sm = metrics(parent), metrics(selected)
    pp, sp = payoff(parent), payoff(selected)
    pal, sal = avg_loss(parent), avg_loss(selected)
    pf_ok = bool(sm.get("profit_factor_unbounded")) or (
        sm.get("profit_factor") is not None and float(sm["profit_factor"]) + EPS >= float(pm["profit_factor"])
    )
    return {
        "selected_T_at_least_10": len(selected) >= 10,
        "selected_symbols_at_least_2": len({str(x["symbol"]) for x in selected}) >= 2,
        "selected_wr_at_least_parent": float(sm.get("win_rate") or 0) + EPS >= float(pm.get("win_rate") or 0),
        "selected_expectancy_at_least_parent": float(sm.get("net_expectancy_bps") or 0) + EPS >= float(pm.get("net_expectancy_bps") or 0),
        "selected_pf_at_least_parent": pf_ok,
        "selected_payoff_at_least_parent": sp is not None and pp is not None and sp + EPS >= pp,
        "selected_dd_no_worse": float(sm.get("drawdown_bps") or 0) <= float(pm.get("drawdown_bps") or 0) + EPS,
        "selected_avg_loss_no_worse": sal is None or pal is None or sal <= pal + EPS,
        "selected_pnl_positive": float(sm.get("net_pnl_bps") or 0) > 0,
    }


def run(broad_path: Path) -> dict[str, Any]:
    lock = read(LOCK)
    broad_doc = read(broad_path)
    if lock.get("state") != "LOCKED_CURRENT_TOP5_PARENT_STRUCTURE":
        raise RuntimeError("TOP5_LOCK_NOT_ACTIVE")
    lane = ((lock.get("lanes") or {}).get("trend_rider_broad_wr7000") or {})
    if int(lane.get("parent_T") or 0) != 30 or abs(float(lane.get("parent_win_rate") or 0) - 0.70) > EPS:
        raise RuntimeError("LOCKED_BROAD30_IDENTITY_MISMATCH")

    broad = [dict(x) for x in broad_doc.get("trades") or []]
    bm = metrics(broad)
    if int(bm["trades"]) != 30 or abs(float(bm["win_rate"]) - 0.70) > EPS:
        raise RuntimeError("BROAD30_AUTHORITY_MISMATCH")
    expected = {
        "net_pnl_bps": 34960.57723836853,
        "net_expectancy_bps": 1165.3525746122843,
        "profit_factor": 60.814848013018874,
        "drawdown_bps": 413.7929696059291,
    }
    for key, val in expected.items():
        if abs(float(bm[key]) - val) > 0.1:
            raise RuntimeError(f"BROAD30_LOCK_METRIC_MISMATCH:{key}:{bm[key]}:{val}")
    if payoff(broad) is None or abs(float(payoff(broad)) - 26.063506291293802) > 0.1:
        raise RuntimeError("BROAD30_PAYOFF_LOCK_MISMATCH")

    current_doc = rebuild_current()
    current = [dict(x) for x in current_doc.get("trades") or []]
    union = {trade_key(x): dict(x) for x in broad + current}
    rows = list(union.values())
    enrich(broad_doc, rows)
    missing = [x for x in rows if bool(x.get("feature_missing"))]
    if missing:
        raise RuntimeError(f"CHASE_COOLING_FEATURE_MISSING:{len(missing)}")
    enriched = {trade_key(x): x for x in rows}
    broad = [dict(enriched[trade_key(x)]) for x in broad]
    current = [dict(enriched[trade_key(x)]) for x in current]

    selected = [dict(x) for x in broad if bool(x["chase_cooling_or_flat"])]
    checks = profile_checks(broad, selected)
    profile_pass = all(checks.values())

    bkeys = {trade_key(x) for x in broad}
    broad_boundary = max(int(x["signal_ts"]) for x in broad)
    lock_boundary = int(lock["lock_boundary_ms"])
    partial_distinct = [
        dict(x) for x in current
        if int(x.get("signal_ts") or 0) > broad_boundary
        and trade_key(x) not in bkeys
        and bool(x["chase_cooling_or_flat"])
    ]
    quarantined = [dict(x) for x in partial_distinct if int(x.get("signal_ts") or 0) <= lock_boundary]
    postlock = [
        dict(x) for x in partial_distinct
        if int(x.get("signal_ts") or 0) > lock_boundary and int(x.get("exit_ts") or 0) > lock_boundary
    ]
    q_ok, q_checks, q_added, q_combined, q_payoff = strict(broad, quarantined) if quarantined else (
        False, {}, metrics([]), metrics(broad), payoff(broad)
    )
    p_ok, p_checks, p_added, p_combined, p_payoff = strict(broad, postlock) if postlock else (
        False, {}, metrics([]), metrics(broad), payoff(broad)
    )

    if not profile_pass:
        state = "REJECT_CHASE_COOLING_ADDONLY_HISTORICAL_PROFILE_BELOW_BROAD30"
        next_step = "ROTATE_TO_DISTINCT_ENTRY_QUALITY_AXIS"
    elif postlock and p_ok:
        state = "HOLD_CHASE_COOLING_POSTLOCK_PARTIAL_SOURCE_STRICT_NEEDS_BASE_BROAD_COVERAGE"
        next_step = "BUILD_BASE_BROAD_POSTLOCK_CANDIDATE_PRODUCER_THEN_RECONFIRM"
    elif quarantined and q_ok:
        state = "HOLD_CHASE_COOLING_PROFILE_PASS_PARTIAL_VALIDATION_PASS_WAIT_COMPLETE_SOURCE"
        next_step = "BUILD_BASE_BROAD_POSTLOCK_CANDIDATE_PRODUCER; DO_NOT_UNION_PARTIAL_ROWS"
    else:
        state = "HOLD_CHASE_COOLING_PROFILE_ONLY_NOT_VALIDATED"
        next_step = "KEEP_PARENT30_AND_COLLECT_COMPLETE_BASE_BROAD_POSTLOCK_SOURCE"

    return {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "mechanism": "CHASE_COOLING_OR_FLAT_ADD_ONLY",
        "axis": {
            "id": AXIS,
            "rule": "current_chase_atr <= prior_closed_bar_chase_atr",
            "all_sessions_same_rule": True,
            "numeric_threshold_sweep": False,
            "alternative_rule_sweep": False,
            "uses_post_outcome_data": False,
        },
        "locked_parent": {"T": 30, "metrics": metrics(broad), "payoff": payoff(broad), "mutated": False},
        "historical_profile": {
            "selected_T": len(selected),
            "selected_metrics": metrics(selected),
            "selected_payoff": payoff(selected),
            "selected_avg_loss_bps": avg_loss(selected),
            "checks": checks,
            "profile_pass": profile_pass,
            "rows": [compact(x) for x in selected],
            "promotion_evidence": False,
        },
        "partial_current_source": {
            "source_identity": "TRANSITION_FRESHNESS_CURRENT_NATIVE_RECEIPT",
            "complete_base_broad_coverage": False,
            "append_authority": False,
            "promotion_evidence": False,
        },
        "quarantined_prelock_partial_validation": {
            "source_T": len(quarantined),
            "strict_add_only_pass": bool(q_ok),
            "checks": q_checks,
            "added_metrics": q_added,
            "combined_metrics": q_combined,
            "combined_payoff": q_payoff,
            "rows": [compact(x) for x in quarantined],
            "append_authority": False,
            "promotion_evidence": False,
        },
        "postlock_partial_validation": {
            "source_T": len(postlock),
            "strict_add_only_pass": bool(p_ok),
            "checks": p_checks,
            "added_metrics": p_added,
            "combined_metrics": p_combined,
            "combined_payoff": p_payoff,
            "rows": [compact(x) for x in postlock],
            "append_authority": False,
            "promotion_evidence": False,
        },
        "parent_trade_deletion": 0,
        "parent_trade_rewrite": 0,
        "automatic_prelock_union": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
        "next": next_step,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broad-source", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_broad30_chase_cooling_addonly_v1.json"))
    args = ap.parse_args()
    r = run(args.broad_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": r["state"],
        "historical_selected_T": r["historical_profile"]["selected_T"],
        "historical_profile_pass": r["historical_profile"]["profile_pass"],
        "quarantined_partial_T": r["quarantined_prelock_partial_validation"]["source_T"],
        "quarantined_partial_strict": r["quarantined_prelock_partial_validation"]["strict_add_only_pass"],
        "postlock_partial_T": r["postlock_partial_validation"]["source_T"],
        "postlock_partial_strict": r["postlock_partial_validation"]["strict_add_only_pass"],
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
