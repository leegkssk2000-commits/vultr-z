#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_trend_ma_macd_ablation_child_v1 as ab
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import concentration, metrics
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig

ROOT = Path(__file__).resolve().parents[3]
HARD = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
SCHEMA = "zel.a1.top6.trend_ma_macd.rr_rescue.v1"
ENTRY_VARIANTS = ("BASELINE", "ABLATE_SLOW_EMA_ALIGNMENT_ONLY")
TP_R_VALUES = (1.0, 1.5, 2.0, 2.5, 3.0)
SL_R_VALUES = (0.45, 0.60, 0.75)
USER_REFERENCE_CELLS = ((2.5, 0.75), (2.0, 0.75), (1.0, 0.45))


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _signals(*, variant: str, symbols: list[str], boundary_ms: int, bars_by: Mapping[str, list[dict[str, Any]]], snapshots: Mapping[str, Any]) -> list[dict[str, Any]]:
    cfg = TrendPolicyConfig()
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        bars = list(bars_by[symbol])
        snap = snapshots[symbol]
        for i in range(64, len(bars) - 1):
            signal_ts = int(bars[i]["ts_ms"])
            if signal_ts < boundary_ms:
                continue
            side, values, atr = ab._side_for_variant(bars, i, variant, symbol)
            if side is None or atr <= 0:
                continue
            signal_close = float(bars[i]["close"])
            native_risk_bps = (1.5 * atr) / max(signal_close, 1e-12) * 10_000
            move_budget_bps = native_risk_bps * 2.0
            if move_budget_bps / max(float(snap["pretrade_verified_cost_bps"]), 1e-12) < cfg.min_cost_budget_ratio:
                continue
            entry_i = i + 1
            last_j = entry_i + int(cfg.timeout_bars)
            if last_j >= len(bars):
                continue
            out.append({
                "symbol": symbol,
                "signal_ts": signal_ts,
                "entry_i": entry_i,
                "last_j": last_j,
                "side": side,
                "atr": float(atr),
                "feature_state_sha256": stable({"values": values, "signal_ts": signal_ts, "symbol": symbol}),
            })
    return out


def _simulate_rr(*, signals: list[dict[str, Any]], tp_r: float, sl_r: float, bars_by: Mapping[str, list[dict[str, Any]]], snapshots: Mapping[str, Any]) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for sig in signals:
        symbol = str(sig["symbol"])
        bars = list(bars_by[symbol])
        snap = snapshots[symbol]
        entry_i = int(sig["entry_i"])
        last_j = int(sig["last_j"])
        entry_bar = bars[entry_i]
        entry = float(entry_bar["open"])
        atr = float(sig["atr"])
        side = str(sig["side"])
        if side == "long":
            stop = entry - sl_r * atr
            target = entry + tp_r * atr
        else:
            stop = entry + sl_r * atr
            target = entry - tp_r * atr

        exit_px = None
        exit_ts = None
        reason = None
        for j in range(entry_i, last_j + 1):
            bar = bars[j]
            lo, hi = float(bar["low"]), float(bar["high"])
            if side == "long":
                hit_sl, hit_tp = lo <= stop, hi >= target
            else:
                hit_sl, hit_tp = hi >= stop, lo <= target
            # Fail-closed intrabar ambiguity: if both can occur inside one OHLC bar, charge the stop first.
            if hit_sl:
                exit_px, exit_ts, reason = stop, int(bar["ts_ms"]), "SL"
                break
            if hit_tp:
                exit_px, exit_ts, reason = target, int(bar["ts_ms"]), "TP"
                break
        if exit_px is None:
            exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), "TIMEOUT"

        funding = ev.funding_cost(int(entry_bar["ts_ms"]), int(exit_ts), list(snap["funding_rows"]))
        cost = float(snap["fee_bps"]) + float(snap["spread_bps"]) + float(snap["impact_bps"]) + funding
        gross = (float(exit_px) - entry) / entry * 10_000 if side == "long" else (entry - float(exit_px)) / entry * 10_000
        trades.append({
            "symbol": symbol,
            "signal_ts": int(sig["signal_ts"]),
            "entry_ts": int(entry_bar["ts_ms"]),
            "exit_ts": int(exit_ts),
            "side": side,
            "entry": entry,
            "exit": float(exit_px),
            "reason": reason,
            "tp_r": tp_r,
            "sl_r": sl_r,
            "gross_bps": gross,
            "realized_cost_bps": cost,
            "net_bps": gross - cost,
            "feature_state_sha256": sig["feature_state_sha256"],
        })
    return trades


