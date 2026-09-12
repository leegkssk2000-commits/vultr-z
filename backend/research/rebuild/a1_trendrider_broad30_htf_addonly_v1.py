#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import metrics, payoff, strict, trade_key

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "backend/research/rebuild/a1_top5_structure_authority_lock_v1.json"
SCHEMA = "zel.a1.trendrider.broad30_htf_addonly.v1"
EPS = 1e-12


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def ema(values: list[float], span: int) -> float | None:
    if len(values) < span:
        return None
    alpha = 2.0 / (span + 1.0)
    out = float(values[0])
    for value in values[1:]:
        out = alpha * float(value) + (1.0 - alpha) * out
    return out


def avg_win(rows: list[Mapping[str, Any]]) -> float | None:
    values = [float(x["net_bps"]) for x in rows if float(x["net_bps"]) > 0]
    return sum(values) / len(values) if values else None


def avg_loss(rows: list[Mapping[str, Any]]) -> float | None:
    values = [-float(x["net_bps"]) for x in rows if float(x["net_bps"]) < 0]
    return sum(values) / len(values) if values else None


def compact(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in (
        "symbol", "signal_ts", "entry_ts", "exit_ts", "side", "net_bps", "reason",
        "htf_trend_up", "htf_prior_close", "htf_ema20", "htf_ema50",
    )}


