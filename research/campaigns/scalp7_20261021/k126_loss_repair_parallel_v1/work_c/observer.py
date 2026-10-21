"""Read-only origin trace for the fixed HG call and fresh-touch admission path.

This is an observer, never a signal/exit policy. ``observe`` consumes COPIES
after the one native call. The incumbent successor then fills ``admission`` on
the returned record. ``finalize_observations`` separates those two phases.
No source replay, market I/O, outcome scoring, or policy patch runs on import.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import scalp7_positive_lanes_v2 as native

IDENTITY = "k126_native_state_origin_observer_c_v1"
NATIVE_SHA256 = "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2"
OBSERVER_HOOK_SHA256 = "683a08d37ad0eab674ba194ebe0c4ff9400c3c586e3728b8dce67fe9747db6a0"
TF_MS = 1_800_000


def verify_native() -> None:
    if hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest() != NATIVE_SHA256:
        raise ValueError("ORIGIN_NATIVE_SOURCE_CHANGED")


def _stamp(value: Any) -> int:
    number = float(value)
    if isinstance(value, bool) or not math.isfinite(number) or int(number) != number or number < 0:
        raise ValueError("ORIGIN_INTEGER_CLOCK_REQUIRED")
    return int(number)


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return deepcopy(value)


def _clock(row: Mapping[str, Any]) -> dict[str, int]:
    opening = _stamp(row["open_ts_ms"])
    closing = _stamp(row["close_ts_ms"])
    raw_available = _stamp(row["available_ts_ms"])
    feature_available = _stamp(row["feature_available_ts_ms"])
    if opening % TF_MS or closing != opening + TF_MS or raw_available < closing or feature_available < raw_available:
        raise ValueError("ORIGIN_COMPLETE_CAUSAL_30M_REQUIRED")
    return {"open_ts_ms": opening, "close_ts_ms": closing,
            "raw_available_ts_ms": raw_available,
            "available_ts_ms": feature_available}


def _origin(row: Mapping[str, Any], value: float | None = None) -> dict[str, Any]:
    return {**_clock(row), "segment_id": str(row["segment_id"]), "price": value,
            "meaning": "NATIVE_STATE_ASSIGNMENT_NOT_RAW_PRICE_MATCH"}


def _flags(row: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, Any]:
    """Label the frozen predicate; this result is NEVER used to change native state."""
    values = [float(row[f"g{n}"]) for n in native.LONG_GMMA]
    required = values + [float(row[k]) for k in ("adx14", "g20", "high", "low", "close")]
    required += [float(previous[k]) for k in ("g20", "g60", "high", "low")]
    if not all(math.isfinite(x) for x in required):
        raise ValueError("ORIGIN_FINITE_FEATURES_REQUIRED")
    long = all(a > b for a, b in zip(values, values[1:])) and row["g60"] > previous["g60"]
    short = all(a < b for a, b in zip(values, values[1:])) and row["g60"] < previous["g60"]
    side = 1 if long else -1 if short else 0
    strong = bool(side and row["adx14"] >= 30 and side * (row["g20"] - previous["g20"]) > 0)
    return {"side": side, "strong": strong, "adx14": float(row["adx14"]),
            "ema20_slope": float(row["g20"] - previous["g20"]),
            "native_weak_reset_predicate": bool(not strong and (row["adx14"] < 25 or side == 0))}


class OriginObserver:
    """Drop-in HGObserver; one instance per symbol/contiguous native segment.

    A mid-episode start stays unknown until an observed assignment. Equal lows
    and highs are price matches, not new origins: native min/max retain the
    existing value. Weak bars do not accumulate extrema in the native function.
    """
    def __init__(self, symbol: str):
        verify_native()
        self.symbol = str(symbol)
        self.origins: dict[str, Any] = {"touch": None, "pull_low": None, "pull_high": None}
        self.last_open: int | None = None
        self.segment: str | None = None
        self.ordinal = 0
        self.weak_retained = 0
        self.last_native_after: dict[str, Any] | None = None

    def _clear(self) -> None:
        self.origins = {"touch": None, "pull_low": None, "pull_high": None}
        self.weak_retained = 0

    def observe(self, before: Mapping[str, Any], after: Mapping[str, Any],
                row: Mapping[str, Any], previous: Mapping[str, Any],
                native_event: Any) -> dict[str, Any]:
        clock, prior = _clock(row), _clock(previous)
        opening, segment = clock["open_ts_ms"], str(row["segment_id"])
        if str(previous["segment_id"]) != segment or prior["close_ts_ms"] != opening:
            raise ValueError("ORIGIN_NONCONTIGUOUS_PREVIOUS")
        if prior["available_ts_ms"] > clock["available_ts_ms"]:
            raise ValueError("ORIGIN_NONCAUSAL_PREVIOUS_AVAILABILITY")
        if self.last_open is not None and (opening != self.last_open + TF_MS or segment != self.segment):
            raise ValueError("ORIGIN_TRACE_COVERAGE_GAP")
        flags = _flags(row, previous)
        transitions: list[str] = []
        if not before["stage"]:
            if self.origins["touch"] is not None:
                transitions.append("POLICY_RESET_OBSERVED_BEFORE_NATIVE")
            self._clear()
        elif self.last_native_after is None:
            transitions.append("PREFIX_STATE_ORIGIN_UNKNOWN")
        elif int(before["side"]) != int(self.last_native_after["side"]):
            self._clear()
            transitions.append("EXTERNAL_SIDE_CHANGE_ORIGIN_UNKNOWN")
        origins_before = deepcopy(self.origins)
        side_changed = bool(flags["strong"] and before["side"] != flags["side"])
        if side_changed:
            self._clear()
            transitions.append("NATIVE_SIDE_RESET")
        if not flags["strong"]:
            if flags["native_weak_reset_predicate"]:
                transitions.append("NATIVE_WEAK_OR_UNORDERED_RESET")
                self._clear()
            else:
                transitions.append("NATIVE_WEAK_STATE_RETAINED_NO_EXTREMA_UPDATE")
                if before["stage"]:
                    self.weak_retained += 1
        elif before["episode_traded"] and not side_changed:
            if not after["episode_traded"] and not after["stage"]:
                transitions.append("NATIVE_REARM_AFTER_NEW_20BAR_EXTREME")
                self._clear()
            else:
                transitions.append("NATIVE_ACCEPTED_EPISODE_WAITING_REARM")
        elif after["stage"] == 1 and (not before["stage"] or side_changed):
            transitions.append("NATIVE_EMA20_TOUCH")
            self.origins = {"touch": _origin(row),
                            "pull_low": _origin(row, float(after["pull_low"])),
                            "pull_high": _origin(row, float(after["pull_high"]))}
        elif before["stage"] == after["stage"] == 1:
            transitions.append("NATIVE_PULL_EXTREMA_ACCUMULATION")
            for field, changed in (("pull_low", after["pull_low"] < before["pull_low"]),
                                   ("pull_high", after["pull_high"] > before["pull_high"])):
                if changed:
                    self.origins[field] = _origin(row, float(after[field]))
                    transitions.append("NATIVE_" + field.upper() + "_STRICT_UPDATE")
        if native_event is not None:
            transitions.append("NATIVE_TURN_EVENT_BEFORE_SUCCESSOR_ADMISSION")
        if not after["stage"]:
            self._clear()
        self.ordinal += 1
        self.last_open, self.segment = opening, segment
        self.last_native_after = _safe(after)
        known = self.origins["touch"] is not None
        regime, regime_available = native._regime(row, None)
        # Explicit input snapshots, not a copy of arbitrary row labels. These
        # let the reader verify touch/turn and distinguish raw availability
        # from the effective regime clock used by the pinned successor.
        inputs = {
            "row_ohlc": {key: float(row[key]) for key in ("open", "high", "low", "close")},
            "previous_ohlc": {key: float(previous[key]) for key in ("open", "high", "low", "close")},
            "previous_bar_clock": prior,
            "ema20": float(row["g20"]), "previous_ema20": float(previous["g20"]),
            "gmma_long": {str(n): float(row[f"g{n}"]) for n in native.LONG_GMMA},
            "previous_g60": float(previous["g60"]),
            "prior20_high": _safe(float(row["hi20"])), "prior20_low": _safe(float(row["lo20"])),
            "regime_as_supplied": {key: _safe(row.get(key)) for key in
                                   ("regime", "regime_available_ts_ms", "regime_fit_end_ts_ms", "regime_spec_sha256")},
            "effective_native_regime": regime,
            "effective_regime_available_ts_ms": int(regime_available),
        }
        record = {
            "schema": "zel.k126.state_origin.observation.v1", "identity": IDENTITY,
            "kind": "KELTNER_STATE_ORIGIN_TRANSITION", "symbol": self.symbol,
            "segment_id": segment, "observation_index": self.ordinal,
            "signal_open_ts_ms": opening, "signal_ts_ms": clock["available_ts_ms"],
            "bar_clock": clock, "phase_order": ["NATIVE_CALL", "SUCCESSOR_ADMISSION"],
            "features_asof": {**flags, "weak_bars_retained_since_observed_touch": self.weak_retained if known else None},
            "native_inputs_asof": inputs,
            "native_event_observed": _safe(native_event),
            "native_state_before": _safe(before), "native_state_after": _safe(after),
            "native_transitions": transitions,
            "origin_before_native": origins_before, "origin_after_native": deepcopy(self.origins),
            "current_bar_equal_price_matches": {
                "low_equals_retained_pull_low": bool(after["stage"] and float(row["low"]) == float(after["pull_low"])),
                "high_equals_retained_pull_high": bool(after["stage"] and float(row["high"]) == float(after["pull_high"]))},
            "coverage": "OBSERVED_FROM_NATIVE_TOUCH" if known else "ORIGIN_UNKNOWN_OR_NO_ACTIVE_PULL",
            "source_sha256": NATIVE_SHA256,
            "admission": {"state": "NO_GENERATED_EVENT" if native_event is None else "PENDING_SUCCESSOR_BRANCH", "reason": None},
            "scope": "OBSERVATION_ONLY_NO_POLICY_OR_OUTCOME",
        }
        return record


def observed_hg_call(observer: OriginObserver, state: Any, row: Mapping[str, Any],
                     previous: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Synthetic call hook. The native function runs exactly once."""
    before = asdict(state)
    event = native._hg_event(state, row, previous)
    return event, observer.observe(before, asdict(state), row, previous, event)


