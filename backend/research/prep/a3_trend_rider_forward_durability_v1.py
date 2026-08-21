from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig, build_trend_rider_intent, compute_trend_rider_feature
from backend.research.prep.a3_forward_context_collector_v1 import fetch_bars

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
POLICY = ROOT / "backend/research/rebuild/trend_policy_batch_v1.py"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def ts_ms(value: str) -> int:
    from datetime import datetime
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def classify(row: dict[str, Any]) -> dict[str, str]:
    trend = float(row["trend_strength"]); vol = float(row["realized_vol_pct"])
    spread = float(row["spread_bps"]); depth = float(row["depth_usdt"])
    funding = float(row["funding_8h_pct"]); oi = float(row["oi_change_pct"])
    hour = int(row.get("session_utc_hour") or 0)
    return {
        "trend_state": "TREND" if abs(trend) >= 0.35 else "RANGE",
        "vol_state": "HIGH_VOL" if vol >= 1.0 else "LOW_VOL",
        "liquidity_state": "THIN" if (spread > 8.0 or depth < 100000.0) else "NORMAL",
        "session_state": "ASIA" if hour <= 7 else ("EU" if hour <= 15 else "US"),
        "funding_oi_state": "CROWDED" if (abs(funding) >= 0.03 and abs(oi) >= 3.0) else "NEUTRAL",
    }


def settle_context(context: dict[str, Any], bars: list[dict[str, Any]], *, policy_sha: str, cost_bps: float) -> dict[str, Any] | None:
    signal_ts = ts_ms(str(context["closed_bar_ts_utc"]))
    index = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
    if signal_ts not in index:
        return {"state": "HOLD_SIGNAL_BAR_NOT_VISIBLE", "symbol": context["symbol"], "signal_ts": signal_ts}
    i = index[signal_ts]
    if i < 64:
        return {"state": "HOLD_SIGNAL_WARMUP", "symbol": context["symbol"], "signal_ts": signal_ts}
    cfg = TrendPolicyConfig()
    feature = compute_trend_rider_feature(bars[:i+1], symbol=str(context["symbol"]), now_ts_ms=signal_ts, config=cfg)
    intent = build_trend_rider_intent(feature, policy_source_sha=policy_sha, verified_round_trip_cost_bps=cost_bps, config=cfg)
    if intent.no_trade:
        return None
    if i + 1 >= len(bars):
        return {"state": "PENDING_ENTRY_BAR", "symbol": context["symbol"], "signal_ts": signal_ts, "side": intent.side, "intent_sha": intent.sha}
    entry_i = i + 1
    entry = float(bars[entry_i]["open"])
    stop = float(intent.sl) if intent.sl is not None else None
    if stop is None:
        return {"state": "HOLD_NO_STOP", "symbol": context["symbol"], "signal_ts": signal_ts}
    timeout_bars = int((intent.timeout or {}).get("bars", cfg.timeout_bars))
    last_i = entry_i + max(1, timeout_bars)
    side = 1 if intent.side == "long" else -1
    exit_px = None; exit_ts = None; reason = None
    scan_last = min(last_i, len(bars)-1)
    for j in range(entry_i, scan_last + 1):
        lo = float(bars[j]["low"]); hi = float(bars[j]["high"])
        if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
            exit_px = stop; exit_ts = int(bars[j]["ts_ms"]); reason = "SL"
            break
    if exit_px is None:
        if last_i >= len(bars):
            return {"state": "PENDING_TIMEOUT", "symbol": context["symbol"], "signal_ts": signal_ts, "side": intent.side, "entry_ts": int(bars[entry_i]["ts_ms"]), "intent_sha": intent.sha}
        exit_px = float(bars[last_i]["close"]); exit_ts = int(bars[last_i]["ts_ms"]); reason = "TIMEOUT"
    gross_bps = side * (float(exit_px) / entry - 1.0) * 10000.0
    net_bps = gross_bps - cost_bps
    return {
        "state": "COMPLETED",
        "symbol": context["symbol"], "signal_ts": signal_ts, "entry_ts": int(bars[entry_i]["ts_ms"]), "exit_ts": exit_ts,
        "side": intent.side, "entry": entry, "exit": float(exit_px), "reason": reason,
        "gross_bps": gross_bps, "cost_bps": cost_bps, "net_bps": net_bps,
        "intent_sha": intent.sha, "feature_sha": intent.feature_sha, "config_sha": intent.config_sha,
        "regime": classify(context), "context_sha256": stable_sha(context),
    }


def metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in rows]
    wins = [x for x in vals if x > 0]; losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    pf = None if gl <= 0 else gp / gl
    payoff = None if not wins or not losses else (gp / len(wins)) / (gl / len(losses))
    return {"trades": len(vals), "net_pnl_bps": sum(vals), "net_expectancy_bps": sum(vals)/len(vals) if vals else None, "profit_factor": pf, "payoff": payoff, "win_rate": len(wins)/len(vals) if vals else None}


def evaluate(context_state: dict[str, Any]) -> dict[str, Any]:
    ledger = read(LEDGER); row = ledger["strategies"]["trend_rider"]
    policy_sha = git_blob_sha(POLICY)
    blockers: list[str] = []
    if policy_sha != str(row.get("policy_sha")):
        blockers.append(f"POLICY_SHA_MISMATCH:{policy_sha}!={row.get('policy_sha')}")
    if context_state.get("blockers"):
        blockers.extend([f"CONTEXT:{x}" for x in context_state.get("blockers") or []])
    cost_bps = float(row.get("verified_pretrade_cost_bps") or 0.0)
    if cost_bps <= 0:
        blockers.append("VERIFIED_COST_MISSING")
    valid_contexts = [x for x in (context_state.get("rows") or []) if isinstance(x, dict) and x.get("valid_for_a3") is True]
    bars_by: dict[str, list[dict[str, Any]]] = {}
    for symbol in sorted({str(x.get("symbol")) for x in valid_contexts if x.get("symbol")}):
        try: bars_by[symbol] = fetch_bars(symbol, 1000)
        except Exception as exc: blockers.append(f"BARS:{symbol}:{type(exc).__name__}:{exc}")
    completed: list[dict[str, Any]] = []; pending: list[dict[str, Any]] = []; signal_count = 0
    if not blockers:
        for context in valid_contexts:
            symbol = str(context["symbol"])
            if symbol not in bars_by: continue
            result = settle_context(context, bars_by[symbol], policy_sha=policy_sha, cost_bps=cost_bps)
            if result is None: continue
            signal_count += 1
            if result.get("state") == "COMPLETED": completed.append(result)
            else: pending.append(result)
    groups: dict[str, dict[str, Any]] = {}
    for dim in ("trend_state", "vol_state", "liquidity_state", "session_state", "funding_oi_state"):
        labels = sorted({x["regime"][dim] for x in completed})
        groups[dim] = {label: metric([x for x in completed if x["regime"][dim] == label]) for label in labels}
    if blockers:
        state = "HOLD_A3_FORWARD_DURABILITY_SOURCE_OR_LINEAGE"
    elif not valid_contexts:
        state = "ACTIVE_A3_FORWARD_WAIT_CONTEXT"
    elif not completed:
        state = "ACTIVE_A3_FORWARD_WAIT_COMPLETED_TRADES"
    else:
        state = "ACTIVE_A3_FORWARD_DURABILITY"
    result = {
        "schema_version": "zel.a3.trend_rider.forward_durability.v1",
        "state": state, "stage": "A3", "candidate_id": "trend_rider",
        "context_receipt_sha256": context_state.get("receipt_sha256"),
        "valid_context_count": len(valid_contexts), "signal_count": signal_count,
        "completed_trade_count": len(completed), "pending_trade_count": len(pending),
        "global_metrics": metric(completed), "regime_metrics": groups,
        "completed_trades": completed, "pending_trades": pending[:50], "blockers": blockers,
        "execution_semantics": "A1_BASELINE_NEXT_BAR_OPEN_INITIAL_SL_48H_TIMEOUT_NO_TP; trailing/runner not newly activated in A3",
        "cost_lineage_bps": cost_bps, "policy_sha": policy_sha,
        "outcome_defined_regime": False, "strategy_retuned": False,
        "final_survivor_decision_made": False,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--context", type=Path, required=True); ap.add_argument("--output", type=Path, default=Path("out/a3_forward_durability_v1.json")); args = ap.parse_args()
    result = evaluate(read(args.context)); args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"state":result["state"],"valid_context_count":result["valid_context_count"],"signal_count":result["signal_count"],"completed_trade_count":result["completed_trade_count"],"pending_trade_count":result["pending_trade_count"],"global_metrics":result["global_metrics"],"blockers":result["blockers"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
