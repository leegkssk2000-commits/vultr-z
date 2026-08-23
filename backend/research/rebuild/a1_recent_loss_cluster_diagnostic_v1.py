#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_trend_rider_transition_freshness_frozen_w123_ab_v1 as tr_ab
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as tr_policy

ROOT = Path(__file__).resolve().parents[3]
TARGETS = ("trend_rider", "supertrend_pullback", "trend_ma_macd", "keltner_trend", "break_and_continue")
AUTH = {
    "selection_authority": False, "promotion_authority": False,
    "execution_authority": "NONE", "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED", "protected_mutations": 0,
}


def sha(v: Any) -> str:
    return ev.stable_sha(v)


def read(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return x


def _run_receipt(strategy_id: str, out: Path) -> dict[str, Any]:
    if strategy_id == "trend_rider":
        return tr_ab._run_exact(out, child=True)
    subprocess.run([
        sys.executable, "-m", "backend.research.rebuild.a1_exact25_generic_evaluator_v2",
        "--strategy-id", strategy_id, "--out", str(out), "--terminal-replay",
    ], check=True, stdout=subprocess.DEVNULL)
    return read(out)


def _session(ts_ms: int) -> str:
    h = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour
    if h < 8:
        return "APAC"
    if h < 14:
        return "EU"
    return "US"


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(x.get(key)) for x in rows))


def _share(rows: list[dict[str, Any]], key: str, value: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for x in rows if str(x.get(key)) == value) / len(rows)


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [float(x[key]) for x in rows if x.get(key) is not None and math.isfinite(float(x[key]))]
    return sum(vals) / len(vals) if vals else None


