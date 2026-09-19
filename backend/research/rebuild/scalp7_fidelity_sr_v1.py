"""SR native lineage matched 30m pair; prior-level reclaim binding is the only axis.

Source cases were frozen before this implementation. Both identities are new
market/timeframe/execution adaptations, never reproductions of the old 5m run.
No evaluator, source fetch, order or live path exists here.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from typing import Any

import numpy as np
import pandas as pd

material: Any = importlib.import_module(
    "backend.research.rebuild.scalp7_materials_program_v2"
)
native: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_native_replay_v1"
)

CONTROL = "sr_levels_30m_native_control_fidelity_v1"
CHILD = "sr_levels_30m_prebreak_reference_reclaim_fidelity_v1"
IDENTITIES = (CONTROL, CHILD)
TF_MS = 30 * 60_000
PREPARED = "scalp7_fidelity_sr_v1_prepared"
SPEC = {
    "identities": list(IDENTITIES),
    "timeframe_min": 30,
    "actual_lineage": "a1_benchmark25_donor_native_replay_v1.signal_masks",
    "axis": "RECLAIM_REFERENCE_FROM_BAR_BEFORE_BREAKOUT",
    "control_reference": "current prior50 includes previous breakout candle",
    "child_reference": "previous candle prior50 excludes breakout candle",
    "warmup_bars": 120,
    "lookback_bars": 50,
    "volume": "real canonical volume; ratio to previous50 mean; units not inferred",
    "atr": "native Wilder14 mean seed then recursive smoothing, reset at gaps",
    "continuation_relative_volume": 1.25,
    "reclaim_relative_volume": 1.0,
    "relative_volume_validity": "finite ratio required in both arms; zero denominator unobserved",
    "stop": "two completed event candle extremes +/-0.15ATR",
    "adverse_stop_fallback_at_fill_atr": 0.9,
    "take_profit_r": 2.0,
    "trail_activate_r": 1.0,
    "trail_atr": 1.7,
    "scratch_mfe_r": 0.4,
    "scratch_elapsed_min": 25,
    "scratch_first_30m_observation_min": 30,
    "legacy_actual_timeout_min": 95,
    "timeout_first_30m_observation_min": 120,
    "max_hold_bars": 4,
    "closed_decision_exit": "NEXT_OPEN",
    "exact_5m_economic_parity_claim": False,
    "historical_threshold_retune": False,
    "order": "BLOCKED",
    "live": "BLOCKED",
}
SPEC_SHA256 = hashlib.sha256(
    json.dumps(SPEC, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def _identity(identity: str) -> bool:
    if identity not in IDENTITIES:
        raise ValueError("SR_UNKNOWN_FROZEN_IDENTITY")
    return identity == CHILD


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.attrs.get(PREPARED):
        return frame
    if "volume" not in frame:
        raise ValueError("SR_REAL_CANONICAL_VOLUME_REQUIRED")
    volume = pd.to_numeric(frame["volume"], errors="coerce").to_numpy(float)
    if not np.isfinite(volume).all() or (volume < 0).any():
        raise ValueError("SR_VOLUME_INVALID")
    x = material._prepare(frame)
    if x.empty:
        x.attrs[PREPARED] = True
        return x
    outputs = []
    for _, group in x.groupby("_local_segment", sort=False):
        g = group.copy()
        g["atr"] = native.wilder_atr(g, 14)
        g["hi50"] = g.high.shift(1).rolling(50).max()
        g["lo50"] = g.low.shift(1).rolling(50).min()
        g["prebreak_hi50"] = g["hi50"].shift(1)
        g["prebreak_lo50"] = g["lo50"].shift(1)
        g["rel_vol50"] = g["volume"] / g["volume"].shift(1).rolling(50).mean()
        outputs.append(g)
    result = pd.concat(outputs).sort_index()
    result.attrs[PREPARED] = True
    return result


def prepare_frames(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {symbol: _prepare(frame) for symbol, frame in frames.items()}


def signal_masks(
    frame: pd.DataFrame, child: bool
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Match actual native masks; change only the two reclaim reference series."""
    c = frame["close"]
    high, low = frame["hi50"], frame["lo50"]
    rv = frame["rel_vol50"].where(np.isfinite(frame["rel_vol50"]))
    continuation_long = (c > high) & (rv >= 1.25)
    continuation_short = (c < low) & (rv >= 1.25)
    reclaim_high = frame["prebreak_hi50"] if child else high
    reclaim_low = frame["prebreak_lo50"] if child else low
    reclaim_long = (
        (frame.high.shift(1) > reclaim_high)
        & (frame.low <= reclaim_high)
        & (c > reclaim_high)
        & (rv >= 1.0)
    )
    reclaim_short = (
        (frame.low.shift(1) < reclaim_low)
        & (frame.high >= reclaim_low)
        & (c < reclaim_low)
        & (rv >= 1.0)
    )
    mode = pd.Series("DEFAULT", index=frame.index, dtype=object)
    mode.loc[continuation_long | continuation_short] = "CONTINUATION"
    # This override order is the actual native replay's order.
    mode.loc[reclaim_long | reclaim_short] = "BREAK_RECLAIM"
    return continuation_long | reclaim_long, continuation_short | reclaim_short, mode


