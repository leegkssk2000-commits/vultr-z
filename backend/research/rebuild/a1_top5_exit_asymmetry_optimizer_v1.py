#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "zel.a1.top5_exit_asymmetry_optimizer.v1"
TOP5 = (
    "trend_rider",
    "keltner_trend",
    "break_and_continue",
    "supertrend_pullback",
    "trend_ma_macd",
)
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
TIMEOUT_STAGE = (48, 72, 96, 120)
LOSS_STAGE = (
    (1.00, None, "CURRENT_STOP"),
    (1.00, 1.00, "BE_AFTER_1R"),
    (1.00, 0.75, "FAST_BE_AFTER_0_75R"),
    (0.85, 1.00, "STOP_0_85X_PLUS_BE_1R"),
    (0.85, 0.75, "STOP_0_85X_PLUS_FAST_BE_0_75R"),
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    net = [_finite(x.get("net_bps")) for x in trades]
    wins = [x for x in net if x > 0.0]
    losses = [-x for x in net if x < 0.0]
    win_r = [_finite(x.get("net_r")) for x in trades if _finite(x.get("net_bps")) > 0.0]
    loss_r = [-_finite(x.get("net_r")) for x in trades if _finite(x.get("net_bps")) < 0.0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    pf = ev.profit_factor(gp, gl)
    payoff = (avg_win / avg_loss) if avg_win is not None and avg_loss not in (None, 0.0) else None
    return {
        "completed_trades": len(net),
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": (sum(net) / len(net)) if net else None,
        "profit_factor": pf,
        "realized_payoff": payoff,
        "win_rate": (len(wins) / len(net)) if net else None,
        "max_drawdown_bps": ev.max_drawdown(net),
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "best_win_bps": max(wins) if wins else None,
        "worst_loss_bps": max(losses) if losses else None,
        "avg_win_r": (sum(win_r) / len(win_r)) if win_r else None,
        "avg_loss_r": (sum(loss_r) / len(loss_r)) if loss_r else None,
    }


def _ratio(value: Any, base: Any, *, inverse: bool = False) -> float:
    v, b = _finite(value), _finite(base)
    if b <= 0.0:
        return 1.0 if v <= 0.0 else max(v, 1.0)
    r = max(v, 1e-12) / b
    return (1.0 / max(r, 1e-12)) if inverse else r


def _score(metrics: Mapping[str, Any], baseline: Mapping[str, Any]) -> float:
    vi = _ratio(metrics.get("net_pnl_bps"), baseline.get("net_pnl_bps"))
    fi = _ratio(metrics.get("net_expectancy_bps"), baseline.get("net_expectancy_bps"))
    ni = _ratio(metrics.get("realized_payoff"), baseline.get("realized_payoff"))
    ri = _ratio(metrics.get("max_drawdown_bps"), baseline.get("max_drawdown_bps"))
    return (vi * fi * ni) / max(ri, 1e-12)


def _pareto(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if int(candidate.get("completed_trades") or 0) < 8:
        reasons.append("MIN_SAMPLE_LT_8")
    pairs_ge = (
        ("net_pnl_bps", "NET_PNL_WORSE"),
        ("net_expectancy_bps", "EXPECTANCY_WORSE"),
        ("avg_win_bps", "AVG_WIN_WORSE"),
    )
    for key, reason in pairs_ge:
        c, b = candidate.get(key), baseline.get(key)
        if c is None or b is None or float(c) + 1e-9 < float(b):
            reasons.append(reason)
    c_loss, b_loss = candidate.get("avg_loss_bps"), baseline.get("avg_loss_bps")
    if c_loss is None or b_loss is None or float(c_loss) > float(b_loss) + 1e-9:
        reasons.append("AVG_LOSS_WORSE")
    c_dd, b_dd = candidate.get("max_drawdown_bps"), baseline.get("max_drawdown_bps")
    if c_dd is None or b_dd is None or float(c_dd) > float(b_dd) + 1e-9:
        reasons.append("DRAWDOWN_WORSE")
    return not reasons, reasons


def _candidate_id(timeout_bars: int, stop_scale: float, be_trigger_r: float | None, label: str) -> str:
    be = "none" if be_trigger_r is None else str(be_trigger_r).replace(".", "p")
    return f"{label.lower()}__t{timeout_bars}__s{stop_scale:.2f}__be{be}"


def _build_signals(strategy_id: str) -> dict[str, Any]:
    ledger = _read(ev.LEDGER_PATH)
    inventory = _read(ev.INVENTORY_PATH)
    authority = _read(ev.COST_PATH)
    entry = (ledger.get("strategies") or {}).get(strategy_id)
    if not isinstance(entry, dict):
        raise RuntimeError(f"STRATEGY_MISSING:{strategy_id}")
    boundary = str(entry.get("prospective_boundary_utc") or "")
    if not boundary:
        raise RuntimeError("PROSPECTIVE_BOUNDARY_REQUIRED")
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    module, policy_path, policy_sha = ev.load_policy(strategy_id, inventory)
    cfg = ev.config_instance(module)
    timeframe_ms = int(getattr(cfg, "timeframe_ms"))
    interval = ev.interval_for_ms(timeframe_ms)
    compute, build = ev.policy_functions(module, strategy_id)
    signals_by: dict[str, list[dict[str, Any]]] = {}
    bars_by: dict[str, list[dict[str, Any]]] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    defects: list[str] = []

    for symbol in SYMBOLS:
        snap = ev.fetch_execution_snapshot(symbol, authority)
        bars = ev.fetch_bars(symbol, interval)
        snapshots[symbol] = snap
        bars_by[symbol] = bars
        signals: list[dict[str, Any]] = []
        warmup = int(getattr(cfg, "warmup_bars", max(64, int(getattr(cfg, "lookback", 20)) + 10)))
        for i in range(max(1, warmup), len(bars) - 1):
            if int(bars[i]["ts_ms"]) < boundary_ms:
                continue
            try:
                feature = compute(bars[: i + 1], symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=cfg)
                intent = build(
                    feature,
                    policy_source_sha=policy_sha,
                    verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]),
                    config=cfg,
                )
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "WINDOW_", "ATR_")):
                    continue
                defects.append(f"{symbol}:{int(bars[i]['ts_ms'])}:POLICY:{exc}")
                continue
            if bool(getattr(intent, "no_trade")):
                continue
            sha = ev.intent_sha(intent)
            if sha in seen:
                defects.append(f"DUPLICATE_INTENT:{sha}")
                continue
            seen.add(sha)
            side = str(getattr(intent, "side"))
            if side not in ("long", "short"):
                defects.append(f"UNSUPPORTED_SIDE:{side}")
                continue
            sl = getattr(intent, "sl", None)
            if sl is None:
                defects.append(f"NO_INITIAL_STOP:{sha}")
                continue
            owns, cooldown = ev.execution_ownership_policy(intent)
            entry_bar = bars[i + 1]
            signal_px = float(getattr(feature, "close"))
            base_sl = float(sl)
            base_r = abs(signal_px - base_sl)
            if base_r <= 0.0:
                defects.append(f"NONPOSITIVE_BASE_R:{sha}")
                continue
            signals.append({
                "symbol": symbol,
                "signal_idx": i,
                "entry_idx": i + 1,
                "signal_ts": int(getattr(intent, "signal_ts")),
                "entry_ts": int(entry_bar["ts_ms"]),
                "entry_px": float(entry_bar["open"]),
                "signal_px": signal_px,
                "side": side,
                "base_sl": base_sl,
                "base_r_px": base_r,
                "intent_sha": sha,
                "owns_position": bool(owns),
                "cooldown_bars": int(cooldown),
            })
        signals_by[symbol] = signals

    return {
        "strategy_id": strategy_id,
        "boundary_utc": boundary,
        "policy_path": str(policy_path.relative_to(ROOT)),
        "policy_sha": policy_sha,
        "config_sha": str(getattr(cfg, "sha", ev.stable_sha(asdict(cfg) if is_dataclass(cfg) else vars(cfg)))),
        "timeframe_ms": timeframe_ms,
        "interval": interval,
        "signals_by": signals_by,
        "bars_by": bars_by,
        "snapshots": snapshots,
        "raw_intent_count": sum(len(v) for v in signals_by.values()),
        "integrity_defects": defects,
    }


