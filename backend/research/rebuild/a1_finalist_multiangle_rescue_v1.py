from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_finalist_good_regime_attribution_v1 as ga
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions

ROOT = Path(__file__).resolve().parents[3]
LIQUID6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
TARGETS = ("supertrend_pullback", "trend_ma_macd")
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
}


def session(ts_ms: int) -> str:
    h = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour
    return "APAC" if h < 8 else ("EU" if h < 16 else "US")


def metrics(trades: list[dict[str, Any]], values: list[float] | None = None) -> dict[str, Any]:
    vals = values if values is not None else [float(x.get("net_bps") or 0.0) for x in trades]
    n = len(vals)
    wins = sum(v > 0 for v in vals)
    buckets: dict[int, float] = defaultdict(float)
    for t, v in zip(trades, vals):
        buckets[int(t.get("exit_ts") or 0)] += v
    eq = peak = dd = 0.0
    for _, pnl in sorted(buckets.items()):
        eq += pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    pnl = sum(vals)
    return {
        "completed_trades": n,
        "wins": wins,
        "losses": sum(v < 0 for v in vals),
        "win_rate": wins / n if n else None,
        "net_pnl_bps": pnl,
        "net_expectancy_bps": pnl / n if n else None,
        "realized_exit_bucket_max_drawdown_bps": dd,
    }