def _trend_enrichment(receipt: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    source = receipt.get("source") if isinstance(receipt.get("source"), Mapping) else {}
    interval = str(source.get("interval") or "1h")
    bars_by: dict[str, list[dict[str, Any]]] = {}
    for symbol in sorted({str(x.get("symbol")) for x in rows}):
        bars_by[symbol] = [dict(x) for x in ev.fetch_bars(symbol, interval, 1000)]
    cfg = tr_policy.TrendRiderTransitionFreshnessConfig()
    for row in rows:
        symbol = str(row["symbol"]); signal_ts = int(row["signal_ts"])
        bars = bars_by[symbol]
        idx = next((i for i, b in enumerate(bars) if int(b["ts_ms"]) == signal_ts), None)
        if idx is None or idx < 64:
            continue
        f = tr_policy.compute_trend_rider_feature(bars[:idx+1], symbol=symbol, now_ts_ms=signal_ts, config=cfg)
        vals = dict(f.values)
        row["st_gap_atr"] = float(vals.get("st_gap_atr")) if vals.get("st_gap_atr") is not None else None
        row["chase_atr"] = float(vals.get("chase_atr")) if vals.get("chase_atr") is not None else None
        row["atr_pct"] = float(f.atr / max(f.close, 1e-12) * 100.0)


def diagnose(strategy_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    rows = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    rows.sort(key=lambda x: (int(x.get("entry_ts") or 0), int(x.get("exit_ts") or 0), str(x.get("symbol") or "")))
    for x in rows:
        x["session"] = _session(int(x.get("signal_ts") or x.get("entry_ts") or 0))
        interval = str((receipt.get("source") or {}).get("interval") or "1h")
        tf_ms = {"5m":300000,"15m":900000,"30m":1800000,"1h":3600000,"2h":7200000,"4h":14400000}.get(interval, 3600000)
        x["hold_bars"] = max(0.0, (int(x.get("exit_ts") or 0) - int(x.get("entry_ts") or 0)) / tf_ms)
        x["cost_to_abs_gross"] = float(x.get("realized_cost_bps") or 0.0) / max(abs(float(x.get("gross_bps") or 0.0)), 1e-9)
    if strategy_id == "trend_rider" and rows:
        _trend_enrichment(receipt, rows)

    streak: list[dict[str, Any]] = []
    for x in reversed(rows):
        if float(x.get("net_bps") or 0.0) <= 0.0:
            streak.append(x)
        else:
            break
    streak.reverse()
    prior = rows[:-len(streak)] if streak else rows[:]
    winners = [x for x in prior if float(x.get("net_bps") or 0.0) > 0]

    candidates: list[dict[str, Any]] = []
    for dim in ("symbol", "side", "session", "reason"):
        if not streak:
            continue
        top, n = Counter(str(x.get(dim)) for x in streak).most_common(1)[0]
        sshare = n / len(streak); bshare = _share(prior, dim, top)
        candidates.append({
            "axis": dim.upper(), "value": top, "loss_streak_share": sshare,
            "prior_share": bshare, "delta_share": sshare - bshare,
            "diagnostic_score": max(0.0, sshare - bshare) * math.log2(2 + len(streak)),
        })

    numeric_keys = ["hold_bars", "realized_cost_bps", "cost_to_abs_gross"]
    if strategy_id == "trend_rider":
        numeric_keys += ["st_gap_atr", "chase_atr", "atr_pct"]
    for key in numeric_keys:
        a = _mean(streak, key); b = _mean(winners or prior, key)
        if a is None or b is None:
            continue
        scale = max(abs(b), 1e-9)
        rel = (a - b) / scale
        candidates.append({
            "axis": key.upper(), "loss_streak_mean": a, "reference_mean": b,
            "relative_delta": rel, "diagnostic_score": min(3.0, abs(rel)) * math.log2(2 + len(streak)) / 2.0,
        })
    candidates.sort(key=lambda x: (-float(x.get("diagnostic_score") or 0.0), str(x.get("axis"))))

    # Hypothesis generation only. No incumbent mutation and no threshold tuning.
    root = candidates[0] if candidates else None
    if len(streak) < 3:
        route = "NO_STREAK_TRIGGER_CONTINUE_COLLECTION"
    elif root is None:
        route = "LOSS_STREAK_PRESENT_BUT_NO_DISCRIMINATING_AXIS"
    elif root["axis"] in {"SIDE", "SYMBOL", "SESSION"}:
        route = f"PREREGISTER_EXCLUSION_OR_CONTEXT_CHILD:{root['axis']}:{root.get('value')}"
    elif root["axis"] in {"CHASE_ATR", "ST_GAP_ATR", "ATR_PCT"}:
        route = f"PREREGISTER_STRUCTURAL_CONTEXT_CHILD:{root['axis']}:BORROW_EXISTING_NON_OUTCOME_THRESHOLD_ONLY"
    elif root["axis"] == "REASON":
        route = f"PREREGISTER_EXIT_GEOMETRY_CHILD:{root.get('value')}:ONE_AXIS_ONLY"
    else:
        route = f"PREREGISTER_DISTINCT_CAUSAL_CHILD:{root['axis']}:ONE_AXIS_ONLY"

    compact_streak = [{k:x.get(k) for k in ("symbol","side","signal_ts","entry_ts","exit_ts","reason","gross_bps","realized_cost_bps","net_bps","session","hold_bars","st_gap_atr","chase_atr","atr_pct") if k in x} for x in streak]
    result = {
        "strategy_id": strategy_id,
        "completed_trades": len(rows),
        "current_loss_streak": len(streak),
        "loss_streak_net_bps": sum(float(x.get("net_bps") or 0.0) for x in streak),
        "loss_streak_trades": compact_streak,
        "prior_trade_count": len(prior),
        "prior_win_count": sum(1 for x in prior if float(x.get("net_bps") or 0.0)>0),
        "categorical_prior": {d:_counts(prior,d) for d in ("symbol","side","session","reason")},
        "ranked_causal_hypotheses": candidates[:8],
        "recommended_route": route,
        "incumbent_mutated": False,
        "post_outcome_threshold_sweep": False,
        "fresh_child_boundary_required": len(streak) >= 3,
        "source_quality_state": ((receipt.get("source_quality_gate") or {}).get("state") if isinstance(receipt.get("source_quality_gate"), Mapping) else None),
        "integrity_defects": list(receipt.get("integrity_defects") or []),
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
        **AUTH,
    }
    result["receipt_sha256"] = sha(result)
    return result


def run(out: Path) -> dict[str, Any]:
    results = []
    with tempfile.TemporaryDirectory(prefix="a1_loss_cluster_") as td:
        for sid in TARGETS:
            receipt = _run_receipt(sid, Path(td) / f"{sid}.json")
            results.append(diagnose(sid, receipt))
    triggered = [x for x in results if int(x["current_loss_streak"]) >= 3]
    row = {
        "schema_version": "zel.a1.recent_loss_cluster_diagnostic.v1",
        "state": "LOSS_CLUSTER_REPAIR_REQUIRED" if triggered else "NO_MULTI_LOSS_CLUSTER_TRIGGER",
        "trigger_min_consecutive_losses": 3,
        "targets": results,
        "triggered_strategy_ids": [x["strategy_id"] for x in triggered],
        "policy": "KEEP_INCUMBENT_FROZEN; DIAGNOSE_NOW; PREREGISTER_ONE_AXIS_CHILD; NEW_FRESH_BOUNDARY; NO_POST_OUTCOME_RETUNE",
        **AUTH,
    }
    row["receipt_sha256"] = sha(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return row


def self_test() -> int:
    fake = {"source":{"interval":"1h"},"trades":[
        {"symbol":"BTC-USDT","side":"long","signal_ts":1,"entry_ts":2,"exit_ts":3,"reason":"TP","gross_bps":100,"realized_cost_bps":10,"net_bps":90},
        {"symbol":"ETH-USDT","side":"long","signal_ts":4,"entry_ts":5,"exit_ts":6,"reason":"SL","gross_bps":-50,"realized_cost_bps":10,"net_bps":-60},
        {"symbol":"ETH-USDT","side":"long","signal_ts":7,"entry_ts":8,"exit_ts":9,"reason":"SL","gross_bps":-50,"realized_cost_bps":10,"net_bps":-60},
        {"symbol":"ETH-USDT","side":"long","signal_ts":10,"entry_ts":11,"exit_ts":12,"reason":"SL","gross_bps":-50,"realized_cost_bps":10,"net_bps":-60}],
        "source_quality_gate":{"state":"PASS"},"integrity_defects":[],"leakage_lookahead":0}
    r = diagnose("break_and_continue", fake)
    assert r["current_loss_streak"] == 3
    assert r["fresh_child_boundary_required"] is True
    assert r["incumbent_mutated"] is False
    print("PASS_A1_RECENT_LOSS_CLUSTER_DIAGNOSTIC_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, default=Path("out/a1_recent_loss_cluster_diagnostic_latest.json")); ap.add_argument("--self-test", action="store_true"); args=ap.parse_args()
    if args.self_test: return self_test()
    r=run(args.out)
    print(json.dumps({"state":r["state"],"triggered":r["triggered_strategy_ids"],"routes":{x['strategy_id']:x['recommended_route'] for x in r['targets']}},sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
