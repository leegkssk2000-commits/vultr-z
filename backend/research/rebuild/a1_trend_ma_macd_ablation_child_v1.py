#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import concentration, economic_gate, metrics
from backend.research.rebuild.policy_kernel_v1 import ema
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig, compute_trend_ma_macd_feature

ROOT = Path(__file__).resolve().parents[3]
A5 = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
HARD = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
SCHEMA = "zel.a1.trend_ma_macd.ablation_child.v1"
VARIANTS = (
    "ABLATE_PRICE_OVER_FAST_FILTER_ONLY",
    "ABLATE_SLOW_EMA_ALIGNMENT_ONLY",
    "ABLATE_MACD_CONFIRMATION_FIRST_ALIGNMENT_OWNER",
)


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def parse_boundary(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def _macd_hist(closes: list[float]) -> list[float]:
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    signal = ema(macd, 9)
    return [a - b for a, b in zip(macd, signal)]


def _side_for_variant(bars: list[dict[str, Any]], i: int, variant: str, symbol: str) -> tuple[str | None, dict[str, Any], float]:
    cfg = TrendPolicyConfig()
    feature = compute_trend_ma_macd_feature(bars[: i + 1], symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=cfg)
    v = dict(feature.values)
    closes = [float(x["close"]) for x in bars[: i + 1]]
    fast = ema(closes, cfg.ema_fast_len)
    slow = ema(closes, cfg.ema_slow_len)
    hist = _macd_hist(closes)
    close = closes[-1]
    chase_ok = float(v["chase_atr"]) <= 1.5

    if variant == "BASELINE":
        long_ok = bool(v["long_cross"] and chase_ok)
        short_ok = bool(v["short_cross"] and chase_ok)
    elif variant == "ABLATE_PRICE_OVER_FAST_FILTER_ONLY":
        long_ok = bool(fast[-1] > slow[-1] and hist[-2] <= 0 < hist[-1] and chase_ok)
        short_ok = bool(fast[-1] < slow[-1] and hist[-2] >= 0 > hist[-1] and chase_ok)
    elif variant == "ABLATE_SLOW_EMA_ALIGNMENT_ONLY":
        long_ok = bool(close > fast[-1] and hist[-2] <= 0 < hist[-1] and chase_ok)
        short_ok = bool(close < fast[-1] and hist[-2] >= 0 > hist[-1] and chase_ok)
    elif variant == "ABLATE_MACD_CONFIRMATION_FIRST_ALIGNMENT_OWNER":
        prev_close = closes[-2]
        prev_long = prev_close > fast[-2] > slow[-2]
        prev_short = prev_close < fast[-2] < slow[-2]
        long_ok = bool(close > fast[-1] > slow[-1] and not prev_long and chase_ok)
        short_ok = bool(close < fast[-1] < slow[-1] and not prev_short and chase_ok)
    else:
        raise RuntimeError(f"UNKNOWN_VARIANT:{variant}")
    if long_ok == short_ok:
        return None, v, float(feature.atr)
    return ("long" if long_ok else "short"), v, float(feature.atr)


def load_shared_inputs(symbols: list[str], authority: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[int, int]], dict[str, Any]]:
    bars_by: dict[str, list[dict[str, Any]]] = {}
    maps: dict[str, dict[int, int]] = {}
    snapshots: dict[str, Any] = {}
    for symbol in symbols:
        bars = ev.fetch_bars(symbol, "1h", 1000)
        bars_by[symbol] = bars
        maps[symbol] = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
        snapshots[symbol] = ev.fetch_execution_snapshot(symbol, dict(authority))
    return bars_by, maps, snapshots


