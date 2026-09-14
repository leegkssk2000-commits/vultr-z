from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

SPEC_PATH = Path(__file__).with_name("benchmark25_donor_state_machine_v2.json")
MICRO_REQUIRED = {"liquidity_sweep", "scalp_snap", "vol_spike_fade", "vwap_revert"}


@dataclass
class MachineState:
    stage: int = 0
    side: str = "flat"
    mode: str = ""
    since: int = -1
    reference: float | None = None
    extreme: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        self.stage = 0
        self.side = "flat"
        self.mode = ""
        self.since = -1
        self.reference = None
        self.extreme = None
        self.payload.clear()


@dataclass(frozen=True)
class EntrySignal:
    strategy_id: str
    child_id: str
    side: str
    index: int
    signal_ts: int
    mode: str
    invalidation_ref: float | None
    event_extreme: float | None
    event_trace: tuple[str, ...]
    benchmark_ids: tuple[str, ...]
    transfer: tuple[str, ...]


def load_spec() -> dict[str, Any]:
    value = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if value.get("state") != "FROZEN_25_DONOR_EVENT_GRAMMARS":
        raise RuntimeError("DONOR_STATE_MACHINE_SPEC_INVALID")
    if len(value.get("children") or {}) != 25:
        raise RuntimeError("DONOR_STATE_MACHINE_COUNT_INVALID")
    return value


def _f(row: pd.Series, key: str, default: float = np.nan) -> float:
    try:
        return float(row.get(key, default))
    except Exception:
        return float(default)


def _micro_valid(row: pd.Series) -> bool:
    return bool(
        _f(row, "m_depth_messages", 0) > 0
        and _f(row, "m_trade_messages", 0) > 0
        and np.isfinite(_f(row, "m_trade_imbalance"))
    )


def _trend_side(row: pd.Series) -> str:
    c, e21, e55, e100 = (_f(row, x) for x in ("close", "ema21", "ema55", "ema100"))
    if c > e21 > e55 > e100:
        return "long"
    if c < e21 < e55 < e100:
        return "short"
    return "flat"


def _reset_if_stale(state: MachineState, i: int, ttl: int = 8) -> None:
    if state.stage and state.since >= 0 and i - state.since > ttl:
        state.reset()


def _arm(
    state: MachineState,
    i: int,
    side: str,
    mode: str = "",
    reference: float | None = None,
    extreme: float | None = None,
    **payload: Any,
) -> None:
    state.stage += 1
    state.since = i
    if side != "flat":
        state.side = side
    if mode:
        state.mode = mode
    if reference is not None and np.isfinite(reference):
        state.reference = float(reference)
    if extreme is not None and np.isfinite(extreme):
        state.extreme = float(extreme)
    state.payload.update(payload)


def _emit(
    sid: str,
    state: MachineState,
    i: int,
    row: pd.Series,
    spec: Mapping[str, Any],
    trace: list[str],
) -> EntrySignal:
    signal = EntrySignal(
        strategy_id=sid,
        child_id=str(spec["child_id"]),
        side=state.side,
        index=i,
        signal_ts=int(row["ts_ms"]),
        mode=state.mode or "DEFAULT",
        invalidation_ref=state.reference,
        event_extreme=state.extreme,
        event_trace=tuple(trace),
        benchmark_ids=tuple(spec["benchmark_ids"]),
        transfer=tuple(spec["source_transfer"]),
    )
    state.reset()
    return signal


def _ref(state: MachineState) -> float:
    if state.reference is None or not np.isfinite(_ref(state)):
        raise RuntimeError("STATE_REFERENCE_REQUIRED")
    return _ref(state)


