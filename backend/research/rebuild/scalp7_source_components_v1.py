"""Source-backed research components; immutable incumbents and no orders.

A: Brooks second-signal concept, operationalized as two completed reclaim
attempts within one Carter squeeze episode. B: Carter initial-thrust failure,
operationalized as nonpositive reference-cost-adjusted PnL after four bars.
These are disclosed translations, not exact replicas of a trader's results.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

import pandas as pd

from backend.research.rebuild import scalp7_positive_lanes_v2 as parent

IDENTITIES = {
    "PA": "scalp7_squeeze_brooks_second_signal_30m_v1",
    "PB": "scalp7_squeeze_carter_thrust4_exit_30m_v1",
    "PAB": "scalp7_squeeze_brooks_carter_components_30m_v1",
}
SPEC = {
    "parent": parent.SQUEEZE_PARENT,
    "timeframe_min": 30,
    "A": "retain parent events; add one closed-bar second reclaim per fire",
    "B": "at held bar4 only: reference-cost-adjusted close PnL<=0 exits next open",
    "episode_expiry_bars": 10,
    "pause": "completed low below prior low OR inside bar",
    "reclaim": "completed close above prior high and above own open",
    "sequence": "pause1 -> reclaim1 -> later pause2 -> later reclaim2",
    "invalidation": "completed close below original fire low; gap; new fire",
    "add_stop": "lowest observed pullback low; no unobserved tick or fill",
    "add_confirmation": "current PANIC_DISPERSION and positive momentum",
    "supplement_gap": "entry through structural stop is rejected, not widened",
    "add_cost_guard": "unchanged ATR20/cost>=4 at next-open admission",
    "add_max_hold": "remaining original11bar expansion lifetime, no reset",
    "occupancy": "same frozen per-symbol owner; rejected conflicts reported",
    "partial": None,
    "grid_search": False,
    "selection": False,
    "promotion": False,
    "order": "BLOCKED",
    "live": "BLOCKED",
}
SPEC_SHA256 = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()


@dataclass
class SecondSignal:
    """Only observations after the origin fire may advance the sequence."""

    fire: dict[str, Any]
    floor: float
    stage: int = 0
    pull_low: float = float("inf")
    consumed: bool = False

    def observe(self, row: Mapping[str, Any], prev: Mapping[str, Any]) -> int:
        elapsed = (int(row["close_ts_ms"]) - self.fire["signal_ts_ms"]) // 1_800_000
        if self.consumed or elapsed <= 0:
            return 0
        if (
            elapsed > 10
            or row["segment_id"] != self.fire["segment_id"]
            or row["open_ts_ms"] != prev["close_ts_ms"]
            or float(row["close"]) < self.floor
        ):
            self.consumed = True
            return 0
        pause = row["low"] < prev["low"] or (
            row["high"] <= prev["high"] and row["low"] >= prev["low"]
        )
        reclaim = row["close"] > prev["high"] and row["close"] > row["open"]
        if self.stage == 0:
            if pause:
                self.stage = 1
                self.pull_low = float(row["low"])
            return 0
        self.pull_low = min(self.pull_low, float(row["low"]))
        if self.stage == 1 and reclaim:
            self.stage = 2
        elif self.stage == 2 and pause:
            self.stage = 3
        elif self.stage == 3 and reclaim:
            self.consumed = True
            return int(elapsed)
        return 0


def generate_signals(
    frames: dict[str, pd.DataFrame], costs: Mapping[str, float], variant: str
) -> list[dict[str, Any]]:
    if variant not in IDENTITIES:
        raise ValueError("UNKNOWN_COMPONENT_VARIANT")
    originals = parent.generate_signals(
        frames, costs=costs, identities=(parent.SQUEEZE_PARENT,)
    )
    signals = deepcopy(originals)
    if variant in ("PA", "PAB"):
        origins = {(s["symbol"], s["signal_open_ts_ms"]): s for s in originals}
        for symbol, frame in sorted(frames.items()):
            for enriched in parent.enriched_segments(frame):
                rows = enriched.to_dict("records")
                state: SecondSignal | None = None
                for i, row in enumerate(rows):
                    origin = origins.get((symbol, row["open_ts_ms"]))
                    if origin is not None:
                        state = SecondSignal(deepcopy(origin), float(row["low"]))
                        continue
                    if state is None or not i:
                        continue
                    elapsed = state.observe(row, rows[i - 1])
                    if not elapsed:
                        continue
                    reg, _ = parent._regime(row, None)
                    if reg != "PANIC_DISPERSION" or not row["momentum"] > 0:
                        continue
                    item = deepcopy(state.fire)
                    item.update(
                        signal_open_ts_ms=int(row["open_ts_ms"]),
                        signal_ts_ms=int(row["feature_available_ts_ms"]),
                        stop_price=state.pull_low,
                        max_hold_bars=max(1, 11 - elapsed),
                    )
                    item["meta"].update(
                        component="BROOKS_SECOND_SIGNAL_TRANSLATION",
                        origin_fire_ts_ms=int(state.fire["signal_ts_ms"]),
                        feature_available_ts_ms=item["signal_ts_ms"],
                        atr_price=float(row["atr20"]),
                        entry_cost_gate={
                            "atr_price": float(row["atr20"]),
                            "min_ratio": 4.0,
                        },
                        event_trace=[
                            "SQUEEZE_ORIGIN",
                            "PAUSE1",
                            "RECLAIM1",
                            "PAUSE2",
                            "RECLAIM2",
                            "NEXT_OPEN",
                        ],
                    )
                    signals.append(item)
    for signal in signals:
        signal["identity"] = IDENTITIES[variant]
        signal["meta"].update(
            component_variant=variant, component_spec_sha256=SPEC_SHA256
        )
        signal["meta"].setdefault("component", "UNCHANGED_PARENT_EVENT")
    return sorted(signals, key=lambda s: (s["signal_ts_ms"], s["symbol"]))


def _parent_signal(signal: Mapping[str, Any]) -> dict[str, Any]:
    if signal["identity"] not in IDENTITIES.values():
        raise ValueError("COMPONENT_IDENTITY_MISMATCH")
    return {**signal, "identity": parent.SQUEEZE_PARENT}


def entry_update(signal: Mapping[str, Any], price: float) -> dict[str, Any]:
    copied = _parent_signal(signal)
    if signal["meta"]["component"] != "UNCHANGED_PARENT_EVENT" and price <= float(
        signal["stop_price"]
    ):
        return {"reject": True, "reason": "SECOND_SIGNAL_GAP_INVALIDATION"}
    return parent.entry_update(copied, price)


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    signal = position["signal"]
    copied = {**position, "signal": _parent_signal(signal)}
    update = parent.exit_update(copied, bar, history)
    if (
        signal["meta"]["component_variant"] in ("PB", "PAB")
        and int(position["hold_bars"]) == 4
    ):
        close_net = (
            float(bar["close"]) / float(position["entry_price"]) - 1
        ) * 10_000 - float(position["cost_bps"])
        if close_net <= 0:
            return {"exit_next_open": True, "reason": "CARTER_THRUST4_NET_FAILURE"}
    return update