def generate_signals(
    frames: dict[str, pd.DataFrame],
    costs: dict[str, float] | None = None,
    identity: str = CONTROL,
) -> list[dict[str, Any]]:
    child = _identity(identity)
    del costs  # No strategy-side cost filter is part of this matched pair.
    signals = []
    for symbol, raw in sorted(frames.items()):
        x = _prepare(raw)
        if x.empty:
            continue
        for _, segment in x.groupby("_local_segment", sort=False):
            group = segment.reset_index(drop=True)
            long_mask, short_mask, modes = signal_masks(group, child)
            for i in np.flatnonzero((long_mask | short_mask).fillna(False)):
                i = int(i)
                if i < 120 or bool(long_mask.iloc[i]) == bool(short_mask.iloc[i]):
                    continue
                row, prev = group.iloc[i], group.iloc[i - 1]
                side = 1 if bool(long_mask.iloc[i]) else -1
                a = float(row["atr"])
                if not np.isfinite(a) or a <= 0:
                    continue
                extreme = (
                    min(float(row.low), float(prev.low))
                    if side == 1
                    else max(float(row.high), float(prev.high))
                )
                stop = extreme - side * 0.15 * a
                if stop <= 0:
                    continue
                mode = str(modes.iloc[i])
                ref = float(
                    row["prebreak_hi50" if side == 1 else "prebreak_lo50"]
                    if child and mode == "BREAK_RECLAIM"
                    else row["hi50" if side == 1 else "lo50"]
                )
                signals.append(
                    {
                        "identity": identity,
                        "lane": "MATERIAL:sr_levels",
                        "timeframe_min": 30,
                        "symbol": symbol,
                        "side": side,
                        "signal_open_ts_ms": int(row.open_ts_ms),
                        "signal_ts_ms": int(row["_feature_available_ts_ms"]),
                        "segment_id": row.segment_id,
                        "stop_price": stop,
                        "max_hold_bars": 4,
                        "take_profit_r": 2.0,
                        "exit_policy": "SR_NATIVE_ELAPSED_LIFECYCLE_30M",
                        "meta": {
                            "spec_sha256": SPEC_SHA256,
                            "mode": mode,
                            "reference": ref,
                            "reference_open_ts_ms": int(
                                prev.open_ts_ms
                                if child and mode == "BREAK_RECLAIM"
                                else row.open_ts_ms
                            ),
                            "feature_available_ts_ms": int(
                                row["_feature_available_ts_ms"]
                            ),
                            "atr_price": a,
                            "rel_vol50": float(row.rel_vol50),
                            "stop_fallback_atr_price": 0.9 * a,
                            "source_timeframe_min": 5,
                            "shared_timeframe_adaptation_min": 30,
                            "legacy_timeout_actual_min": 95,
                            "timeout_observation_min": 120,
                            "scratch_observation_min": 30,
                            "volume_basis": "CANONICAL_RECORDED_UNITS_RATIO_ONLY",
                            "historical_outcome_features": False,
                        },
                    }
                )
    return sorted(signals, key=lambda s: (s["signal_ts_ms"], s["symbol"]))


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    _identity(position["signal"]["identity"])
    if bar["segment_id"] != position["signal"]["segment_id"]:
        return {"exit_next_open": False, "reason": "GAP_HOLD_ENGINE_OWNS_BOUNDARY"}
    if int(bar["available_ts_ms"]) < int(bar["close_ts_ms"]):
        raise ValueError("SR_CLOSED_BAR_REQUIRED")
    elapsed = int(bar["close_ts_ms"]) - int(position["entry_ts_ms"])
    mfe = float(position["mfe_R"])
    if elapsed >= 25 * 60_000 and mfe < 0.4:
        return {"exit_next_open": True, "reason": "SR_SCRATCH_ELAPSED_25M"}
    if elapsed >= 95 * 60_000:
        return {"exit_next_open": True, "reason": "SR_TIMEOUT_ELAPSED_95M"}
    update: dict[str, Any] = {"exit_next_open": False, "reason": "SR_THESIS_INTACT"}
    if mfe >= 1.0:
        prepared = _prepare(history)
        a = float(prepared.iloc[-1]["atr"])
        if not np.isfinite(a) or a <= 0:
            raise ValueError("SR_CAUSAL_ATR_REQUIRED")
        side = int(position["side"])
        peak = float(position["entry_price"]) + side * mfe * float(
            position["initial_risk"]
        )
        update["next_stop"] = peak - side * 1.7 * a
    return update
