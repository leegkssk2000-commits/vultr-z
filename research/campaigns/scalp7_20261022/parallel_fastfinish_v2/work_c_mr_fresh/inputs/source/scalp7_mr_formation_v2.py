"""Preregistered causal MR formation; emits intents, never executes orders or replays.

The fixed BTC/ETH pair is intentionally a separate architecture identity from
cross-sectional MR V1 and its frozen bar-four re-expansion child. Formation is
fitted on completed prior UTC-week prices only. Economic execution belongs to
the campaign owner; this module does not infer a missing fill or cost source.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from math import isfinite, log
from typing import Any, Mapping

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

IDENTITY = "mr_btceth_weekly_formation_30m_v2"
PAIR = ("BTC-USDT", "ETH-USDT")
TF_MS = 1_800_000
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
MONDAY_ZERO_MS = 4 * DAY_MS  # 1970-01-05 00:00 UTC
FORMATION_BARS = 336
ENTRY_Z = 2.0
MAX_HOLD_BARS = 8


def week_start(ts_ms: int) -> int:
    return ((ts_ms - MONDAY_ZERO_MS) // WEEK_MS) * WEEK_MS + MONDAY_ZERO_MS


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class FrozenFormation:
    trading_start_ms: int
    trading_end_ms: int
    formation_start_ms: int
    formation_end_ms: int
    fitted_available_ts_ms: int
    beta: float
    intercept: float
    residual_mean: float
    residual_sd: float
    residual_phi: float
    training_sha256: str
    btc_segment_id: str
    eth_segment_id: str

    @property
    def sha256(self) -> str:
        return _digest(asdict(self))

    @property
    def weights(self) -> dict[str, float]:
        return {
            PAIR[0]: 1.0 / (1.0 + self.beta),
            PAIR[1]: self.beta / (1.0 + self.beta),
        }

    def zscore(self, btc_price: float, eth_price: float) -> float:
        if not all(isfinite(p) and p > 0 for p in (btc_price, eth_price)):
            raise ValueError("INVALID_PAIR_PRICE")
        return (
            log(btc_price)
            - self.intercept
            - self.beta * log(eth_price)
            - self.residual_mean
        ) / self.residual_sd


def _bar_open_ts(bar: Mapping[str, Any]) -> int:
    key = "open_ts_ms" if "open_ts_ms" in bar else "ts_ms"
    return int(bar[key])


def _frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "open_ts_ms" in out.columns:
        if "ts_ms" in out.columns and not out["ts_ms"].equals(out["open_ts_ms"]):
            raise ValueError("BAR_OPEN_ALIAS_MISMATCH")
        out["ts_ms"] = out["open_ts_ms"]
    required = {"ts_ms", "close", "segment_id"}
    if not required.issubset(out.columns):
        raise ValueError("MISSING_CAUSAL_BAR_COLUMNS")
    if out["ts_ms"].duplicated().any() or not out["ts_ms"].is_monotonic_increasing:
        raise ValueError("DUPLICATE_OR_UNSORTED_BAR")
    if ((out["ts_ms"] % TF_MS) != 0).any():
        raise ValueError("NON_UTC_30M_BAR")
    if (
        "close_ts_ms" in out.columns
        and (out["close_ts_ms"] != out["ts_ms"] + TF_MS).any()
    ):
        raise ValueError("BAR_CLOSE_NOT_EXCLUSIVE_30M")
    present = [
        key
        for key in ("available_ts_ms", "available_at_ms", "available_at_ts_ms")
        if key in out.columns
    ]
    if not present:
        raise ValueError("BAR_AVAILABILITY_UNBOUND")
    out["available_ms"] = out[present[0]]
    for key in present[1:]:
        if not out[key].equals(out["available_ms"]):
            raise ValueError("BAR_AVAILABILITY_ALIAS_MISMATCH")
    if (out["available_ms"] < out["ts_ms"] + TF_MS).any():
        raise ValueError("BAR_AVAILABLE_BEFORE_CLOSE")
    return out.set_index("ts_ms", drop=False)


def _fit_prepared(
    frames: Mapping[str, pd.DataFrame],
    trading_start_ms: int,
    as_of_ts_ms: int | None = None,
) -> FrozenFormation | None:
    if trading_start_ms != week_start(trading_start_ms):
        raise ValueError("TRADING_WINDOW_NOT_UTC_MONDAY")
    observed_asof = trading_start_ms if as_of_ts_ms is None else as_of_ts_ms
    if observed_asof < trading_start_ms:
        return None
    start = trading_start_ms - WEEK_MS
    wanted = np.arange(start, trading_start_ms, TF_MS, dtype=np.int64)
    selected: dict[str, pd.DataFrame] = {}
    for symbol in PAIR:
        frame = frames[symbol]
        window = frame.loc[(frame.index >= start) & (frame.index < trading_start_ms)]
        if len(window) != FORMATION_BARS or not np.array_equal(
            window.index.to_numpy(), wanted
        ):
            return None
        if window["segment_id"].isna().any() or window["segment_id"].nunique() != 1:
            return None
        if (window["available_ms"] > observed_asof).any() or window[
            "available_ms"
        ].isna().any():
            return None
        prices = window["close"].to_numpy(dtype=float)
        if not np.isfinite(prices).all() or not (prices > 0).all():
            return None
        selected[symbol] = window
    y = np.log(selected[PAIR[0]]["close"].to_numpy(dtype=float))
    x = np.log(selected[PAIR[1]]["close"].to_numpy(dtype=float))
    xc, yc = x - x.mean(), y - y.mean()
    denominator = float(xc @ xc)
    if denominator <= 0:
        return None
    beta = float((xc @ yc) / denominator)
    if not isfinite(beta) or beta <= 0:
        return None
    intercept = float(y.mean() - beta * x.mean())
    residual = y - intercept - beta * x
    center = float(residual.mean())
    sd = float(residual.std(ddof=1))
    if not isfinite(sd) or sd <= np.finfo(float).eps:
        return None
    previous = residual[:-1] - residual[:-1].mean()
    following = residual[1:] - residual[1:].mean()
    denom_phi = float(previous @ previous)
    if denom_phi <= 0:
        return None
    phi = float((previous @ following) / denom_phi)
    if not 0 < phi < 1:
        return None
    train = {
        symbol: [
            [
                int(row.ts_ms),
                float(row.close),
                int(row.available_ms),
                str(row.segment_id),
            ]
            for row in selected[symbol].itertuples()
        ]
        for symbol in PAIR
    }
    return FrozenFormation(
        trading_start_ms=trading_start_ms,
        trading_end_ms=trading_start_ms + WEEK_MS,
        formation_start_ms=start,
        formation_end_ms=trading_start_ms,
        fitted_available_ts_ms=max(
            trading_start_ms,
            *(int(selected[symbol]["available_ms"].max()) for symbol in PAIR),
        ),
        beta=beta,
        intercept=intercept,
        residual_mean=center,
        residual_sd=sd,
        residual_phi=phi,
        training_sha256=_digest(train),
        btc_segment_id=str(selected[PAIR[0]]["segment_id"].iloc[-1]),
        eth_segment_id=str(selected[PAIR[1]]["segment_id"].iloc[-1]),
    )


def fit_formation(
    frames: Mapping[str, pd.DataFrame],
    trading_start_ms: int,
    as_of_ts_ms: int | None = None,
) -> FrozenFormation | None:
    """Return an immutable prior-week fit, or None for any unfit/gapped window."""
    if not all(symbol in frames for symbol in PAIR):
        return None
    return _fit_prepared(
        {symbol: _frame(frames[symbol]) for symbol in PAIR},
        trading_start_ms,
        as_of_ts_ms,
    )


def entry_side(previous_z: float, current_z: float) -> int:
    """BTC direction; signal only on an outside-band same-sign contraction."""
    if not all(isfinite(z) for z in (previous_z, current_z)):
        return 0
    if (
        previous_z * current_z <= 0
        or abs(current_z) < ENTRY_Z
        or abs(current_z) >= abs(previous_z)
    ):
        return 0
    return -1 if current_z > 0 else 1


def exit_reason(
    signal_z: float,
    current_z: float,
    held_bars: int,
    decision_ts_ms: int,
    formation: FrozenFormation,
) -> str | None:
    if held_bars < 1:
        return None
    if decision_ts_ms >= formation.trading_end_ms:
        return "FORMATION_WINDOW_END"
    if signal_z * current_z <= 0:
        return "FROZEN_MEAN_REACHED"
    if abs(current_z) >= abs(signal_z):
        return "FROZEN_SPREAD_REEXPANSION"
    if held_bars >= MAX_HOLD_BARS:
        return "TIME_8BAR"
    return None


def generate_pair_events(frames: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Emit chronological paired ENTER/EXIT/UNRESOLVED intents without fills.

    Entry and exit prices are deliberately absent: the central engine must bind
    both legs to the exact next open and preserve missing executions as HOLD.
    Future rows cannot change already emitted events. All input frames must use
    UTC bar-open timestamps and segment IDs supplied by the source validator.
    """
    if not all(symbol in frames for symbol in PAIR):
        return []
    prepared = {symbol: _frame(frames[symbol]) for symbol in PAIR}
    left = prepared[PAIR[0]][["ts_ms", "close", "segment_id", "available_ms"]].rename(
        columns={
            "close": "btc",
            "segment_id": "btc_segment",
            "available_ms": "btc_available",
        }
    )
    right = prepared[PAIR[1]][["close", "segment_id", "available_ms"]].rename(
        columns={
            "close": "eth",
            "segment_id": "eth_segment",
            "available_ms": "eth_available",
        }
    )
    aligned = left.join(right, how="outer").sort_index()
    events: list[dict[str, Any]] = []
    formation: FrozenFormation | None = None
    active_week: int | None = None
    invalid_week: int | None = None
    previous_z: float | None = None
    previous_ts: int | None = None
    previous_decision_ts = 0
    previous_segments: tuple[str, str] | None = None
    position: dict[str, Any] | None = None
    excursion_consumed = False
    for row in aligned.itertuples():
        ts = int(row.Index)
        decision_ts = ts + TF_MS
        current_week = week_start(ts)
        valid = all(
            isfinite(float(v))
            for v in (row.btc, row.eth, row.btc_available, row.eth_available)
        )
        valid = valid and row.btc > 0 and row.eth > 0
        if valid:
            decision_ts = max(
                decision_ts,
                int(row.btc_available),
                int(row.eth_available),
                previous_decision_ts,
            )
            previous_decision_ts = decision_ts
        segments = (str(row.btc_segment), str(row.eth_segment))
        contiguous = previous_ts is None or (
            ts == previous_ts + TF_MS and segments == previous_segments
        )
        if not valid or not contiguous:
            if position is not None:
                events.append(
                    {
                        "action": "UNRESOLVED_GAP",
                        "position_id": position["position_id"],
                        "decision_ts_ms": decision_ts,
                        "reason": "NO_SYNTHETIC_PAIR_FILL",
                    }
                )
                position = None
            invalid_week = current_week
            previous_z = None
            excursion_consumed = False
        if current_week != active_week:
            formation = _fit_prepared(prepared, current_week, decision_ts)
            active_week = current_week
            previous_z = None
            excursion_consumed = False
        if formation is None or invalid_week == current_week or not valid:
            previous_ts, previous_segments = ts, segments
            continue
        if segments != (formation.btc_segment_id, formation.eth_segment_id):
            invalid_week = current_week
            previous_ts, previous_segments = ts, segments
            continue
        z = formation.zscore(float(row.btc), float(row.eth))
        if previous_z is not None and z * previous_z <= 0:
            excursion_consumed = False
        exited = False
        if position is not None:
            held_bars = int((ts - int(position["signal_open_ts_ms"])) // TF_MS)
            reason = exit_reason(
                float(position["signal_z"]), z, held_bars, decision_ts, formation
            )
            if reason:
                events.append(
                    {
                        "action": "EXIT",
                        "position_id": position["position_id"],
                        "decision_ts_ms": decision_ts,
                        "execute_ts_ms": decision_ts,
                        "reason": reason,
                        "formation_sha256": formation.sha256,
                        "held_bars": held_bars,
                        "exit_z": z,
                    }
                )
                position = None
                exited = True
        if (
            position is None
            and not exited
            and not excursion_consumed
            and previous_z is not None
            and decision_ts < formation.trading_end_ms
        ):
            side = entry_side(previous_z, z)
            if side:
                position_id = _digest(
                    {
                        "identity": IDENTITY,
                        "decision_ts_ms": decision_ts,
                        "formation_sha256": formation.sha256,
                    }
                )
                position = {
                    "action": "ENTER",
                    "identity": IDENTITY,
                    "lane": "cross_sectional_mean_reversion",
                    "decision_timeframe_ms": TF_MS,
                    "position_id": position_id,
                    "signal_open_ts_ms": ts,
                    "signal_ts_ms": decision_ts,
                    "decision_ts_ms": decision_ts,
                    "execute_ts_ms": decision_ts,
                    "sides": {PAIR[0]: side, PAIR[1]: -side},
                    "weights": formation.weights,
                    "signal_z": z,
                    "previous_z": previous_z,
                    "formation_sha256": formation.sha256,
                    "formation": asdict(formation),
                }
                events.append(dict(position))
                excursion_consumed = True
        previous_z = z
        previous_ts, previous_segments = ts, segments
    return events


def pair_economics(
    entry_prices: Mapping[str, float],
    exit_prices: Mapping[str, float],
    sides: Mapping[str, int],
    weights: Mapping[str, float],
    round_trip_cost_bps: Mapping[str, float],
) -> dict[str, float]:
    """Both-leg arithmetic only; caller must independently bind source authority."""
    if set(weights) != set(PAIR) or abs(sum(weights.values()) - 1.0) > 1e-12:
        raise ValueError("GROSS_EXPOSURE_NOT_ONE")
    if set(sides) != set(PAIR) or set(sides.values()) != {-1, 1}:
        raise ValueError("PAIR_SIDES_INVALID")
    gross = cost = 0.0
    for symbol in PAIR:
        values = (
            float(entry_prices[symbol]),
            float(exit_prices[symbol]),
            float(weights[symbol]),
            float(round_trip_cost_bps[symbol]),
        )
        if (
            not all(isfinite(v) for v in values)
            or min(values[:3]) <= 0
            or values[3] < 0
        ):
            raise ValueError("PAIR_PRICE_WEIGHT_OR_COST_INVALID")
        entry, exit_px, weight, leg_cost = values
        gross += weight * sides[symbol] * (exit_px / entry - 1.0) * 10_000.0
        cost += weight * leg_cost
    return {
        "gross_bps": gross,
        "cost_bps": cost,
        "net_bps": gross - cost,
        "stress2x_net_bps": gross - 2.0 * cost,
    }


def _formation_signals(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Adapter for the centrally owned paired execution engine."""
    signals: list[dict[str, Any]] = []
    for event in generate_pair_events(frames):
        if event["action"] != "ENTER":
            continue
        formation = event["formation"]
        signals.append(
            {
                "identity": IDENTITY,
                "lane": "cross_sectional_mean_reversion",
                "timeframe_min": 30,
                "symbol": "|".join(PAIR),
                "signal_open_ts_ms": event["signal_open_ts_ms"],
                "signal_ts_ms": event["signal_ts_ms"],
                "segment_id": formation["btc_segment_id"],
                "max_hold_bars": MAX_HOLD_BARS,
                "stop_price": None,
                "legs": [
                    {
                        "symbol": symbol,
                        "side": event["sides"][symbol],
                        "weight": event["weights"][symbol],
                    }
                    for symbol in PAIR
                ],
                "meta": {
                    "formation": formation,
                    "fit_hash": event["formation_sha256"],
                    "signal_z": event["signal_z"],
                    "previous_z": event["previous_z"],
                    "position_id": event["position_id"],
                    "pair_segment_ids": {
                        PAIR[0]: formation["btc_segment_id"],
                        PAIR[1]: formation["eth_segment_id"],
                    },
                },
            }
        )
    return signals


def _formation_exit_update(
    position: Mapping[str, Any],
    bar: Mapping[str, Mapping[str, Any]],
    history: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    """Evaluate the frozen residual at a completed close; fill belongs next open."""
    del history  # No refitting from any in-trade or future candles.
    signal = position["signal"]
    meta = signal["meta"]
    formation = FrozenFormation(**meta["formation"])
    ts = {_bar_open_ts(bar[symbol]) for symbol in PAIR}
    if len(ts) != 1:
        raise ValueError("PAIR_CLOSE_TIMESTAMPS_DIFFER")
    decision_ts = max(_bar_open_ts(bar[symbol]) + TF_MS for symbol in PAIR)
    for symbol in PAIR:
        for column in ("available_ts_ms", "available_at_ms", "available_at_ts_ms"):
            if column in bar[symbol]:
                decision_ts = max(decision_ts, int(bar[symbol][column]))
    z = formation.zscore(float(bar[PAIR[0]]["close"]), float(bar[PAIR[1]]["close"]))
    reason = exit_reason(
        float(meta["signal_z"]), z, int(position["hold_bars"]), decision_ts, formation
    )
    return {"exit_next_open": bool(reason), "reason": reason, "zscore": z}


PARENT_IDENTITY = "mr_cross_sectional_v1_30m_causal_control_v2"
REEXPANSION_IDENTITY = "mr_reexpansion_bar4_30m_causal_control_v2"
IDENTITIES = (PARENT_IDENTITY, REEXPANSION_IDENTITY, IDENTITY)
PARENT_SYMBOLS = (
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "XRP-USDT",
    "LINK-USDT",
    "DOGE-USDT",
)
PARENT_LOOKBACK = 12
PARENT_STRETCH = 0.03
PARENT_MIN_FAIL_BARS = 4


def _control_signals(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
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
    positions: dict[str, dict[str, Any] | None] = {
        PARENT_IDENTITY: None,
        REEXPANSION_IDENTITY: None,
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
            positions = {PARENT_IDENTITY: None, REEXPANSION_IDENTITY: None}
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
        for identity in (PARENT_IDENTITY, REEXPANSION_IDENTITY):
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
                        "parent_source": "a1_cross_sectional_mean_reversion_v1.py",
                        "child_source": (
                            "a1_scalp7_mr_reexpansion_exit_v1.py"
                            if identity == REEXPANSION_IDENTITY
                            else None
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
    frames: dict[str, pd.DataFrame], identity: str | None = None
) -> list[dict[str, Any]]:
    """All three independent MR identities, or one explicit frozen identity."""
    if identity is not None and identity not in IDENTITIES:
        raise ValueError("UNKNOWN_MR_IDENTITY")
    signals = []
    if identity is None or identity == IDENTITY:
        signals.extend(_formation_signals(frames))
    if identity is None or identity in (PARENT_IDENTITY, REEXPANSION_IDENTITY):
        signals.extend(_control_signals(frames))
    return sorted(
        (row for row in signals if identity is None or row["identity"] == identity),
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
    """Dispatch exact frozen formation or legacy-grammar control lifecycle."""
    signal = position["signal"]
    identity = str(signal["identity"])
    if identity == IDENTITY:
        return _formation_exit_update(position, bar, history)
    if identity not in (PARENT_IDENTITY, REEXPANSION_IDENTITY):
        raise ValueError("UNKNOWN_MR_IDENTITY")
    held = int(position["hold_bars"])
    reason: str | None = "TIME_8BAR" if held >= MAX_HOLD_BARS else None
    current_spread: float | None = None
    if identity == REEXPANSION_IDENTITY and held >= PARENT_MIN_FAIL_BARS:
        meta = signal["meta"]
        symbols = (str(meta["leader"]), str(meta["laggard"]))
        current_ts = {_bar_open_ts(bar[symbol]) for symbol in symbols}
        if len(current_ts) != 1:
            raise ValueError("PAIR_CLOSE_TIMESTAMPS_DIFFER")
        ts = current_ts.pop()
        decision_ts = max(
            ts + TF_MS,
            *(
                int(
                    bar[symbol].get(
                        "available_ts_ms",
                        bar[symbol].get(
                            "available_at_ms",
                            bar[symbol].get("available_at_ts_ms", ts + TF_MS),
                        ),
                    )
                )
                for symbol in symbols
            ),
        )
        returns: dict[str, float] = {}
        for symbol in symbols:
            frame = _frame(history[symbol])
            earlier = ts - PARENT_LOOKBACK * TF_MS
            wanted = np.arange(earlier, ts + TF_MS, TF_MS)
            window = frame.loc[(frame.index >= earlier) & (frame.index <= ts)]
            if (
                not np.array_equal(window.index.to_numpy(), wanted)
                or window["segment_id"].nunique() != 1
            ):
                raise ValueError("PAIR_REEXPANSION_HISTORY_UNBOUND")
            if (window["available_ms"] > decision_ts).any():
                raise ValueError("PAIR_CLOSE_NOT_YET_AVAILABLE")
            returns[symbol] = (
                float(bar[symbol]["close"]) / float(window.iloc[0]["close"]) - 1.0
            )
        current_spread = returns[symbols[0]] - returns[symbols[1]]
        if current_spread >= float(meta["signal_spread6h"]):
            reason = "THESIS_REEXPAND_FAIL_BAR4"
    return {
        "exit_next_open": bool(reason),
        "reason": reason,
        "current_spread6h": current_spread,
    }
