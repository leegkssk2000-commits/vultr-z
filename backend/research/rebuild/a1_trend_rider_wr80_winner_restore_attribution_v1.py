#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as diag
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as parent
from backend.research.rebuild import trend_rider_transition_freshness_non_us_child_policy_v1 as nonus

SCHEMA = "zel.a1.trend_rider.wr80_winner_restore_attribution.v1"
FROZEN_COUNT = 24
EXPECTED_PARENT_WR = 0.5833333333333334
EXPECTED_PARENT_NET_BPS = 24812.448723667734
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    wins = sum(1 for x in rows if float(x.get("net_bps") or 0.0) > 0.0)
    net = sum(float(x.get("net_bps") or 0.0) for x in rows)
    return {
        "trades": n,
        "wins": wins,
        "win_rate": wins / n if n else None,
        "net_pnl_bps": net,
        "net_expectancy_bps": net / n if n else None,
    }


def _enrich(receipt: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    interval = str((receipt.get("source") or {}).get("interval") or "1h")
    cfg = parent.TrendRiderTransitionFreshnessConfig()
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    index: dict[str, dict[int, int]] = {}
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, interval, 1000)]
        by_symbol[symbol] = bars
        index[symbol] = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    for row in rows:
        symbol = str(row["symbol"])
        signal_ts = int(row["signal_ts"])
        i = index[symbol].get(signal_ts)
        if i is None or i < 65:
            row["feature_missing"] = True
            continue
        cur = parent.compute_trend_rider_feature(
            by_symbol[symbol][: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg
        )
        prv = parent.compute_trend_rider_feature(
            by_symbol[symbol][:i], symbol=symbol,
            now_ts_ms=int(by_symbol[symbol][i - 1]["ts_ms"]), config=cfg
        )
        cv = dict(cur.values)
        pv = dict(prv.values)
        st_cur = float(cv["st_gap_atr"])
        st_prev = float(pv["st_gap_atr"])
        chase_cur = float(cv["chase_atr"])
        chase_prev = float(pv["chase_atr"])
        atr_pct_cur = float(cur.atr / max(cur.close, 1e-12) * 100.0)
        atr_pct_prev = float(prv.atr / max(prv.close, 1e-12) * 100.0)
        row.update({
            "session": nonus._session(signal_ts),
            "st_gap_atr": st_cur,
            "st_gap_state": "EXPANDING" if st_cur > st_prev else "COOLING_OR_FLAT",
            "chase_atr": chase_cur,
            "chase_state": "EXPANDING" if chase_cur > chase_prev else "COOLING_OR_FLAT",
            "atr_pct": atr_pct_cur,
            "atr_state": "EXPANDING" if atr_pct_cur > atr_pct_prev else "COOLING_OR_FLAT",
            "geometry_balance": "ST_GAP_GE_CHASE" if st_cur >= chase_cur else "CHASE_GT_ST_GAP",
            "feature_missing": False,
        })


def _candidate_rows(non_us_rows: list[dict[str, Any]], us_rows: list[dict[str, Any]],
                    axis: str, value: str) -> list[dict[str, Any]]:
    return non_us_rows + [x for x in us_rows if str(x.get(axis)) == value]


def run(out: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trend_wr80_restore_") as td:
        receipt = diag._run_receipt("trend_rider", Path(td) / "trend.json")
    rows = [dict(x) for x in (receipt.get("trades") or [])]
    rows.sort(key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
    if len(rows) < FROZEN_COUNT:
        raise RuntimeError(f"FROZEN_24_UNAVAILABLE:{len(rows)}")
    rows = rows[:FROZEN_COUNT]
    _enrich(receipt, rows)

    parent_stats = _stats(rows)
    authority_ok = (
        parent_stats["trades"] == FROZEN_COUNT
        and abs(float(parent_stats["win_rate"]) - EXPECTED_PARENT_WR) <= 1e-12
        and abs(float(parent_stats["net_pnl_bps"]) - EXPECTED_PARENT_NET_BPS) <= 0.05
        and not any(bool(x.get("feature_missing")) for x in rows)
    )
    if not authority_ok:
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_FROZEN_24_AUTHORITY_MISMATCH",
            "frozen_parent": parent_stats,
            "expected_parent": {
                "trades": FROZEN_COUNT,
                "win_rate": EXPECTED_PARENT_WR,
                "net_pnl_bps": EXPECTED_PARENT_NET_BPS,
            },
            "authority_match": False,
            "next": "DO_NOT_SELECT_RESTORE_CHILD",
            **AUTH,
        }
        result["receipt_sha256"] = ev.stable_sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return result

    non_us_rows = [x for x in rows if x["session"] != "US"]
    us_rows = [x for x in rows if x["session"] == "US"]
    us_winners = [x for x in us_rows if float(x.get("net_bps") or 0.0) > 0.0]
    us_losers = [x for x in us_rows if float(x.get("net_bps") or 0.0) <= 0.0]
    non_us_stats = _stats(non_us_rows)

    axes = ("symbol", "side", "st_gap_state", "chase_state", "atr_state", "geometry_balance")
    candidates: list[dict[str, Any]] = []
    for axis in axes:
        for value in sorted({str(x.get(axis)) for x in us_rows}):
            selected_us = [x for x in us_rows if str(x.get(axis)) == value]
            selected_winners = [x for x in selected_us if float(x.get("net_bps") or 0.0) > 0.0]
            selected_losers = [x for x in selected_us if float(x.get("net_bps") or 0.0) <= 0.0]
            stats = _stats(_candidate_rows(non_us_rows, us_rows, axis, value))
            candidates.append({
                "axis": axis,
                "value": value,
                "candidate": stats,
                "delta_vs_non_us_wr": float(stats["win_rate"]) - float(non_us_stats["win_rate"]),
                "delta_vs_non_us_net_pnl_bps": float(stats["net_pnl_bps"]) - float(non_us_stats["net_pnl_bps"]),
                "delta_vs_parent_net_pnl_bps": float(stats["net_pnl_bps"]) - float(parent_stats["net_pnl_bps"]),
                "us_trade_reintroduced": len(selected_us),
                "us_winner_reintroduced": len(selected_winners),
                "us_loser_reintroduced": len(selected_losers),
                "us_winner_pnl_restored_bps": sum(float(x.get("net_bps") or 0.0) for x in selected_winners),
                "us_loser_pnl_reintroduced_bps": sum(float(x.get("net_bps") or 0.0) for x in selected_losers),
                "preentry_only": True,
                "numeric_threshold_fitted": False,
            })

    pareto = []
    for c in candidates:
        cw = float(c["candidate"]["win_rate"])
        cp = float(c["candidate"]["net_pnl_bps"])
        dominated = False
        for d in candidates:
            if d is c:
                continue
            dw = float(d["candidate"]["win_rate"])
            dp = float(d["candidate"]["net_pnl_bps"])
            if dw >= cw and dp >= cp and (dw > cw or dp > cp):
                dominated = True
                break
        if not dominated:
            pareto.append(c)

    strict_restore = [
        c for c in candidates
        if float(c["candidate"]["win_rate"]) >= float(non_us_stats["win_rate"])
        and float(c["candidate"]["net_pnl_bps"]) > float(non_us_stats["net_pnl_bps"])
    ]
    key = lambda c: (-float(c["candidate"]["net_pnl_bps"]), -float(c["candidate"]["win_rate"]), str(c["axis"]), str(c["value"]))
    strict_restore.sort(key=key)
    pareto.sort(key=key)
    recommended = strict_restore[0] if strict_restore else (pareto[0] if pareto else None)
    state = "STRICT_WR_PRESERVING_WINNER_RESTORE_FOUND" if strict_restore else "PARETO_ONLY_NO_STRICT_WR_PRESERVING_RESTORE"
    next_step = f"PREREGISTER_FRESH_US_CONDITIONAL_REENABLE:{recommended['axis']}:{recommended['value']}" if recommended else "NO_RESTORE_CHILD"

    compact_us = [{k: x.get(k) for k in (
        "symbol", "side", "signal_ts", "net_bps", "session", "st_gap_atr", "st_gap_state",
        "chase_atr", "chase_state", "atr_pct", "atr_state", "geometry_balance"
    )} for x in us_rows]
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "frozen_parent_commit_receipt": "7511cc036cb854015f800008d9488b5eb0897034",
        "authority_match": True,
        "frozen_parent": parent_stats,
        "non_us_partial_success": non_us_stats,
        "us_trade_count": len(us_rows),
        "us_winner_count": len(us_winners),
        "us_loser_count": len(us_losers),
        "us_winner_net_pnl_bps": sum(float(x.get("net_bps") or 0.0) for x in us_winners),
        "us_loser_net_pnl_bps": sum(float(x.get("net_bps") or 0.0) for x in us_losers),
        "discovery_axes": list(axes),
        "candidate_count": len(candidates),
        "strict_restore_candidates": strict_restore,
        "pareto_candidates": pareto,
        "recommended_discovery_child": recommended,
        "us_trade_attribution": compact_us,
        "outcome_used_for_discovery_only": True,
        "outcome_used_at_runtime": False,
        "fresh_proof_required": True,
        "numeric_threshold_sweep": False,
        "parent_incumbent_mutated": False,
        "non_us_partial_success_branch_mutated": False,
        "next": next_step,
        **AUTH,
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    s = _stats([{"net_bps": 10.0}, {"net_bps": -2.0}, {"net_bps": 4.0}])
    assert s["trades"] == 3 and s["wins"] == 2
    assert abs(float(s["win_rate"]) - 2 / 3) < 1e-12
    assert nonus._session(15 * 3600 * 1000) == "EU"
    assert nonus._session(16 * 3600 * 1000) == "US"
    print("PASS_A1_TREND_RIDER_WR80_WINNER_RESTORE_ATTRIBUTION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_wr80_winner_restore_attribution_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "authority_match": r["authority_match"],
        "non_us_partial_success": r.get("non_us_partial_success"),
        "recommended": r.get("recommended_discovery_child"),
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
