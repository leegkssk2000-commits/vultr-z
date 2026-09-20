"""Source-bound session/daily components; no replay, economics, or live orders.

Daily clocks never become intraday bar counts. Native session models need an
explicit point-in-time calendar. All returned orders are research intents.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import math
import json
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules
from backend.research.rebuild import scalp7_positive_lanes_v2 as frozen

SOURCES = {
    "S301": "https://www.youtube.com/watch?v=10pHBNVi4Jc",
    "S325": "https://www.vnpy.com/forum/topic/4463-yi-ge-ke-yi-jiao-yi-ye-pan-de-rbreakerstrategy",
    "S310": "https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf",
    "S311": "https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf",
    "R08": "https://www.tradingblox.com/originalturtles/originalturtlerules.pdf",
}
MODES = {
    "break_and_continue": ("gajjala_flag_declared_v1", "stocks_in_play_orb_v1"),
    "rbreaker_like": ("vnpy_20200903_levels_v1",),
    "session_bias": ("noise_area_paper14_v1", "stocks_in_play_orb_v1"),
    "squeeze_break": ("frozen_ttm_component_v1",),
    "trend_rider": ("noise_area_paper14_v1",),
    "turtle_trend": (
        "turtle_system2_daily_component_v1",
        "turtle_system1_daily_component_v1",
    ),
}
GAPS = {
    "break_and_continue": "Flag management/discretion remains unbound; ORB native PIT universe and fill-relative stop need caller.",
    "rbreaker_like": "Native 1m session execution, broker position/OCO, and trailing/EOD fills are not provided by levels.",
    "session_bias": "Native calendar, synchronized full universe for ORB, actual fills and finite capital remain caller responsibilities.",
    "squeeze_break": "TTM numerical component is not Carter options strategy; no options payoff, daily/weekly ATR or three-trading-day translation.",
    "trend_rider": "Noise-Area direction/exit targets are callable; native SPY fills, share sizing and account state remain unbound.",
    "turtle_trend": "Daily references and actual-filled unit state only; System1 virtual breakout ledger and portfolio correlation/capital caps remain unimplemented.",
}


def catalog() -> dict[str, dict[str, Any]]:
    return {
        k: {
            "strategy_id": k,
            "mode_ids": list(v),
            "default_noise_stop_mode": (
                "CURRENT_BAND_VWAP" if "noise_area_paper14_v1" in v else None
            ),
            "noise_stop_modes": (
                ["CURRENT_BAND_VWAP", "OPPOSITE_BAND"]
                if "noise_area_paper14_v1" in v
                else []
            ),
            "complete_strategy": False,
            "implementation_status": "CALLABLE_NUMERICAL_COMPONENT",
            "lifecycle_gap": GAPS[k],
            "new_full_runs": 0,
        }
        for k, v in MODES.items()
    }


def _rule(
    key: str, expression: str, unit: str, source: str, mode: str
) -> dict[str, Any]:
    return {
        "rule_id": key,
        "expression": expression,
        "unit": unit,
        "origin": "SOURCE_DIRECT",
        "version": "20260920.v1",
        "source_id": source,
        "source_locator": SOURCES[source],
        "source_mode": mode,
    }


def _hypothesis(key: str, expression: str, hypothesis: str) -> dict[str, Any]:
    return {
        "rule_id": key,
        "expression": expression,
        "unit": "declared model policy",
        "origin": "DECLARED_HYPOTHESIS",
        "version": "20260920.v1",
        "hypothesis_id": hypothesis,
        "rationale": "Operational definition not fully specified by source.",
    }


def _number(value: Any, name: str, positive: bool = False) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("INVALID_NUMBER:" + name)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_NUMBER:" + name) from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("INVALID_NUMBER:" + name)
    return result


def _integer(value: Any, name: str) -> int:
    number = _number(value, name)
    if number < 0 or number != math.floor(number):
        raise ValueError("INTEGER_TIMESTAMP_OR_INDEX_REQUIRED:" + name)
    return int(number)


def _frame(frame: pd.DataFrame, tf: int) -> pd.DataFrame:
    x = frame.copy().reset_index(drop=True)
    required = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    if not required.issubset(x.columns):
        raise ValueError("CANONICAL_FRAME_REQUIRED")
    if x.empty:
        return x
    for k in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        a = pd.to_numeric(x[k]).to_numpy(float)
        if not np.isfinite(a).all() or (a < 0).any() or (a != np.floor(a)).any():
            raise ValueError("INTEGER_TIMESTAMP_REQUIRED")
        x[k] = a.astype(np.int64)
    if (
        x.open_ts_ms.duplicated().any()
        or not x.open_ts_ms.is_monotonic_increasing
        or (x.open_ts_ms.iloc[1:].to_numpy() < x.close_ts_ms.iloc[:-1].to_numpy()).any()
    ):
        raise ValueError("STRICT_BAR_ORDER_REQUIRED")
    if (
        (x.close_ts_ms - x.open_ts_ms != tf * 60_000)
        | (x.available_ts_ms < x.close_ts_ms)
    ).any():
        raise ValueError("BAR_CLOCK_INVALID")
    if not x.available_ts_ms.is_monotonic_increasing or x.segment_id.isna().any():
        raise ValueError("AVAILABILITY_OR_SEGMENT_INVALID")
    vals = x[["open", "high", "low", "close", "volume"]].to_numpy(float)
    if (
        not np.isfinite(vals).all()
        or (vals[:, :4] <= 0).any()
        or (vals[:, 4] < 0).any()
    ):
        raise ValueError("OHLCV_INVALID")
    if (
        (x.low > x[["open", "close"]].min(axis=1))
        | (x.high < x[["open", "close"]].max(axis=1))
    ).any():
        raise ValueError("CANDLE_GEOMETRY_INVALID")
    x["_boundary"] = (
        (x.segment_id != x.segment_id.shift()) | (x.open_ts_ms != x.close_ts_ms.shift())
    ).cumsum()
    return x


def _event(symbol: str, row: dict, kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "kind": kind,
        "setup_ts_ms": int(row["close_ts_ms"]),
        "feature_available_ts_ms": int(row["available_ts_ms"]),
        "segment_id": row["segment_id"],
        **extra,
    }


def _intent(
    symbol: str,
    row: dict,
    mode: str,
    side: int,
    trigger: float,
    stop: float | None,
    expires: int,
    kind: str = "STOP_MARKET",
) -> dict[str, Any]:
    return {
        **_event(symbol, row, "RESEARCH_ORDER_INTENT"),
        "mode_id": mode,
        "side": side,
        "order_kind": kind,
        "trigger_price": trigger,
        "protective_stop": stop,
        "expires_ts_ms": int(expires),
        "lifecycle_gap": "Requires actual fill, sizing and declared exit adapter",
        "economic_credit": False,
    }


def _session_rows(x: pd.DataFrame, config: dict) -> list[tuple[str, list[dict]]]:
    required = {
        "session_id",
        "session_index",
        "session_open_ts_ms",
        "session_close_ts_ms",
        "session_known_ts_ms",
    }
    if not required.issubset(x.columns):
        raise ValueError("EXPLICIT_SESSION_CALENDAR_REQUIRED")
    ref = config.get("session_source", {})
    if not ref.get("source_ref") or not ref.get("timezone") or not ref.get("market"):
        raise ValueError("SESSION_PROVENANCE_REQUIRED")
    tz = ZoneInfo(ref["timezone"])
    output = []
    seen = set()
    last_session_index = -1
    for session, frame in x.groupby("session_id", sort=False):
        if session in seen:
            raise ValueError("SESSION_REUSE")
        seen.add(session)
        rows = frame.to_dict("records")
        for row in rows:
            for key in (
                "session_index",
                "session_open_ts_ms",
                "session_close_ts_ms",
                "session_known_ts_ms",
            ):
                row[key] = _integer(row[key], key)
        first = rows[0]
        index = int(first["session_index"])
        if index <= last_session_index or any(
            int(r["session_index"]) != index for r in rows
        ):
            raise ValueError("SESSION_INDEX_INVALID")
        last_session_index = index
        start, end = int(first["session_open_ts_ms"]), int(first["session_close_ts_ms"])
        if not start < end:
            raise ValueError("SESSION_BOUNDARY_INVALID")
        if ref["market"] == "US_EQUITY_REGULAR":
            a, b = [datetime.fromtimestamp(t / 1000, tz) for t in (start, end)]
            if (
                (a.hour, a.minute, b.hour, b.minute) != (9, 30, 16, 0)
                or a.date() != b.date()
                or a.weekday() >= 5
                or ref["timezone"] != "America/New_York"
            ):
                raise ValueError("NATIVE_NY_SESSION_CLOCK_REQUIRED")
        elif not config.get("clock_hypothesis_id"):
            raise ValueError("NON_NATIVE_CLOCK_NEEDS_DECLARED_HYPOTHESIS")
        for r in rows:
            if (int(r["session_open_ts_ms"]), int(r["session_close_ts_ms"])) != (
                start,
                end,
            ):
                raise ValueError("SESSION_REFERENCE_CHANGED")
            if (
                int(r["session_known_ts_ms"]) > int(r["open_ts_ms"])
                or not start <= int(r["open_ts_ms"]) < int(r["close_ts_ms"]) <= end
            ):
                raise ValueError("SESSION_CALENDAR_NOT_CAUSAL")
        output.append((str(session), rows))
    return output


def _daily(config: dict, symbol: str, before: int) -> pd.DataFrame:
    raw = config.get("daily_frames", {}).get(symbol)
    if raw is None:
        raise ValueError("GENUINE_DAILY_HISTORY_REQUIRED")
    x = raw.copy().reset_index(drop=True)
    required = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "session_index",
        "high",
        "low",
        "close",
        "source_ref",
        "timeframe_unit",
    }
    if (
        not required.issubset(x.columns)
        or not (x.timeframe_unit == "DAY").all()
        or x.source_ref.isna().any()
    ):
        raise ValueError("DAILY_UNITS_AND_PROVENANCE_REQUIRED")
    for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms", "session_index"):
        x[key] = [_integer(v, key) for v in x[key].tolist()]
    if "volume" in x:
        volumes = [_number(v, "daily_volume") for v in x.volume.tolist()]
        if any(v < 0 for v in volumes):
            raise ValueError("DAILY_VOLUME_INVALID")
        x["volume"] = volumes
    if (
        x.session_index.duplicated().any()
        or x.open_ts_ms.duplicated().any()
        or not x.open_ts_ms.is_monotonic_increasing
        or (x.open_ts_ms.iloc[1:].to_numpy() < x.close_ts_ms.iloc[:-1].to_numpy()).any()
        or not x.session_index.is_monotonic_increasing
        or not x.available_ts_ms.is_monotonic_increasing
    ):
        raise ValueError("DAILY_ORDER_INVALID")
    if ((x.open_ts_ms >= x.close_ts_ms) | (x.close_ts_ms > x.available_ts_ms)).any():
        raise ValueError("DAILY_CLOCK_INVALID")
    for r in x.to_dict("records"):
        h, low, c = [_number(r[k], k, True) for k in ("high", "low", "close")]
        if not low <= c <= h or not str(r["source_ref"]).strip():
            raise ValueError("DAILY_GEOMETRY_INVALID")
    return x[(x.available_ts_ms <= before) & (x.close_ts_ms <= before)].copy()


def _noise(
    symbol: str, x: pd.DataFrame, config: dict, mode: str
) -> tuple[list, list, list]:
    sessions = _session_rows(x, config)
    events: list[dict[str, Any]] = []
    intents: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    prior: list[dict] = []
    stop_mode = config.get("noise_stop_mode", "CURRENT_BAND_VWAP")
    if stop_mode not in ("CURRENT_BAND_VWAP", "OPPOSITE_BAND"):
        raise ValueError("NOISE_STOP_MODE_REQUIRED")
    for session, rows in sessions:
        first = rows[0]
        start, end = int(first["session_open_ts_ms"]), int(first["session_close_ts_ms"])
        complete_prefix = int(first["open_ts_ms"]) == start
        current: dict[int, dict] = {}
        total_pv = total_v = 0.0
        exposure = 0
        exposure_available = start
        for i, r in enumerate(rows):
            if i and (
                r["open_ts_ms"] != rows[i - 1]["close_ts_ms"]
                or r["segment_id"] != rows[i - 1]["segment_id"]
            ):
                complete_prefix = False
            slot = int(r["close_ts_ms"] - start) // 60000
            total_v += float(r["volume"])
            total_pv += (r["high"] + r["low"] + r["close"]) / 3 * r["volume"]
            vwap = total_pv / total_v if total_v else None
            current[slot] = {
                "move": abs(r["close"] / first["open"] - 1),
                "available": int(r["available_ts_ms"]),
            }
            history = prior[-14:]
            eligible = (
                complete_prefix
                and len(history) == 14
                and total_v > 0
                and [d["session_index"] for d in history]
                == list(
                    range(int(first["session_index"]) - 14, int(first["session_index"]))
                )
                and all(
                    slot in d["slots"]
                    and d["slots"][slot]["available"] <= r["available_ts_ms"]
                    and d["complete"]
                    and d["available"] <= start
                    for d in history
                )
            )
            signal = exposure
            values: dict[str, Any] = {
                "session_id": session,
                "slot_min": slot,
                "exposure_for_current_bar": (
                    exposure if exposure_available <= r["open_ts_ms"] else None
                ),
                "vwap_hlc3_proxy": vwap,
                "eligible": eligible,
                "reference_sessions": len(history),
                "exposure_model": "LAGGED_TARGET_NOT_OBSERVED_FILL; null if activation overlaps interval",
            }
            if eligible:
                sigma = sum(d["slots"][slot]["move"] for d in history) / 14
                upper = max(first["open"], history[-1]["close"]) * (1 + sigma)
                lower = min(first["open"], history[-1]["close"]) * (1 - sigma)
                values.update(sigma_open=sigma, upper=upper, lower=lower)
                if slot % 30 == 0:
                    if stop_mode == "CURRENT_BAND_VWAP":
                        signal = (
                            1
                            if r["close"] > max(upper, vwap)
                            else -1 if r["close"] < min(lower, vwap) else 0
                        )
                    elif exposure == 1:
                        signal = 1 if r["close"] >= lower else -1
                    elif exposure == -1:
                        signal = -1 if r["close"] <= upper else 1
                    else:
                        signal = (
                            1 if r["close"] > upper else -1 if r["close"] < lower else 0
                        )
            if not complete_prefix:
                signal = 0
            if int(r["close_ts_ms"]) == end:
                signal = 0
            values["target_after_available"] = signal
            components.append(_event(symbol, r, "NOISE_AREA", **values))
            if signal != exposure:
                events.append(
                    _event(
                        symbol,
                        r,
                        "TARGET_EXPOSURE",
                        side=signal,
                        prior_side=exposure,
                        session_id=session,
                        next_execution_only=True,
                        reason="EOD" if r["close_ts_ms"] == end else "BAND_DECISION",
                    )
                )
            exposure = signal
            exposure_available = int(r["available_ts_ms"])
        prior.append(
            {
                "slots": current,
                "session_index": int(first["session_index"]),
                "close": rows[-1]["close"],
                "complete": complete_prefix and rows[-1]["close_ts_ms"] == end,
                "available": int(rows[-1]["available_ts_ms"]),
            }
        )
    return events, intents, components


def rbreaker_levels(high: float, low: float, close: float) -> dict[str, float]:
    high, low, close = [_number(v, "HLC", True) for v in (high, low, close)]
    if not low <= close <= high:
        raise ValueError("PREVIOUS_SESSION_HLC_INVALID")
    buy_setup = low - 0.25 * (high - close)
    sell_setup = high + 0.25 * (close - low)
    return {
        "buy_setup": buy_setup,
        "sell_setup": sell_setup,
        "buy_enter": 1.07 / 2 * (high + low) - 0.07 * high,
        "sell_enter": 1.07 / 2 * (high + low) - 0.07 * low,
        "buy_break": buy_setup + 0.2 * (sell_setup - buy_setup),
        "sell_break": sell_setup - 0.2 * (sell_setup - buy_setup),
    }


def rbreaker_native_plan(
    bars: pd.DataFrame, previous_hlc: dict, position: dict, *, session_close_ts_ms: int
) -> dict[str, Any]:
    """Exact community 1m numerical order branches, without simulated fills.

    Position is actual broker/fill state. The published callback cancels orders
    each bar but contains no immediate fill-cancels-sibling implementation.
    Therefore plans require an explicit OCO adapter before executable replay.
    """
    x = _frame(bars, 1)
    if x.empty or len(x) < 30:
        return {"orders": [], "status": "NATIVE_30_MINUTE_HISTORY_REQUIRED"}
    if x._boundary.nunique() != 1:
        return {"orders": [], "status": "GAP_BLOCKED"}
    r = x.iloc[-1].to_dict()
    if int(previous_hlc["available_ts_ms"]) > int(x.open_ts_ms.iloc[0]):
        raise ValueError("R_BREAKER_REFERENCE_FUTURE")
    if not previous_hlc.get("source_ref"):
        raise ValueError("R_BREAKER_REFERENCE_PROVENANCE_REQUIRED")
    levels = rbreaker_levels(
        previous_hlc["high"], previous_hlc["low"], previous_hlc["close"]
    )
    qty = _number(position.get("qty_base", 0), "qty_base")
    if qty and (
        not position.get("fill_id")
        or _integer(position.get("fill_ts_ms"), "fill_ts_ms")
        > int(r["available_ts_ms"])
    ):
        raise ValueError("R_BREAKER_ACTUAL_POSITION_REQUIRED")
    orders: list[dict[str, Any]] = []
    known = int(r["available_ts_ms"])
    if known >= session_close_ts_ms - 300000:
        if qty:
            orders.append(
                {
                    "action": "CLOSE",
                    "order_kind": "LIMIT",
                    "qty_base": abs(qty),
                    "trigger_price": r["close"] * (0.99 if qty > 0 else 1.01),
                    "limit_marketable_not_assumed_filled": True,
                }
            )
    elif qty:
        if not position.get("fill_id") or int(position["fill_ts_ms"]) > known:
            raise ValueError("R_BREAKER_ACTUAL_POSITION_REQUIRED")
        since = x[x.open_ts_ms >= int(position["fill_ts_ms"])]
        if since.empty:
            return {"orders": [], "status": "ENTRY_STRADDLING_BAR_UNRESOLVED"}
        if qty > 0:
            extreme = max(
                _number(position["intra_trade_high"], "intra_trade_high", True),
                float(since.high.max()),
            )
            stop = extreme * 0.996
        else:
            extreme = min(
                _number(position["intra_trade_low"], "intra_trade_low", True),
                float(since.low.min()),
            )
            stop = extreme * 1.004
        orders.append(
            {
                "action": "CLOSE",
                "order_kind": "STOP_MARKET",
                "qty_base": abs(qty),
                "trigger_price": stop,
            }
        )
    elif float(x.high.tail(30).max()) > levels["sell_setup"]:
        orders = [
            {
                "action": "ENTER",
                "side": 1,
                "source_size_units": 1,
                "trigger_price": max(levels["buy_break"], float(x.high.max())),
            },
            {
                "action": "ENTER",
                "side": -1,
                "source_size_units": 3,
                "trigger_price": levels["sell_enter"],
            },
        ]
    elif float(x.low.tail(30).min()) < levels["buy_setup"]:
        orders = [
            {
                "action": "ENTER",
                "side": -1,
                "source_size_units": 1,
                "trigger_price": min(levels["sell_break"], float(x.low.min())),
            },
            {
                "action": "ENTER",
                "side": 1,
                "source_size_units": 3,
                "trigger_price": levels["buy_enter"],
            },
        ]
    for order in orders:
        order.setdefault("order_kind", "STOP_MARKET")
        order["feature_available_ts_ms"] = known
        order["economic_credit"] = False
    return {
        "orders": orders,
        "levels": levels,
        "status": "NATIVE_PLAN_ONLY",
        "cancel_previous_orders": True,
        "oco_implemented": False,
        "complete_strategy": False,
        "source_bar_timeframe_min": 1,
    }


def _rbreaker(
    symbol: str, x: pd.DataFrame, config: dict, mode: str
) -> tuple[list, list, list]:
    events, components = [], []
    for session, rows in _session_rows(x, config):
        start = int(rows[0]["session_open_ts_ms"])
        daily = _daily(config, symbol, start)
        if daily.empty:
            continue
        d = daily.iloc[-1]
        levels = rbreaker_levels(d.high, d.low, d.close)
        for i, r in enumerate(rows):
            # 30-source-bar Donchian belongs to the 1m source, never 30 intraday bars.
            components.append(
                _event(
                    symbol,
                    r,
                    "R_BREAKER_FIXED_LEVELS",
                    session_id=session,
                    levels=levels,
                    reference_available_ts_ms=int(d.available_ts_ms),
                    source_donchian_window_bars=30,
                    source_bar_timeframe_min=1,
                    source_exit_schedule_ts_ms=int(r["session_close_ts_ms"]) - 300000,
                )
            )
            if i and r["open_ts_ms"] != rows[i - 1]["close_ts_ms"]:
                events.append(_event(symbol, r, "GAP_INVALIDATES_EXECUTION_STATE"))
    return events, [], components


def _flag(
    symbol: str, x: pd.DataFrame, config: dict, mode: str
) -> tuple[list, list, list]:
    hypothesis = config.get("flag_hypothesis", {})
    if not hypothesis.get("hypothesis_id"):
        raise ValueError("FLAG_NUMERICAL_HYPOTHESIS_REQUIRED")
    min_return = _number(
        hypothesis.get("impulse_return_min"), "impulse_return_min", True
    )
    max_pull = _number(
        hypothesis.get("pullback_fraction_max"), "pullback_fraction_max", True
    )
    if max_pull >= 1:
        raise ValueError("FLAG_PULLBACK_FRACTION_INVALID")
    events, intents, features = [], [], []
    for _, segment in x.groupby("_boundary", sort=False):
        state: dict[str, Any] | None = None
        for r in segment.to_dict("records"):
            if state is None:
                if r["close"] / r["open"] - 1 >= min_return:
                    state = {"impulse": r, "pull": None}
                    events.append(_event(symbol, r, "IMPULSE"))
                continue
            impulse, pull = state["impulse"], state["pull"]
            distance = impulse["high"] - impulse["low"]
            retrace = (impulse["high"] - r["low"]) / distance if distance else math.inf
            features.append(
                _event(
                    symbol,
                    r,
                    "FLAG_ANATOMY",
                    retracement_fraction=retrace,
                    volume_ratio=(
                        r["volume"] / impulse["volume"] if impulse["volume"] else None
                    ),
                )
            )
            if r["low"] <= impulse["low"] or retrace > max_pull:
                events.append(_event(symbol, r, "FLAG_INVALIDATED"))
                state = None
            elif pull is not None and r["close"] > pull["high"]:
                events.append(
                    _event(
                        symbol,
                        r,
                        "CONTINUATION_CLOSE",
                        source_market_trigger_not_reproduced=True,
                    )
                )
                intents.append(
                    _intent(
                        symbol,
                        r,
                        mode,
                        1,
                        r["close"],
                        pull["low"],
                        int(r["available_ts_ms"])
                        + int(config["timeframe_min"]) * 60000,
                        "NEXT_OPEN",
                    )
                )
                state = None
            elif r["close"] < impulse["close"] and r["volume"] < impulse["volume"]:
                state["pull"] = {
                    "high": max(r["high"], pull["high"]) if pull else r["high"],
                    "low": min(r["low"], pull["low"]) if pull else r["low"],
                }
                events.append(_event(symbol, r, "LOW_VOLUME_PULLBACK"))
    return events, intents, features


def _orb(
    symbol: str, x: pd.DataFrame, config: dict, mode: str
) -> tuple[list, list, list]:
    events: list[dict[str, Any]] = []
    intents: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    if config.get("session_source", {}).get("market") != "US_EQUITY_REGULAR":
        raise ValueError("ORB_NATIVE_US_UNIVERSE_REQUIRED")
    for session, rows in _session_rows(x, config):
        r = rows[0]
        if r["open_ts_ms"] != r["session_open_ts_ms"]:
            continue
        daily = _daily(config, symbol, int(r["session_open_ts_ms"]))
        if len(daily) < 15 or "volume" not in daily:
            continue
        h = daily.tail(15)
        if not (h.session_index.diff().dropna() == 1).all():
            continue
        prev = h.close.shift(1)
        tr = (
            pd.concat(
                [h.high - h.low, (h.high - prev).abs(), (h.low - prev).abs()], axis=1
            )
            .max(axis=1)
            .iloc[1:]
        )
        atr = float(tr.mean())
        avg_volume = float(h.volume.iloc[-14:].mean())
        universe = config.get("universe_snapshot", {})
        if (
            not universe.get("source_ref")
            or not universe.get("sha256")
            or universe.get("volume_unit") != "SHARES"
        ):
            raise ValueError("ORB_PIT_UNIVERSE_PROVENANCE_REQUIRED")
        if _integer(universe["available_ts_ms"], "universe_available_ts_ms") > int(
            r["session_open_ts_ms"]
        ):
            raise ValueError("ORB_UNIVERSE_FUTURE")
        members = universe.get("symbols")
        membership_sha = hashlib.sha256(
            json.dumps(sorted(config["_orb_frames"]), separators=(",", ":")).encode()
        ).hexdigest()
        if (
            not isinstance(members, list)
            or len(members) != len(set(members))
            or set(members) != set(config["_orb_frames"])
            or universe.get("symbols_sha256") != membership_sha
        ):
            raise ValueError("ORB_UNIVERSE_MEMBERSHIP_NOT_BOUND")
        scores = []
        for name, other in config["_orb_frames"].items():
            prior_openings = []
            opening = None
            for sid, bars in _session_rows(other, config):
                first = bars[0]
                if sid == session:
                    opening = first
                    break
                if (
                    first["open_ts_ms"] == first["session_open_ts_ms"]
                    and bars[-1]["close_ts_ms"] == first["session_close_ts_ms"]
                    and bars[-1]["available_ts_ms"] <= r["session_open_ts_ms"]
                ):
                    prior_openings.append(first)
            if (
                opening is None
                or len(prior_openings) < 14
                or opening["available_ts_ms"] > r["available_ts_ms"]
            ):
                continue
            if [int(z["session_index"]) for z in prior_openings[-14:]] != list(
                range(int(opening["session_index"]) - 14, int(opening["session_index"]))
            ):
                continue
            reference = sum(z["volume"] for z in prior_openings[-14:]) / 14
            if reference <= 0:
                continue
            dh = _daily(config, name, int(r["session_open_ts_ms"])).tail(15)
            if (
                len(dh) < 15
                or "volume" not in dh
                or not (dh.session_index.diff().dropna() == 1).all()
            ):
                continue
            pc = dh.close.shift()
            atr_n = float(
                pd.concat(
                    [dh.high - dh.low, (dh.high - pc).abs(), (dh.low - pc).abs()],
                    axis=1,
                )
                .max(axis=1)
                .iloc[1:]
                .mean()
            )
            ratio = opening["volume"] / reference
            if (
                opening["close"] > 5
                and dh.volume.tail(14).mean() >= 1_000_000
                and atr_n > 0.5
                and ratio >= 1
            ):
                scores.append((float(ratio), name))
        scores.sort(key=lambda item: (-item[0], item[1]))
        eligible = symbol in [name for _, name in scores[:20]]
        components.append(
            _event(
                symbol,
                r,
                "ORB_SCREEN",
                eligible=eligible,
                daily_atr14=atr,
                prior_daily_volume14=avg_volume,
            )
        )
        side = 1 if r["close"] > r["open"] else -1 if r["close"] < r["open"] else 0
        if eligible and side:
            trigger = r["high"] if side == 1 else r["low"]
            intent = _intent(
                symbol, r, mode, side, trigger, None, r["session_close_ts_ms"]
            )
            intent.update(
                stop_distance_from_actual_fill=0.1 * atr,
                source_eod_ts_ms=int(r["session_close_ts_ms"]),
                lifecycle_gap="Fill-relative stop and EOD market closure need caller; sizing unbound",
            )
            intents.append(intent)
    return events, intents, components


def _squeeze(
    symbol: str, x: pd.DataFrame, config: dict, mode: str
) -> tuple[list, list, list]:
    events, components = [], []
    for _, segment in x.groupby("_boundary", sort=False):
        enriched = frozen._enrich_segment(segment)
        previous = False
        for r in enriched.to_dict("records"):
            ready = math.isfinite(float(r["momentum"]))
            active = bool(r["squeeze_on"]) if ready else False
            momentum = float(r["momentum"]) if ready else None
            components.append(
                _event(
                    symbol,
                    r,
                    "FROZEN_TTM_NUMERICS",
                    squeeze_on=active,
                    momentum=momentum,
                    ready=ready,
                    numerical_version="frozen EMA20 first-value seed/Wilder20 TR/BB20 population/linreg20",
                )
            )
            if ready and previous and not active and momentum is not None:
                events.append(
                    _event(
                        symbol,
                        r,
                        "SQUEEZE_FIRE",
                        side=1 if momentum > 0 else -1 if momentum < 0 else 0,
                    )
                )
            previous = active
    return events, [], components


def turtle_n(daily: pd.DataFrame) -> list[float | None]:
    values: list[float | None] = []
    tr: list[float] = []
    n: float | None = None
    prev: dict | None = None
    for row in daily.to_dict("records"):
        if prev and row["session_index"] != prev["session_index"] + 1:
            n, tr, prev = None, [], None
        if prev is None:
            # First supplied close is the predecessor for TR, not an assumed zero overnight gap.
            values.append(None)
            prev = row
            continue
        value = max(
            row["high"] - row["low"],
            abs(row["high"] - prev["close"]),
            abs(row["low"] - prev["close"]),
        )
        tr.append(float(value))
        if n is not None:
            n = (19 * n + value) / 20
        elif len(tr) == 20:
            n = sum(tr) / 20
        values.append(n)
        prev = row
    return values


def turtle_filled_units(fills: list[dict], n: float, side: int) -> dict[str, Any]:
    """Standard 2N stop, not alternate whipsaw. Only actual filled adds count."""
    n = _number(n, "N", True)
    if side not in (-1, 1) or not fills or len(fills) > 4:
        raise ValueError("TURTLE_FILLED_UNITS_INVALID")
    old_time = -1
    unit_ids: set[str] = set()
    stops: list[float] = []
    for i, fill in enumerate(fills):
        if (
            not fill.get("fill_id")
            or fill.get("state") != "FILLED"
            or int(fill["fill_ts_ms"]) <= old_time
            or not fill.get("unit_id")
            or fill["unit_id"] in unit_ids
            or fill.get("unit_complete") is not True
        ):
            raise ValueError("ACTUAL_CHRONOLOGICAL_FILLS_REQUIRED")
        unit_ids.add(fill["unit_id"])
        price = _number(fill["fill_price"], "fill_price", True)
        _number(fill["qty_base"], "qty_base", True)
        if i and side * (price - float(fills[i - 1]["fill_price"])) < 0.5 * n:
            raise ValueError("TURTLE_ADD_NOT_HALF_N_FROM_ACTUAL_FILL")
        stops = [stop + side * 0.5 * n for stop in stops]
        stops.append(price - side * 2 * n)
        old_time = int(fill["fill_ts_ms"])
    return {
        "units": len(fills),
        "stop_prices": stops,
        "next_add_trigger": (
            float(fills[-1]["fill_price"]) + side * 0.5 * n if len(fills) < 4 else None
        ),
        "N_frozen_at_initial_entry": n,
        "risk_unit_state_only": True,
    }


def _turtle(
    symbol: str, x: pd.DataFrame, config: dict, mode: str
) -> tuple[list, list, list]:
    components, events = [], []
    system1 = "system1" in mode
    for r in x.to_dict("records"):
        daily = _daily(config, symbol, int(r["available_ts_ms"]))
        if len(daily) < 55:
            continue
        d = daily.tail(55)
        if not (d.session_index.diff().dropna() == 1).all():
            continue
        ns = turtle_n(daily)
        n = ns[-1]
        if n is None or n <= 0:
            continue
        entry_n, exit_n = (20, 10) if system1 else (55, 20)
        comp = _event(
            symbol,
            r,
            "TURTLE_DAILY_REFERENCE",
            N=n,
            source_unit="TRADING_DAY",
            entry_high=float(d.tail(entry_n).high.max()),
            entry_low=float(d.tail(entry_n).low.min()),
            exit_high=float(d.tail(exit_n).high.max()),
            exit_low=float(d.tail(exit_n).low.min()),
            failsafe55_high=float(d.high.max()),
            failsafe55_low=float(d.low.min()),
            reference_available_ts_ms=int(d.available_ts_ms.iloc[-1]),
            entries_enabled=False,
        )
        components.append(comp)
        if system1:
            events.append(_event(symbol, r, "SYSTEM1_VIRTUAL_LEDGER_REQUIRED"))
    return events, [], components


def evaluate(
    strategy_id: str, frames: dict[str, pd.DataFrame], config: dict
) -> dict[str, Any]:
    if strategy_id not in MODES:
        raise ValueError("UNKNOWN_EXACT25_SESSION_STRATEGY")
    tf = config.get("timeframe_min")
    if isinstance(tf, bool) or tf not in (15, 30):
        raise ValueError("SCALP7_DECISION_TIMEFRAME_REQUIRED")
    mode = config.get("mode_id", MODES[strategy_id][0])
    if mode not in MODES[strategy_id]:
        raise ValueError("STRATEGY_MODE_MISMATCH")
    output: dict[str, Any] = {
        "strategy_id": strategy_id,
        "mode_id": mode,
        "events": [],
        "intents": [],
        "components": [],
        "limitations": [GAPS[strategy_id]],
        "complete_strategy": False,
        "new_full_runs": 0,
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
    }
    rules = []
    if mode == "noise_area_paper14_v1":
        fn = _noise
        rules.append(
            _rule(
                "noise_same_slot",
                "mean(abs(prior14 same-session-slot close/session_open-1)); gap adjusted bands; completed30m decisions; exposure lag; session zero; selected stop="
                + config.get("noise_stop_mode", "CURRENT_BAND_VWAP")
                + "; CURRENT_BAND_VWAP long above max(UB,VWAP), short below min(LB,VWAP); OPPOSITE_BAND retains direction until opposite boundary",
                "14 trading sessions / 30 minutes",
                "S310",
                mode,
            )
        )
        rules.append(
            _hypothesis(
                "vwap_proxy",
                "cumulative HLC3*volume / volume, not trade VWAP; no dividend auto-adjustment",
                "NOISE_CANDLE_VWAP_PROXY_V1",
            )
        )
        output["limitations"].append(
            "Paper14 selected; blog min_periods13, optional overnight-fade and vol sizing explicitly excluded. Dividend-adjusted session data must be externally bound."
        )
    elif mode == "stocks_in_play_orb_v1":
        fn = _orb
        rules.append(
            _rule(
                "orb",
                f"completed first{tf}minute opening direction and high/low; doji no entry; PIT screen/rank; 0.1 dailyATR14 SMA true-range stop from actual fill; session EOD",
                "shares / USD / trading days",
                "S311",
                mode,
            )
        )
    elif mode == "vnpy_20200903_levels_v1":
        fn = _rbreaker
        rules.append(
            _rule(
                "rbreaker",
                "fixed previous session HLC; setup=.25,break=.2,enter1=1.07,enter2=.07; exact published internal break levels",
                "native session price",
                "S325",
                mode,
            )
        )
        output["limitations"].append(
            "Source internal buy/sell break levels preserved; not Saidenberg proof. Source 30x1m Donchian and 5min EOD require native data; no 30x15m replacement or fake OCO."
        )
    elif mode == "gajjala_flag_declared_v1":
        fn = _flag
        rules.append(
            _rule(
                "flag_sequence",
                "impulse -> higher level lower volume pullback -> price continuation",
                "price / actual volume",
                "S301",
                mode,
            )
        )
        h = config.get("flag_hypothesis", {})
        rules.append(
            _hypothesis(
                "flag_numeric",
                "declared thresholds="
                + str(h)
                + "; next-open after completed-close continuation; one-decision-bar entry expiry; observed pullback low risk; no inherited exit",
                str(h.get("hypothesis_id", "MISSING")),
            )
        )
    elif mode == "frozen_ttm_component_v1":
        fn = _squeeze
        rules.append(
            {
                "rule_id": "ttm_numerics",
                "origin": "EXISTING_FROZEN",
                "expression": "call unchanged positive_lanes._enrich_segment numerical component only",
                "unit": "configured bar minutes",
                "version": "PR1338 frozen",
                "code_path": "backend/research/rebuild/scalp7_positive_lanes_v2.py",
                "code_sha": hashlib.sha256(
                    Path(frozen.__file__).read_bytes()
                ).hexdigest(),
            }
        )
    else:
        fn = _turtle
        rules.append(
            _rule(
                "turtle_daily",
                "20/55 trading DAY breakout and10/20 DAY exit;20TR SMA seed then(19N+TR)/20;add .5N actual-fill;standard2N stops;max4units",
                "trading days / price N / actual filled units",
                "R08",
                mode,
            )
        )
    if config.get("clock_hypothesis_id"):
        rules.append(
            _hypothesis(
                "session_clock",
                str(config.get("session_source")),
                config["clock_hypothesis_id"],
            )
        )
    output["rules"] = rules
    output["rule_digest"] = validate_rules(rules)
    config = dict(config)
    if mode == "stocks_in_play_orb_v1":
        config["_orb_frames"] = {
            symbol: _frame(frame, tf) for symbol, frame in frames.items()
        }
    for symbol, frame in sorted(frames.items()):
        x = _frame(frame, tf)
        if x.empty:
            continue
        events, intents, components = fn(symbol, x, config, mode)
        output["events"].extend(events)
        output["intents"].extend(intents)
        output["components"].extend(components)
    return output