def _simulate(bundle: Mapping[str, Any], *, timeout_bars: int, stop_scale: float,
              be_trigger_r: float | None, label: str) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    open_count = 0
    rejected = 0
    exit_reasons: dict[str, int] = {"SL": 0, "BE": 0, "TIMEOUT": 0}
    per_symbol: dict[str, dict[str, Any]] = {}
    timeframe_ms = int(bundle["timeframe_ms"])

    for symbol in SYMBOLS:
        bars = list(bundle["bars_by"][symbol])
        snap = dict(bundle["snapshots"][symbol])
        blocked_until_ts = -1
        symbol_trades: list[dict[str, Any]] = []
        symbol_open = 0
        symbol_rejected = 0
        for sig in bundle["signals_by"][symbol]:
            entry_ts = int(sig["entry_ts"])
            owns = bool(sig["owns_position"])
            cooldown = int(sig["cooldown_bars"])
            if owns and ev.ownership_blocked(entry_ts, blocked_until_ts):
                rejected += 1
                symbol_rejected += 1
                continue
            side = 1 if sig["side"] == "long" else -1
            entry_px = float(sig["entry_px"])
            signal_px = float(sig["signal_px"])
            stop = signal_px + (float(sig["base_sl"]) - signal_px) * float(stop_scale)
            initial_r_px = abs(entry_px - stop)
            if initial_r_px <= 0.0:
                raise RuntimeError(f"CANDIDATE_NONPOSITIVE_R:{symbol}:{sig['intent_sha']}")
            effective_stop = float(stop)
            be_armed = False
            entry_idx = int(sig["entry_idx"])
            last_j = min(len(bars) - 1, entry_idx + max(1, int(timeout_bars)))
            exit_px: float | None = None
            exit_ts: int | None = None
            reason: str | None = None
            for j in range(entry_idx, last_j + 1):
                bar = bars[j]
                low, high = float(bar["low"]), float(bar["high"])
                stop_hit = (side == 1 and low <= effective_stop) or (side == -1 and high >= effective_stop)
                if stop_hit:
                    exit_px, exit_ts = effective_stop, int(bar["ts_ms"])
                    reason = "BE" if be_armed and abs(effective_stop - entry_px) <= max(1e-12, entry_px * 1e-12) else "SL"
                    break
                if be_trigger_r is not None and j < last_j:
                    favorable_close = side * (float(bar["close"]) - entry_px)
                    if favorable_close >= float(be_trigger_r) * initial_r_px:
                        if side == 1:
                            effective_stop = max(effective_stop, entry_px)
                        else:
                            effective_stop = min(effective_stop, entry_px)
                        be_armed = True
            if exit_px is None:
                if last_j >= len(bars) - 1:
                    open_count += 1
                    symbol_open += 1
                    if owns:
                        blocked_until_ts = max(
                            blocked_until_ts,
                            ev.reserve_position_ownership(
                                exit_ts=None,
                                open_horizon_ts=int(bars[-1]["ts_ms"]),
                                cooldown_bars=cooldown,
                                timeframe_ms=timeframe_ms,
                            ),
                        )
                    continue
                exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), "TIMEOUT"
            if owns:
                blocked_until_ts = max(
                    blocked_until_ts,
                    ev.reserve_position_ownership(
                        exit_ts=int(exit_ts),
                        open_horizon_ts=None,
                        cooldown_bars=cooldown,
                        timeframe_ms=timeframe_ms,
                    ),
                )
            fee = float(snap["fee_bps"])
            spread = float(snap["spread_bps"])
            impact = float(snap["impact_bps"])
            fund = ev.funding_cost(entry_ts, int(exit_ts), list(snap["funding_rows"]))
            cost = fee + spread + impact + fund
            gross = side * (float(exit_px) - entry_px) / entry_px * 10_000.0
            net = gross - cost
            initial_r_bps = initial_r_px / entry_px * 10_000.0
            row = {
                "symbol": symbol,
                "entry_ts": entry_ts,
                "exit_ts": int(exit_ts),
                "side": sig["side"],
                "reason": reason,
                "net_bps": net,
                "gross_bps": gross,
                "cost_bps": cost,
                "initial_r_bps": initial_r_bps,
                "net_r": net / initial_r_bps,
            }
            trades.append(row)
            symbol_trades.append(row)
            exit_reasons[str(reason)] = exit_reasons.get(str(reason), 0) + 1
        sm = _metrics(symbol_trades)
        sm.update({"open_intents": symbol_open, "ownership_rejected": symbol_rejected})
        per_symbol[symbol] = sm

    m = _metrics(trades)
    admitted = int(m["completed_trades"]) + open_count
    m.update({
        "open_intents": open_count,
        "admitted_total": admitted,
        "ownership_rejected": rejected,
        "raw_intent_count": int(bundle["raw_intent_count"]),
        "exit_reasons": exit_reasons,
    })
    return {
        "candidate_id": _candidate_id(timeout_bars, stop_scale, be_trigger_r, label),
        "label": label,
        "timeout_bars": int(timeout_bars),
        "stop_scale_vs_incumbent": float(stop_scale),
        "be_trigger_r": be_trigger_r,
        "hard_tp_r": None,
        "winner_cap": "UNBOUNDED_NO_HARD_TP",
        "entry_signal_generation_changed": False,
        "notional_policy_changed": False,
        "metrics": m,
        "per_symbol": per_symbol,
    }


