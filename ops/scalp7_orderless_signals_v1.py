"""Thin incremental bindings for the four existing 30m development versions.

No market transport, key lookup, order client, economic replay or capital model
is present. The caller persists the supplied JSON state together with its ledger.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from typing import Any, Mapping

import pandas as pd

from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild.scalp7_fresh_forward_v2 import bind_frozen_context
from ops.scalp7_dual_native_funnel_v1 import _keltner_parent_signal
from ops.scalp7_squeeze_regime_overlay_child_v1 import (
    _source_condition, _squeeze_parent_signal,
)
from ops.scalp7_squeeze_signal_low_successor_v1 import (
    bind_signal_low, native_exit_update,
)
from research.campaigns.scalp7_20261013.dual_streak_v1.streak_successor_policies import (
    KELTNER_SUCCESSOR, SQUEEZE_SUCCESSOR, RejectedHGEventReset,
)

VERSIONS = (positive.KELTNER_PARENT, KELTNER_SUCCESSOR,
            positive.SQUEEZE_PARENT, SQUEEZE_SUCCESSOR)
PARENTS = {VERSIONS[0]: VERSIONS[0], VERSIONS[1]: VERSIONS[0],
           VERSIONS[2]: VERSIONS[2], VERSIONS[3]: VERSIONS[2]}
SOURCE_COLUMNS = ("open_ts_ms", "close_ts_ms", "available_ts_ms", "segment_id",
                  "open", "high", "low", "close")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def verify_fit(fit: Mapping[str, Any], decision_ms: int) -> None:
    """Verify the stored fit body and its causal clock; never refit here."""
    body = dict(fit)
    claimed = body.pop("sha256", None)
    if claimed != _digest(body):
        raise ValueError("CONTEXT_FIT_HASH_MISMATCH")
    start, end = int(fit["train_start_ms"]), int(fit["train_end_ms"])
    if (end - start != 90 * context.DAY or start % context.DAY
            or end % context.DAY or end > decision_ms
            or not start <= int(fit["last_fit_observation_ms"]) < end
            or int(fit["last_fit_observation_ms"]) >= decision_ms
            or int(fit["train_rows"]) < 72
            or len(str(fit["training_feature_sha256"])) != 64):
        raise ValueError("CONTEXT_FIT_NOT_CAUSAL")
    if any(not math.isfinite(float(fit[k])) for k in
           ("disp_q67", "meanabs_q85", "vol_q25", "vol_q67")):
        raise ValueError("CONTEXT_FIT_NONFINITE")


def bind_causal_context(frames: dict[str, pd.DataFrame],
                        fit: Mapping[str, Any]) -> dict[str, pd.DataFrame]:
    """Reuse the existing frozen-context binder, with an explicit fit check."""
    if set(frames) != context.SYMBOLS or any(x.empty for x in frames.values()):
        raise ValueError("EXACT_SIX_SYMBOL_CONTEXT_REQUIRED")
    decision = min(int(x.iloc[-1].close_ts_ms) for x in frames.values())
    verify_fit(fit, decision)
    return bind_frozen_context({30: frames}, dict(fit))[30]


def _state_key(version: str, symbol: str) -> str:
    if version not in VERSIONS or symbol not in context.SYMBOLS:
        raise ValueError("FROZEN_VERSION_AND_SYMBOL_REQUIRED")
    return version + "|" + symbol


def _hg_dump(value: positive.HolyGrailState) -> dict[str, Any]:
    out = asdict(value)
    for key in ("pull_low", "pull_high"):
        if not math.isfinite(out[key]):
            out[key] = None
    return out


def _hg_load(value: Mapping[str, Any]) -> positive.HolyGrailState:
    out = dict(value)
    if out.get("pull_low") is None:
        out["pull_low"] = math.inf
    if out.get("pull_high") is None:
        out["pull_high"] = -math.inf
    return positive.HolyGrailState(**out)


def _prefix_hash(frame: pd.DataFrame) -> str:
    return _digest(json.loads(frame[list(SOURCE_COLUMNS)].to_json(orient="records")))


def on_bar(state: dict[str, Any], *, version: str, symbol: str,
           frame: pd.DataFrame, cost_bps: float, asof_ms: int,
           fit: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Consume only the latest closed bar, preserving each HG version's state.

    The first call reconstructs the parent HG's indicator-context state once,
    without emitting historical signals or fills. Fresh-touch cannot infer old
    admission decisions: it remains UNKNOWN until a native weak/side reset is
    actually observed. Subsequent calls must supply an unmodified growing prefix.
    A pending fresh-touch signal requires decide_entry() before another bar.
    """
    key = _state_key(version, symbol)
    result: dict[str, Any] = {"version": version, "symbol": symbol,
        "status": "UNKNOWN", "reason": None, "signal": None, "hg_calls": 0,
        "historical_context_hg_calls": 0, "order_calls": 0}
    try:
        checked = positive._validated(frame)
        if checked.empty:
            raise ValueError("CLOSED_BAR_HISTORY_MISSING")
        row0 = checked.iloc[-1]
        opened = int(row0.open_ts_ms)
        if (checked.available_ts_ms > asof_ms).any() or int(row0.close_ts_ms) > asof_ms:
            raise ValueError("UNAVAILABLE_OR_INCOMPLETE_BAR")
        saved = state.get(key)
        if saved is not None:
            if saved.get("halted"):
                raise ValueError(str(saved["halted"]))
            previous_open = int(saved["last_open_ts_ms"])
            historical = checked.loc[checked.open_ts_ms <= previous_open]
            if historical.empty or _prefix_hash(historical) != saved["prefix_sha256"]:
                saved["halted"] = "HISTORY_CHANGED_OR_TRUNCATED"
                raise ValueError(saved["halted"])
            if opened == previous_open:
                result.update(status="DUPLICATE", reason="ALREADY_CONSUMED")
                return result
            if opened != previous_open + positive.TIMEFRAME_MS:
                saved["halted"] = "MISSING_OR_REORDERED_BAR"
                raise ValueError(saved["halted"])
            if str(row0.segment_id) != saved["segment_id"]:
                saved["halted"] = "SEGMENT_CHANGED"
                raise ValueError(saved["halted"])
            if saved.get("pending_ts_ms") is not None:
                raise ValueError("UNRESOLVED_PRIOR_ENTRY_DECISION")
        segments = positive.enriched_segments(checked)
        enriched = segments[-1]
        rows = enriched.to_dict("records")
        i = len(rows) - 1
        row = rows[-1]
        previous = rows[-2] if i >= 1 else row
        # Missing cross-symbol context/fit/cost is recoverable on this candle.
        # Validate it before calling HG or advancing the durable bar cursor.
        result.update(source_open_ts_ms=opened, source_close_ts_ms=int(row["close_ts_ms"]),
                      available_ts_ms=int(row["available_ts_ms"]))
        if fit is None:
            raise ValueError("CONTEXT_FIT_MISSING")
        verify_fit(fit, int(row["close_ts_ms"]))
        regime, available = positive._regime(row, None)
        if regime in {"UNBOUND", "NO_CONTEXT"} or row.get("regime_spec_sha256") != fit["sha256"]:
            raise ValueError("CAUSAL_CONTEXT_UNBOUND")
        if not math.isfinite(float(cost_bps)) or float(cost_bps) <= 0:
            raise ValueError("FROZEN_COST_UNBOUND")
        hg = _hg_load(saved["hg"]) if saved is not None else positive.HolyGrailState()
        fresh_unknown = bool(saved.get("bootstrap_admission_unknown", False)) if saved else False
        is_hg = PARENTS[version] == positive.KELTNER_PARENT
        if saved is None and is_hg:
            for j in range(121, i):
                positive._hg_event(hg, rows[j], rows[j - 1])
                result["historical_context_hg_calls"] += 1
            # Accepted/rejected historical opportunities cannot be invented for
            # the fresh-touch child. Wait for a new observed native reset.
            fresh_unknown = version == KELTNER_SUCCESSOR and hg.side != 0
        before_side = hg.side
        event = None
        if is_hg and i >= 121:
            event = positive._hg_event(hg, row, previous)
            result["hg_calls"] = 1
            if fresh_unknown and (hg.side == 0 or hg.side != before_side):
                fresh_unknown = False
        if version == KELTNER_SUCCESSOR and event is not None:
            hg.episode_traded = False  # existing accepted-entry successor contract
        current = {"last_open_ts_ms": opened, "segment_id": str(row["segment_id"]),
            "prefix_sha256": _prefix_hash(checked), "hg": _hg_dump(hg),
            "pending_ts_ms": None, "bootstrap_admission_unknown": fresh_unknown,
            "native_calls": int(saved.get("native_calls", 0) if saved else 0) + result["hg_calls"]}
        # These two UNKNOWNs require a later bar, not repaired inputs. Preserve
        # their validated progress, including the observed native reset state.
        if is_hg and i < 121 or not is_hg and i < 80:
            state[key] = current
            raise ValueError("INDICATOR_WARMUP_INCOMPLETE")
        if fresh_unknown:
            state[key] = current
            raise ValueError("HISTORICAL_HG_ADMISSION_UNKNOWN_WAIT_NATIVE_RESET")
        signal = None
        if is_hg and event is not None and regime in {"PANIC_DISPERSION", "TREND_DISPERSED"}:
            signal = _keltner_parent_signal(symbol, row, event[0], event[1],
                                             regime, available, float(cost_bps))
            if version == KELTNER_SUCCESSOR:
                policy = RejectedHGEventReset()
                policy.generated(int(signal["signal_ts_ms"]))
                current["pending_ts_ms"] = policy.pending_ts_ms
        elif not is_hg:
            first_fire = bool(previous["squeeze_on"]) and not bool(row["squeeze_on"])
            allowed = {"PANIC_DISPERSION"} if version == positive.SQUEEZE_PARENT else {"PANIC_DISPERSION", "TREND_DISPERSED"}
            if first_fire and _source_condition(row, previous) and regime in allowed:
                signal = _squeeze_parent_signal(symbol, row, regime, available, float(cost_bps))
                if regime == "PANIC_DISPERSION":
                    signal["meta"]["event_trace"][-1] = "PANIC_LONG"
                if version == SQUEEZE_SUCCESSOR:
                    signal = bind_signal_low(signal, checked)
        if signal is not None:
            signal["meta"]["lifecycle_adapter_parent_identity"] = PARENTS[version]
            signal["identity"] = version
            result.update(status="SIGNAL", reason="FROZEN_NATIVE_SIGNAL", signal=signal)
        else:
            result.update(status="NO_SIGNAL", reason="FROZEN_NATIVE_CONDITIONS_NOT_MET")
        state[key] = current
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        result.update(status="UNKNOWN", reason=str(exc), signal=None)
    return result