def _strict_gate(candidate: Mapping[str, Any], base: Mapping[str, Any], h5: Mapping[str, Any], base_h5: Mapping[str, Any]) -> tuple[bool, list[str]]:
    checks: list[tuple[bool, str]] = [
        (int(candidate.get("trades") or 0) >= int(base.get("trades") or 0), "T_WORSE"),
        (float(candidate.get("win_rate") or 0.0) + 1e-12 >= float(base.get("win_rate") or 0.0), "WR_WORSE"),
        (float(candidate.get("net_pnl_bps") or 0.0) + 1e-9 >= float(base.get("net_pnl_bps") or 0.0), "PNL_WORSE"),
        (float(candidate.get("net_expectancy_bps") or 0.0) + 1e-9 >= float(base.get("net_expectancy_bps") or 0.0), "EXPECTANCY_WORSE"),
        (float(candidate.get("profit_factor") or 0.0) + 1e-12 >= float(base.get("profit_factor") or 0.0), "PF_WORSE"),
        (float(candidate.get("payoff") or 0.0) + 1e-12 >= float(base.get("payoff") or 0.0), "PAYOFF_WORSE"),
        (float(candidate.get("drawdown_bps") or 1e30) <= float(base.get("drawdown_bps") or 0.0) + 1e-9, "DD_WORSE"),
        (int(h5.get("blocker_count") or 0) <= int(base_h5.get("blocker_count") or 0), "CONCENTRATION_WORSE"),
    ]
    reasons = [reason for ok, reason in checks if not ok]
    return not reasons, reasons


def _score(m: Mapping[str, Any], base: Mapping[str, Any]) -> float:
    def ratio(k: str, inverse: bool = False) -> float:
        x, b = float(m.get(k) or 0.0), float(base.get(k) or 0.0)
        if b <= 0:
            return 1.0
        r = max(x, 1e-12) / b
        return 1.0 / max(r, 1e-12) if inverse else r
    return ratio("net_pnl_bps") * ratio("net_expectancy_bps") * ratio("profit_factor") * ratio("payoff") * ratio("drawdown_bps", inverse=True)


