#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions

ROOT = Path(__file__).resolve().parents[3]
LIQUID6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
TARGETS = ("supertrend_pullback", "trend_ma_macd")

KEYWORDS = {
    "supertrend_pullback": ("supertrend", "st_gap", "reclaim", "pullback", "depth", "chase", "align"),
    "trend_ma_macd": ("macd", "ema", "chase", "align", "reaccel", "cross"),
}
FORBIDDEN_NAME_PARTS = (
    "pnl", "profit", "loss", "win", "exit", "reason", "hold", "cost", "fee", "slippage",
    "mfe", "mae", "future", "realized", "outcome", "tp", "sl",
)
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
}


def _finite(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    return None


def _scalar_map(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        raw = asdict(value)
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raw = dict(vars(value)) if hasattr(value, "__dict__") else {}
    # Some policy feature dataclasses expose the useful strategy-specific values under .values.
    nested = getattr(value, "values", None)
    if isinstance(nested, Mapping):
        raw = {**raw, **dict(nested)}
    out: dict[str, Any] = {}

    def visit(prefix: str, obj: Any) -> None:
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                visit(f"{prefix}.{k}" if prefix else str(k), v)
            return
        if isinstance(obj, (str, bool, int, float)) and not isinstance(obj, complex):
            if not isinstance(obj, float) or math.isfinite(obj):
                out[prefix.lower()] = obj

    visit("", raw)
    return out


def _allowed(strategy_id: str, key: str) -> bool:
    k = key.lower()
    if any(x in k for x in FORBIDDEN_NAME_PARTS):
        return False
    return any(x in k for x in KEYWORDS[strategy_id])


def _state_rows(strategy_id: str, current: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, str]:
    states: dict[str, str] = {}
    keys = sorted(set(current) | set(previous))
    for key in keys:
        if not _allowed(strategy_id, key):
            continue
        cur = current.get(key)
        prev = previous.get(key)
        cnum = _finite(cur)
        pnum = _finite(prev)
        if cnum is not None and pnum is not None:
            if cnum > pnum:
                states[f"{key}__direction"] = "UP"
            elif cnum < pnum:
                states[f"{key}__direction"] = "DOWN"
            else:
                states[f"{key}__direction"] = "FLAT"
            # Zero is an intrinsic boundary only for signed alignment / spread / MACD-like fields.
            if any(x in key for x in ("macd", "gap", "spread")):
                states[f"{key}__sign"] = "POSITIVE" if cnum > 0 else ("NEGATIVE" if cnum < 0 else "ZERO")
                if pnum <= 0 < cnum:
                    states[f"{key}__zero_cross"] = "CROSS_UP"
                elif pnum >= 0 > cnum:
                    states[f"{key}__zero_cross"] = "CROSS_DOWN"
                else:
                    states[f"{key}__zero_cross"] = "NO_CROSS"
        elif isinstance(cur, (str, bool)):
            states[f"{key}__current"] = str(cur).upper()
    return states


def _dd(trades: list[dict[str, Any]]) -> float:
    buckets: dict[int, float] = defaultdict(float)
    for t in trades:
        buckets[int(t.get("exit_ts") or 0)] += float(t.get("net_bps") or 0.0)
    equity = peak = max_dd = 0.0
    for _, pnl in sorted(buckets.items()):
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _metrics(trades: list[dict[str, Any]], parent: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    n = len(trades)
    wins = [t for t in trades if float(t.get("net_bps") or 0.0) > 0.0]
    losses = [t for t in trades if float(t.get("net_bps") or 0.0) < 0.0]
    pnl = sum(float(t.get("net_bps") or 0.0) for t in trades)
    p_wins = [t for t in (parent or trades) if float(t.get("net_bps") or 0.0) > 0.0]
    p_losses = [t for t in (parent or trades) if float(t.get("net_bps") or 0.0) < 0.0]
    return {
        "completed_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / n) if n else None,
        "net_pnl_bps": pnl,
        "net_expectancy_bps": (pnl / n) if n else None,
        "realized_exit_bucket_max_drawdown_bps": _dd(trades),
        "winner_retention": (len(wins) / len(p_wins)) if p_wins else None,
        "loss_retention": (len(losses) / len(p_losses)) if p_losses else None,
        "trade_retention": (n / len(parent)) if parent else 1.0,
    }


def _relation(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    higher = ("win_rate", "net_pnl_bps", "net_expectancy_bps", "winner_retention")
    lower = ("realized_exit_bucket_max_drawdown_bps", "loss_retention")
    improved: list[str] = []
    worsened: list[str] = []
    for k in higher:
        p, c = _finite(parent.get(k)), _finite(child.get(k))
        if p is None or c is None:
            continue
        if c > p: improved.append(k)
        elif c < p: worsened.append(k)
    for k in lower:
        p, c = _finite(parent.get(k)), _finite(child.get(k))
        if p is None or c is None:
            continue
        if c < p: improved.append(k)
        elif c > p: worsened.append(k)
    if improved and not worsened:
        state = "PARETO_DOMINATES_PARENT"
    elif improved and worsened:
        state = "PARTIAL_SUCCESS_PRESERVE_FOR_FRESH_PROOF"
    elif worsened and not improved:
        state = "DOMINATED"
    else:
        state = "NEUTRAL"
    return {"relation": state, "improved_metrics": improved, "worsened_metrics": worsened}


def _feature_states(strategy_id: str, receipt: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    inventory = ev.load_json(ev.INVENTORY_PATH)
    module, policy_path, policy_sha = ev.load_policy(strategy_id, inventory)
    cfg = ev.config_instance(module)
    compute, _ = policy_functions(module, strategy_id)
    timeframe_ms = int(getattr(cfg, "timeframe_ms"))
    interval = ev.interval_for_ms(timeframe_ms)
    trades = [dict(x) for x in (receipt.get("trades") or [])]
    symbols = sorted({str(x.get("symbol")) for x in trades})
    bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    idx_by_symbol: dict[str, dict[int, int]] = {}
    defects: list[str] = []
    for symbol in symbols:
        bars = [dict(x) for x in ev.fetch_bars(symbol, interval)]
        bars_by_symbol[symbol] = bars
        idx_by_symbol[symbol] = {int(x["ts_ms"]): i for i, x in enumerate(bars)}

    enriched: list[dict[str, Any]] = []
    for trade in trades:
        symbol = str(trade.get("symbol"))
        signal_ts = int(trade.get("signal_ts") or 0)
        i = idx_by_symbol.get(symbol, {}).get(signal_ts)
        if i is None or i < 1:
            defects.append(f"FEATURE_BAR_MISSING:{strategy_id}:{symbol}:{signal_ts}")
            continue
        bars = bars_by_symbol[symbol]
        try:
            cur = compute(bars[: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg)
            prv_ts = int(bars[i - 1]["ts_ms"])
            prv = compute(bars[:i], symbol=symbol, now_ts_ms=prv_ts, config=cfg)
        except Exception as exc:
            defects.append(f"FEATURE_COMPUTE:{strategy_id}:{symbol}:{signal_ts}:{type(exc).__name__}:{exc}")
            continue
        states = _state_rows(strategy_id, _scalar_map(cur), _scalar_map(prv))
        if not states:
            defects.append(f"NO_ALLOWED_FEATURE_STATE:{strategy_id}:{symbol}:{signal_ts}")
            continue
        row = dict(trade)
        row["preentry_states"] = states
        enriched.append(row)
    return enriched, defects


def analyze(strategy_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    if strategy_id not in TARGETS:
        raise RuntimeError("UNSUPPORTED_STRATEGY")
    if str(receipt.get("strategy_id")) != strategy_id:
        raise RuntimeError(f"RECEIPT_STRATEGY_MISMATCH:{strategy_id}:{receipt.get('strategy_id')}")
    if receipt.get("integrity_defects"):
        raise RuntimeError(f"SOURCE_RECEIPT_INTEGRITY:{strategy_id}")
    if int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError(f"SOURCE_RECEIPT_LOOKAHEAD:{strategy_id}")
    source_symbols = tuple(sorted(str(x.get("symbol")) for x in ((receipt.get("source") or {}).get("symbols") or [])))
    if source_symbols and source_symbols != tuple(sorted(LIQUID6)):
        raise RuntimeError(f"NOT_FIXED_LIQUID6:{strategy_id}:{source_symbols}")

    trades, defects = _feature_states(strategy_id, receipt)
    original_n = len(receipt.get("trades") or [])
    authority_match = len(trades) == original_n and not defects
    if not authority_match:
        return {
            "strategy_id": strategy_id,
            "state": "HOLD_FEATURE_ATTRIBUTION_AUTHORITY_MISMATCH",
            "source_trade_count": original_n,
            "enriched_trade_count": len(trades),
            "defects": defects,
            "runtime_selector_enabled": False,
            **AUTH,
        }

    parent = _metrics(trades)
    # Candidate states are finite, strategy-native categorical/ordinal conditions. No numeric cut search.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        for axis, state in trade["preentry_states"].items():
            groups[(axis, state)].append(trade)

    candidates: list[dict[str, Any]] = []
    for (axis, state), subset in sorted(groups.items()):
        child = _metrics(subset, parent=trades)
        rel = _relation(parent, child)
        if rel["relation"] == "DOMINATED":
            continue
        candidates.append({
            "axis": axis,
            "state": state,
            "metrics": child,
            "relation": rel,
            "preentry_only": True,
            "numeric_threshold_fitted": False,
            "runtime_enabled": False,
        })

    relation_rank = {
        "PARETO_DOMINATES_PARENT": 0,
        "PARTIAL_SUCCESS_PRESERVE_FOR_FRESH_PROOF": 1,
        "NEUTRAL": 2,
    }
    candidates.sort(key=lambda x: (
        relation_rank.get(x["relation"]["relation"], 9),
        -float(x["metrics"].get("net_pnl_bps") or -1e99),
        -float(x["metrics"].get("net_expectancy_bps") or -1e99),
        -float(x["metrics"].get("win_rate") or -1e99),
        str(x["axis"]), str(x["state"]),
    ))
    recommended = candidates[0] if candidates else None
    state = "GOOD_REGIME_DISCOVERY_CANDIDATE_FOUND" if recommended else "NO_ONE_AXIS_GOOD_REGIME_DISCOVERY_CANDIDATE"
    return {
        "schema_version": "zel.a1.finalist.good_regime_attribution.v1",
        "strategy_id": strategy_id,
        "state": state,
        "fixed_liquid6": list(LIQUID6),
        "source_receipt_sha256": receipt.get("receipt_sha256"),
        "source_trade_count": original_n,
        "authority_match": True,
        "allowed_feature_keywords": list(KEYWORDS[strategy_id]),
        "parent": parent,
        "candidate_count": len(candidates),
        "recommended_discovery_candidate": recommended,
        "top_candidates": candidates[:12],
        "discovery_only": True,
        "fresh_oos_required": True,
        "identity_h4_h5_required": True,
        "numeric_threshold_sweep": False,
        "post_outcome_runtime_feature_use": False,
        "strategy_parameters_changed": False,
        "runtime_selector_enabled": False,
        "next": "PREREGISTER_ONE_AXIS_FRESH_CHILD_IF_CANDIDATE_FOUND; PRESERVE_PARENT; NO_RUNTIME_BLOCK_OR_BOOST_BEFORE_FRESH_H4_H5",
        "defects": [],
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
        rows = [
            {"net_bps": 10.0, "exit_ts": 2},
            {"net_bps": -4.0, "exit_ts": 3},
            {"net_bps": 8.0, "exit_ts": 4},
        ]
        p = _metrics(rows)
        c = _metrics([rows[0], rows[2]], parent=rows)
        r = _relation(p, c)
        assert c["win_rate"] == 1.0 and c["loss_retention"] == 0.0
        assert r["relation"] in {"PARETO_DOMINATES_PARENT", "PARTIAL_SUCCESS_PRESERVE_FOR_FRESH_PROOF"}, r
        assert _allowed("trend_ma_macd", "values.macd_hist")
        assert not _allowed("trend_ma_macd", "realized_pnl")
        print("PASS_A1_FINALIST_GOOD_REGIME_ATTRIBUTION_V1_SELF_TEST")
        return 0
    if not args.strategy_id or not args.receipt or not args.out:
        ap.error("--strategy-id --receipt --out required")
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    result = analyze(args.strategy_id, receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "strategy_id": result["strategy_id"],
        "state": result["state"],
        "authority_match": result.get("authority_match"),
        "parent": result.get("parent"),
        "recommended": result.get("recommended_discovery_candidate"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