def _basic(row: pd.Series, prev: pd.Series) -> dict[str, float]:
    a = max(_f(row, "atr"), 1e-12)
    c, p = _f(row, "close"), _f(prev, "close")
    return {
        "a": a,
        "c": c,
        "p": p,
        "o": _f(row, "open"),
        "h": _f(row, "high"),
        "l": _f(row, "low"),
        "hi20": _f(row, "hi20"),
        "lo20": _f(row, "lo20"),
        "hi50": _f(row, "hi50"),
        "lo50": _f(row, "lo50"),
        "e8": _f(row, "ema8"),
        "e21": _f(row, "ema21"),
        "e50": _f(row, "ema50"),
        "e55": _f(row, "ema55"),
        "e100": _f(row, "ema100"),
        "v20": _f(row, "vwap20"),
        "v50": _f(row, "vwap50"),
        "mean20": _f(row, "mean20"),
        "sd20": _f(row, "sd20"),
        "rv": _f(row, "rel_vol20"),
        "rv50": _f(row, "rel_vol50"),
        "rsi": _f(row, "rsi"),
        "rsi_prev": _f(row, "rsi_prev"),
        "mfi": _f(row, "mfi"),
        "mfi_prev": _f(row, "mfi_prev"),
        "obv": _f(row, "obv_delta34"),
        "bb": _f(row, "bb_width_atr"),
        "bbp": _f(row, "bb_prev_width_atr"),
        "hour": _f(row, "hour"),
        "avl": _f(row, "avwap_long"),
        "avs": _f(row, "avwap_short"),
        "ti": _f(row, "m_trade_imbalance"),
        "im": _f(row, "m_imbalance_delta"),
        "bc": _f(row, "m_bid_change"),
        "ac": _f(row, "m_ask_change"),
    }