def _pick(candidates: Sequence[dict[str, Any]], baseline: Mapping[str, Any]) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    for c in candidates:
        passed, reasons = _pareto(c["metrics"], baseline)
        c["pareto_gate_pass"] = passed
        c["pareto_gate_reasons"] = reasons
        c["score_vs_reference"] = _score(c["metrics"], baseline)
        if passed:
            valid.append(c)
    if not valid:
        raise RuntimeError("BASELINE_MUST_ALWAYS_BE_PARETO_VALID")
    return max(valid, key=lambda x: (float(x["score_vs_reference"]), _finite(x["metrics"].get("net_pnl_bps"))))


def run(strategy_id: str, out: Path) -> dict[str, Any]:
    if strategy_id not in TOP5:
        raise RuntimeError(f"NOT_ACTIVE_TOP5:{strategy_id}")
    bundle = _build_signals(strategy_id)
    if bundle["integrity_defects"]:
        raise RuntimeError("INTEGRITY_DEFECTS:" + "|".join(bundle["integrity_defects"][:5]))

    timeout_candidates = [
        _simulate(bundle, timeout_bars=t, stop_scale=1.0, be_trigger_r=None,
                  label="INCUMBENT_BASELINE" if t == 48 else f"RUNNER_TIMEOUT_{t}")
        for t in TIMEOUT_STAGE
    ]
    baseline = timeout_candidates[0]
    stage_a = _pick(timeout_candidates, baseline["metrics"])

    loss_candidates: list[dict[str, Any]] = []
    for scale, be, label in LOSS_STAGE:
        loss_candidates.append(
            _simulate(bundle, timeout_bars=int(stage_a["timeout_bars"]), stop_scale=scale,
                      be_trigger_r=be, label=label)
        )
    stage_b = _pick(loss_candidates, stage_a["metrics"])

    final_metrics = stage_b["metrics"]
    baseline_metrics = baseline["metrics"]
    final_vs_baseline, final_reasons = _pareto(final_metrics, baseline_metrics)
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TOP5_EXIT_ASYMMETRY_CURRENT_BOUNDARY" if final_vs_baseline else "HOLD_EXIT_INCUMBENT",
        "strategy_id": strategy_id,
        "boundary_utc": bundle["boundary_utc"],
        "symbols": list(SYMBOLS),
        "policy_path": bundle["policy_path"],
        "policy_sha": bundle["policy_sha"],
        "config_sha": bundle["config_sha"],
        "raw_intent_count": bundle["raw_intent_count"],
        "baseline": baseline,
        "stage_a_profit_capture": {
            "axis": "TIME_EXPOSURE_WITH_UNCAPPED_WINNERS",
            "candidates": timeout_candidates,
            "selected": stage_a,
        },
        "stage_b_loss_cap": {
            "axis": "INITIAL_STOP_AND_CAUSAL_BREAK_EVEN",
            "candidates": loss_candidates,
            "selected": stage_b,
        },
        "final_selected": stage_b,
        "final_vs_incumbent_pareto_pass": final_vs_baseline,
        "final_vs_incumbent_reasons": final_reasons,
        "final_score_vs_incumbent": _score(final_metrics, baseline_metrics),
        "selection_semantics": {
            "objective": "MAX_NET_PNL_EXPECTANCY_REALIZED_PAYOFF_PER_DRAWDOWN_WITH_NO_AVG_WIN_OR_AVG_LOSS_REGRESSION",
            "hard_tp": "NONE_UNCAPPED",
            "entry_logic_mutated": False,
            "signal_universe_mutated": False,
            "risk_fraction_mutated": False,
            "notional_policy_mutated": False,
            "numeric_threshold_broad_sweep": False,
            "one_primary_axis_per_stage": True,
            "same_raw_signal_stream_per_candidate": True,
            "ownership_replayed_per_candidate": True,
            "bar_close_break_even_activation_for_next_bar": True,
        },
        "validation": {
            "current_boundary_only": True,
            "independent_fresh_oos_required": True,
            "production_final": False,
            "promotion_authority": False,
            "selection_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
        },
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("FINAL_TOP5_EXIT_RESULT " + json.dumps({
        "strategy_id": strategy_id,
        "state": result["state"],
        "baseline": baseline_metrics,
        "selected_geometry": {
            "timeout_bars": stage_b["timeout_bars"],
            "stop_scale_vs_incumbent": stage_b["stop_scale_vs_incumbent"],
            "be_trigger_r": stage_b["be_trigger_r"],
            "hard_tp_r": None,
        },
        "selected": final_metrics,
        "score": result["final_score_vs_incumbent"],
        "fresh_oos_required": True,
    }, sort_keys=True, allow_nan=False))
    return result


