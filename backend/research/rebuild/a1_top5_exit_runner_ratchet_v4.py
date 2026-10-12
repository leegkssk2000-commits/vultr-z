#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_top5_exit_asymmetry_optimizer_v1 as v1
from backend.research.rebuild import a1_top5_exit_asymmetry_optimizer_v3 as v3

SCHEMA = "zel.a1.top5_exit_runner_ratchet.v4"
BASE_TIMEOUT = 48
RUNNERS = (
    (96, 1.50, 0.75, "RUNNER96_ARM1_5R_TRAIL0_75R"),
    (120, 2.00, 1.00, "RUNNER120_ARM2R_TRAIL1R"),
    (120, 2.50, 1.50, "RUNNER120_ARM2_5R_TRAIL1_5R"),
)


def _simulate_runner(bundle: Mapping[str, Any], *, extension_bars: int, arm_r: float,
                     trail_r: float, label: str) -> dict[str, Any]:
    ev = v1.ev
    trades: list[dict[str, Any]] = []
    open_count = 0
    rejected = 0
    exit_reasons: dict[str, int] = {"SL": 0, "TRAIL": 0, "TIMEOUT": 0}
    per_symbol: dict[str, dict[str, Any]] = {}
    timeframe_ms = int(bundle["timeframe_ms"])

    for symbol in v1.SYMBOLS:
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
            initial_stop = float(sig["base_sl"])
            initial_r_px = abs(entry_px - initial_stop)
            if initial_r_px <= 0.0:
                raise RuntimeError(f"NONPOSITIVE_R:{symbol}:{sig['intent_sha']}")

            effective_stop = initial_stop
            trail_armed = False
            entry_idx = int(sig["entry_idx"])
            base_end = min(len(bars) - 1, entry_idx + BASE_TIMEOUT)
            max_end = min(len(bars) - 1, entry_idx + int(extension_bars))
            exit_px: float | None = None
            exit_ts: int | None = None
            reason: str | None = None

            for j in range(entry_idx, max_end + 1):
                bar = bars[j]
                low, high = float(bar["low"]), float(bar["high"])
                stop_hit = (side == 1 and low <= effective_stop) or (side == -1 and high >= effective_stop)
                if stop_hit:
                    exit_px = effective_stop
                    exit_ts = int(bar["ts_ms"])
                    reason = "TRAIL" if trail_armed else "SL"
                    break

                favorable_close = side * (float(bar["close"]) - entry_px)
                if favorable_close >= float(arm_r) * initial_r_px:
                    trail_armed = True
                if trail_armed and j < max_end:
                    candidate_stop = float(bar["close"]) - side * float(trail_r) * initial_r_px
                    if side == 1:
                        effective_stop = max(effective_stop, candidate_stop)
                    else:
                        effective_stop = min(effective_stop, candidate_stop)

                # Only proven winners may consume time beyond the incumbent 48-bar horizon.
                if j >= base_end and not trail_armed:
                    exit_px = float(bar["close"])
                    exit_ts = int(bar["ts_ms"])
                    reason = "TIMEOUT"
                    break

            if exit_px is None:
                if max_end >= len(bars) - 1:
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
                exit_px = float(bars[max_end]["close"])
                exit_ts = int(bars[max_end]["ts_ms"])
                reason = "TIMEOUT"

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

        sm = v1._metrics(symbol_trades)
        sm.update({"open_intents": symbol_open, "ownership_rejected": symbol_rejected})
        per_symbol[symbol] = sm

    m = v1._metrics(trades)
    m.update({
        "open_intents": open_count,
        "admitted_total": int(m["completed_trades"]) + open_count,
        "ownership_rejected": rejected,
        "raw_intent_count": int(bundle["raw_intent_count"]),
        "exit_reasons": exit_reasons,
    })
    return {
        "candidate_id": label.lower(),
        "label": label,
        "base_timeout_bars": BASE_TIMEOUT,
        "extension_bars": int(extension_bars),
        "runner_arm_r": float(arm_r),
        "runner_trail_r": float(trail_r),
        "stop_scale_vs_incumbent": 1.0,
        "hard_tp_r": None,
        "winner_cap": "UNBOUNDED_UNTIL_CAUSAL_RATCHET_OR_MAX_HORIZON",
        "loser_extension_beyond_48": False,
        "entry_signal_generation_changed": False,
        "metrics": m,
        "per_symbol": per_symbol,
    }