def decide_entry(state: dict[str, Any], *, version: str, symbol: str,
                 accepted: bool, decision_ts_ms: int) -> None:
    """Apply only an evidenced observed-paper admission outcome, never timeout."""
    key = _state_key(version, symbol)
    if version != KELTNER_SUCCESSOR:
        return
    current = state[key]
    hg = _hg_load(current["hg"])
    policy = RejectedHGEventReset(pending_ts_ms=current["pending_ts_ms"])
    policy.decided(hg, accepted=accepted, decision_ts_ms=decision_ts_ms)
    current.update(hg=_hg_dump(hg), pending_ts_ms=policy.pending_ts_ms)


class NativeCallbacks:
    """ObservedPaper facade preserving the original callbacks' parent identity."""
    def __init__(self, version: str):
        if version not in VERSIONS:
            raise ValueError("FROZEN_VERSION_REQUIRED")
        self.version = version

    def _signal(self, signal: Mapping[str, Any]) -> dict[str, Any]:
        if signal.get("identity") != self.version:
            raise ValueError("CALLBACK_VERSION_MISMATCH")
        out = deepcopy(dict(signal))
        out["identity"] = PARENTS[self.version]
        return out

    def entry_update(self, signal: Mapping[str, Any], price: float) -> dict[str, Any]:
        return positive.entry_update(self._signal(signal), price)

    def exit_update(self, position: dict[str, Any], bar: dict[str, Any],
                    history: pd.DataFrame) -> dict[str, Any]:
        local = deepcopy(position)
        local["signal"] = self._signal(position["signal"])
        if self.version == SQUEEZE_SUCCESSOR:
            return native_exit_update(local, bar, history)
        return positive.exit_update(local, bar, history)


def callback_modules() -> dict[str, NativeCallbacks]:
    return {version: NativeCallbacks(version) for version in VERSIONS}


def callbacks(version: str) -> NativeCallbacks:
    return NativeCallbacks(version)