def step_machine(
    sid: str, state: MachineState, x: pd.DataFrame, i: int, spec: Mapping[str, Any]
) -> EntrySignal | None:
    if i < 101:
        return None
    row, prev = x.iloc[i], x.iloc[i - 1]
    b = _basic(row, prev)
    _reset_if_stale(
        state, i, 10 if sid in {"break_and_continue", "squeeze_break"} else 8
    )
    trend = _trend_side(row)
    trace = list(spec["event_sequence"])
    a, c, p = b["a"], b["c"], b["p"]
    dist21 = abs(c - b["e21"]) / a
    flat = abs(b["e21"] - b["e55"]) / a

    if sid == "turtle_trend":
        if state.stage == 0 and np.isfinite(b["hi20"]):
            _arm(state, i, "flat", "DONCHIAN_RANGE")
        elif state.stage == 1:
            if c > b["hi20"]:
                _arm(state, i, "long", reference=b["hi20"])
                return _emit(sid, state, i, row, spec, trace)
            if c < b["lo20"]:
                _arm(state, i, "short", reference=b["lo20"])
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "bb_revert":
        if state.stage == 0 and flat <= 0.65:
            _arm(state, i, "flat", "RANGE_REGIME")
        elif state.stage == 1:
            lo, hi = b["mean20"] - 1.8 * b["sd20"], b["mean20"] + 1.8 * b["sd20"]
            if b["l"] < lo:
                _arm(state, i, "long", reference=lo, extreme=b["l"])
            elif b["h"] > hi:
                _arm(state, i, "short", reference=hi, extreme=b["h"])
        elif state.stage == 2:
            ok = (
                c > _ref(state) and c > p
                if state.side == "long"
                else c < _ref(state) and c < p
            )
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "anchor_vwap_trend":
        if state.stage == 0 and trend != "flat":
            ref = b["avl"] if trend == "long" else b["avs"]
            _arm(state, i, trend, "AVWAP_REFERENCE", reference=ref)
        elif state.stage == 1:
            ref = _ref(state)
            touched = b["l"] <= ref if state.side == "long" else b["h"] >= ref
            if touched:
                _arm(
                    state,
                    i,
                    state.side,
                    extreme=b["l"] if state.side == "long" else b["h"],
                )
        elif state.stage == 2:
            ref = _ref(state)
            ok = (
                c > ref and c > p and b["rv"] >= 0.8
                if state.side == "long"
                else c < ref and c < p and b["rv"] >= 0.8
            )
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "vwap_revert":
        if not _micro_valid(row):
            state.reset()
            return None
        if state.stage == 0:
            if c < b["v20"] - 0.7 * a:
                _arm(
                    state,
                    i,
                    "long",
                    "VWAP_DISPLACEMENT",
                    reference=b["v20"],
                    extreme=b["l"],
                )
            elif c > b["v20"] + 0.7 * a:
                _arm(
                    state,
                    i,
                    "short",
                    "VWAP_DISPLACEMENT",
                    reference=b["v20"],
                    extreme=b["h"],
                )
        elif state.stage == 1:
            exhausted = (
                b["ti"] >= -0.05 and b["im"] > 0
                if state.side == "long"
                else b["ti"] <= 0.05 and b["im"] < 0
            )
            if exhausted:
                _arm(state, i, state.side)
        elif state.stage == 2:
            reclaim = c > p if state.side == "long" else c < p
            if reclaim:
                _arm(state, i, state.side)
        elif state.stage == 3:
            if int(b["hour"]) not in (21, 22, 23):
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "break_and_continue":
        if state.stage == 0 and b["bb"] <= 3.0:
            _arm(state, i, "flat", "COMPRESSION")
        elif state.stage == 1:
            if c > b["hi20"]:
                _arm(state, i, "long", "BREAKOUT", reference=b["hi20"], extreme=b["h"])
            elif c < b["lo20"]:
                _arm(state, i, "short", "BREAKOUT", reference=b["lo20"], extreme=b["l"])
        elif state.stage == 2:
            ref = _ref(state)
            hold = (
                b["l"] <= ref + 0.35 * a and c > ref
                if state.side == "long"
                else b["h"] >= ref - 0.35 * a and c < ref
            )
            if hold:
                _arm(state, i, state.side)
        elif state.stage == 3:
            cont = (
                c > p and dist21 <= 1.5
                if state.side == "long"
                else c < p and dist21 <= 1.5
            )
            if cont:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid in {"keltner_trend", "supertrend_pullback", "trend_rider"}:
        if state.stage == 0 and trend != "flat":
            if (
                sid != "trend_rider"
                or (trend == "long" and b["e50"] >= _f(prev, "ema50"))
                or (trend == "short" and b["e50"] <= _f(prev, "ema50"))
            ):
                _arm(state, i, trend, "TREND_STATE", reference=b["e21"])
        elif state.stage == 1:
            if sid == "keltner_trend":
                exp = (
                    (c > b["e21"] + 1.2 * a and (b["h"] - b["l"]) / a >= 0.8)
                    if state.side == "long"
                    else (c < b["e21"] - 1.2 * a and (b["h"] - b["l"]) / a >= 0.8)
                )
                if exp:
                    _arm(
                        state,
                        i,
                        state.side,
                        extreme=b["h"] if state.side == "long" else b["l"],
                    )
            else:
                pull = (
                    b["l"] <= b["e21"] + 0.7 * a
                    if state.side == "long"
                    else b["h"] >= b["e21"] - 0.7 * a
                )
                if pull:
                    _arm(
                        state,
                        i,
                        state.side,
                        extreme=b["l"] if state.side == "long" else b["h"],
                    )
        elif state.stage == 2:
            if sid == "keltner_trend":
                pull = dist21 <= 1.2 and (
                    (c > b["e21"]) if state.side == "long" else (c < b["e21"])
                )
                if pull:
                    _arm(state, i, state.side)
            else:
                reclaim = (
                    c > p and c > b["e21"]
                    if state.side == "long"
                    else c < p and c < b["e21"]
                )
                if reclaim:
                    _arm(state, i, state.side)
                    return _emit(sid, state, i, row, spec, trace)
        elif state.stage == 3 and sid == "keltner_trend":
            cont = (
                c > p and dist21 <= 1.6
                if state.side == "long"
                else c < p and dist21 <= 1.6
            )
            if cont:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "squeeze_break":
        if state.stage == 0 and b["bb"] <= 2.2:
            _arm(state, i, "flat", "SQUEEZE")
        elif state.stage == 1 and b["bb"] > b["bbp"]:
            _arm(state, i, "flat")
        elif state.stage == 2:
            rng = (b["h"] - b["l"]) / a
            if rng >= 0.9 and c > b["hi20"]:
                _arm(state, i, "long", reference=b["hi20"])
            elif rng >= 0.9 and c < b["lo20"]:
                _arm(state, i, "short", reference=b["lo20"])
        elif state.stage == 3:
            ok = (
                c > p and dist21 <= 1.5
                if state.side == "long"
                else c < p and dist21 <= 1.5
            )
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "trend_ma_macd":
        hist = _f(row, "macd_hist")
        hp = _f(prev, "macd_hist")
        if state.stage == 0 and trend != "flat":
            _arm(state, i, trend, "GMMA_TREND", reference=b["e21"])
        elif state.stage == 1:
            reset = hist <= 0 if state.side == "long" else hist >= 0
            if reset:
                _arm(state, i, state.side)
        elif state.stage == 2:
            accel = (
                hist > 0 and hp <= 0 and dist21 <= 1.25
                if state.side == "long"
                else hist < 0 and hp >= 0 and dist21 <= 1.25
            )
            if accel:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid in {"liquidity_sweep", "scalp_snap", "vol_spike_fade"}:
        if not _micro_valid(row):
            state.reset()
            return None
        if sid == "liquidity_sweep":
            if state.stage == 0:
                if b["bc"] < -0.05 or b["im"] < -0.10:
                    _arm(state, i, "long", "L2_DEPLETION")
                elif b["ac"] < -0.05 or b["im"] > 0.10:
                    _arm(state, i, "short", "L2_DEPLETION")
            elif state.stage == 1:
                sweep = (
                    b["l"] < b["lo20"] if state.side == "long" else b["h"] > b["hi20"]
                )
                if sweep:
                    _arm(
                        state,
                        i,
                        state.side,
                        reference=b["lo20"] if state.side == "long" else b["hi20"],
                        extreme=b["l"] if state.side == "long" else b["h"],
                    )
            elif state.stage == 2:
                rep = (
                    (b["bc"] > 0 and b["im"] > 0)
                    if state.side == "long"
                    else (b["ac"] > 0 and b["im"] < 0)
                )
                if rep:
                    _arm(state, i, state.side)
            elif state.stage == 3:
                ref = _ref(state)
                ok = c > ref if state.side == "long" else c < ref
                if ok:
                    _arm(state, i, state.side)
                    return _emit(sid, state, i, row, spec, trace)
        elif sid == "scalp_snap":
            move = c - p
            if state.stage == 0:
                if move <= -0.9 * a:
                    _arm(state, i, "long", "FAILED_IMPULSE", extreme=b["l"])
                elif move >= 0.9 * a:
                    _arm(state, i, "short", "FAILED_IMPULSE", extreme=b["h"])
            elif state.stage == 1:
                ex = b["ti"] >= -0.05 if state.side == "long" else b["ti"] <= 0.05
                if ex:
                    _arm(state, i, state.side)
            elif state.stage == 2:
                rec = (
                    (b["bc"] > 0 and b["im"] > 0)
                    if state.side == "long"
                    else (b["ac"] > 0 and b["im"] < 0)
                )
                if rec:
                    _arm(state, i, state.side)
            elif state.stage == 3:
                snap = (
                    (c - p) >= 0.4 * a if state.side == "long" else (p - c) >= 0.4 * a
                )
                if snap:
                    _arm(state, i, state.side)
                    return _emit(sid, state, i, row, spec, trace)
        else:
            rng = (b["h"] - b["l"]) / a
            if state.stage == 0 and rng >= 1.2:
                _arm(state, i, "flat", "RANGE_EXPANSION")
            elif state.stage == 1 and b["rv"] >= 1.8:
                side = "short" if c > b["o"] else "long"
                _arm(state, i, side, extreme=b["h"] if side == "short" else b["l"])
            elif state.stage == 2:
                fail = (
                    (c < p and b["ti"] <= 0.05 and b["im"] < 0)
                    if state.side == "short"
                    else (c > p and b["ti"] >= -0.05 and b["im"] > 0)
                )
                if fail:
                    _arm(state, i, state.side)
                    return _emit(sid, state, i, row, spec, trace)
        return None

    if sid in {"range_fade", "grid_rebalance"}:
        if state.stage == 0 and flat <= 0.7:
            _arm(state, i, "flat", "RANGE_REGIME")
        elif state.stage == 1:
            if sid == "range_fade":
                if b["l"] < b["lo20"]:
                    _arm(state, i, "long", reference=b["lo20"], extreme=b["l"])
                elif b["h"] > b["hi20"]:
                    _arm(state, i, "short", reference=b["hi20"], extreme=b["h"])
            else:
                ext = (c - b["v50"]) / a
                if ext <= -0.9:
                    _arm(state, i, "long", reference=b["v50"], extreme=b["l"])
                elif ext >= 0.9:
                    _arm(state, i, "short", reference=b["v50"], extreme=b["h"])
        elif state.stage == 2:
            ref = _ref(state)
            reclaim = (
                (c > p and c > ref - 0.5 * a)
                if state.side == "long"
                else (c < p and c < ref + 0.5 * a)
            )
            if reclaim:
                _arm(state, i, state.side)
                if sid == "grid_rebalance":
                    return _emit(sid, state, i, row, spec, trace)
        elif state.stage == 3 and sid == "range_fade":
            veto = not (
                (state.side == "long" and trend == "short")
                or (state.side == "short" and trend == "long")
            )
            if veto:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "fvg_revert":
        if state.stage == 0 and (b["h"] - b["l"]) / a >= 1.3:
            side = "long" if c < b["o"] else "short"
            _arm(
                state,
                i,
                side,
                "DISPLACEMENT",
                reference=(b["h"] + b["l"]) / 2,
                extreme=b["l"] if side == "long" else b["h"],
            )
        elif state.stage == 1:
            fail = c > p if state.side == "long" else c < p
            if fail:
                _arm(state, i, state.side)
        elif state.stage == 2:
            ref = _ref(state)
            ok = c > ref if state.side == "long" else c < ref
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "pivot_reversal":
        if state.stage == 0 and np.isfinite(b["hi20"]):
            _arm(state, i, "flat", "REFERENCE_LEVEL")
        elif state.stage == 1:
            if b["l"] < b["lo20"] and c > b["lo20"]:
                _arm(state, i, "long", reference=b["lo20"], extreme=b["l"])
            elif b["h"] > b["hi20"] and c < b["hi20"]:
                _arm(state, i, "short", reference=b["hi20"], extreme=b["h"])
        elif state.stage == 2:
            ok = c >= b["v20"] if state.side == "long" else c <= b["v20"]
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "rsi_swing_fail":
        if state.stage == 0:
            if b["l"] < b["lo20"]:
                _arm(
                    state,
                    i,
                    "long",
                    "FAILED_SWING",
                    reference=b["lo20"],
                    extreme=b["l"],
                )
            elif b["h"] > b["hi20"]:
                _arm(
                    state,
                    i,
                    "short",
                    "FAILED_SWING",
                    reference=b["hi20"],
                    extreme=b["h"],
                )
        elif state.stage == 1:
            ref = _ref(state)
            ok = c > ref if state.side == "long" else c < ref
            if ok:
                _arm(state, i, state.side)
        elif state.stage == 2:
            osc = (
                b["rsi"] > b["rsi_prev"]
                if state.side == "long"
                else b["rsi"] < b["rsi_prev"]
            )
            if osc:
                _arm(state, i, state.side)
        elif state.stage == 3 and flat <= 1.2:
            _arm(state, i, state.side)
            return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "alpha_combo":
        gap = abs(b["e21"] - b["e55"]) / a
        if state.stage == 0:
            mode = "MOMENTUM_REGIME" if gap >= 0.7 else "MEAN_REVERSION_REGIME"
            _arm(state, i, "flat", mode)
        elif state.stage == 1:
            if state.mode == "MOMENTUM_REGIME":
                if trend == "long" and c > b["hi20"]:
                    _arm(state, i, "long")
                elif trend == "short" and c < b["lo20"]:
                    _arm(state, i, "short")
            else:
                if c < b["v20"] - 0.6 * a:
                    _arm(state, i, "long", reference=b["v20"])
                elif c > b["v20"] + 0.6 * a:
                    _arm(state, i, "short", reference=b["v20"])
        elif state.stage == 2:
            ok = (
                (b["rv"] >= 1.0)
                if state.mode == "MOMENTUM_REGIME"
                else (c > p if state.side == "long" else c < p)
            )
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "ema_ribbon_scalp":
        sep = (abs(b["e8"] - b["e21"]) + abs(b["e21"] - b["e55"])) / a
        ribbon = (
            "long"
            if c > b["e8"] > b["e21"] > b["e55"]
            else "short" if c < b["e8"] < b["e21"] < b["e55"] else "flat"
        )
        if state.stage == 0 and ribbon != "flat" and sep >= 0.2:
            _arm(state, i, ribbon, "RIBBON_STATE", reference=b["e21"])
        elif state.stage == 1:
            pull = (
                b["l"] <= b["e8"] + 0.4 * a
                if state.side == "long"
                else b["h"] >= b["e8"] - 0.4 * a
            )
            if pull:
                _arm(
                    state,
                    i,
                    state.side,
                    extreme=b["l"] if state.side == "long" else b["h"],
                )
        elif state.stage == 2:
            ok = (
                c > p and dist21 <= 0.85
                if state.side == "long"
                else c < p and dist21 <= 0.85
            )
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "mfi_rsi_div":
        if state.stage == 0:
            if b["l"] <= b["lo50"]:
                _arm(
                    state,
                    i,
                    "long",
                    "STRUCTURAL_EXTREME",
                    reference=b["lo50"],
                    extreme=b["l"],
                )
            elif b["h"] >= b["hi50"]:
                _arm(
                    state,
                    i,
                    "short",
                    "STRUCTURAL_EXTREME",
                    reference=b["hi50"],
                    extreme=b["h"],
                )
        elif state.stage == 1:
            fail = c > p if state.side == "long" else c < p
            if fail:
                _arm(state, i, state.side)
        elif state.stage == 2:
            div = (
                (b["rsi"] > b["rsi_prev"] and b["mfi"] > b["mfi_prev"])
                if state.side == "long"
                else (b["rsi"] < b["rsi_prev"] and b["mfi"] < b["mfi_prev"])
            )
            if div:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "obv_trend":
        if state.stage == 0 and trend != "flat":
            _arm(state, i, trend, "TREND_STRUCTURE", reference=b["e21"])
        elif state.stage == 1:
            br = c > b["hi20"] if state.side == "long" else c < b["lo20"]
            if br:
                _arm(
                    state,
                    i,
                    state.side,
                    reference=b["hi20"] if state.side == "long" else b["lo20"],
                )
        elif state.stage == 2:
            part = b["rv"] >= 1.15 and (
                b["obv"] > 0 if state.side == "long" else b["obv"] < 0
            )
            if part:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "rbreaker_like":
        if state.stage == 0 and np.isfinite(b["hi20"]):
            _arm(state, i, "flat", "PRIOR_RANGE")
        elif state.stage == 1:
            if c > b["hi20"]:
                _arm(state, i, "long", "BREAKOUT", reference=b["hi20"])
            elif c < b["lo20"]:
                _arm(state, i, "short", "BREAKOUT", reference=b["lo20"])
            elif b["l"] < b["lo20"] and c > b["lo20"]:
                _arm(state, i, "long", "FAILED_BREAK_REVERSAL", reference=b["lo20"])
            elif b["h"] > b["hi20"] and c < b["hi20"]:
                _arm(state, i, "short", "FAILED_BREAK_REVERSAL", reference=b["hi20"])
        elif state.stage == 2:
            ok = c > p if state.side == "long" else c < p
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "session_bias":
        liquid = (
            b["rv"] >= 1.05
            and (b["h"] - b["l"]) / a >= 0.8
            and int(b["hour"]) not in (21, 22, 23)
        )
        if state.stage == 0 and liquid:
            _arm(state, i, "flat", "LIQUIDITY_REGIME")
        elif state.stage == 1:
            _arm(state, i, "flat", reference=b["hi20"])
        elif state.stage == 2:
            if c > b["hi20"]:
                _arm(state, i, "long", reference=b["hi20"])
            elif c < b["lo20"]:
                _arm(state, i, "short", reference=b["lo20"])
        elif state.stage == 3:
            ok = c > p if state.side == "long" else c < p
            if ok:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    if sid == "sr_levels":
        if state.stage == 0 and np.isfinite(b["hi50"]):
            _arm(state, i, "flat", "PRIOR_LEVEL")
        elif state.stage == 1:
            if c > b["hi50"]:
                _arm(state, i, "long", "CONTINUATION", reference=b["hi50"])
            elif c < b["lo50"]:
                _arm(state, i, "short", "CONTINUATION", reference=b["lo50"])
            elif _f(prev, "high") > b["hi50"] and b["l"] <= b["hi50"] < c:
                _arm(state, i, "long", "BREAK_RECLAIM", reference=b["hi50"])
            elif _f(prev, "low") < b["lo50"] and b["h"] >= b["lo50"] > c:
                _arm(state, i, "short", "BREAK_RECLAIM", reference=b["lo50"])
        elif state.stage == 2:
            if b["rv50"] >= 1.25:
                _arm(state, i, state.side)
                return _emit(sid, state, i, row, spec, trace)
        return None

    raise KeyError(f"STATE_MACHINE_UNMAPPED:{sid}")


