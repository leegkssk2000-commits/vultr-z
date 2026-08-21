from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import trend_policy_batch_v1 as trend
from backend.research.architecture_factory.a1_trend_rider_transition_repair_evaluator_v1 import _eligible
from backend.tools.zel_survivor_tiering_gate_v3 import sha

WORKFLOW_WAKE = "PROSPECTIVE_REPAIR_LANE_BOUND"
ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/prep/a2_cost_turnover_ssot_v1.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
CANDIDATE_ID = "trend_rider_confirm_transition_v1"
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _plus_one_bar(receipt: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
    cfg = trend.TrendPolicyConfig()
    interval = ev.interval_for_ms(cfg.timeframe_ms)
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by = {symbol: ev.fetch_bars(symbol, interval, 1000) for symbol in symbols}
    maps = {symbol: {int(x["ts_ms"]): i for i, x in enumerate(bars_by[symbol])} for symbol in symbols}
    snaps = {symbol: ev.fetch_execution_snapshot(symbol, dict(authority)) for symbol in symbols}
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    vals: list[float] = []
    parent_policy_sha = str(receipt.get("parent_policy_sha") or "")
    if not parent_policy_sha:
        return {"pass": False, "state": "HOLD_PLUS_ONE_BAR", "blockers": ["PARENT_POLICY_SHA_MISSING"], "rows": []}

    for trade in trades:
        symbol = str(trade["symbol"]); bars = bars_by[symbol]; mp = maps[symbol]
        signal_ts = int(trade["signal_ts"]); original_entry_ts = int(trade["entry_ts"])
        if signal_ts not in mp or original_entry_ts not in mp:
            blockers.append(f"BAR_LINEAGE_MISSING:{symbol}:{signal_ts}:{original_entry_ts}"); continue
        signal_i = mp[signal_ts]; entry_i = mp[original_entry_ts]
        if entry_i != signal_i + 1:
            blockers.append(f"ENTRY_NOT_NEXT_BAR:{symbol}:{signal_i}:{entry_i}"); continue
        if signal_i <= 0:
            blockers.append(f"PREVIOUS_SIGNAL_BAR_MISSING:{symbol}:{signal_ts}"); continue
        try:
            cur = trend.compute_trend_rider_feature(bars[:signal_i+1], symbol=symbol, now_ts_ms=signal_ts, config=cfg)
            prev_ts = int(bars[signal_i-1]["ts_ms"])
            prev = trend.compute_trend_rider_feature(bars[:signal_i], symbol=symbol, now_ts_ms=prev_ts, config=cfg)
            long_now, short_now = _eligible(cur); long_prev, short_prev = _eligible(prev)
            long_fire = long_now and not long_prev; short_fire = short_now and not short_prev
            if long_fire == short_fire:
                blockers.append(f"TRANSITION_SIGNAL_NOT_REPRODUCED:{symbol}:{signal_ts}"); continue
            intent = trend.build_trend_rider_intent(
                cur,
                policy_source_sha=parent_policy_sha,
                verified_round_trip_cost_bps=float((receipt.get("execution_snapshots") or {}).get(symbol, {}).get("pretrade_verified_cost_bps") or snaps[symbol]["pretrade_verified_cost_bps"]),
                config=cfg,
            )
        except Exception as exc:
            blockers.append(f"POLICY_REPLAY:{symbol}:{type(exc).__name__}:{exc}"); continue
        side_name = str(getattr(intent, "side")); expected = "long" if long_fire else "short"
        if bool(getattr(intent, "no_trade")) or side_name != expected:
            blockers.append(f"TRANSITION_INTENT_MISMATCH:{symbol}:{signal_ts}"); continue
        if ev.intent_sha(intent) != str(trade.get("parent_intent_sha") or ""):
            blockers.append(f"PARENT_INTENT_SHA_MISMATCH:{symbol}:{signal_ts}"); continue

        delayed_i = entry_i + 1
        timeout = int((getattr(intent, "timeout", {}) or {}).get("bars", cfg.timeout_bars))
        last_i = delayed_i + max(1, timeout)
        if last_i >= len(bars):
            blockers.append(f"PENDING_DELAYED_TIMEOUT:{symbol}:{signal_ts}"); continue
        sl, tp = getattr(intent, "sl", None), getattr(intent, "tp", None)
        if sl is None and tp is None:
            blockers.append(f"NO_EXIT_GEOMETRY:{symbol}:{signal_ts}"); continue
        side = 1 if side_name == "long" else -1
        entry = float(bars[delayed_i]["open"])
        exit_px = exit_ts = reason = None
        for j in range(delayed_i, last_i + 1):
            lo, hi = float(bars[j]["low"]), float(bars[j]["high"])
            if sl is not None and ((side == 1 and lo <= float(sl)) or (side == -1 and hi >= float(sl))):
                exit_px, exit_ts, reason = float(sl), int(bars[j]["ts_ms"]), "SL"; break
            if tp is not None and ((side == 1 and hi >= float(tp)) or (side == -1 and lo <= float(tp))):
                exit_px, exit_ts, reason = float(tp), int(bars[j]["ts_ms"]), "TP"; break
        if exit_px is None:
            exit_px, exit_ts, reason = float(bars[last_i]["close"]), int(bars[last_i]["ts_ms"]), "TIMEOUT"
        snap = snaps[symbol]
        funding = ev.funding_cost(int(bars[delayed_i]["ts_ms"]), int(exit_ts), list(snap["funding_rows"]))
        cost_bps = float(snap["fee_bps"]) + float(snap["spread_bps"]) + float(snap["impact_bps"]) + funding
        gross_bps = side * (float(exit_px) / entry - 1.0) * 10000.0
        net_r = (gross_bps - cost_bps) / 100.0
        vals.append(net_r)
        rows.append({"symbol":symbol,"signal_ts":signal_ts,"delayed_entry_ts":int(bars[delayed_i]["ts_ms"]),"exit_ts":exit_ts,"side":side_name,"reason":reason,"gross_bps":gross_bps,"cost_bps":cost_bps,"net_R":net_r})
    complete = bool(trades) and len(vals) == len(trades) and not blockers
    net_r = sum(vals) if vals else None; exp_r = net_r / len(vals) if vals and net_r is not None else None
    return {
        "pass": complete and exp_r is not None and exp_r > 0.0,
        "state": "PASS_PLUS_ONE_BAR" if complete and exp_r is not None and exp_r > 0.0 else "HOLD_PLUS_ONE_BAR",
        "candidate_trade_count": len(trades), "stress_trade_count": len(vals), "net_R": net_r, "expectancy_R": exp_r,
        "blockers": blockers[:30], "rows": rows,
        "semantics": "same frozen transition signal; fill delayed exactly one 1h bar; original parent SL/TP/48-bar timeout; current public BingX stress costs; no retune",
    }


def evaluate(transition: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    ssot, authority = read(SSOT), read(COST)
    if transition.get("state") != "PASS_A1_CAUSAL_READY_FOR_A2" or transition.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("A1_REPAIR_CAUSAL_READY_REQUIRED")
    if receipt.get("strategy_id") != CANDIDATE_ID:
        raise RuntimeError("A1_A2_REPAIR_IDENTITY_MISMATCH")
    if ((transition.get("evidence") or {}).get("lineage") or {}).get("candidate_receipt_sha256") != receipt.get("receipt_sha256"):
        raise RuntimeError("A1_A2_REPAIR_RECEIPT_LINEAGE_MISMATCH")
    if ssot.get("state") != "A2_PREP_READY" or authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("A2_SSOT_OR_COST_INVALID")
    tiering = transition.get("tiering") if isinstance(transition.get("tiering"), Mapping) else {}
    if tiering.get("a2_entry_allowed") is not True:
        raise RuntimeError("A2_ENTRY_NOT_ALLOWED")
    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    if metrics.get("gross_expectancy_bps") is None:
        raise RuntimeError("GROSS_EXPECTANCY_MISSING")

    symbols = sorted((receipt.get("execution_snapshots") or {}).keys()) or ["BTC-USDT", "ETH-USDT"]
    snaps = {symbol: ev.fetch_execution_snapshot(symbol, authority) for symbol in symbols}
    worst = max(symbols, key=lambda s: float(snaps[s]["pretrade_verified_cost_bps"]))
    one_x = float(snaps[worst]["pretrade_verified_cost_bps"]); two_x = 2.0 * one_x
    p95 = max(float(snaps[s]["funding_p95_abs_bps"]) for s in symbols)
    gross_exp = float(metrics["gross_expectancy_bps"]); one_x_exp = gross_exp - one_x; two_x_exp = gross_exp - two_x
    plus_one = _plus_one_bar(receipt, authority)
    trades = [x for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    boundary = datetime.fromisoformat(str(receipt["boundary_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    end = datetime.fromtimestamp(max(int(x["exit_ts"]) for x in trades) / 1000, tz=timezone.utc)
    elapsed_days = max((end - boundary).total_seconds() / 86400.0, 1e-9); turnover = len(trades) / elapsed_days
    stress = {
        "1X_COST": {"pass": one_x_exp > 0.0, "gross_expectancy_bps": gross_exp, "cost_bps_per_trade": one_x, "net_expectancy_bps": one_x_exp},
        "2X_COST": {"pass": two_x_exp > 0.0, "gross_expectancy_bps": gross_exp, "cost_bps_per_trade": two_x, "net_expectancy_bps": two_x_exp},
        "P95_FUNDING": {"pass": one_x_exp > 0.0, "p95_funding_abs_bps": p95, "cost_bps_per_trade": one_x, "net_expectancy_bps": one_x_exp},
        "PLUS_ONE_BAR": plus_one,
        "TURNOVER": {"pass": len(trades) > 0 and turnover > 0.0, "round_trips": len(trades), "elapsed_days": elapsed_days, "round_trips_per_day": turnover, "cost_bps_total_at_1x": one_x * len(trades), "integrity_defects": list(receipt.get("integrity_defects") or [])},
    }
    passed = all(x.get("pass") is True for x in stress.values()) and not list(receipt.get("integrity_defects") or [])
    result = {
        "schema_version": "zel.a2.trend_rider_transition_repair.v1",
        "stage": "A2",
        "candidate_id": CANDIDATE_ID,
        "state": "PASS_A2_COST_TURNOVER" if passed else "HOLD_A2_COST_TURNOVER",
        "a1_transition_receipt_sha256": transition.get("receipt_sha256"),
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "a1_tier": tiering.get("a1_tier"),
        "a1_activation_mode": tiering.get("activation", {}).get("mode"),
        "cost_authority": {"ssot_sha256":sha(ssot),"cost_authority_sha256":sha(authority),"worst_current_symbol":worst,"one_x_cost_bps":one_x,"two_x_cost_bps":two_x,"funding_p95_abs_bps":p95},
        "stress": stress,
        "stress_contract": ["1X_COST","2X_COST","P95_FUNDING","PLUS_ONE_BAR","TURNOVER"],
        "next_stage_if_pass": "A3_FORWARD_REGIME_DURABILITY",
        "promotion_authority_note": "A2 pass does not grant Survivor; A3 sealed prospective durability remains mandatory.",
        **AUTH,
    }
    result["receipt_sha256"] = sha(result)
    return result


def self_test() -> int:
    ssot = read(SSOT)
    assert WORKFLOW_WAKE == "PROSPECTIVE_REPAIR_LANE_BOUND"
    assert set(ssot.get("stress_contract") or []) >= {"1X_COST","2X_COST","P95_FUNDING","PLUS_ONE_BAR"}
    print("PASS_A2_TREND_RIDER_TRANSITION_REPAIR_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--transition",type=Path); ap.add_argument("--receipt",type=Path); ap.add_argument("--output",type=Path,default=Path("out/a2_trend_rider_transition_repair_v1.json")); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    if args.self_test: return self_test()
    if not args.transition or not args.receipt: raise SystemExit("--transition and --receipt required")
    result=evaluate(read(args.transition),read(args.receipt)); args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"stress":{k:v.get("pass") for k,v in result["stress"].items()},"next":result["next_stage_if_pass"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0 if result["state"] == "PASS_A2_COST_TURNOVER" else 2


if __name__ == "__main__":
    raise SystemExit(main())