def simulate(*, variant: str, symbols: list[str], boundary_ms: int, bars_by: Mapping[str, list[dict[str, Any]]], snapshots: Mapping[str, Any]) -> list[dict[str, Any]]:
    cfg = TrendPolicyConfig()
    trades: list[dict[str, Any]] = []
    for symbol in symbols:
        bars = list(bars_by[symbol])
        snap = snapshots[symbol]
        for i in range(64, len(bars) - 1):
            if int(bars[i]["ts_ms"]) < boundary_ms:
                continue
            side, values, a = _side_for_variant(bars, i, variant, symbol)
            if side is None:
                continue
            signal_close = float(bars[i]["close"])
            stop = signal_close - 1.5 * a if side == "long" else signal_close + 1.5 * a
            risk_distance_bps = abs(signal_close - stop) / max(signal_close, 1e-12) * 10_000
            move_budget_bps = risk_distance_bps * 2.0
            if move_budget_bps / max(float(snap["pretrade_verified_cost_bps"]), 1e-12) < cfg.min_cost_budget_ratio:
                continue
            entry_bar = bars[i + 1]
            entry = float(entry_bar["open"])
            last_j = min(len(bars) - 1, i + 1 + cfg.timeout_bars)
            exit_px = exit_ts = reason = None
            for j in range(i + 1, last_j + 1):
                bar = bars[j]
                lo, hi = float(bar["low"]), float(bar["high"])
                if side == "long" and lo <= stop:
                    exit_px, exit_ts, reason = stop, int(bar["ts_ms"]), "SL"
                    break
                if side == "short" and hi >= stop:
                    exit_px, exit_ts, reason = stop, int(bar["ts_ms"]), "SL"
                    break
            if exit_px is None:
                if last_j >= len(bars) - 1:
                    continue
                exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), "TIMEOUT"
            cost = float(snap["fee_bps"]) + float(snap["spread_bps"]) + float(snap["impact_bps"]) + ev.funding_cost(int(entry_bar["ts_ms"]), int(exit_ts), list(snap["funding_rows"]))
            gross = (float(exit_px) - entry) / entry * 10_000 if side == "long" else (entry - float(exit_px)) / entry * 10_000
            trades.append({
                "symbol": symbol, "signal_ts": int(bars[i]["ts_ms"]), "entry_ts": int(entry_bar["ts_ms"]),
                "exit_ts": int(exit_ts), "side": side, "entry": entry, "exit": float(exit_px), "reason": reason,
                "gross_bps": gross, "realized_cost_bps": cost, "net_bps": gross - cost, "variant": variant,
                "feature_state_sha256": stable({"values": values, "signal_ts": int(bars[i]["ts_ms"]), "symbol": symbol}),
            })
    return trades


def identity_set(trades: list[dict[str, Any]]) -> set[tuple[str, int, str]]:
    return {(str(x["symbol"]), int(x["signal_ts"]), str(x["side"])) for x in trades}


