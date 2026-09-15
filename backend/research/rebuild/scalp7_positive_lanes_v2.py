"""UTC causal adapters of frozen Keltner HG / Squeeze 30m lineages.

Old inspected trade receipts remain their original identity. This version emits
potential closed-bar events and delegates occupancy, admission, partial fills,
next-open closes and gap handling to the common research execution engine.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

TIMEFRAME_MIN = 30
TIMEFRAME_MS = 1_800_000
KELTNER_PARENT = "scalp7_keltner_hg_parent_utc30m_v2"
KELTNER_TD075 = "scalp7_keltner_hg_td075_utc30m_v2"
SQUEEZE_PARENT = "scalp7_squeeze_panic_cost4_parent_utc30m_v2"
SQUEEZE_BE1R = "scalp7_squeeze_panic_cost4_be1r_utc30m_v2"
IDENTITIES = (KELTNER_PARENT, KELTNER_TD075, SQUEEZE_PARENT, SQUEEZE_BE1R)
LONG_GMMA = (30, 35, 40, 45, 50, 60)
SPEC = {
    "identities": IDENTITIES,
    "decision_timeframe_min": 30,
    "keltner": {
        "source": "a1_keltner_holygrail_streak_guard_v11.py",
        "entry_source": "a1_benchmark_web_holygrail_rearm_v9.py",
        "regimes": ["PANIC_DISPERSION", "TREND_DISPERSED"],
        "entry_atr_cost_min": 4.5,
        "stop_buffer_atr": 0.10,
        "fallback_stop_atr": 1.2,
        "be_arm_r": 1.0,
        "td_child_be_arm_r": 0.75,
        "fee_be_net_lock_bps": 2.0,
        "partial_r": 2.0,
        "partial_fraction": 0.10,
        "trail_arm_r": 3.0,
        "trail_gap_r": 1.25,
        "scratch_held_bars": 5,
        "scratch_mfe_r_below": 0.40,
        "max_held_bars": 25,
    },
    "squeeze": {
        "source": "a1_benchmark_web_squeeze_v7.py",
        "regime": "PANIC_DISPERSION",
        "side": 1,
        "entry_atr_cost_min": 4.0,
        "stop_ema21_atr20_mult": 2.0,
        "fallback_stop_atr": 2.0,
        "max_held_bars": 11,
        "exit": "two consecutive positive but weakening momentum closes",
        "child_be_arm_r": 1.0,
        "child_be_net_lock_bps": 0.0,
    },
    "execution_deltas": [
        "UTC complete bars instead of old offset aggregation",
        "entry-price cost guard at next-open admission, never future-open feature",
        "all potential setup events, common engine owns occupancy",
        "close-driven exits on next open",
        "stop/partial same-bar ambiguity resolved adverse-first by engine",
    ],
    "historical_parity_claim": False,
    "historical_retune": False,
    "order": "BLOCKED",
    "live": "BLOCKED",
}
SPEC_SHA256 = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()


def _validated(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.copy().reset_index(drop=True)
    needed = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
    }
    if not needed.issubset(x.columns):
        raise ValueError("POSITIVE_LANE_BAR_SCHEMA_REQUIRED")
    if x.empty:
        return x
    for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        values = pd.to_numeric(x[key], errors="raise").to_numpy(float)
        if not np.isfinite(values).all() or not (values == np.floor(values)).all():
            raise ValueError("INTEGER_TIMESTAMPS_REQUIRED")
        x[key] = values.astype(np.int64)
    if not x.open_ts_ms.is_monotonic_increasing or x.open_ts_ms.duplicated().any():
        raise ValueError("ORDERED_UNIQUE_BAR_REQUIRED")
    if (
        (x.open_ts_ms % TIMEFRAME_MS != 0)
        | (x.close_ts_ms != x.open_ts_ms + TIMEFRAME_MS)
        | (x.available_ts_ms < x.close_ts_ms)
    ).any():
        raise ValueError("UTC_COMPLETE_AVAILABLE_30M_REQUIRED")
    if x.segment_id.isna().any():
        raise ValueError("SEGMENT_REQUIRED")
    prices = x[["open", "high", "low", "close"]].to_numpy(float)
    if not np.isfinite(prices).all() or not (prices > 0).all():
        raise ValueError("POSITIVE_FINITE_OHLC_REQUIRED")
    if (
        (x.low > x[["open", "close"]].min(axis=1))
        | (x.high < x[["open", "close"]].max(axis=1))
    ).any():
        raise ValueError("CANDLE_GEOMETRY_INVALID")
    return x


def _atr(x: pd.DataFrame, length: int) -> pd.Series:
    previous = x.close.shift(1)
    tr = (
        pd.concat(
            [x.high - x.low, (x.high - previous).abs(), (x.low - previous).abs()],
            axis=1,
        )
        .max(axis=1)
        .to_numpy(float)
    )
    values = np.full(len(x), np.nan)
    if len(x) >= length:
        current = float(np.mean(tr[:length]))
        values[length - 1] = current
        for i in range(length, len(x)):
            current = ((length - 1) * current + tr[i]) / length
            values[i] = current
    return pd.Series(values, index=x.index)


def _linreg_endpoint(values: np.ndarray) -> float:
    if not np.isfinite(values).all():
        return float("nan")
    centered = np.arange(20, dtype=float) - 9.5
    return float(
        values.mean() + np.dot(values, centered) / np.dot(centered, centered) * 9.5
    )


def _enrich_segment(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy().reset_index(drop=True)
    x["atr"] = _atr(x, 14)
    x["atr20"] = _atr(x, 20)
    for n in sorted(set(LONG_GMMA + (8, 20, 21, 34))):
        x[f"g{n}"] = x.close.ewm(span=n, adjust=False).mean()
    up, down = x.high.diff(), -x.low.diff()
    plus = up.where((up > down) & (up > 0), 0.0)
    minus = down.where((down > up) & (down > 0), 0.0)
    pc = x.close.shift(1)
    tr = pd.concat(
        [x.high - x.low, (x.high - pc).abs(), (x.low - pc).abs()], axis=1
    ).max(axis=1)
    adxatr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / 14, adjust=False).mean() / adxatr
    mdi = 100 * minus.ewm(alpha=1 / 14, adjust=False).mean() / adxatr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    x["adx14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    x["hi20"] = x.high.shift(1).rolling(20).max()
    x["lo20"] = x.low.shift(1).rolling(20).min()
    mean20 = x.close.rolling(20).mean()
    sigma = x.close.rolling(20).std(ddof=0)
    x["squeeze_on"] = (mean20 + 2 * sigma < x.g20 + 1.5 * x.atr20) & (
        mean20 - 2 * sigma > x.g20 - 1.5 * x.atr20
    )
    delta = (
        x.close
        - ((x.high.rolling(20).max() + x.low.rolling(20).min()) / 2 + mean20) / 2
    )
    x["momentum"] = delta.rolling(20).apply(_linreg_endpoint, raw=True)
    x["feature_available_ts_ms"] = x.available_ts_ms.cummax()
    return x


def enriched_segments(frame: pd.DataFrame) -> list[pd.DataFrame]:
    x = _validated(frame)
    if x.empty:
        return []
    boundary = (
        (x.segment_id != x.segment_id.shift(1))
        | (x.open_ts_ms != x.close_ts_ms.shift(1))
    ).cumsum()
    return [_enrich_segment(group) for _, group in x.groupby(boundary, sort=False)]


def _regime(
    row: Mapping[str, Any], regimes: Mapping[int, Mapping[str, Any]] | None
) -> tuple[str, int]:
    record = dict(row)
    if regimes is not None:
        record.update(regimes.get(int(row["close_ts_ms"]), {}))
    fields = (
        "regime",
        "regime_available_ts_ms",
        "regime_fit_end_ts_ms",
        "regime_spec_sha256",
    )
    if any(k not in record or pd.isna(record[k]) for k in fields):
        return "UNBOUND", 0
    available = int(record["regime_available_ts_ms"])
    if (
        available > int(row["close_ts_ms"])
        or int(record["regime_fit_end_ts_ms"]) >= int(row["close_ts_ms"])
        or len(str(record["regime_spec_sha256"])) != 64
    ):
        return "UNBOUND", 0
    return str(record["regime"]), available


@dataclass
class HolyGrailState:
    side: int = 0
    episode_traded: bool = False
    stage: int = 0
    pull_low: float = math.inf
    pull_high: float = -math.inf

    def event_reset(self) -> None:
        self.stage, self.pull_low, self.pull_high = 0, math.inf, -math.inf

    def reset(self) -> None:
        self.side, self.episode_traded = 0, False
        self.event_reset()


def _hg_event(
    state: HolyGrailState, row: Mapping[str, Any], previous: Mapping[str, Any]
) -> tuple[int, float] | None:
    values = [float(row[f"g{n}"]) for n in LONG_GMMA]
    long = (
        all(a > z for a, z in zip(values, values[1:])) and row["g60"] > previous["g60"]
    )
    short = (
        all(a < z for a, z in zip(values, values[1:])) and row["g60"] < previous["g60"]
    )
    side = 1 if long else -1 if short else 0
    strong = (
        side != 0 and row["adx14"] >= 30 and side * (row["g20"] - previous["g20"]) > 0
    )
    if not strong:
        if row["adx14"] < 25 or side == 0:
            state.reset()
        return None
    if state.side != side:
        state.reset()
        state.side = side
    if state.episode_traded:
        renewed = row["high"] > row["hi20"] if side == 1 else row["low"] < row["lo20"]
        if renewed:
            state.episode_traded = False
            state.event_reset()
        return None
    if state.stage == 0:
        touched = row["low"] <= row["g20"] if side == 1 else row["high"] >= row["g20"]
        if touched:
            state.stage = 1
            state.pull_low, state.pull_high = float(row["low"]), float(row["high"])
        return None
    state.pull_low = min(state.pull_low, float(row["low"]))
    state.pull_high = max(state.pull_high, float(row["high"]))
    turn = (
        row["close"] > previous["high"] and row["close"] > row["g20"]
        if side == 1
        else row["close"] < previous["low"] and row["close"] < row["g20"]
    )
    if turn:
        state.episode_traded = True
        return side, state.pull_low if side == 1 else state.pull_high
    return None


def generate_signals(
    frames: dict[str, pd.DataFrame],
    regimes: Mapping[int, Mapping[str, Any]] | None = None,
    costs: Mapping[str, float] | None = None,
    identities: tuple[str, ...] = IDENTITIES,
) -> list[dict[str, Any]]:
    if any(identity not in IDENTITIES for identity in identities):
        raise ValueError("POSITIVE_IDENTITY_UNKNOWN")
    if costs is None:
        return []
    output: list[dict[str, Any]] = []
    for symbol, frame in sorted(frames.items()):
        cost = float(costs.get(symbol, float("nan")))
        if not math.isfinite(cost) or cost <= 0:
            continue
        for x in enriched_segments(frame):
            rows = x.to_dict("records")
            state = HolyGrailState()
            for i in range(1, len(rows)):
                row, previous = rows[i], rows[i - 1]
                hg = _hg_event(state, row, previous) if i >= 121 else None
                regime, regime_available = _regime(row, regimes)
                common = {
                    "symbol": symbol,
                    "timeframe_min": TIMEFRAME_MIN,
                    "signal_open_ts_ms": row["open_ts_ms"],
                    "signal_ts_ms": max(
                        int(row["feature_available_ts_ms"]), regime_available
                    ),
                    "segment_id": row["segment_id"],
                    "take_profit_r": None,
                }
                meta = {
                    "spec_sha256": SPEC_SHA256,
                    "regime": regime,
                    "feature_available_ts_ms": common["signal_ts_ms"],
                    "frozen_cost_bps": cost,
                    "historical_parity_claim": False,
                }
                if hg and regime in {"PANIC_DISPERSION", "TREND_DISPERSED"}:
                    side, reference = hg
                    for identity in (KELTNER_PARENT, KELTNER_TD075):
                        if identity not in identities:
                            continue
                        output.append(
                            {
                                **common,
                                "identity": identity,
                                "lane": "keltner_holygrail",
                                "side": side,
                                "stop_price": reference - side * 0.10 * row["atr"],
                                "invalidation_price": reference,
                                "max_hold_bars": 25,
                                "exit_policy": "KELTNER_HG_FEE_BE_PARTIAL_RUNNER",
                                "partial_take_profit_r": 2.0,
                                "partial_fraction": 0.10,
                                "meta": {
                                    **meta,
                                    "atr_price": row["atr"],
                                    "entry_cost_gate": {
                                        "atr_price": row["atr"],
                                        "min_ratio": 4.5,
                                    },
                                    "fallback_stop_atr_mult": 1.2,
                                    "be_arm_r": (
                                        0.75
                                        if identity == KELTNER_TD075
                                        and regime == "TREND_DISPERSED"
                                        else 1.0
                                    ),
                                    "event_trace": [
                                        "HG_GMMA",
                                        "FIRST_OR_RENEWED_EPISODE",
                                        "20EMA_PULLBACK",
                                        "TURN_TRIGGER",
                                    ],
                                },
                            }
                        )
                squeeze = (
                    i >= 80
                    and bool(previous["squeeze_on"])
                    and not bool(row["squeeze_on"])
                    and math.isfinite(row["momentum"])
                    and row["momentum"] > 0
                    and row["momentum"] > previous["momentum"]
                    and row["close"] > row["g34"]
                    and row["g8"] > row["g21"] > row["g34"]
                )
                if squeeze and regime == "PANIC_DISPERSION":
                    for identity in (SQUEEZE_PARENT, SQUEEZE_BE1R):
                        if identity not in identities:
                            continue
                        output.append(
                            {
                                **common,
                                "identity": identity,
                                "lane": "squeeze_break",
                                "side": 1,
                                "stop_price": row["g21"] - 2 * row["atr20"],
                                "max_hold_bars": 11,
                                "exit_policy": "SQUEEZE_TWO_WEAK_MOMENTUM",
                                "meta": {
                                    **meta,
                                    "atr_price": row["atr20"],
                                    "entry_cost_gate": {
                                        "atr_price": row["atr20"],
                                        "min_ratio": 4.0,
                                    },
                                    "fallback_stop_atr_mult": 2.0,
                                    "be_arm_r": (
                                        1.0 if identity == SQUEEZE_BE1R else None
                                    ),
                                    "event_trace": [
                                        "BB_KC_FIRST_FIRE",
                                        "MOMENTUM_ACCEL",
                                        "STACKED_MA",
                                        "PANIC_LONG",
                                    ],
                                },
                            }
                        )
    return sorted(
        output, key=lambda row: (row["signal_ts_ms"], row["symbol"], row["identity"])
    )


def entry_admission(signal: Mapping[str, Any], entry_price: float) -> dict[str, Any]:
    """Called only at actual next open; all non-entry inputs are frozen at signal."""
    if (
        signal["identity"] not in IDENTITIES
        or not math.isfinite(entry_price)
        or entry_price <= 0
    ):
        raise ValueError("INVALID_POSITIVE_ENTRY")
    meta = signal["meta"]
    gate = meta["entry_cost_gate"]
    cost, atr = float(meta["frozen_cost_bps"]), float(gate["atr_price"])
    fallback_mult = float(meta["fallback_stop_atr_mult"])
    minimum_ratio = float(gate["min_ratio"])
    if (
        not math.isfinite(fallback_mult)
        or fallback_mult <= 0
        or not math.isfinite(minimum_ratio)
        or minimum_ratio <= 0
    ):
        return {"allowed": False, "reason": "INVALID_FROZEN_ENTRY_GEOMETRY"}
    if not math.isfinite(cost) or cost <= 0 or not math.isfinite(atr) or atr <= 0:
        return {"allowed": False, "reason": "UNBOUND_COST_OR_ATR"}
    if atr / entry_price * 10_000 / cost < float(gate["min_ratio"]):
        return {"allowed": False, "reason": "ENTRY_ATR_COST_GATE"}
    side, stop = int(signal["side"]), float(signal["stop_price"])
    if side not in (-1, 1):
        return {"allowed": False, "reason": "INVALID_SIDE"}
    if side * (entry_price - stop) <= 0:
        stop = entry_price - side * fallback_mult * atr
    if not math.isfinite(stop) or stop <= 0:
        return {"allowed": False, "reason": "INVALID_FINAL_STOP"}
    return {
        "allowed": side * (entry_price - stop) > 0,
        "stop_price": stop,
        "reason": "FROZEN_ENTRY_ATR_COST_ADMITTED",
    }


def entry_update(signal: Mapping[str, Any], entry_price: float) -> dict[str, Any]:
    admission = entry_admission(signal, entry_price)
    if not admission["allowed"]:
        return {"reject": True, "reason": admission["reason"]}
    return {"stop_price": admission["stop_price"]}


def _last_momenta(history: pd.DataFrame) -> np.ndarray:
    # Three endpoints need 20 + 20 - 1 + 2 = 41 closed bars, no EMA seed.
    x = history.iloc[-41:]
    mean = x.close.rolling(20).mean()
    delta = (
        x.close - ((x.high.rolling(20).max() + x.low.rolling(20).min()) / 2 + mean) / 2
    )
    return delta.rolling(20).apply(_linreg_endpoint, raw=True).iloc[-3:].to_numpy(float)


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    signal = position["signal"]
    identity = signal["identity"]
    if identity not in IDENTITIES:
        raise ValueError("POSITIVE_POSITION_IDENTITY_MISMATCH")
    if history.empty or int(history.iloc[-1]["open_ts_ms"]) != int(bar["open_ts_ms"]):
        raise ValueError("POSITIVE_CLOSED_PREFIX_REQUIRED")
    if (history.available_ts_ms > int(bar["available_ts_ms"])).any():
        raise ValueError("POSITIVE_FUTURE_FEATURE_AVAILABILITY")
    if int(bar["open_ts_ms"]) < int(position["entry_ts_ms"]):
        raise ValueError("POSITIVE_EXIT_BEFORE_ENTRY")
    side = int(position["side"])
    if side not in (-1, 1):
        raise ValueError("POSITIVE_SIDE_INVALID")
    meta = signal["meta"]
    entry, risk = float(position["entry_price"]), float(position["initial_risk"])
    if risk <= 0:
        raise ValueError("POSITIVE_RISK_REQUIRED")
    result: dict[str, Any] = {
        "exit_next_open": False,
        "reason": "POSITIVE_LIFECYCLE_HOLD",
    }
    mfe = float(position["mfe_R"])
    arm = meta["be_arm_r"]
    lock = 2.0 if identity in (KELTNER_PARENT, KELTNER_TD075) else 0.0
    if arm is not None and mfe >= float(arm):
        result["next_stop"] = entry * (
            1 + side * (float(meta["frozen_cost_bps"]) + lock) / 10_000
        )
        result["reason"] = "FEE_BE_NEXT_BAR"
    if identity in (KELTNER_PARENT, KELTNER_TD075):
        if int(position["hold_bars"]) >= 5 and mfe < 0.40:
            return {"exit_next_open": True, "reason": "HG_FROZEN_5BAR_MFE_SCRATCH"}
        if mfe >= 3.0:
            # MFE fixes the already observed favorable extreme without future price.
            peak = entry + side * mfe * risk
            proposed = peak - side * 1.25 * risk
            prior = float(result.get("next_stop", position["stop_price"]))
            result["next_stop"] = (
                max(prior, proposed) if side == 1 else min(prior, proposed)
            )
            result["reason"] = "HG_3R_RUNNER_NEXT_BAR"
        partial_price = entry + side * 2.0 * risk
        touched = (
            float(bar["high"]) >= partial_price
            if side == 1
            else float(bar["low"]) <= partial_price
        )
        if float(position.get("remaining", 1.0)) == 1.0 and touched:
            result.update(partial_fraction=0.10, partial_price=partial_price)
        return result
    if len(history) >= 41:
        last = history.iloc[-3:]
        momenta = _last_momenta(history)
        if (
            last.iloc[0]["segment_id"] == last.iloc[-1]["segment_id"]
            and int(last.iloc[-2]["open_ts_ms"]) >= int(position["entry_ts_ms"])
            and np.isfinite(momenta).all()
            and momenta[2] > 0
            and momenta[1] > 0
            and momenta[2] < momenta[1] < momenta[0]
        ):
            result.update(
                exit_next_open=True, reason="SQUEEZE_TWO_WEAK_MOMENTUM_NEXT_OPEN"
            )
    return result