def finalize_observations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read caller-filled admissions; do not mutate caller records or native state.

    OUTSIDE_EVALUATION_WINDOW is intentionally ambiguous: a pre-first-window
    event remains consumed, while an inter-window event is unconsumed. The next
    observed state can resolve it; the observer never guesses from the label.
    """
    output = deepcopy(records)
    next_by_stream: dict[tuple[str, str], dict[str, Any]] = {}
    for record in reversed(output):
        if record.get("identity") != IDENTITY:
            raise ValueError("ORIGIN_OBSERVATION_MISSING_OR_UNKNOWN")
        stream = (record["symbol"], record["segment_id"])
        following = next_by_stream.get(stream)
        if following is not None and following["observation_index"] == 1:
            # enriched_segments may start another contiguous piece with the
            # same source segment label after a data gap. Its observer is new.
            following = None
        after = deepcopy(record["native_state_after"])
        admission = record["admission"]
        state = admission["state"]
        policy_after = deepcopy(admission.get("state_after_policy"))
        origin_after = deepcopy(record["origin_after_native"])
        transition = "NO_SUCCESSOR_EVENT_POLICY"
        certainty = "EXPLICIT_OR_NATIVE_UNCHANGED"
        if state in {"REGIME_INELIGIBLE_NO_RESET", "UNKNOWN_NO_RESET"}:
            after["episode_traded"] = False
            policy_after = after
            transition = state
        elif state == "REJECTED_RESET":
            transition = "EXPLICIT_ADMISSION_REJECTION_EVENT_RESET"
            if policy_after is None:
                raise ValueError("ORIGIN_EXPLICIT_REJECTION_STATE_MISSING")
            if policy_after["stage"] != 0 or policy_after["pull_low"] is not None or policy_after["pull_high"] is not None:
                raise ValueError("ORIGIN_EXPLICIT_REJECTION_RESET_DRIFT")
            origin_after = {"touch": None, "pull_low": None, "pull_high": None}
        elif state == "ACCEPTED":
            transition = "ADMISSION_ACCEPTED_EPISODE_CONSUMED"
            if policy_after is None or not policy_after["episode_traded"]:
                raise ValueError("ORIGIN_ACCEPTED_STATE_MISSING")
        elif state == "NO_GENERATED_EVENT":
            policy_after = after
        elif state == "OUTSIDE_EVALUATION_WINDOW":
            transition = "OUTSIDE_WINDOW_BRANCH_REQUIRES_NEXT_STATE"
            policy_after = None
            certainty = "UNKNOWN_WITHOUT_NEXT_OBSERVED_STATE"
        else:
            raise ValueError("ORIGIN_SUCCESSOR_ADMISSION_UNFINISHED:" + str(state))
        if following is not None:
            if following["signal_open_ts_ms"] != record["signal_open_ts_ms"] + TF_MS:
                raise ValueError("ORIGIN_FINALIZE_TRACE_GAP")
            actual_next = following["native_state_before"]
            if policy_after is not None and policy_after != actual_next:
                raise ValueError("ORIGIN_POLICY_NEXT_NATIVE_STATE_MISMATCH")
            if policy_after is None:
                policy_after = deepcopy(actual_next)
                certainty = "OBSERVED_NEXT_NATIVE_PRESTATE"
        decision = admission.get("decision_ts_ms")
        if decision is not None and _stamp(decision) < record["signal_ts_ms"]:
            raise ValueError("ORIGIN_ADMISSION_BEFORE_SIGNAL")
        record["successor_transition"] = transition
        record["policy_state_after"] = policy_after
        record["policy_state_certainty"] = certainty
        record["origin_after_policy"] = origin_after
        record["decision_order"] = {
            "native_event_available_ts_ms": record["signal_ts_ms"],
            "admission_decision_ts_ms": decision,
            "same_timestamp_order": "NATIVE_THEN_ADMISSION; next touch after rejection must be strictly later",
        }
        next_by_stream[stream] = record
    return output


@contextmanager
def observation_patch():
    """Temporary callback substitution only; fixed strategy/engine stay intact."""
    verify_native()
    from ops import scalp7_benchmark_observer_v1 as hook
    if hashlib.sha256(Path(hook.__file__).read_bytes()).hexdigest() != OBSERVER_HOOK_SHA256:
        raise ValueError("ORIGIN_OBSERVER_HOOK_SOURCE_CHANGED")
    original = hook.HGObserver
    hook.HGObserver = OriginObserver
    try:
        yield
    finally:
        hook.HGObserver = original
