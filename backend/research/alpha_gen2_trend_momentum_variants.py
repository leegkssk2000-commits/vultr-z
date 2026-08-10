#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import alpha_gen2_trend_momentum_base as base


V1 = "TM_GEN2_V1_PRIOR_HIGH_CONFIRM_LONG_V1"
V2 = "TM_GEN2_V2_TWO_CLOSE_PERSISTENCE_LONG_V1"


def replay_variant(rows: list[dict[str, float]], candidate_id: str, fast_n: int, slow_n: int, slope_lag: int) -> dict[str, Any]:
    closes = [float(x["close"]) for x in rows]
    highs = [float(x["high"]) for x in rows]
    fast = base.ema_series(closes, fast_n)
    slow = base.ema_series(closes, slow_n)
    pos: base.Position | None = None
    pending_entry = False
    pending_exit = False
    armed = False
    arm_close: float | None = None
    armed_at: int | None = None
    trades: list[dict[str, Any]] = []
    entry_signals = 0
    exit_signals = 0
    arm_signals = 0
    exposure_bars = 0
    warmup = slow_n + slope_lag

    for i, bar in enumerate(rows):
        if pending_exit and pos is not None:
            trades.append({
                "entry_ts": pos.entry_ts,
                "exit_ts": int(bar["timestamp_ms"]),
                "entry": pos.entry_price,
                "exit": float(bar["open"]),
                "gross_return": float(bar["open"]) / pos.entry_price - 1.0,
                "bars_held": i - pos.entry_i,
            })
            pos = None
            pending_exit = False
        if pending_entry and pos is None:
            pos = base.Position(i, int(bar["timestamp_ms"]), float(bar["open"]))
            pending_entry = False
        if pos is not None:
            exposure_bars += 1

        if i < warmup or i + 1 >= len(rows):
            continue

        close = closes[i]
        prev_close = closes[i - 1]
        slow_rising = slow[i] > slow[i - slope_lag]
        trend_regime = fast[i] > slow[i] and close > slow[i] and slow_rising
        base_recapture = prev_close <= fast[i - 1] and close > fast[i] and close > prev_close

        if pos is not None and not pending_exit:
            trend_broken = close < slow[i] or fast[i] < slow[i] or not slow_rising
            if trend_broken:
                pending_exit = True
                exit_signals += 1
            continue

        if pos is not None or pending_entry:
            continue

        if candidate_id == V1:
            if trend_regime and prev_close <= fast[i - 1] and close > fast[i] and close > highs[i - 1]:
                pending_entry = True
                entry_signals += 1
        elif candidate_id == V2:
            if armed:
                exactly_next_bar = armed_at is not None and i == armed_at + 1
                confirmed = bool(exactly_next_bar and trend_regime and close > fast[i] and arm_close is not None and close > arm_close)
                if confirmed:
                    pending_entry = True
                    entry_signals += 1
                armed = False
                arm_close = None
                armed_at = None
            if not pending_entry and not armed and trend_regime and base_recapture:
                armed = True
                arm_close = close
                armed_at = i
                arm_signals += 1
        else:
            raise SystemExit(f"UNKNOWN_VARIANT:{candidate_id}")

    return {
        "entry_signal_count": entry_signals,
        "exit_signal_count": exit_signals,
        "arm_signal_count": arm_signals,
        "closed_trades": len(trades),
        "open_position_at_end": pos is not None or pending_entry,
        "armed_at_end": armed,
        "exposure_fraction": exposure_bars / len(rows),
        "trades": trades,
    }