def self_test() -> int:
    base = {
        "completed_trades": 10,
        "net_pnl_bps": 1000.0,
        "net_expectancy_bps": 100.0,
        "avg_win_bps": 200.0,
        "avg_loss_bps": 100.0,
        "max_drawdown_bps": 300.0,
        "realized_payoff": 2.0,
    }
    better = dict(base)
    better.update({"net_pnl_bps": 1200.0, "net_expectancy_bps": 120.0,
                   "avg_win_bps": 220.0, "avg_loss_bps": 90.0, "max_drawdown_bps": 250.0,
                   "realized_payoff": 220.0 / 90.0})
    passed, reasons = _pareto(better, base)
    assert passed and not reasons
    worse_loss = dict(better); worse_loss["avg_loss_bps"] = 101.0
    passed, reasons = _pareto(worse_loss, base)
    assert not passed and "AVG_LOSS_WORSE" in reasons
    assert _score(better, base) > 1.0
    assert TOP5 == ("trend_rider", "keltner_trend", "break_and_continue", "supertrend_pullback", "trend_ma_macd")
    assert TIMEOUT_STAGE[0] == 48 and LOSS_STAGE[0][:2] == (1.0, None)
    print("PASS_A1_TOP5_EXIT_ASYMMETRY_OPTIMIZER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy-id", choices=TOP5)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_exit_asymmetry_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.strategy_id:
        raise SystemExit("--strategy-id required")
    run(args.strategy_id, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