def validate_coverage() -> int:
    spec = load_spec()
    expected = set(spec["children"])
    mapped = {
        "alpha_combo",
        "anchor_vwap_trend",
        "bb_revert",
        "break_and_continue",
        "ema_ribbon_scalp",
        "fvg_revert",
        "grid_rebalance",
        "keltner_trend",
        "liquidity_sweep",
        "mfi_rsi_div",
        "obv_trend",
        "pivot_reversal",
        "range_fade",
        "rbreaker_like",
        "rsi_swing_fail",
        "scalp_snap",
        "session_bias",
        "squeeze_break",
        "sr_levels",
        "supertrend_pullback",
        "trend_ma_macd",
        "trend_rider",
        "turtle_trend",
        "vol_spike_fade",
        "vwap_revert",
    }
    if expected != mapped:
        raise RuntimeError(
            f"STATE_MACHINE_COVERAGE_MISMATCH:{sorted(expected ^ mapped)}"
        )
    for sid, child in spec["children"].items():
        seq = child["event_sequence"]
        if "ENTER" not in seq and "ENTER_FADE" not in seq:
            raise RuntimeError(f"STATE_MACHINE_ENTRY_STAGE_MISSING:{sid}")
        reuse = child["parent_reuse"]
        if any(reuse.values()):
            raise RuntimeError(f"PARENT_REUSE_FORBIDDEN:{sid}")
    print("PASS_DONOR_STATE_MACHINE_25_OF_25")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate_coverage())