def _pick(rows: Sequence[dict[str, Any]], baseline: Mapping[str, Any]) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    for row in rows:
        passed, reasons = v3._pareto(row["metrics"], baseline)
        row["production_pareto_pass"] = passed
        row["production_pareto_reasons"] = reasons
        row["score_vs_incumbent"] = v1._score(row["metrics"], baseline)
        if passed:
            valid.append(row)
    if not valid:
        raise RuntimeError("INCUMBENT_BASELINE_MUST_PASS")
    return max(valid, key=lambda x: (float(x["score_vs_incumbent"]), v1._finite(x["metrics"].get("net_pnl_bps"))))


def run(strategy_id: str, out: Path) -> dict[str, Any]:
    if strategy_id not in v1.TOP5:
        raise RuntimeError(f"NOT_ACTIVE_TOP5:{strategy_id}")
    bundle = v1._build_signals(strategy_id)
    if bundle["integrity_defects"]:
        raise RuntimeError("INTEGRITY_DEFECTS:" + "|".join(bundle["integrity_defects"][:5]))

    baseline = v1._simulate(bundle, timeout_bars=BASE_TIMEOUT, stop_scale=1.0,
                            be_trigger_r=None, label="INCUMBENT_48_NO_HARD_TP")
    candidates = [baseline]
    for extension, arm, trail, label in RUNNERS:
        candidates.append(_simulate_runner(bundle, extension_bars=extension, arm_r=arm, trail_r=trail, label=label))
    selected = _pick(candidates, baseline["metrics"])
    changed = selected["candidate_id"] != baseline["candidate_id"]

    result = {
        "schema_version": SCHEMA,
        "state": "READY_RUNNER_CHALLENGER_CURRENT_BOUNDARY" if changed else "KEEP_INCUMBENT_EXIT_GEOMETRY",
        "strategy_id": strategy_id,
        "boundary_utc": bundle["boundary_utc"],
        "symbols": list(v1.SYMBOLS),
        "policy_path": bundle["policy_path"],
        "policy_sha": bundle["policy_sha"],
        "raw_intent_count": bundle["raw_intent_count"],
        "baseline": baseline,
        "candidates": candidates,
        "selected": selected,
        "selected_changed": changed,
        "objective": "MIN_LOSS_TAIL_AND_DD_WHILE_MAXIMIZING_UNCAPPED_WINNERS_WITH_ZERO_TRADE_DENSITY_REGRESSION",
        "constraints": {
            "completed_trades_non_decrease": True,
            "admitted_total_non_decrease": True,
            "avg_loss_non_increase": True,
            "worst_loss_non_increase": True,
            "avg_win_non_decrease": True,
            "best_win_non_decrease": True,
            "net_pnl_non_decrease": True,
            "expectancy_non_decrease": True,
            "drawdown_non_increase": True,
            "hard_tp": None,
            "losers_never_extended_past_48": True,
            "runner_stop_updates_after_completed_bar_only": True,
        },
        "validation": {
            "current_boundary_only": True,
            "independent_fresh_oos_required": changed,
            "production_final": not changed,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
        },
    }
    result["receipt_sha256"] = v1.ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("FINAL_TOP5_RUNNER_V4 " + json.dumps({
        "strategy_id": strategy_id,
        "state": result["state"],
        "baseline": baseline["metrics"],
        "selected_id": selected["candidate_id"],
        "selected": selected["metrics"],
        "runner_geometry": {
            "base_timeout_bars": selected.get("base_timeout_bars", selected.get("timeout_bars")),
            "extension_bars": selected.get("extension_bars"),
            "arm_r": selected.get("runner_arm_r"),
            "trail_r": selected.get("runner_trail_r"),
            "hard_tp_r": None,
        },
        "score": selected["score_vs_incumbent"],
        "fresh_oos_required": result["validation"]["independent_fresh_oos_required"],
    }, sort_keys=True, allow_nan=False))
    return result


def self_test() -> int:
    assert BASE_TIMEOUT == 48
    assert len(RUNNERS) == 3
    assert all(x[0] > BASE_TIMEOUT for x in RUNNERS)
    assert all(x[1] > x[2] > 0 for x in RUNNERS)
    base = {
        "completed_trades": 10, "admitted_total": 10,
        "net_pnl_bps": 1000.0, "net_expectancy_bps": 100.0,
        "avg_win_bps": 200.0, "best_win_bps": 500.0,
        "avg_loss_bps": 100.0, "worst_loss_bps": 180.0,
        "max_drawdown_bps": 300.0,
    }
    sparse = dict(base); sparse["completed_trades"] = 9; sparse["admitted_total"] = 9
    passed, reasons = v3._pareto(sparse, base)
    assert not passed and "PRODUCTION_TRADE_COUNT_DECREASE" in reasons
    print("PASS_A1_TOP5_EXIT_RUNNER_RATCHET_V4_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy-id", choices=v1.TOP5)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_exit_runner_v4_latest.json"))
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