def run(parent_path: Path, symbols: list[str], output: Path) -> dict[str, Any]:
    parent = read(parent_path)
    if parent.get("strategy_id") != "trend_ma_macd":
        raise RuntimeError("TREND_MA_MACD_PARENT_REQUIRED")
    if parent.get("execution_authority") not in ("NONE", None) or parent.get("order_authority") not in ("BLOCKED", None):
        raise RuntimeError("PARENT_AUTHORITY_NOT_BLOCKED")
    boundary = str(parent.get("boundary_utc") or "")
    if not boundary:
        raise RuntimeError("PARENT_BOUNDARY_REQUIRED")
    a5, hard, authority = read(A5), read(HARD), read(COST)
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_NOT_FROZEN")
    axes = {str(x["axis"]) for x in a5["strategies"]["trend_ma_macd"]["repair_axes"]}
    if "REDUNDANT_COMPONENT_ABLATION_ONLY" not in axes:
        raise RuntimeError("ABLATION_AXIS_NOT_FROZEN")

    bars_by, maps, snapshots = load_shared_inputs(symbols, authority)
    boundary_ms = parse_boundary(boundary)
    baseline = simulate(variant="BASELINE", symbols=symbols, boundary_ms=boundary_ms, bars_by=bars_by, snapshots=snapshots)
    base_metrics = metrics(baseline)
    base_h5 = concentration(baseline, bars_by, maps, hard)
    base_ids = identity_set(baseline)
    candidates: list[dict[str, Any]] = []

    for variant in VARIANTS:
        child = simulate(variant=variant, symbols=symbols, boundary_ms=boundary_ms, bars_by=bars_by, snapshots=snapshots)
        child_ids = identity_set(child)
        retained = 100.0 * len(base_ids & child_ids) / max(1, len(base_ids))
        m = metrics(child)
        h5 = concentration(child, bars_by, maps, hard)
        econ_ok, blockers = economic_gate(m, retained, hard)
        h5_improved = int(h5["blocker_count"]) < int(base_h5["blocker_count"])
        row = {
            "candidate_id": "trend_ma_macd__ablation_child__" + variant.lower(),
            "changed_axis": "REDUNDANT_COMPONENT_ABLATION_ONLY", "changed_variant": variant, "changed_axis_count": 1,
            "parameter_sweep": False, "post_outcome_threshold_rescue": False, "parent_thresholds_changed": False,
            "parent_cost_model_changed": False, "shared_bar_snapshot": True, "shared_execution_cost_snapshot": True,
            "development_comparator_rebuilt_same_boundary": True, "fresh_prospective_validation_required": True,
            "completed_trades": len(child), "trade_retention_pct": retained, "metrics": m, "concentration": h5,
            "economic_gate_pass": econ_ok, "economic_gate_blockers": blockers,
            "h5_blocker_count_improved_vs_baseline": h5_improved,
            "development_candidate_ready": bool(econ_ok and h5_improved),
            "trade_identity_sha256": stable(sorted(child_ids)),
        }
        row["candidate_sha256"] = stable(row)
        candidates.append(row)

    candidates.sort(key=lambda x: (
        not bool(x["development_candidate_ready"]), int(x["concentration"]["blocker_count"]),
        -float(x["metrics"].get("net_expectancy_bps") or -1e18), -float(x["metrics"].get("profit_factor") or 0.0),
        float(x["metrics"].get("drawdown_bps") or 1e18), -float(x["trade_retention_pct"]), str(x["candidate_id"]),
    ))
    ready = [x for x in candidates if x["development_candidate_ready"]]
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TREND_MA_MACD_ABLATION_CHILD_READY" if ready else "HOLD_TREND_MA_MACD_NEXT_DISTINCT_AXIS_REQUIRED",
        "strategy_id": "trend_ma_macd", "parent_receipt_sha256": parent.get("receipt_sha256"), "boundary_utc": boundary,
        "symbols": symbols,
        "baseline": {"completed_trades": len(baseline), "metrics": base_metrics, "concentration": base_h5, "trade_identity_sha256": stable(sorted(base_ids))},
        "candidates": candidates, "development_ready_count": len(ready), "next_candidate": ready[0] if ready else None,
        "cost_snapshot_sha256_by_symbol": {k: str(v["snapshot_sha256"]) for k, v in snapshots.items()},
        "policy": {
            "one_redundant_component_ablated_per_variant": True, "no_numeric_threshold_sweep": True,
            "parent_chase_and_risk_thresholds_frozen": True, "shared_bar_snapshot": True,
            "shared_execution_cost_snapshot": True, "same_boundary_required": True,
            "development_only": True, "fresh_prospective_validation_required": True,
        },
        "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE",
        "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False,
        "protected_mutations": 0, "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    axes = {x["axis"] for x in read(A5)["strategies"]["trend_ma_macd"]["repair_axes"]}
    assert "REDUNDANT_COMPONENT_ABLATION_ONLY" in axes
    assert len(VARIANTS) == 3
    assert read(HARD)["survivor_gate"]["minimum_retention_pct"] == 60.0
    print("PASS_A1_TREND_MA_MACD_ABLATION_CHILD_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--symbols", default="BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,1INCH-USDT,ETHFI-USDT,HYPE-USDT,BCH-USDT,APE-USDT,1000PEPE-USDT,DOGE-USDT,LINK-USDT")
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_ma_macd_ablation_child_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.parent is None:
        raise SystemExit("--parent required")
    result = run(args.parent, [x.strip() for x in args.symbols.split(",") if x.strip()], args.out)
    print("A1_TREND_MA_MACD_ABLATION_CHILD=" + json.dumps({"state": result["state"], "ready": result["development_ready_count"], "next": (result.get("next_candidate") or {}).get("candidate_id"), "receipt": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
