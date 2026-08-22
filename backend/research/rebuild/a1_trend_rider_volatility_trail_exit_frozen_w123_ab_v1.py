#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact
from backend.research.rebuild import a1_trend_rider_fresh_w123_audit_v1 as w123
from backend.research.rebuild import trend_policy_batch_v1 as parent_policy

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
SCHEMA = "zel.a1_trend_rider_volatility_trail_exit_frozen_w123_ab.v1"
BASELINE_IDENTITY = "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
AXIS = "VOLATILITY_ADAPTIVE_TRAIL_EXIT_ONLY"
FROZEN_OBSERVATION_RUN_ID = 32436283144
FROZEN_BOUNDARY_UTC = "2026-08-16T18:45:01Z"
FROZEN_LAST_POST_BOUNDARY_TS = 1787274000000
ATR_LEN = 14
TRAIL_ATR_MULT = 1.5
EXPECTED_PARENT = {
    "trades": 22,
    "win_rate": 0.5909090909090909,
    "net_pnl_bps": 16509.276493685335,
    "net_expectancy_bps": 750.4216588038788,
    "profit_factor": 29.24609724094979,
    "payoff": 20.247298089888314,
    "drawdown_bps": 474.30214106823223,
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _run_parent_exact(out: Path) -> dict[str, Any]:
    inventory = _read(INVENTORY)
    with tempfile.TemporaryDirectory(prefix="trend_rider_volatility_trail_ab_") as td:
        inv = Path(td) / "inventory.json"
        inv.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        old_inventory = exact.v1.INVENTORY_PATH
        old_argv = sys.argv[:]
        try:
            exact.v1.INVENTORY_PATH = inv
            sys.argv = [old_argv[0], "--strategy-id", "trend_rider", "--out", str(out), "--terminal-replay"]
            exact.main()
        finally:
            exact.v1.INVENTORY_PATH = old_inventory
            sys.argv = old_argv
    return _read(out)


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (str(row.get("symbol")), int(row.get("signal_ts")), int(row.get("entry_ts")), str(row.get("side")))


def _freeze_parent(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if str(receipt.get("boundary_utc")) != FROZEN_BOUNDARY_UTC:
        raise RuntimeError("FROZEN_BOUNDARY_DRIFT")
    boundary_ms = int(datetime.fromisoformat(FROZEN_BOUNDARY_UTC.replace("Z", "+00:00")).timestamp() * 1000)
    w123_end = boundary_ms + 3 * 86_400_000
    rows = [
        copy.deepcopy(x)
        for x in (receipt.get("trades") or [])
        if boundary_ms <= int(x.get("entry_ts")) < w123_end
        and int(x.get("exit_ts")) < FROZEN_LAST_POST_BOUNDARY_TS
    ]
    out = copy.deepcopy(dict(receipt))
    out["trades"] = rows
    out["completed_trades"] = len(rows)
    out["frozen_observation"] = {
        "run_id": FROZEN_OBSERVATION_RUN_ID,
        "boundary_utc": FROZEN_BOUNDARY_UTC,
        "last_post_boundary_ts": FROZEN_LAST_POST_BOUNDARY_TS,
        "completion_cutoff_rule": "exit_ts_strictly_before_last_observed_bar",
    }
    return out


def _matches_expected(m: Mapping[str, Any]) -> bool:
    for key, expected in EXPECTED_PARENT.items():
        actual = m.get(key)
        if not isinstance(actual, (int, float)):
            return False
        if key == "trades":
            if int(actual) != int(expected):
                return False
        elif not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-9):
            return False
    return True


def _load_bars(symbols: set[str]) -> dict[str, list[dict[str, Any]]]:
    return {symbol: exact.v1.fetch_bars(symbol, "1h") for symbol in sorted(symbols)}


def _trail_exit(row: Mapping[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    out = copy.deepcopy(dict(row))
    by_ts = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    entry_ts = int(row["entry_ts"])
    parent_exit_ts = int(row["exit_ts"])
    if entry_ts not in by_ts or parent_exit_ts not in by_ts:
        raise RuntimeError(f"BAR_COVERAGE_MISSING:{row['symbol']}:{entry_ts}:{parent_exit_ts}")
    entry_i = by_ts[entry_ts]
    parent_exit_i = by_ts[parent_exit_ts]
    side = str(row["side"])
    if side not in {"long", "short"}:
        raise RuntimeError(f"SIDE_UNSUPPORTED:{side}")

    entry = float(row["entry"])
    high_water = entry
    low_water = entry
    trail: float | None = None
    activated = False
    chosen: tuple[int, float, float, float] | None = None

    # At bar j open, only bars through j-1 are closed and may update ATR/watermark/trail.
    # Parent exit bar is excluded to avoid any ambiguous same-bar ordering versus the canonical parent exit.
    for j in range(entry_i + 1, parent_exit_i):
        prev_bar = bars[j - 1]
        high_water = max(high_water, float(prev_bar["high"]))
        low_water = min(low_water, float(prev_bar["low"]))
        atr_prev = float(parent_policy.atr(bars[:j], ATR_LEN))
        if side == "long" and high_water > entry:
            candidate = high_water - TRAIL_ATR_MULT * atr_prev
            trail = candidate if trail is None else max(trail, candidate)
            activated = True
        elif side == "short" and low_water < entry:
            candidate = low_water + TRAIL_ATR_MULT * atr_prev
            trail = candidate if trail is None else min(trail, candidate)
            activated = True

        if trail is None:
            continue
        bar = bars[j]
        bar_open = float(bar["open"])
        if side == "long" and float(bar["low"]) <= trail:
            fill = min(bar_open, trail)
            chosen = (j, fill, trail, atr_prev)
            break
        if side == "short" and float(bar["high"]) >= trail:
            fill = max(bar_open, trail)
            chosen = (j, fill, trail, atr_prev)
            break

    if chosen is None:
        out["volatility_trail_changed"] = False
        out["volatility_trail_activated"] = activated
        return out

    fill_i, exit_px, trail_level, atr_used = chosen
    direction = 1.0 if side == "long" else -1.0
    gross = direction * (exit_px - entry) / entry * 10_000.0
    # Conservative: no credit for reduced funding/holding duration.
    cost = float(row["realized_cost_bps"])
    out.update({
        "exit": float(exit_px),
        "exit_ts": int(bars[fill_i]["ts_ms"]),
        "reason": "VOLATILITY_ADAPTIVE_TRAIL",
        "gross_bps": gross,
        "realized_cost_bps": cost,
        "net_bps": gross - cost,
        "volatility_trail_changed": True,
        "volatility_trail_activated": True,
        "trail_fill_ts": int(bars[fill_i]["ts_ms"]),
        "trail_level": float(trail_level),
        "trail_atr_used": float(atr_used),
        "trail_high_water": float(high_water),
        "trail_low_water": float(low_water),
        "parent_exit_ts": parent_exit_ts,
        "parent_exit": float(row["exit"]),
        "parent_reason": str(row["reason"]),
        "cost_rule": "inherit_full_parent_realized_cost_bps_no_early_exit_credit",
    })
    return out


def _child_receipt(parent_frozen: Mapping[str, Any], bars_by_symbol: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = []
    for row in parent_frozen.get("trades") or []:
        symbol = str(row["symbol"])
        if symbol not in bars_by_symbol:
            raise RuntimeError(f"SYMBOL_BARS_MISSING:{symbol}")
        rows.append(_trail_exit(row, bars_by_symbol[symbol]))
    out = copy.deepcopy(dict(parent_frozen))
    out["trades"] = rows
    out["completed_trades"] = len(rows)
    out["exit_axis"] = AXIS
    out["atr_len"] = ATR_LEN
    out["trail_atr_mult"] = TRAIL_ATR_MULT
    out["entry_policy_unchanged"] = True
    out["threshold_sweep"] = False
    out["best_horizon_selection"] = False
    out["post_outcome_trade_deletion"] = False
    return out


def _metric_delta(parent: Mapping[str, Any], child: Mapping[str, Any], key: str, *, lower_better: bool = False) -> dict[str, Any]:
    p = parent.get(key)
    c = child.get(key)
    delta = None if not isinstance(p, (int, float)) or not isinstance(c, (int, float)) else float(c) - float(p)
    improvement = None if delta is None else (-delta if lower_better else delta)
    return {"parent": p, "child": c, "delta_child_minus_parent": delta, "improvement": improvement, "lower_is_better": lower_better}


def run(output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    parent_path = output.parent / "trend_rider_parent_current_receipt.json"
    parent_current = _run_parent_exact(parent_path)
    parent_frozen = _freeze_parent(parent_current)
    parent_audit = w123.run(parent_frozen)
    p = parent_audit["aggregate"]
    parent_anchor_match = _matches_expected(p)

    symbols = {str(x["symbol"]) for x in parent_frozen.get("trades") or []}
    bars_by_symbol = _load_bars(symbols)
    child_frozen = _child_receipt(parent_frozen, bars_by_symbol)
    child_audit = w123.run(child_frozen)
    c = child_audit["aggregate"]

    parent_rows = list(parent_frozen.get("trades") or [])
    child_rows = list(child_frozen.get("trades") or [])
    parent_ids = [_identity(x) for x in parent_rows]
    child_ids = [_identity(x) for x in child_rows]
    same_entry_set = parent_ids == child_ids
    same_entry_geometry = len(parent_rows) == len(child_rows) and all(
        _identity(a) == _identity(b)
        and math.isclose(float(a["entry"]), float(b["entry"]), rel_tol=0.0, abs_tol=1e-12)
        for a, b in zip(parent_rows, child_rows)
    )
    changed = [x for x in child_rows if bool(x.get("volatility_trail_changed"))]
    activated = [x for x in child_rows if bool(x.get("volatility_trail_activated"))]
    retention = 100.0 if same_entry_set and len(parent_rows) == len(child_rows) else (100.0 * len(child_rows) / max(1, len(parent_rows)))
    direct_ab = bool(parent_anchor_match and same_entry_set and same_entry_geometry and len(parent_rows) == 22)

    deltas = {
        "win_rate": _metric_delta(p, c, "win_rate"),
        "net_expectancy_bps": _metric_delta(p, c, "net_expectancy_bps"),
        "net_pnl_bps": _metric_delta(p, c, "net_pnl_bps"),
        "profit_factor": _metric_delta(p, c, "profit_factor"),
        "payoff": _metric_delta(p, c, "payoff"),
        "drawdown_bps": _metric_delta(p, c, "drawdown_bps", lower_better=True),
        "trades": _metric_delta(p, c, "trades"),
    }
    expectancy_improved = isinstance(c.get("net_expectancy_bps"), (int, float)) and float(c["net_expectancy_bps"]) > float(p["net_expectancy_bps"])
    net_improved = isinstance(c.get("net_pnl_bps"), (int, float)) and float(c["net_pnl_bps"]) > float(p["net_pnl_bps"])
    dd_improved = isinstance(c.get("drawdown_bps"), (int, float)) and float(c["drawdown_bps"]) < float(p["drawdown_bps"])
    wr_non_regression = isinstance(c.get("win_rate"), (int, float)) and float(c["win_rate"]) >= float(p["win_rate"])
    robustness_improved = bool(
        (isinstance(c.get("profit_factor"), (int, float)) and isinstance(p.get("profit_factor"), (int, float)) and float(c["profit_factor"]) > float(p["profit_factor"]))
        or (isinstance(c.get("payoff"), (int, float)) and isinstance(p.get("payoff"), (int, float)) and float(c["payoff"]) > float(p["payoff"]))
        or dd_improved
    )
    screen_pass = bool(
        direct_ab
        and len(changed) > 0
        and retention == 100.0
        and child_audit.get("economics_gate_pass") is True
        and expectancy_improved
        and net_improved
        and dd_improved
        and wr_non_regression
        and robustness_improved
    )

    if not parent_anchor_match:
        state = "HOLD_FROZEN_PARENT_W123_AUTHORITY_MISMATCH"
    elif not direct_ab:
        state = "HOLD_VOLATILITY_TRAIL_DIRECT_AB_INTEGRITY"
    elif not changed:
        state = "FAIL_VOLATILITY_TRAIL_NO_CAUSAL_EXIT_EVENTS"
    elif screen_pass:
        state = "PASS_VOLATILITY_TRAIL_DEVELOPMENT_SCREEN_PENDING_H4_H5"
    else:
        state = "FAIL_VOLATILITY_TRAIL_DEVELOPMENT_SCREEN"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "frozen_observation_authority": {
            "run_id": FROZEN_OBSERVATION_RUN_ID,
            "issue_comment_id": 5364074212,
            "boundary_utc": FROZEN_BOUNDARY_UTC,
            "last_post_boundary_ts": FROZEN_LAST_POST_BOUNDARY_TS,
            "expected_parent": EXPECTED_PARENT,
        },
        "axis_contract": {
            "entry_rule_unchanged": True,
            "entry_count_unchanged_required": True,
            "atr_len": ATR_LEN,
            "trail_atr_mult": TRAIL_ATR_MULT,
            "multiplier_provenance": "reuses_parent_initial_stop_1.5x_ATR_geometry",
            "activation_rule": "first_strictly_favorable_closed_bar_excursion; no numeric activation threshold",
            "trail_update_rule": "ratchet_only_from_closed_bar_high_low_watermark_and_prior_closed_bar_ATR14",
            "fill_rule": "gap_aware_stop_fill_on_later_bar; parent_exit_bar_excluded_for_ordering_safety",
            "same_bar_lookahead": False,
            "numeric_threshold_sweep": False,
            "best_horizon_selection": False,
            "post_outcome_trade_deletion": False,
            "cost_rule": "inherit_full_parent_realized_cost_bps_no_early_exit_credit",
        },
        "parent_w123": parent_audit,
        "child_w123": child_audit,
        "metric_deltas": deltas,
        "trade_retention_pct": retention,
        "trail_activated_trades": len(activated),
        "trail_changed_trades": len(changed),
        "trail_unchanged_trades": len(child_rows) - len(changed),
        "direct_same_frozen_original_fresh_w123_parent_child_ab_receipt_present": direct_ab,
        "development_screen": {
            "parent_anchor_match": parent_anchor_match,
            "same_entry_set": same_entry_set,
            "same_entry_geometry": same_entry_geometry,
            "retention_100pct": retention == 100.0,
            "causal_exit_events_present": len(changed) > 0,
            "child_w123_economics_gate_pass": child_audit.get("economics_gate_pass") is True,
            "net_expectancy_improved": expectancy_improved,
            "net_pnl_improved": net_improved,
            "drawdown_improved": dd_improved,
            "win_rate_non_regression": wr_non_regression,
            "robustness_improved_pf_or_payoff_or_drawdown": robustness_improved,
            "pass": screen_pass,
        },
        "next_if_pass": "H4_NEGATIVE_CONTROLS_THEN_H5_FRAGILITY_THEN_A2_COST_REVALIDATION_THEN_A3_FRESH_DURABILITY",
        "next_if_fail": "MULTIHORIZON_EXIT_CONSENSUS_ONLY",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = exact.v1.stable_sha(result)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert EXPECTED_PARENT["trades"] == 22
    assert math.isclose(float(EXPECTED_PARENT["win_rate"]), 13.0 / 22.0, rel_tol=0.0, abs_tol=1e-15)
    assert ATR_LEN == 14
    assert math.isclose(TRAIL_ATR_MULT, 1.5, rel_tol=0.0, abs_tol=0.0)
    assert AXIS == "VOLATILITY_ADAPTIVE_TRAIL_EXIT_ONLY"
    print("PASS_A1_TREND_RIDER_VOLATILITY_TRAIL_EXIT_FROZEN_W123_AB_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_volatility_trail_exit_frozen_w123_ab_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    p = r["parent_w123"]["aggregate"]
    c = r["child_w123"]["aggregate"]
    print(json.dumps({
        "state": r["state"],
        "parent": p,
        "child": c,
        "deltas": r["metric_deltas"],
        "retention_pct": r["trade_retention_pct"],
        "trail_activated_trades": r["trail_activated_trades"],
        "trail_changed_trades": r["trail_changed_trades"],
        "direct_ab": r["direct_same_frozen_original_fresh_w123_parent_child_ab_receipt_present"],
        "screen_pass": r["development_screen"]["pass"],
        "next_if_pass": r["next_if_pass"],
        "next_if_fail": r["next_if_fail"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