def enrich_htf(receipt: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    interval = str((receipt.get("source") or {}).get("interval") or "1h")
    if interval != "1h":
        raise RuntimeError(f"HTF_SOURCE_INTERVAL_MISMATCH:{interval}")
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    index: dict[str, dict[int, int]] = {}
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, interval, 1000)]
        by_symbol[symbol] = bars
        index[symbol] = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
    for row in rows:
        symbol = str(row["symbol"])
        signal_ts = int(row["signal_ts"])
        i = index[symbol].get(signal_ts)
        if i is None or i < 50:
            row["feature_missing"] = True
            continue
        # Strictly prior 1h bars only. The signal bar itself is excluded to avoid lookahead ambiguity.
        prior = by_symbol[symbol][:i]
        closes = [float(x["close"]) for x in prior]
        e20 = ema(closes, 20)
        e50 = ema(closes, 50)
        if e20 is None or e50 is None:
            row["feature_missing"] = True
            continue
        close = float(closes[-1])
        row.update({
            "htf_prior_close": close,
            "htf_ema20": e20,
            "htf_ema50": e50,
            "htf_trend_up": bool(close > e20 > e50),
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
        "selected_T_at_least_5": len(selected) >= 5,
        "selected_symbols_at_least_2": len({str(x["symbol"]) for x in selected}) >= 2,
        "selected_wr_at_least_parent": float(sm.get("win_rate") or 0) + EPS >= float(pm.get("win_rate") or 0),
        "selected_expectancy_at_least_parent": float(sm.get("net_expectancy_bps") or 0) + EPS >= float(pm.get("net_expectancy_bps") or 0),
        "selected_pf_at_least_parent": pf_ok,
        "selected_payoff_at_least_parent": sp is not None and pp is not None and sp + EPS >= pp,
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
    for key in ("net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps"):
        expected_key = "parent_" + ("drawdown_bps" if key == "drawdown_bps" else key)
        expected = lane.get(expected_key)
        if expected is not None and abs(float(bm[key]) - float(expected)) > 0.1:
            raise RuntimeError(f"BROAD30_LOCK_METRIC_MISMATCH:{key}:{bm[key]}:{expected}")
    bp = payoff(broad)
    if bp is None or abs(float(bp) - float(lane["parent_payoff"])) > 0.1:
        raise RuntimeError("BROAD30_PAYOFF_LOCK_MISMATCH")

    current_doc = rebuild_current()
    current = [dict(x) for x in current_doc.get("trades") or []]
    by_key = {trade_key(x): dict(x) for x in broad + current}
    rows = list(by_key.values())
    enrich_htf(broad_doc, rows)
    missing = [x for x in rows if bool(x.get("feature_missing"))]
    if missing:
        raise RuntimeError(f"HTF_FEATURE_MISSING:{len(missing)}")
    enriched = {trade_key(x): x for x in rows}
    broad = [dict(enriched[trade_key(x)]) for x in broad]
    current = [dict(enriched[trade_key(x)]) for x in current]

    selected = [dict(x) for x in broad if bool(x["htf_trend_up"])]
    checks = profile_checks(broad, selected)
    hist_profile_pass = all(checks.values())

    bkeys = {trade_key(x) for x in broad}
    broad_boundary = max(int(x["signal_ts"]) for x in broad)
    lock_boundary = int(lock["lock_boundary_ms"])
    diagnostic_holdout = [
        dict(x) for x in current
        if int(x.get("signal_ts") or 0) > broad_boundary and trade_key(x) not in bkeys
    ]
    diag_selected = [dict(x) for x in diagnostic_holdout if bool(x["htf_trend_up"])]
    diag_ok, diag_checks, diag_added, diag_combined, diag_payoff = strict(broad, diag_selected) if diag_selected else (
        False, {}, metrics([]), metrics(broad), payoff(broad)
    )

    prospective = [
        dict(x) for x in diagnostic_holdout
        if int(x.get("signal_ts") or 0) > lock_boundary
        and int(x.get("exit_ts") or 0) > lock_boundary
    ]
    prospective_selected = [dict(x) for x in prospective if bool(x["htf_trend_up"])]
    prospective_ok, prospective_checks, prospective_added, prospective_combined, prospective_payoff = strict(
        broad, prospective_selected
    ) if prospective_selected else (False, {}, metrics([]), metrics(broad), payoff(broad))

    if not hist_profile_pass:
        state = "REJECT_HTF_ADDONLY_HISTORICAL_PROFILE_BELOW_BROAD30"
        next_step = "ROTATE_TO_DISTINCT_ADD_ONLY_ENTRY_QUALITY_AXIS"
    elif prospective_selected and prospective_ok:
        state = "PASS_HTF_ADDONLY_POSTLOCK_STRICT_CANDIDATE_NONPROMOTABLE"
        next_step = "FREEZE_GATE_AND_REQUIRE_ADDITIONAL_POSTLOCK_PROSPECTIVE_CONFIRMATION"
    elif diag_selected and diag_ok:
        state = "HOLD_HTF_ADDONLY_HISTORICAL_VALIDATION_PASS_WAIT_POSTLOCK_T"
        next_step = "KEEP_PARENT30_AND_WAIT_POSTLOCK_HTF_TRUE_CLOSED_T"
    else:
        state = "HOLD_HTF_ADDONLY_NOT_YET_STRICT"
        next_step = "ROTATE_OR_WAIT_WITHOUT_PARENT_MUTATION"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "mechanism": "HTF_TREND_UP_ADD_ONLY_FUTURE_ADMISSION",
        "htf_semantics": {
            "source_interval": "1h",
            "causal_cutoff": "STRICTLY_PRIOR_SIGNAL_BAR",
            "formula": "prior_close > EMA20(prior_1h_close) > EMA50(prior_1h_close)",
            "threshold_sweep": False,
            "alternative_rule_sweep": False,
            "gate_value": True,
        },
        "locked_parent": {
            "T": 30,
            "metrics": metrics(broad),
            "payoff": payoff(broad),
            "mutated": False,
        },
        "historical_profile": {
            "source_T": len(broad),
            "selected_T": len(selected),
            "selected_metrics": metrics(selected),
            "selected_payoff": payoff(selected),
            "selected_avg_win_bps": avg_win(selected),
            "selected_avg_loss_bps": avg_loss(selected),
            "checks": checks,
            "profile_pass": hist_profile_pass,
            "rows": [compact(x) for x in selected],
            "promotion_evidence": False,
        },
        "quarantined_prelock_validation": {
            "source_T": len(diagnostic_holdout),
            "selected_T": len(diag_selected),
            "strict_add_only_pass": bool(diag_ok),
            "checks": diag_checks,
            "added_metrics": diag_added,
            "combined_metrics": diag_combined,
            "combined_payoff": diag_payoff,
            "rows": [compact(x) for x in diag_selected],
            "append_authority": False,
            "promotion_evidence": False,
        },
        "postlock_prospective": {
            "lock_boundary_ms": lock_boundary,
            "source_T": len(prospective),
            "selected_T": len(prospective_selected),
            "strict_add_only_pass": bool(prospective_ok),
            "checks": prospective_checks,
            "added_metrics": prospective_added,
            "combined_metrics": prospective_combined,
            "combined_payoff": prospective_payoff,
            "rows": [compact(x) for x in prospective_selected],
            "promotion_evidence": False,
        },
        "old_htf_filter_failure_not_repeated": True,
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
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broad-source", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_broad30_htf_addonly_v1.json"))
    args = ap.parse_args()
    result = run(args.broad_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "historical_selected_T": result["historical_profile"]["selected_T"],
        "historical_profile_pass": result["historical_profile"]["profile_pass"],
        "diagnostic_holdout_selected_T": result["quarantined_prelock_validation"]["selected_T"],
        "diagnostic_holdout_strict": result["quarantined_prelock_validation"]["strict_add_only_pass"],
        "postlock_selected_T": result["postlock_prospective"]["selected_T"],
        "postlock_strict": result["postlock_prospective"]["strict_add_only_pass"],
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
