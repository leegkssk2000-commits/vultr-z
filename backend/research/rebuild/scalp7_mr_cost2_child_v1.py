"""Issue1377 cost-covered MR child; distinct source version from frozen MR V2.

The scanner is extracted from PR1378 without changing child signal metadata,
cost admission or independent occupancy. Parent helpers/constants remain bound
to the original preregistered module. This module has no execution authority.
"""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.research.rebuild import scalp7_mr_formation_v2 as parent

TF_MS = parent.TF_MS
MAX_HOLD_BARS = parent.MAX_HOLD_BARS
PARENT_SYMBOLS = parent.PARENT_SYMBOLS
PARENT_LOOKBACK = parent.PARENT_LOOKBACK
PARENT_STRETCH = parent.PARENT_STRETCH
PARENT_MIN_FAIL_BARS = parent.PARENT_MIN_FAIL_BARS
REEXPANSION_IDENTITY = parent.REEXPANSION_IDENTITY
COST_COVERED_IDENTITY = "mr_cross_sectional_contraction_cost2_gate_30m_v1"
_frame = parent._frame


def _control_signals(
    frames: dict[str, pd.DataFrame],
    identities: tuple[str, ...] = (COST_COVERED_IDENTITY,),
    costs_bps: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Frozen parent/PR1335 grammar on UTC bars; separate occupancy per identity.

    The original files remain unchanged. New control identities explicitly bind
    closes as observable and execute lifecycle exits at the next common open.
    They are independently replayed controls, not old result reproductions.
    """
    if not all(symbol in frames for symbol in PARENT_SYMBOLS):
        return []
    prepared = {symbol: _frame(frames[symbol]) for symbol in PARENT_SYMBOLS}
    times = sorted(set().union(*(set(frame.index) for frame in prepared.values())))
    close = np.column_stack(
        [
            prepared[symbol]["close"].reindex(times).to_numpy(dtype=float)
            for symbol in PARENT_SYMBOLS
        ]
    )
    available = np.column_stack(
        [
            prepared[symbol]["available_ms"].reindex(times).to_numpy(dtype=float)
            for symbol in PARENT_SYMBOLS
        ]
    )
    segments = np.column_stack(
        [
            prepared[symbol]["segment_id"].reindex(times).to_numpy()
            for symbol in PARENT_SYMBOLS
        ]
    )
    result: list[dict[str, Any]] = []
    if COST_COVERED_IDENTITY in identities:
        if costs_bps is None or not all(
            symbol in costs_bps for symbol in PARENT_SYMBOLS
        ):
            raise ValueError("ISSUE1377_FROZEN_COST_AUTHORITY_REQUIRED")
        if not all(
            isfinite(float(costs_bps[symbol])) and float(costs_bps[symbol]) >= 0
            for symbol in PARENT_SYMBOLS
        ):
            raise ValueError("ISSUE1377_INVALID_FROZEN_COST")
    positions: dict[str, dict[str, Any] | None] = {
        identity: None for identity in identities
    }
    segment_start = 0
    previous_segments: tuple[str, ...] | None = None
    previous_ts: int | None = None
    previous_decision_ts = 0
    for i, raw_ts in enumerate(times):
        ts = int(raw_ts)
        decision_ts = ts + TF_MS
        valid = bool(
            np.isfinite(close[i]).all()
            and (close[i] > 0).all()
            and np.isfinite(available[i]).all()
            and not pd.isna(segments[i]).any()
        )
        if valid:
            decision_ts = max(
                decision_ts, int(available[i].max()), previous_decision_ts
            )
            previous_decision_ts = decision_ts
        segment = tuple(str(value) for value in segments[i])
        if not valid or (
            previous_ts is not None
            and (ts != previous_ts + TF_MS or segment != previous_segments)
        ):
            segment_start = i if valid else i + 1
            positions = {identity: None for identity in identities}
        previous_ts, previous_segments = ts, segment
        if not valid or i - segment_start < 20:
            continue
        current = close[i] / close[i - PARENT_LOOKBACK] - 1.0
        previous = close[i - 1] / close[i - PARENT_LOOKBACK - 1] - 1.0
        leader, laggard = int(np.argmax(current)), int(np.argmin(current))
        spread = float(current[leader] - current[laggard])
        previous_spread = float(previous.max() - previous.min())
        entry_valid = (
            spread >= PARENT_STRETCH
            and leader == int(np.argmax(previous))
            and laggard == int(np.argmin(previous))
            and spread < previous_spread
        )
        for identity in identities:
            position = positions[identity]
            if position is not None:
                held = i - int(position["signal_index"])
                pair_spread = float(
                    current[int(position["leader_index"])]
                    - current[int(position["laggard_index"])]
                )
                reexpanded = (
                    identity == REEXPANSION_IDENTITY
                    and held >= PARENT_MIN_FAIL_BARS
                    and pair_spread >= float(position["signal_spread"])
                )
                if held >= MAX_HOLD_BARS or reexpanded:
                    positions[identity] = None
                # A close used to decide an exit cannot also decide a replacement entry.
                continue
            if not entry_valid:
                continue
            leader_symbol, laggard_symbol = (
                PARENT_SYMBOLS[leader],
                PARENT_SYMBOLS[laggard],
            )
            pair_cost_1x_bps: float | None = None
            observed_contraction_bps = (previous_spread - spread) * 10_000.0
            if identity == COST_COVERED_IDENTITY:
                assert costs_bps is not None
                pair_cost_1x_bps = 0.5 * (
                    float(costs_bps[leader_symbol]) + float(costs_bps[laggard_symbol])
                )
                # No fitted multiple: the completed-bar convergence already
                # observed before entry must cover the exact frozen 2x pair
                # round-trip debit.  Entry/exit/occupancy remain the parent.
                if observed_contraction_bps < 2.0 * pair_cost_1x_bps:
                    continue
            result.append(
                {
                    "identity": identity,
                    "lane": "cross_sectional_mean_reversion",
                    "timeframe_min": 30,
                    "symbol": "|".join([laggard_symbol, leader_symbol]),
                    "signal_open_ts_ms": ts,
                    "signal_ts_ms": decision_ts,
                    "segment_id": segment[laggard],
                    "max_hold_bars": MAX_HOLD_BARS,
                    "stop_price": None,
                    "legs": [
                        {"symbol": laggard_symbol, "side": 1, "weight": 0.5},
                        {"symbol": leader_symbol, "side": -1, "weight": 0.5},
                    ],
                    "meta": {
                        "leader": leader_symbol,
                        "laggard": laggard_symbol,
                        "signal_spread6h": spread,
                        "previous_spread6h": previous_spread,
                        "observed_contraction_bps": observed_contraction_bps,
                        "frozen_pair_cost_1x_bps": pair_cost_1x_bps,
                        "cost2_hurdle_bps": (
                            2.0 * pair_cost_1x_bps
                            if pair_cost_1x_bps is not None
                            else None
                        ),
                        "issue1377_gate": (
                            "OBSERVED_FIRST_CONTRACTION_GTE_EXACT_FROZEN_PAIR_COST2"
                            if identity == COST_COVERED_IDENTITY
                            else None
                        ),
                        "parent_source": "a1_cross_sectional_mean_reversion_v1.py",
                        "child_source": (
                            "a1_scalp7_mr_reexpansion_exit_v1.py"
                            if identity == REEXPANSION_IDENTITY
                            else (
                                "issue1377_contraction_cost2_entry_gate_v1"
                                if identity == COST_COVERED_IDENTITY
                                else None
                            )
                        ),
                        "source_identity_note": "PRESERVED_GRAMMAR_UTC_COMPLETED_BARS_NEXT_OPEN_EXIT_CONTROL",
                        "pair_segment_ids": {
                            laggard_symbol: segment[laggard],
                            leader_symbol: segment[leader],
                        },
                    },
                }
            )
            positions[identity] = {
                "signal_index": i,
                "leader_index": leader,
                "laggard_index": laggard,
                "signal_spread": spread,
            }
    return result


def generate_signals(
    frames: dict[str, pd.DataFrame],
    identity: str | None = None,
    costs_bps: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Emit only the opt-in child, with its own cost-gated occupancy scan."""
    if identity not in (None, COST_COVERED_IDENTITY):
        raise ValueError("UNKNOWN_MR_IDENTITY")
    return sorted(
        _control_signals(frames, costs_bps=costs_bps),
        key=lambda row: (
            int(row["signal_ts_ms"]),
            str(row["identity"]),
            str(row["symbol"]),
        ),
    )


def exit_update(
    position: Mapping[str, Any],
    bar: Mapping[str, Mapping[str, Any]],
    history: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    """Keep the parent's exact fixed-hold exit without mutating caller state."""
    signal = position["signal"]
    if signal["identity"] != COST_COVERED_IDENTITY:
        raise ValueError("UNKNOWN_MR_IDENTITY")
    parent_position = {
        **position,
        "signal": {**signal, "identity": parent.PARENT_IDENTITY},
    }
    return parent.exit_update(parent_position, bar, history)