def evaluate_symbol(data_root: Path, manifest: dict[str, Any], window: str, symbol: str, plan: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    m = base.manifest_row(manifest, window, symbol)
    path = base.locate_file(data_root, m)
    rows, integ = base.load_csv(path)
    integ.update({
        "manifest_rows_match": len(rows) == int(m["rows"]),
        "manifest_sha_match": integ["sha256"] == m["sha256"],
        "manifest_range_match": integ["first_timestamp_ms"] == int(m["start_ms"]) and integ["last_timestamp_ms"] == int(m["end_ms"]),
    })
    integrity_ok = bool(integ["state"] == "PASS" and integ["manifest_rows_match"] and integ["manifest_sha_match"] and integ["manifest_range_match"])
    if not integrity_ok:
        raise SystemExit(f"HOLD_DATA_INTEGRITY:{window}:{symbol}:{json.dumps(integ,sort_keys=True)}")
    s = plan["shared"]
    r = replay_variant(rows, candidate_id, int(s["fast_ema_bars"]), int(s["slow_ema_bars"]), int(s["slow_slope_lag_bars"]))
    gross_rets = [float(t["gross_return"]) for t in r["trades"]]
    return {
        "window": window,
        "symbol": symbol,
        "integrity_ok": True,
        "integrity": integ,
        "entry_signal_count": r["entry_signal_count"],
        "exit_signal_count": r["exit_signal_count"],
        "arm_signal_count": r["arm_signal_count"],
        "closed_trades": r["closed_trades"],
        "open_position_at_end": r["open_position_at_end"],
        "armed_at_end": r["armed_at_end"],
        "exposure_fraction": r["exposure_fraction"],
        "gross": base.metrics(gross_rets),
        "trades": r["trades"],
    }


def validate_plan(plan: dict[str, Any], terminal: dict[str, Any]) -> None:
    if plan.get("state") != "FROZEN_BEFORE_VARIANT_REPLAY":
        raise SystemExit("HOLD_VARIANT_PLAN_NOT_FROZEN")
    if plan.get("family") != "trend_momentum" or plan.get("predeclared_before_any_variant_replay") is not True:
        raise SystemExit("HOLD_VARIANT_PLAN_STATE")
    ids = [x.get("candidate_id") for x in plan.get("variants", [])]
    if ids != [V1, V2]:
        raise SystemExit(f"HOLD_VARIANT_IDS:{ids}")
    if terminal.get("state") != "FAIL_GEN2_W1_GROSS_EDGE":
        raise SystemExit(f"HOLD_PARENT_NOT_FAILED:{terminal.get('state')}")
    if terminal.get("candidate_id") != plan.get("parent_candidate_id"):
        raise SystemExit("HOLD_PARENT_ID_MISMATCH")
    s = plan.get("shared", {})
    if (int(s.get("fast_ema_bars", -1)), int(s.get("slow_ema_bars", -1)), int(s.get("slow_slope_lag_bars", -1))) != (16, 96, 16):
        raise SystemExit("HOLD_VARIANT_HORIZON_DRIFT")
    if s.get("fill") != "next_bar_open" or s.get("same_bar_fill") is not False:
        raise SystemExit("HOLD_VARIANT_FILL_DRIFT")
    if any(s.get(k) is not None for k in ("stop_loss", "take_profit", "trailing_overlay", "volume_filter")):
        raise SystemExit("HOLD_VARIANT_OVERLAY")
    if s.get("exit_optimization_performed") is not False or s.get("parameter_selection_performed") is not False:
        raise SystemExit("HOLD_VARIANT_OPTIMIZATION")
    if plan.get("execution_authority") != "NONE" or plan.get("order_authority") != "BLOCKED":
        raise SystemExit("HOLD_VARIANT_AUTHORITY")


def public_result(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "trades"}


def aggregate_candidate(rows: list[dict[str, Any]], gate: dict[str, Any], cost: dict[str, float] | None) -> dict[str, Any]:
    trades = [t for r in rows for t in r["trades"]]
    gross = base.metrics([float(t["gross_return"]) for t in trades])
    symbols_with_closed_trade = sum(1 for r in rows if r["closed_trades"] > 0)
    out: dict[str, Any] = {
        "results": [public_result(r) for r in rows],
        "aggregate_gross": gross,
        "symbols_with_closed_trade": symbols_with_closed_trade,
    }
    if cost is None:
        passed = bool(
            gross["trade_count"] >= int(gate["minimum_closed_trades_total"])
            and symbols_with_closed_trade >= int(gate["minimum_symbols_with_closed_trade"])
            and gross["compound_return"] > 0
            and (gross["expectancy_per_trade"] or 0.0) > 0
        )
        out["gate_pass"] = passed
        return out
    net_rets, applied = base.apply_cost(trades, cost)
    net = base.metrics(net_rets)
    passed = bool(
        net["trade_count"] >= int(gate["minimum_closed_trades_total"])
        and symbols_with_closed_trade >= int(gate["minimum_symbols_with_closed_trade"])
        and net["compound_return"] > 0
        and (net["expectancy_per_trade"] or 0.0) > 0
    )
    out["aggregate_net"] = net
    out["cost_applied"] = applied
    out["gate_pass"] = passed
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("w1_gross", "w2_cost"), required=True)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--parent-terminal", type=Path, required=True)
    ap.add_argument("--w1-receipt", type=Path)
    ap.add_argument("--cost-model", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    plan = json.loads(ns.plan.read_text())
    terminal = json.loads(ns.parent_terminal.read_text())
    validate_plan(plan, terminal)
    manifest = base.load_manifest(ns.manifest)
    data = plan["data"]
    window = data["development_window"] if ns.mode == "w1_gross" else data["oos_window"]

    if ns.mode == "w1_gross":
        if ns.cost_model is not None:
            raise SystemExit("HOLD_W1_MUST_NOT_ACCESS_COST")
        candidate_ids = [x["candidate_id"] for x in plan["variants"]]
        cost_env = None
        gate = plan["w1_gross_gate"]
    else:
        if ns.w1_receipt is None or not ns.w1_receipt.is_file():
            raise SystemExit("HOLD_VARIANT_W1_RECEIPT_REQUIRED")
        w1 = json.loads(ns.w1_receipt.read_text())
        candidate_ids = list(w1.get("W1_passing_candidates", []))
        if not candidate_ids:
            raise SystemExit("HOLD_NO_W1_PASSING_VARIANT")
        if ns.cost_model is None or not ns.cost_model.is_file():
            raise SystemExit("HOLD_VARIANT_COST_REQUIRED")
        cost_raw = json.loads(ns.cost_model.read_text())
        base.require_cost(cost_raw)
        cost_env = base.worst_cost(cost_raw)
        gate = plan["w2_cost_gate"]

    candidate_rows: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        rows = [evaluate_symbol(ns.data_root, manifest, window, symbol, plan, candidate_id) for symbol in plan["shared"]["symbols"]]
        agg = aggregate_candidate(rows, gate, cost_env)
        agg["candidate_id"] = candidate_id
        candidate_rows.append(agg)

    passing = [x["candidate_id"] for x in candidate_rows if x["gate_pass"]]
    if ns.mode == "w1_gross":
        state = "PASS_GEN2_VARIANTS_W1_GROSS_EDGE_EXISTS" if passing else "FAIL_GEN2_VARIANTS_W1_GROSS_EDGE"
    else:
        state = "PASS_GEN2_VARIANTS_W2_NET_EDGE_HOLD_DD_SSOT" if passing else "FAIL_GEN2_VARIANTS_W2_NET_EDGE"

    receipt: dict[str, Any] = {
        "schema_version": "zel.alpha_gen2.trend_momentum_variants.replay.v1",
        "state": state,
        "mode": ns.mode,
        "family": "trend_momentum",
        "parent_candidate_id": plan["parent_candidate_id"],
        "variants_predeclared_before_replay": True,
        "parameter_selection_performed": False,
        "exit_optimization_performed": False,
        "variant_selection_on_W1_performed": False,
        "window": window,
        "candidate_rows": candidate_rows,
        "W1_passing_candidates": passing if ns.mode == "w1_gross" else None,
        "W2_passing_candidates": passing if ns.mode == "w2_cost" else None,
        "W3_untouched": True,
        "DD_gate_required_next": bool(ns.mode == "w2_cost" and passing),
        "DD_gate_resolved": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold" if passing else "route_change"
    }
    if ns.mode == "w2_cost":
        cost_raw = json.loads(ns.cost_model.read_text())
        receipt["cost_source"] = {
            "receipt_sha256": cost_raw["receipt_sha256"],
            "source_tier": cost_raw["source_tier"],
            "calibration_mode": cost_raw["calibration_mode"],
            "observed_at": cost_raw.get("observed_at"),
            "worst_available_cost_envelope": cost_env
        }

    material = dict(receipt)
    receipt["receipt_sha256"] = base.canonical_sha(material)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(state)
    for row in candidate_rows:
        g = row["aggregate_gross"]
        n = row.get("aggregate_net")
        print(json.dumps({
            "candidate_id": row["candidate_id"],
            "trades": g["trade_count"],
            "gross_compound": g["compound_return"],
            "gross_expectancy": g["expectancy_per_trade"],
            "gross_pf": g["profit_factor"],
            "gross_wr": g["win_rate"],
            "net_compound": None if n is None else n["compound_return"],
            "net_expectancy": None if n is None else n["expectancy_per_trade"],
            "gate_pass": row["gate_pass"]
        }, sort_keys=True))


if __name__ == "__main__":
    main()
