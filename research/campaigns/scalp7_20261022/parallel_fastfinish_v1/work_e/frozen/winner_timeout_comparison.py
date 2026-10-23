"""Paired Keltner timeout comparison, not a trading or dispatch entry point.

The economic owner must bind an approved finite horizon, original source/window,
all 128 control entries and incremental carry before using real prices. This
module changes only the 25-bar timeout after a causally observed 2R excursion.
It delegates fills, stops, partials and fee-BE/trailing to the frozen engine.
No default extension duration, parameter sweep, market API, or promotion.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
from typing import Any

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive

CONTROL = "scalp7_keltner_hg_fresh_touch_after_reject_utc30m_v1"
COMPARISON = "keltner_observed_2r_bounded_time_extension_comparison_v1"
PINS = {
    execution: "d1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1",
    positive: "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2",
}


def verify_dependencies() -> None:
    for module, expected in PINS.items():
        if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != expected:
            raise ValueError("FROZEN_DEPENDENCY_CHANGED:" + module.__name__)


def _native(signal: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(signal)
    if out["identity"] == CONTROL:
        if out["meta"].get("lifecycle_adapter_parent_identity") != positive.KELTNER_PARENT:
            raise ValueError("CONTROL_PARENT_NOT_BOUND")
        out["identity"] = positive.KELTNER_PARENT
    if out["identity"] != positive.KELTNER_PARENT or out.get("legs"):
        raise ValueError("EXACT_KELTNER_CONTROL_REQUIRED")
    if out["timeframe_min"] != 30 or out["max_hold_bars"] != 25:
        raise ValueError("CONTROL_TIME_RULE_CHANGED")
    if out.get("partial_take_profit_r") != 2.0 or out.get("partial_fraction") != 0.10:
        raise ValueError("CONTROL_PARTIAL_RULE_CHANGED")
    return out


def _continuation_callback(trace: list[dict[str, Any]]):
    def callback(position, bar, history):
        update = positive.exit_update(position, bar, history)
        if update.get("exit_next_open") or int(position["hold_bars"]) < 25:
            return update
        # The engine has already checked the current stop, updated MFE from the
        # current completed bar and checked availability before calling us.
        mfe = float(position["mfe_R"])
        if not math.isfinite(mfe):
            raise ValueError("OBSERVED_MFE_REQUIRED")
        if int(position["hold_bars"]) == 25:
            trace.append({
                "available_ts_ms": int(bar["available_ts_ms"]),
                "hold_bars": 25,
                "observed_mfe_R": mfe,
                "extend": mfe >= 2.0,
                "basis": "CURRENT_COMPLETED_PREFIX_NOT_FINAL_TRADE_MFE",
            })
        if mfe < 2.0:
            update.update(exit_next_open=True, reason="MAX_HOLD_NEXT_OPEN")
        # Otherwise leave original protective-stop/partial/runner updates intact.
        # The engine enforces the separately frozen finite maximum horizon.
        return update
    return callback


def _check_control(actual, saved):
    if actual is None:
        raise ValueError("CONTROL_NOT_REPRODUCED")
    exact = ("symbol", "side", "entry_ts_ms", "exit_ts_ms",
             "outcome_available_ts_ms", "hold_bars", "reason")
    numeric = ("gross_bps", "cost_bps", "net_bps", "mfe_R", "mae_R")
    if any(actual[k] != saved[k] for k in exact):
        raise ValueError("CONTROL_EVENT_MISMATCH")
    if any(not math.isclose(float(actual[k]), float(saved[k]),
                            rel_tol=0, abs_tol=1e-8) for k in numeric):
        raise ValueError("CONTROL_ECONOMICS_MISMATCH")
    if actual["entry_prices"] != saved["entry_prices"] or actual["exit_prices"] != saved["exit_prices"]:
        raise ValueError("CONTROL_FILL_MISMATCH")


def compare_one(saved: dict[str, Any], frame, *, window_end_ms: int,
                hard_max_hold_bars: int, horizon_authority: str,
                additional_carry_bps: float | None = None) -> dict[str, Any]:
    """Run one paired entry, never a selected-group or portfolio acceptance.

    Hard horizon MUST be frozen by the existing owner before real-price use;
    it has no default. Window end stays unchanged. Missing/gapped/end-of-source
    continuation stays unresolved, with no fabricated close or net delta.
    additional_carry_bps is the signed incremental cost for the longer holding
    period (not copied from the shorter control). None forbids a net claim.
    """
    verify_dependencies()
    if (isinstance(hard_max_hold_bars, bool) or not isinstance(hard_max_hold_bars, int)
            or hard_max_hold_bars <= 25 or not horizon_authority.strip()):
        raise ValueError("EXPLICIT_FROZEN_FINITE_HORIZON_REQUIRED")
    if not isinstance(window_end_ms, int) or window_end_ms % positive.TIMEFRAME_MS:
        raise ValueError("EXACT_WINDOW_END_REQUIRED")
    if additional_carry_bps is not None and not math.isfinite(additional_carry_bps):
        raise ValueError("FINITE_INCREMENTAL_CARRY_REQUIRED")
    if frame.empty or "close_ts_ms" not in frame:
        raise ValueError("ACTUAL_PRICE_ROWS_REQUIRED")
    f = frame[frame.close_ts_ms <= window_end_ms].copy().reset_index(drop=True)
    records, indexes = execution._frame_records(f, 30)
    native = _native(saved["signal"])
    cost = float(saved["cost_bps"])
    if cost <= 0 or not math.isfinite(cost) or cost != float(native["meta"]["frozen_cost_bps"]):
        raise ValueError("CONTROL_COST_BINDING_REQUIRED")
    base, base_open, _, reason = execution._single(
        deepcopy(native), f, records, indexes, cost, positive.exit_update, positive.entry_update)
    if reason or base_open:
        raise ValueError("CONTROL_REPLAY_REJECTED_OR_UNRESOLVED")
    _check_control(base, saved)
    modified = deepcopy(native)
    modified["max_hold_bars"] = hard_max_hold_bars
    trace: list[dict[str, Any]] = []
    child, unresolved, _, rejected = execution._single(
        modified, f, records, indexes, cost, _continuation_callback(trace), positive.entry_update)
    if rejected:
        raise ValueError("CHILD_ADMISSION_DRIFT:" + rejected)
    if child:
        child["identity"] = COMPARISON
        child["signal"]["identity"] = COMPARISON
    if unresolved:
        unresolved["identity"] = COMPARISON
        unresolved["position"]["signal"]["identity"] = COMPARISON
    delta = None if child is None else child["gross_bps"] - base["gross_bps"]
    same_exit = child is not None and child["exit_ts_ms"] == base["exit_ts_ms"]
    carry = 0.0 if same_exit else additional_carry_bps
    net_delta = None if delta is None or carry is None else delta - carry
    return {
        "comparison": COMPARISON,
        "control": deepcopy(saved), "child": child, "unresolved": unresolved,
        "timeout_decisions": trace, "hard_max_hold_bars": hard_max_hold_bars,
        "horizon_authority": horizon_authority, "window_end_ms": window_end_ms,
        "gross_delta_trade_bps": delta,
        "incremental_carry_trade_bps": carry,
        "net_delta_trade_bps": net_delta,
        "net_delta_cost2x_trade_bps": None if net_delta is None else delta - 2 * carry,
        "valuation_complete": child is not None and carry is not None,
        "all_128_comparison_complete": False,
        "full_timeline_occupancy_compared": False,
        "account_nav_or_oos": False, "economic_pass": False,
        "order_authority": "BLOCKED", "live_authority": "BLOCKED",
    }
