#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
PARENT_PATH = ROOT / "backend/research/rebuild/a1_break_and_continue_production_main_v1.json"
SCHEMA = "zel.a1.break_main.loss_tail_path_replay.v1"
STOP_SCALES = (1.00, 0.90, 0.85, 0.80)
BE_TRIGGERS_R = (None, 1.00, 0.75)
TIMEOUT_BARS = (48, 72, 96)
EPS = 1e-9


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _finite(value: Any) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise RuntimeError(f"NONFINITE:{value}")
    return out


def _metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    net = [_finite(t["net_bps"]) for t in trades]
    wins = [x for x in net if x > 0.0]
    losses = [-x for x in net if x < 0.0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    payoff = (avg_win / avg_loss) if avg_win is not None and avg_loss not in (None, 0.0) else None
    return {
        "completed_trades": len(net),
        "wins": len(wins),
        "win_rate": len(wins) / len(net) if net else None,
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": sum(net) / len(net) if net else None,
        "profit_factor": ev.profit_factor(gp, gl),
        "realized_payoff": payoff,
        "max_drawdown_bps": ev.max_drawdown(net),
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "best_win_bps": max(wins) if wins else None,
        "worst_loss_bps": max(losses) if losses else None,
    }


def _trade_id(row: Mapping[str, Any]) -> str:
    return "|".join(
        [
            str(row["symbol"]),
            str(row["side"]),
            str(int(row["signal_ts"])),
            str(int(row["entry_ts"])),
        ]
    )


def _bar_map(symbols: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    return {symbol: list(ev.fetch_bars(symbol, "1h", limit=1000)) for symbol in sorted(set(symbols))}


def _simulate_trade(
    parent: Mapping[str, Any],
    bars: Sequence[Mapping[str, Any]],
    *,
    stop_scale: float,
    be_trigger_r: float | None,
    timeout_bars: int,
) -> dict[str, Any]:
    entry_ts = int(parent["entry_ts"])
    entry_px = _finite(parent["entry"])
    side_name = str(parent["side"])
    side = 1.0 if side_name == "long" else -1.0
    if side_name not in ("long", "short"):
        raise RuntimeError(f"SIDE_INVALID:{side_name}")

    geometry = parent.get("intent_geometry")
    if not isinstance(geometry, Mapping):
        raise RuntimeError("INTENT_GEOMETRY_REQUIRED")
    original_sl = _finite(geometry["sl"])
    original_r_px = abs(entry_px - original_sl)
    if original_r_px <= 0.0:
        raise RuntimeError(f"NONPOSITIVE_ORIGINAL_R:{_trade_id(parent)}")

    idx_by_ts = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    if entry_ts not in idx_by_ts:
        raise RuntimeError(f"ENTRY_BAR_MISSING:{_trade_id(parent)}")
    entry_idx = idx_by_ts[entry_ts]
    last_idx = entry_idx + int(timeout_bars)
    if last_idx >= len(bars):
        raise RuntimeError(f"TIMEOUT_HORIZON_MISSING:{_trade_id(parent)}:{timeout_bars}")

    stop = entry_px - side * original_r_px * float(stop_scale)
    effective_stop = stop
    be_armed = False
    exit_px: float | None = None
    exit_ts: int | None = None
    reason: str | None = None

    for i in range(entry_idx, last_idx + 1):
        bar = bars[i]
        low, high = _finite(bar["low"]), _finite(bar["high"])
        stop_hit = (side > 0 and low <= effective_stop) or (side < 0 and high >= effective_stop)
        if stop_hit:
            exit_px = effective_stop
            exit_ts = int(bar["ts_ms"])
            reason = "BE" if be_armed and abs(effective_stop - entry_px) <= max(1e-12, entry_px * 1e-12) else "SL"
            break

        if be_trigger_r is not None and i < last_idx:
            favorable_close = side * (_finite(bar["close"]) - entry_px)
            if favorable_close >= float(be_trigger_r) * original_r_px:
                effective_stop = max(effective_stop, entry_px) if side > 0 else min(effective_stop, entry_px)
                be_armed = True

    if exit_px is None:
        exit_px = _finite(bars[last_idx]["close"])
        exit_ts = int(bars[last_idx]["ts_ms"])
        reason = "TIMEOUT"

    cost_bps = _finite(parent["realized_cost_bps"])
    gross_bps = side * (exit_px - entry_px) / entry_px * 10_000.0
    net_bps = gross_bps - cost_bps
    return {
        "trade_id": _trade_id(parent),
        "symbol": parent["symbol"],
        "side": side_name,
        "signal_ts": int(parent["signal_ts"]),
        "entry_ts": entry_ts,
        "exit_ts": int(exit_ts),
        "entry": entry_px,
        "exit": exit_px,
        "reason": reason,
        "gross_bps": gross_bps,
        "realized_cost_bps": cost_bps,
        "net_bps": net_bps,
        "parent_net_bps": _finite(parent["net_bps"]),
        "parent_was_win": _finite(parent["net_bps"]) > 0.0,
        "original_r_bps": original_r_px / entry_px * 10_000.0,
    }


def _candidate(
    parent_trades: Sequence[Mapping[str, Any]],
    bars_by: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    stop_scale: float,
    be_trigger_r: float | None,
    timeout_bars: int,
) -> dict[str, Any]:
    trades = [
        _simulate_trade(
            row,
            bars_by[str(row["symbol"])],
            stop_scale=stop_scale,
            be_trigger_r=be_trigger_r,
            timeout_bars=timeout_bars,
        )
        for row in parent_trades
    ]
    metrics = _metrics(trades)
    winner_retained = sum(1 for t in trades if t["parent_was_win"] and _finite(t["net_bps"]) > 0.0)
    metrics["parent_winner_retained"] = winner_retained
    return {
        "candidate_id": f"stop{stop_scale:.2f}__be{'none' if be_trigger_r is None else str(be_trigger_r)}__t{timeout_bars}",
        "stop_scale": stop_scale,
        "be_trigger_r": be_trigger_r,
        "timeout_bars": timeout_bars,
        "metrics": metrics,
        "trades": trades,
    }


def _gate(candidate: Mapping[str, Any], baseline: Mapping[str, Any], parent_wins: int) -> tuple[bool, list[str]]:
    m = candidate["metrics"]
    reasons: list[str] = []
    if int(m["completed_trades"]) != int(baseline["completed_trades"]):
        reasons.append("T_CHANGED")
    if int(m["parent_winner_retained"]) != int(parent_wins):
        reasons.append("PARENT_WINNER_CLIPPED")
    if _finite(m["win_rate"]) + EPS < _finite(baseline["win_rate"]):
        reasons.append("WR_WORSE")
    if _finite(m["net_pnl_bps"]) <= _finite(baseline["net_pnl_bps"]) + EPS:
        reasons.append("PNL_NOT_BETTER")
    if m["profit_factor"] is None or _finite(m["profit_factor"]) <= _finite(baseline["profit_factor"]) + EPS:
        reasons.append("PF_NOT_BETTER")
    if m["realized_payoff"] is None or _finite(m["realized_payoff"]) <= _finite(baseline["realized_payoff"]) + EPS:
        reasons.append("PAYOFF_NOT_BETTER")
    if _finite(m["max_drawdown_bps"]) > _finite(baseline["max_drawdown_bps"]) + EPS:
        reasons.append("DD_WORSE")
    if _finite(m["avg_win_bps"]) + EPS < _finite(baseline["avg_win_bps"]):
        reasons.append("AVG_WIN_WORSE")
    if _finite(m["avg_loss_bps"]) >= _finite(baseline["avg_loss_bps"]) - EPS:
        reasons.append("AVG_LOSS_NOT_BETTER")
    return not reasons, reasons


def _score(metrics: Mapping[str, Any], baseline: Mapping[str, Any]) -> float:
    pnl = _finite(metrics["net_pnl_bps"]) / max(_finite(baseline["net_pnl_bps"]), EPS)
    pf = _finite(metrics["profit_factor"]) / max(_finite(baseline["profit_factor"]), EPS)
    payoff = _finite(metrics["realized_payoff"]) / max(_finite(baseline["realized_payoff"]), EPS)
    dd = _finite(metrics["max_drawdown_bps"]) / max(_finite(baseline["max_drawdown_bps"]), EPS)
    return (pnl * pf * payoff) / max(dd, EPS)


def run(out_path: Path) -> dict[str, Any]:
    parent = _read(PARENT_PATH)
    if parent.get("state") != "FROZEN_PRODUCTION_MAIN" or parent.get("strategy_id") != "break_and_continue":
        raise RuntimeError("EXACT_BREAK_MAIN_PARENT_REQUIRED")
    if parent.get("execution_authority") != "NONE" or parent.get("order_authority") != "BLOCKED":
        raise RuntimeError("AUTHORITY_NOT_BLOCKED")
    parent_trades = parent.get("trades")
    if not isinstance(parent_trades, list) or len(parent_trades) != 9:
        raise RuntimeError("EXACT_9T_PARENT_REQUIRED")

    baseline = _metrics(parent_trades)
    sealed = parent.get("metrics") or {}
    checks = {
        "completed_trades": (baseline["completed_trades"], sealed.get("trades")),
        "wins": (baseline["wins"], sealed.get("wins")),
        "win_rate": (baseline["win_rate"], sealed.get("win_rate")),
        "net_pnl_bps": (baseline["net_pnl_bps"], sealed.get("net_pnl_bps")),
        "profit_factor": (baseline["profit_factor"], sealed.get("profit_factor")),
        "realized_payoff": (baseline["realized_payoff"], sealed.get("payoff")),
        "max_drawdown_bps": (baseline["max_drawdown_bps"], sealed.get("drawdown_bps")),
    }
    for key, (calc, expected) in checks.items():
        if expected is None or abs(_finite(calc) - _finite(expected)) > 1e-6:
            raise RuntimeError(f"PARENT_METRIC_DRIFT:{key}:{calc}:{expected}")

    bars_by = _bar_map([str(t["symbol"]) for t in parent_trades])
    candidates: list[dict[str, Any]] = []
    for timeout_bars in TIMEOUT_BARS:
        for stop_scale in STOP_SCALES:
            for be_trigger_r in BE_TRIGGERS_R:
                c = _candidate(
                    parent_trades,
                    bars_by,
                    stop_scale=stop_scale,
                    be_trigger_r=be_trigger_r,
                    timeout_bars=timeout_bars,
                )
                passed, reasons = _gate(c, baseline, int(baseline["wins"]))
                c["development_gate_pass"] = passed
                c["gate_reasons"] = reasons
                c["score"] = _score(c["metrics"], baseline) if passed else 0.0
                candidates.append(c)

    passing = sorted((c for c in candidates if c["development_gate_pass"]), key=lambda x: x["score"], reverse=True)
    best = passing[0] if passing else None
    result = {
        "schema_version": SCHEMA,
        "strategy_id": "break_and_continue",
        "lane": "Break Main",
        "parent_path": str(PARENT_PATH.relative_to(ROOT)),
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "parent_metrics": baseline,
        "grid": {
            "stop_scales": list(STOP_SCALES),
            "be_triggers_r": list(BE_TRIGGERS_R),
            "timeout_bars": list(TIMEOUT_BARS),
            "candidate_count": len(candidates),
        },
        "passing_count": len(passing),
        "best_candidate": best,
        "decision": "DEVELOPMENT_CANDIDATE_REQUIRES_FRESH_OOS" if best else "KEEP_INCUMBENT",
        "promotion_allowed": False,
        "requires_fresh_oos": True,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "notes": [
            "Exact 9T parent membership is preserved; no trade deletion is permitted.",
            "Original realized costs are preserved per trade.",
            "Parent winners must remain winners; any winner clipping fails the gate.",
            "This is development path replay only; no candidate may promote without fresh OOS evidence.",
        ],
        "candidates_summary": [
            {
                "candidate_id": c["candidate_id"],
                "development_gate_pass": c["development_gate_pass"],
                "gate_reasons": c["gate_reasons"],
                "score": c["score"],
                "metrics": c["metrics"],
            }
            for c in candidates
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    bars = [
        {"ts_ms": 0, "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5},
        {"ts_ms": 1, "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5},
        {"ts_ms": 2, "open": 101.5, "high": 101.6, "low": 99.8, "close": 100.0},
    ]
    parent = {
        "symbol": "BTC-USDT", "side": "long", "signal_ts": -1, "entry_ts": 0, "entry": 100.0,
        "net_bps": -100.0, "realized_cost_bps": 0.0,
        "intent_geometry": {"sl": 99.0},
    }
    row = _simulate_trade(parent, bars, stop_scale=1.0, be_trigger_r=1.0, timeout_bars=2)
    assert row["reason"] == "BE" and abs(row["net_bps"]) < 1e-9
    print("PASS_BREAK_MAIN_LOSS_TAIL_PATH_REPLAY_SELF_TEST")
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", default="backend/research/rebuild/a1_break_main_loss_tail_path_replay_v1.json")
    args = p.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    result = run(ROOT / args.out)
    best = result.get("best_candidate")
    if best:
        m = best["metrics"]
        print(
            "PASS_BREAK_MAIN_LOSS_TAIL_CANDIDATE",
            best["candidate_id"],
            f"T={m['completed_trades']}",
            f"WR={m['win_rate']:.6f}",
            f"PNL_BPS={m['net_pnl_bps']:.6f}",
            f"PF={m['profit_factor']:.6f}",
            f"PAYOFF={m['realized_payoff']:.6f}",
            f"DD_BPS={m['max_drawdown_bps']:.6f}",
        )
    else:
        print("KEEP_BREAK_MAIN_NO_VALID_LOSS_TAIL_CANDIDATE")


if __name__ == "__main__":
    main()
