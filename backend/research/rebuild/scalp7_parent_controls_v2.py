"""Current 15m/30m causal opportunity controls, not exact occupied-ledger replay."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

sm: Any = importlib.import_module(
    "backend.research.rebuild.benchmark25_donor_state_machine_v2"
)
FREEZE_SHA256 = "b656b00954cd0ec06de105b9b6c6467e7f426e7744fd803ae838f907dca614ec"
CONTROL_KIND = "CAUSAL_UTC_OPPORTUNITY_GRAMMAR_CONTROL_NOT_EXACT_OLD_TRADE_REPLAY"
TIMEFRAMES = {"trend_rider": 15, "break_and_continue": 15, "supertrend_pullback": 30}
IDENTITIES = {
    lane: f"scalp7_{lane}_opportunity_control_{tf}m_v2"
    for lane, tf in TIMEFRAMES.items()
}
SPEC_PATH = Path(__file__).with_name("benchmark25_donor_state_machine_v2.json")
FREEZE_PATH = (
    Path(__file__).resolve().parents[3]
    / "research/campaigns/scalp7_20260915/broad_v2/supertrend/PARENT_CONTROLS_FREEZE_V2.json"
)


def _freeze() -> dict[str, Any]:
    raw = FREEZE_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FREEZE_SHA256:
        raise ValueError("PARENT_CONTROL_FREEZE_CHANGED")
    result: dict[str, Any] = json.loads(raw)
    for name in (
        "benchmark25_donor_state_machine_v2.py",
        "benchmark25_donor_state_machine_v2.json",
    ):
        if (
            hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            != result["sources"][name]
        ):
            raise ValueError("PARENT_CONTROL_SOURCE_CHANGED")
    return result


def _lane(identity: str) -> str:
    for lane in TIMEFRAMES:
        if identity in (lane, IDENTITIES[lane]):
            return lane
    raise ValueError("PARENT_CONTROL_UNKNOWN_CURRENT_LANE")


def _validate(frame: pd.DataFrame, tf_ms: int) -> pd.DataFrame:
    required = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
    }
    if not required.issubset(frame.columns):
        raise ValueError("PARENT_CONTROL_REQUIRED_CANDLE_FIELD")
    x = frame.copy().reset_index(drop=True)
    if x.empty:
        return x
    for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        values = pd.to_numeric(x[key], errors="raise")
        if not np.isfinite(values).all() or (values != values.astype("int64")).any():
            raise ValueError("PARENT_CONTROL_INVALID_TIMESTAMP")
        x[key] = values.astype("int64")
    if (x.open_ts_ms % tf_ms != 0).any() or (
        x.close_ts_ms - x.open_ts_ms != tf_ms
    ).any():
        raise ValueError("PARENT_CONTROL_WRONG_UTC_TIMEFRAME")
    if (x.available_ts_ms < x.close_ts_ms).any() or (
        x.open_ts_ms.diff().dropna() <= 0
    ).any():
        raise ValueError("PARENT_CONTROL_UNAVAILABLE_OR_NONINCREASING_TIME")
    if x.segment_id.isna().any():
        raise ValueError("PARENT_CONTROL_SEGMENT_REQUIRED")
    x["segment_id"] = x.segment_id.astype(str)
    for key in ("open", "high", "low", "close"):
        x[key] = pd.to_numeric(x[key], errors="raise")
        if not np.isfinite(x[key]).all() or (x[key] <= 0).any():
            raise ValueError("PARENT_CONTROL_INVALID_PRICE")
    if (
        (x.low > x[["open", "close"]].min(axis=1))
        | (x.high < x[["open", "close"]].max(axis=1))
    ).any():
        raise ValueError("PARENT_CONTROL_INVALID_OHLC")
    x["_run"] = (
        (x.open_ts_ms.diff() != tf_ms) | (x.segment_id != x.segment_id.shift())
    ).cumsum()
    return x


def _features(segment: pd.DataFrame) -> pd.DataFrame:
    """Exact minimal inherited features used by the three donor grammars; no volume."""
    x = segment.copy().reset_index(drop=True)
    high, low, close = x.high, x.low, x.close
    previous = close.shift()
    tr = (
        pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1)
        .max(axis=1)
        .to_numpy(float)
    )
    atr = np.full(len(tr), np.nan)
    if len(tr) >= 14:
        value = float(np.mean(tr[:14]))
        atr[13] = value
        for i in range(14, len(tr)):
            value = (13 * value + tr[i]) / 14
            atr[i] = value
    x["atr"] = atr
    for n in (8, 21, 50, 55, 100):
        x[f"ema{n}"] = close.ewm(span=n, adjust=False).mean()
    for n in (20, 50):
        x[f"hi{n}"] = high.shift().rolling(n).max()
        x[f"lo{n}"] = low.shift().rolling(n).min()
    x["mean20"] = close.rolling(20).mean()
    x["sd20"] = close.rolling(20).std(ddof=0)
    x["bb_width_atr"] = 4 * x.sd20 / x.atr
    x["bb_prev_width_atr"] = x.bb_width_atr.shift()
    x["ts_ms"] = x.open_ts_ms
    x["_available_prefix_ms"] = x.available_ts_ms.cummax()
    return x


def _initial_stop(signal: Mapping[str, Any], entry: float) -> float:
    side = int(signal["side"])
    meta = signal["meta"]
    atr = float(meta["atr_at_signal"])
    risk = meta["source_spec"]["risk"]
    fallback = entry - side * float(risk["stop_atr_mult"]) * atr
    candidate = fallback
    ref = signal.get("invalidation_price")
    if risk["stop_mode"] == "reference_failure_plus_atr_buffer" and ref is not None:
        candidate = float(ref) - side * 0.20 * atr
    if not math.isfinite(candidate) or side * (entry - candidate) <= 0:
        candidate = fallback
    if candidate <= 0 or side * (entry - candidate) <= 0:
        raise ValueError("PARENT_CONTROL_INVALID_ENTRY_STOP")
    return candidate


def entry_update(signal: Mapping[str, Any], entry_price: float) -> dict[str, Any]:
    """Shared engine calls at actual next-open fill, before placing brackets."""
    lane = _lane(str(signal["identity"]))
    if signal["identity"] != IDENTITIES[lane]:
        raise ValueError("PARENT_CONTROL_IDENTITY_MISMATCH")
    if not math.isfinite(entry_price) or entry_price <= 0:
        raise ValueError("PARENT_CONTROL_INVALID_ENTRY_PRICE")
    stop = _initial_stop(signal, entry_price)
    return {
        "stop_price": stop,
        "initial_stop": stop,
        "initial_risk": abs(entry_price - stop),
        "take_profit_r": signal["take_profit_r"],
        "partial_take_profit_r": signal["partial_take_profit_r"],
        "partial_fraction": signal["partial_fraction"],
    }


def generate_signals(
    frames: dict[str, pd.DataFrame],
    identity: str = "trend_rider",
) -> list[dict[str, Any]]:
    lane = _lane(identity)
    freeze = _freeze()
    bound = freeze["lanes"][lane]
    spec = deepcopy(bound["source_spec"])
    spec["child_id"] = IDENTITIES[lane]
    tf_ms = TIMEFRAMES[lane] * 60000
    result: list[dict[str, Any]] = []
    for symbol, frame in sorted(frames.items()):
        valid = _validate(frame, tf_ms)
        if valid.empty:
            continue
        for _, segment in valid.groupby("_run", sort=False):
            x = _features(segment)
            state = sm.MachineState()
            for i in range(101, len(x)):
                signal = sm.step_machine(lane, state, x, i, spec)
                if signal is None:
                    continue
                row = x.iloc[i]
                meta = {
                    "control_kind": CONTROL_KIND,
                    "freeze_sha256": FREEZE_SHA256,
                    "source_spec": deepcopy(spec),
                    "atr_at_signal": float(row.atr),
                    "close_at_signal": float(row.close),
                    "event_trace": list(signal.event_trace),
                    "opportunity_state_advances_while_engine_busy": True,
                    "entry_stop_policy": "RECOMPUTE_ORIGINAL_GEOMETRY_AT_ACTUAL_NEXT_OPEN",
                }
                emitted: dict[str, Any] = {
                    "identity": IDENTITIES[lane],
                    "lane": lane,
                    "timeframe_min": TIMEFRAMES[lane],
                    "symbol": symbol,
                    "side": 1 if signal.side == "long" else -1,
                    "signal_open_ts_ms": int(row.open_ts_ms),
                    "signal_ts_ms": max(
                        int(row.close_ts_ms), int(row._available_prefix_ms)
                    ),
                    "segment_id": str(row.segment_id),
                    "max_hold_bars": bound["effective_max_hold_bars"],
                    "take_profit_r": spec["lifecycle"]["target_r"],
                    "invalidation_price": signal.invalidation_ref,
                    "partial_take_profit_r": bound["partial_take_profit_r"],
                    "partial_fraction": bound["partial_fraction"],
                    "exit_policy": "DONOR_PARENT_OPPORTUNITY_CONTROL",
                    "meta": meta,
                }
                emitted["stop_price"] = _initial_stop(emitted, float(row.close))
                result.append(emitted)
    return sorted(result, key=lambda s: (s["signal_ts_ms"], s["symbol"]))


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    signal = position["signal"]
    lane = _lane(str(signal["identity"]))
    row = _validate(pd.DataFrame([bar]), TIMEFRAMES[lane] * 60000).iloc[0]
    if not history.empty and int(history.open_ts_ms.max()) > int(row.open_ts_ms):
        raise ValueError("PARENT_CONTROL_FUTURE_HISTORY")
    if int(row.open_ts_ms) < int(position["entry_ts_ms"]):
        raise ValueError("PARENT_CONTROL_EXIT_BEFORE_ENTRY")
    side = int(position["side"])
    last = position.get("_parent_control_state")
    if last is not None and last["open_ts_ms"] == int(row.open_ts_ms):
        return dict(last["result"])
    if last is None:
        last = {
            "atr": float(signal["meta"]["atr_at_signal"]),
            "close": float(signal["meta"]["close_at_signal"]),
            "open_ts_ms": int(signal["signal_open_ts_ms"]),
            "peak": float(position["entry_price"]),
            "trail": None,
            "segment_id": str(signal["segment_id"]),
        }
    if (
        int(row.open_ts_ms) != last["open_ts_ms"] + TIMEFRAMES[lane] * 60000
        or str(row.segment_id) != last["segment_id"]
    ):
        return {"exit_next_open": True, "reason": "DATA_GAP_HOLD", "next_stop": None}
    tr = max(
        float(row.high - row.low),
        abs(float(row.high) - last["close"]),
        abs(float(row.low) - last["close"]),
    )
    atr = (13 * last["atr"] + tr) / 14
    ref = signal.get("invalidation_price")
    invalid = ref is not None and side * (float(row.close) - float(ref)) < -0.15 * atr
    life = signal["meta"]["source_spec"]["lifecycle"]
    mfe = float(position["mfe_R"])
    scratch = int(position["hold_bars"]) >= int(
        life["scratch_after_bars"]
    ) and mfe < float(life["scratch_if_mfe_below_r"])
    peak = (
        max(float(last["peak"]), float(row.high))
        if side == 1
        else min(float(last["peak"]), float(row.low))
    )
    trail = last["trail"]
    if not invalid and mfe >= max(1.5, float(life["trail_activate_r"])):
        candidate = peak - side * float(life["trail_atr_mult"]) * atr
        trail = (
            candidate
            if trail is None
            else max(trail, candidate) if side == 1 else min(trail, candidate)
        )
    next_stop = None
    if trail is not None and not invalid and not scratch:
        next_stop = (
            max(float(position["stop_price"]), trail)
            if side == 1
            else min(float(position["stop_price"]), trail)
        )
    result: dict[str, Any] = {
        "exit_next_open": bool(invalid or scratch),
        "reason": (
            "STRUCTURE_INVALIDATION_NEXT_OPEN"
            if invalid
            else (
                "NO_PROGRESS_SCRATCH_NEXT_OPEN"
                if scratch
                else "DONOR_NATIVE_LIFECYCLE_TRAIL"
            )
        ),
        "next_stop": next_stop,
    }
    if not invalid and not position.get("_parent_partial_done", False):
        trigger_r = float(signal["partial_take_profit_r"])
        trigger_price = float(position["entry_price"]) + side * trigger_r * float(
            position["initial_risk"]
        )
        touched = (
            float(row.high) >= trigger_price
            if side == 1
            else float(row.low) <= trigger_price
        )
        if touched:
            # Conservatively retain the predeclared limit on a favorable opening gap.
            partial_price = trigger_price
            result["partial_fraction"] = float(signal["partial_fraction"])
            result["partial_price"] = partial_price
            position["_parent_partial_done"] = True
    position["_parent_control_state"] = {
        "atr": atr,
        "close": float(row.close),
        "open_ts_ms": int(row.open_ts_ms),
        "peak": peak,
        "trail": trail,
        "segment_id": str(row.segment_id),
        "result": dict(result),
    }
    return result