def run(parent_path: Path, symbols: list[str], output: Path) -> dict[str, Any]:
    parent = read(parent_path)
    if parent.get("strategy_id") != "trend_ma_macd":
        raise RuntimeError("TREND_MA_MACD_PARENT_REQUIRED")
    boundary = str(parent.get("boundary_utc") or "")
    if not boundary:
        raise RuntimeError("PARENT_BOUNDARY_REQUIRED")
    hard, authority = read(HARD), read(COST)
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_NOT_FROZEN")

    bars_by, maps, snapshots = ab.load_shared_inputs(symbols, authority)
    boundary_ms = ab.parse_boundary(boundary)
    native = ab.simulate(variant="BASELINE", symbols=symbols, boundary_ms=boundary_ms, bars_by=bars_by, snapshots=snapshots)
    base = metrics(native)
    base_h5 = concentration(native, bars_by, maps, hard)

    rows: list[dict[str, Any]] = []
    for variant in ENTRY_VARIANTS:
        signals = _signals(variant=variant, symbols=symbols, boundary_ms=boundary_ms, bars_by=bars_by, snapshots=snapshots)
        for tp_r in TP_R_VALUES:
            for sl_r in SL_R_VALUES:
                trades = _simulate_rr(signals=signals, tp_r=tp_r, sl_r=sl_r, bars_by=bars_by, snapshots=snapshots)
                m = metrics(trades)
                h5 = concentration(trades, bars_by, maps, hard)
                ok, reasons = _strict_gate(m, base, h5, base_h5)
                row = {
                    "candidate_id": f"trend_ma_macd__{variant.lower()}__tp{tp_r:.2f}r__sl{sl_r:.2f}r",
                    "entry_variant": variant,
                    "tp_r": tp_r,
                    "sl_r": sl_r,
                    "nominal_reward_risk": tp_r / sl_r,
                    "user_reference_cell": (tp_r, sl_r) in USER_REFERENCE_CELLS,
                    "metrics": m,
                    "concentration": h5,
                    "strict_rescue_pass": ok,
                    "strict_rescue_blockers": reasons,
                    "score_vs_native": _score(m, base),
                    "entry_signal_count": len(signals),
                    "trade_identity_sha256": stable(sorted((str(t["symbol"]), int(t["signal_ts"]), str(t["side"])) for t in trades)),
                }
                row["candidate_sha256"] = stable(row)
                rows.append(row)

    rows.sort(key=lambda x: (not bool(x["strict_rescue_pass"]), -float(x["score_vs_native"]), -int(x["metrics"].get("trades") or 0), str(x["candidate_id"])))
    passed = [x for x in rows if x["strict_rescue_pass"]]
    best = rows[0] if rows else None
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TOP6_RR_RESCUE_CANDIDATE" if passed else "ROUTE_TREND_MA_MACD_TO_DONOR_NURSERY",
        "strategy_id": "trend_ma_macd",
        "purpose": "Try to rescue the sixth strategy with bounded fixed TP/SL asymmetry while preserving WR/T/economics; if no cell passes, route strategy to material nursery.",
        "boundary_utc": boundary,
        "native_baseline": {"metrics": base, "concentration": base_h5},
        "grid": {"tp_r": list(TP_R_VALUES), "sl_r": list(SL_R_VALUES), "user_reference_cells": [list(x) for x in USER_REFERENCE_CELLS], "entry_variants": list(ENTRY_VARIANTS), "cell_count": len(rows)},
        "strict_gate": ["T_NONDECREASE", "WR_NONDECREASE", "PNL_NONDECREASE", "EXPECTANCY_NONDECREASE", "PF_NONDECREASE", "PAYOFF_NONDECREASE", "DD_NONINCREASE", "CONCENTRATION_NONWORSE"],
        "strict_pass_count": len(passed),
        "best_candidate": best,
        "passed_candidates": passed[:5],
        "candidates": rows,
        "next": "FRESH_VALIDATE_TOP6_RESCUE" if passed else "C_GRADE_DONOR_PAIR_NURSERY",
        "production_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert (2.5, 0.75) in USER_REFERENCE_CELLS
    assert (2.0, 0.75) in USER_REFERENCE_CELLS
    assert (1.0, 0.45) in USER_REFERENCE_CELLS
    assert len(TP_R_VALUES) * len(SL_R_VALUES) * len(ENTRY_VARIANTS) == 30
    assert min(SL_R_VALUES) == 0.45 and max(TP_R_VALUES) == 3.0
    print("PASS_A1_TOP6_TREND_MA_MACD_RR_RESCUE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--symbols", default="BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,1INCH-USDT,ETHFI-USDT,HYPE-USDT,BCH-USDT,APE-USDT,1000PEPE-USDT,DOGE-USDT,LINK-USDT")
    ap.add_argument("--out", type=Path, default=Path("out/a1_top6_trend_ma_macd_rr_rescue_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.parent is None:
        raise SystemExit("--parent required")
    result = run(args.parent, [x.strip() for x in args.symbols.split(",") if x.strip()], args.out)
    b = result.get("best_candidate") or {}
    print("A1_TOP6_TREND_MA_MACD_RR_RESCUE=" + json.dumps({"state": result["state"], "pass": result["strict_pass_count"], "best": b.get("candidate_id"), "best_metrics": b.get("metrics"), "next": result["next"], "receipt": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