def pareto(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    higher = ("win_rate", "net_pnl_bps", "net_expectancy_bps")
    lower = ("realized_exit_bucket_max_drawdown_bps",)
    improved: list[str] = []
    worsened: list[str] = []
    for k in higher:
        p, c = parent.get(k), child.get(k)
        if isinstance(p, (int, float)) and isinstance(c, (int, float)):
            if c > p:
                improved.append(k)
            elif c < p:
                worsened.append(k)
    for k in lower:
        p, c = parent.get(k), child.get(k)
        if isinstance(p, (int, float)) and isinstance(c, (int, float)):
            if c < p:
                improved.append(k)
            elif c > p:
                worsened.append(k)
    state = "PARETO_DOMINATES_PARENT" if improved and not worsened else (
        "PARTIAL_SUCCESS" if improved else ("DOMINATED" if worsened else "NEUTRAL")
    )
    return {"relation": state, "improved_metrics": improved, "worsened_metrics": worsened}


def canonical_state_map(states: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in states.items():
        out[k.removeprefix("values.")] = v
    return out


def pairwise_discovery(strategy_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    enriched, defects = ga._feature_states(strategy_id, receipt)
    if defects or len(enriched) != len(receipt.get("trades") or []):
        return {"state": "HOLD_PAIRWISE_FEATURE_AUTHORITY", "defects": defects}
    for t in enriched:
        t["preentry_states"] = canonical_state_map(t["preentry_states"])
        t["context_states"] = {
            "context.side": str(t.get("side") or "").upper(),
            "context.session": session(int(t.get("signal_ts") or 0)),
            "context.symbol": str(t.get("symbol") or ""),
        }
        t["all_states"] = {**t["preentry_states"], **t["context_states"]}

    parent = ga._metrics(enriched)
    state_members: dict[tuple[str, str], set[int]] = defaultdict(set)
    for i, t in enumerate(enriched):
        for axis, state in t["all_states"].items():
            state_members[(axis, state)].add(i)

    unique: list[tuple[str, str, set[int]]] = []
    seen_memberships: set[tuple[int, ...]] = set()
    for (axis, state), idxs in sorted(state_members.items()):
        sig = tuple(sorted(idxs))
        if not sig or sig in seen_memberships:
            continue
        seen_memberships.add(sig)
        unique.append((axis, state, idxs))

    min_support = max(6, math.ceil(len(enriched) / 4))
    pairs: list[dict[str, Any]] = []
    for (a1, s1, i1), (a2, s2, i2) in combinations(unique, 2):
        if a1 == a2:
            continue
        idxs = sorted(i1 & i2)
        if len(idxs) < min_support or len(idxs) == len(enriched):
            continue
        subset = [enriched[i] for i in idxs]
        m = ga._metrics(subset, parent=enriched)
        rel = ga._relation(parent, m)
        if rel["relation"] == "DOMINATED":
            continue
        loo_symbol = []
        for sym in sorted({str(x["symbol"]) for x in subset}):
            rem = [x for x in subset if str(x["symbol"]) != sym]
            if rem:
                loo_symbol.append({"left_out": sym, "net_pnl_bps": ga._metrics(rem)["net_pnl_bps"], "n": len(rem)})
        loo_session = []
        for ses in sorted({session(int(x["signal_ts"])) for x in subset}):
            rem = [x for x in subset if session(int(x["signal_ts"])) != ses]
            if rem:
                loo_session.append({"left_out": ses, "net_pnl_bps": ga._metrics(rem)["net_pnl_bps"], "n": len(rem)})
        robust = all(x["net_pnl_bps"] > 0 for x in loo_symbol + loo_session)
        pairs.append({
            "axis1": a1,
            "state1": s1,
            "axis2": a2,
            "state2": s2,
            "metrics": m,
            "relation": rel,
            "support_floor": min_support,
            "leave_one_symbol_out": loo_symbol,
            "leave_one_session_out": loo_session,
            "robust_positive_after_each_leave_one_out": robust,
            "context_fragile": a1 == "context.symbol" or a2 == "context.symbol",
            "discovery_only": True,
            "fresh_oos_required": True,
        })
    rank = {"PARETO_DOMINATES_PARENT": 0, "PARTIAL_SUCCESS_PRESERVE_FOR_FRESH_PROOF": 1, "NEUTRAL": 2}
    pairs.sort(key=lambda x: (
        0 if x["robust_positive_after_each_leave_one_out"] else 1,
        rank.get(x["relation"]["relation"], 9),
        1 if x["context_fragile"] else 0,
        -float(x["metrics"]["net_pnl_bps"]),
        -float(x["metrics"]["net_expectancy_bps"]),
        -int(x["metrics"]["completed_trades"]),
    ))
    return {
        "state": "PASS_PAIRWISE_DISCOVERY",
        "parent": parent,
        "minimum_pair_support": min_support,
        "candidate_count": len(pairs),
        "top_candidates": pairs[:20],
        "numeric_threshold_sweep": False,
        "runtime_selector_enabled": False,
        "fresh_oos_required": True,
    }


def _net(side: str, entry: float, exit_px: float, cost: float) -> float:
    return (1.0 if side == "long" else -1.0) * (exit_px / entry - 1.0) * 10000.0 - cost


def exit_counterfactual(strategy_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    inventory = ev.load_json(ev.INVENTORY_PATH)
    module, _, _ = ev.load_policy(strategy_id, inventory)
    cfg = ev.config_instance(module)
    compute, _ = policy_functions(module, strategy_id)
    timeframe_ms = int(getattr(cfg, "timeframe_ms"))
    interval = ev.interval_for_ms(timeframe_ms)
    trades = [dict(x) for x in (receipt.get("trades") or [])]
    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by = {s: [dict(x) for x in ev.fetch_bars(s, interval)] for s in symbols}
    idx_by = {s: {int(b["ts_ms"]): i for i, b in enumerate(bars)} for s, bars in bars_by.items()}

    parent_m = metrics(trades)
    native_values: list[float] = []
    firstbar_values: list[float] = []
    native_changed = firstbar_changed = 0

    for t in trades:
        symbol = str(t["symbol"])
        side = str(t["side"])
        bars = bars_by[symbol]
        mp = idx_by[symbol]
        entry_i = mp.get(int(t["entry_ts"]))
        exit_i = mp.get(int(t["exit_ts"]))
        signal_i = mp.get(int(t["signal_ts"]))
        if entry_i is None or exit_i is None or signal_i is None:
            raise RuntimeError(f"BAR_INDEX_MISSING:{strategy_id}:{symbol}")
        original = float(t["net_bps"])

        nv = original
        for j in range(entry_i, exit_i):
            try:
                feat = compute(bars[: j + 1], symbol=symbol, now_ts_ms=int(bars[j]["ts_ms"]), config=cfg)
            except Exception:
                continue
            v = dict(getattr(feat, "values", {}) or {})
            close = float(getattr(feat, "close"))
            if strategy_id == "supertrend_pullback":
                direction = int(v.get("direction", 0))
                ema50 = float(v.get("ema50", close))
                aligned = (direction == 1 and close > ema50) if side == "long" else (direction == -1 and close < ema50)
            else:
                fast = float(v.get("ema_fast", close))
                slow = float(v.get("ema_slow", close))
                aligned = (close > fast > slow) if side == "long" else (close < fast < slow)
            nxt = j + 1
            if not aligned and nxt <= exit_i:
                px = float(bars[nxt]["open"])
                nv = _net(side, float(t["entry"]), px, float(t["realized_cost_bps"]))
                native_changed += 1
                break
        native_values.append(nv)

        fv = original
        j = entry_i
        nxt = j + 1
        if nxt <= exit_i:
            close = float(bars[j]["close"])
            entry = float(t["entry"])
            failed = close <= entry if side == "long" else close >= entry
            if failed:
                px = float(bars[nxt]["open"])
                fv = _net(side, entry, px, float(t["realized_cost_bps"]))
                firstbar_changed += 1
        firstbar_values.append(fv)

    native_m = metrics(trades, native_values)
    firstbar_m = metrics(trades, firstbar_values)
    return {
        "state": "PASS_EXIT_COUNTERFACTUAL_DISCOVERY",
        "parent": parent_m,
        "native_alignment_break_exit": {
            "changed_trades": native_changed,
            "metrics": native_m,
            "relation": pareto(parent_m, native_m),
            "closed_bar_only": True,
            "next_bar_open_execution": True,
        },
        "first_bar_failed_followthrough_exit": {
            "changed_trades": firstbar_changed,
            "metrics": firstbar_m,
            "relation": pareto(parent_m, firstbar_m),
            "closed_bar_only": True,
            "next_bar_open_execution": True,
        },
        "numeric_threshold_sweep": False,
        "post_outcome_runtime_use": False,
        "discovery_only": True,
        "fresh_exit_proof_required": True,
    }


def run(strategy_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    if strategy_id not in TARGETS or str(receipt.get("strategy_id")) != strategy_id:
        raise RuntimeError("STRATEGY_ID_MISMATCH")
    if receipt.get("integrity_defects") or int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("SOURCE_INTEGRITY_FAIL")
    source_symbols = tuple(sorted(str(x.get("symbol")) for x in ((receipt.get("source") or {}).get("symbols") or [])))
    if source_symbols and source_symbols != tuple(sorted(LIQUID6)):
        raise RuntimeError("SOURCE_NOT_FIXED_LIQUID6")
    return {
        "schema_version": "zel.a1.finalist.multiangle_rescue.v1",
        "strategy_id": strategy_id,
        "source_receipt_sha256": receipt.get("receipt_sha256"),
        "source_trade_count": len(receipt.get("trades") or []),
        "fixed_liquid6": list(LIQUID6),
        "pairwise_preentry": pairwise_discovery(strategy_id, receipt),
        "exit_geometry": exit_counterfactual(strategy_id, receipt),
        "strategy_parameters_changed": False,
        "runtime_changed": False,
        "fresh_lanes_changed": False,
        "numeric_threshold_sweep": False,
        "next": "PREREGISTER_ONLY_DISTINCT_ROBUST_PARETO_DISCOVERIES; OTHERWISE_PRESERVE_CURRENT_FRESH_LANES",
        **AUTH,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy-id", choices=TARGETS)
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        assert session(0) == "APAC"
        p = {"win_rate": .5, "net_pnl_bps": 10, "net_expectancy_bps": 1, "realized_exit_bucket_max_drawdown_bps": 5}
        c = {"win_rate": .5, "net_pnl_bps": 11, "net_expectancy_bps": 2, "realized_exit_bucket_max_drawdown_bps": 4}
        assert pareto(p, c)["relation"] == "PARETO_DOMINATES_PARENT"
        print("PASS_A1_FINALIST_MULTIANGLE_RESCUE_V1_SELF_TEST")
        return 0
    if not args.strategy_id or not args.receipt or not args.out:
        ap.error("--strategy-id --receipt --out required")
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    result = run(args.strategy_id, receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    pair = result["pairwise_preentry"]
    ex = result["exit_geometry"]
    print(json.dumps({
        "strategy_id": args.strategy_id,
        "pair_candidates": pair.get("candidate_count"),
        "pair_top": (pair.get("top_candidates") or [None])[0],
        "native_exit": ex["native_alignment_break_exit"]["relation"],
        "firstbar_exit": ex["first_bar_failed_followthrough_exit"]["relation"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
