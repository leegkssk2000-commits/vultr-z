"""Passive K117 execution chronology. No signals, fills, or exits are replaced.

The enabled wrapper executes the supplied, exact-built K117 callable ONCE.
Python line tracing observes the pinned native _single function; no AST rewrite
or callback/engine monkeypatch is performed. Stopped/target/pending terminal
bars never donate their high/low to a pre-exit observation. Import is inert.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
import hashlib
import inspect
import json
import math
from pathlib import Path
import sys
from types import CodeType
from typing import Any

from backend.research.rebuild import scalp7_execution_v2 as execution

IDENTITY = "k117_passive_exit_observer_c_v1"
BASELINE_IDENTITY = "scalp7_k126_veto_objective_completed_fresh_touch_v1"
ENGINE_SHA256 = "d1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1"
OBJECTIVE_SHA256 = "40659bc91044cca35ea6fc0aad383487b59ac16ec8aeb74639f8f5663e131bb7"
OBJECTIVE_AXIS = "VETO_EXPIRY_ONLY_WHEN_ORIGINAL_PRIOR20_OBJECTIVE_COMPLETE"


def _signature(code: CodeType):
    return (code.co_code, code.co_names, code.co_varnames, code.co_argcount,
            code.co_kwonlyargcount, code.co_freevars, code.co_cellvars,
            tuple(_signature(c) if isinstance(c, CodeType) else c for c in code.co_consts))


def _safe(value):
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return deepcopy(value)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _key(signal):
    return [str(signal["symbol"]), int(signal["side"]), int(signal["signal_ts_ms"])]


def _clock(bar):
    return {k: int(bar[k]) for k in ("open_ts_ms", "close_ts_ms", "available_ts_ms")}


def _position(position):
    # A whitelist keeps final labels or unrelated caller metadata out of inputs.
    return _safe({k: position[k] for k in (
        "side", "entry_price", "entry_ts_ms", "initial_stop", "initial_risk",
        "stop_price", "hold_bars", "mfe_R", "mae_R", "cost_bps", "remaining",
        "realized_parts_bps", "partial_executed", "unresolved_reason") if k in position})


def _signal(signal):
    out = {k: signal.get(k) for k in (
        "identity", "lane", "symbol", "side", "timeframe_min", "segment_id",
        "signal_open_ts_ms", "signal_ts_ms", "stop_price", "invalidation_price",
        "max_hold_bars", "take_profit_r", "partial_take_profit_r", "partial_fraction")}
    meta = signal.get("meta", {})
    out["meta"] = {k: meta.get(k) for k in ("atr_price", "be_arm_r", "frozen_cost_bps", "regime",
                                            "feature_available_ts_ms")}
    return _safe(out)


def _verify_engine():
    raw = Path(execution.__file__).read_bytes()
    if _sha(raw) != ENGINE_SHA256:
        raise ValueError("PASSIVE_ENGINE_SOURCE_CHANGED")
    text, start = inspect.getsourcelines(execution._single)
    source = "".join(text)
    namespace = {}
    # Full-module compilation preserves the compiler's imported-name call
    # specialization; an isolated function excerpt can have different bytecode
    # despite identical source and semantics on Python 3.12.
    exec(compile(raw, "verify_passive_engine_only.py", "exec", dont_inherit=True), namespace)
    if _signature(namespace["_single"].__code__) != _signature(execution._single.__code__):
        raise ValueError("PASSIVE_ENGINE_LOADED_CODE_CHANGED")
    tree = ast.parse(source)
    fn = tree.body[0]
    anchors = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"tp_r", "update", "fraction"}:
                # entry_update also assigns update; only the actual exit callback.
                if name == "update" and not (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "callback"):
                    continue
                if name in anchors:
                    raise ValueError("PASSIVE_NONUNIQUE_TRACE_ANCHOR")
                anchors[name] = start + node.lineno - 1
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "pending":
            anchors["bar_open"] = start + node.lineno - 1
    loops = [n for n in fn.body if isinstance(n, ast.For)]
    if len(loops) != 1 or ast.unparse(loops[0].body[-1]) != "previous = bar":
        raise ValueError("PASSIVE_ENGINE_LOOP_CHANGED")
    anchors["bar_committed"] = start + loops[0].body[-1].lineno - 1
    if set(anchors) != {"tp_r", "update", "fraction", "bar_open", "bar_committed"}:
        raise ValueError("PASSIVE_TRACE_ANCHOR_MISSING")
    return anchors


def _verify_objective(cls):
    raw = Path(inspect.getfile(cls)).read_bytes()
    if _sha(raw) != OBJECTIVE_SHA256:
        raise ValueError("PASSIVE_OBJECTIVE_SOURCE_CHANGED")
    namespace = {}
    exec(compile(raw, "verify_passive_objective_only.py", "exec", dont_inherit=True), namespace)
    for name in ("after_native", "rejected", "clear", "_expire"):
        if _signature(getattr(cls, name).__code__) != _signature(getattr(namespace["ObjectiveLifetime"], name).__code__):
            raise ValueError("PASSIVE_OBJECTIVE_LOADED_CODE_CHANGED")


class PassiveTrace:
    """Records invocation sessions, including auxiliary/rejected calls.

    The sink is not an order interface. Event ordering is native ordering, not
    inferred from outcome reasons. The old tracing hook must be empty so this
    context cannot silently displace another profiler/debugger.
    """
    def __init__(self, observations: list, objective_class=None):
        if not isinstance(observations, list):
            raise TypeError("PASSIVE_LIST_SINK_REQUIRED")
        self.sink = observations
        self.anchors = _verify_engine()
        self.single_code = execution._single.__code__
        self.objective_class = objective_class
        if objective_class is not None:
            _verify_objective(objective_class)
        self.objective_code = None if objective_class is None else objective_class.after_native.__code__
        self.sessions = {}
        self.touch_by_object = {}
        self.touch_by_signal = {}
        self.objective_exceptions = set()

    def _objective_return(self, frame, returned):
        local = frame.f_locals
        policy, before, state, row = (local[k] for k in ("self", "before", "state", "row"))
        current = id(policy)
        owner_frame = frame.f_back
        owner_token = id(owner_frame) if owner_frame is not None else None
        event = local["event"]
        event_key = None if event is None else (owner_token, str(local["symbol"]), int(event[0]), int(row["feature_available_ts_ms"]))
        if event_key is not None:
            self.touch_by_signal.pop(event_key, None)
        if not state.stage or policy.touch_ts is None:
            self.touch_by_object.pop(current, None)
            return
        if before["stage"] == 0 or before["side"] != state.side:
            self.touch_by_object[current] = {
                "status": "BOUND_TO_ACTUAL_K117_OBJECTIVE_TOUCH",
                "touch_open_ts_ms": int(row["open_ts_ms"]),
                "touch_close_ts_ms": int(row["close_ts_ms"]),
                "touch_raw_available_ts_ms": int(row["available_ts_ms"]),
                "touch_feature_available_ts_ms": int(policy.touch_ts),
                "frozen_prior20_objective": float(policy.target),
            }
        if event is not None and not returned:
            binding = self.touch_by_object.get(current)
            if binding is not None:
                self.touch_by_signal[event_key] = deepcopy(binding)

    def _start(self, frame):
        signal = frame.f_locals["signal"]
        key = _key(signal)
        ancestor, window, owner_token = frame.f_back, None, None
        while ancestor is not None:
            if ancestor.f_code.co_name == "_fresh_touch_successor" and "_ObjectiveLifetime" in ancestor.f_globals:
                owner_token = id(ancestor)
                current = ancestor.f_locals.get("window")
                if current is not None:
                    window = {k: current[k] for k in ("label", "partition", "start_ms", "end_ms")}
                break
            ancestor = ancestor.f_back
        session = {
            "schema": "zel.k117.passive_exit_session.v1", "observer_identity": IDENTITY,
            "baseline_identity": BASELINE_IDENTITY, "call_sequence": len(self.sink) + 1,
            "signal_key": key, "signal": _signal(signal),
            "window": _safe(window),
            "callback_qualname": getattr(frame.f_locals["callback"], "__qualname__", "UNKNOWN"),
            "touch_binding": deepcopy(self.touch_by_signal.get((owner_token, *key), {
                "status": "UNKNOWN_NOT_BOUND", "touch_feature_available_ts_ms": None})),
            "events": [], "outcome": None,
            "terminal_extremes_used_as_features": False,
        }
        self.sessions[id(frame)] = session
        self.sink.append(session)

    def _event(self, frame, kind, **fields):
        session = self.sessions[id(frame)]
        session["events"].append({"sequence": len(session["events"]) + 1, "kind": kind, **_safe(fields)})

    def _callback_pre(self, frame):
        loc = frame.f_locals
        bar, position, j, data = (loc[k] for k in ("bar", "position", "j", "frame"))
        clock = _clock(bar)
        prefix = data.iloc[: j + 1]
        if clock["available_ts_ms"] != clock["close_ts_ms"]:
            raise ValueError("PASSIVE_CALLBACK_NOT_COMPLETED_AVAILABLE_BAR")
        if prefix.empty or int(prefix.iloc[-1]["open_ts_ms"]) != clock["open_ts_ms"]:
            raise ValueError("PASSIVE_CALLBACK_PREFIX_MISMATCH")
        if (prefix.available_ts_ms > clock["available_ts_ms"]).any():
            raise ValueError("PASSIVE_FUTURE_PREFIX_REJECTED")
        for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms", "segment_id", "open", "high", "low", "close"):
            if prefix.iloc[-1][key] != bar[key]:
                raise ValueError("PASSIVE_CALLBACK_BAR_MISMATCH")
        if clock["open_ts_ms"] < int(position["entry_ts_ms"]):
            raise ValueError("PASSIVE_PREENTRY_CALLBACK")
        self._event(frame, "CALLBACK_PRE", decision_available_ts_ms=clock["available_ts_ms"],
                    bar_clock=clock, completed_bar={k: float(bar[k]) for k in ("open", "high", "low", "close")},
                    position=_position(position), prefix_rows=len(prefix),
                    current_bar_survived_native_stop_and_target=True,
                    mfe_semantics="AFTER_STOP_CHECK_ONLY; observed movement is not realizable profit")

    def _line(self, frame):
        line, loc = frame.f_lineno, frame.f_locals
        if line == self.anchors["tp_r"]:
            self._event(frame, "ENTRY", decision_available_ts_ms=int(loc["position"]["entry_ts_ms"]),
                        position=_position(loc["position"]), initial_risk_definition="side*(next_open-entry_stop)")
        elif line == self.anchors["bar_open"]:
            # Native pending exit is before this new bar's stop check. Only
            # open and prior completed observations are visible at this phase.
            self._event(frame, "BAR_OPEN", decision_available_ts_ms=int(loc["opened"]),
                        bar_open_ts_ms=int(loc["opened"]), open_price=float(loc["bar"]["open"]),
                        prior_position=_position(loc["position"]), pending_from_prior_completed_bar=loc["pending"],
                        high_low_close_not_observed=True)
        elif line == self.anchors["update"]:
            self._callback_pre(frame)
        elif line == self.anchors["fraction"]:
            self._event(frame, "CALLBACK_POST", decision_available_ts_ms=int(loc["bar"]["available_ts_ms"]),
                        bar_clock=_clock(loc["bar"]), position_before_engine_apply=_position(loc["position"]),
                        callback_update={k: loc["update"].get(k) for k in
                                         ("exit_next_open", "reason", "next_stop", "partial_fraction", "partial_price")})
        elif line == self.anchors["bar_committed"]:
            self._event(frame, "BAR_COMMITTED", decision_available_ts_ms=int(loc["bar"]["available_ts_ms"]),
                        bar_clock=_clock(loc["bar"]), position=_position(loc["position"]),
                        pending_next_open=loc["pending"],
                        scratch_scheduled=loc["pending"] == "HG_FROZEN_5BAR_MFE_SCRATCH",
                        runner_action=loc["update"].get("reason") == "HG_3R_RUNNER_NEXT_BAR",
                        fee_be_action=loc["update"].get("reason") == "FEE_BE_NEXT_BAR")

    def _finish(self, frame, result):
        session = self.sessions.pop(id(frame))
        loc = frame.f_locals
        if result is None:
            session["outcome"] = {"kind": "EXCEPTION_NO_COMPLETED_NATIVE_RETURN"}
            return
        row, unresolved, until, reason = result
        if row is not None:
            outcome = {"kind": "CLOSED", **{k: row[k] for k in (
                "entry_ts_ms", "exit_ts_ms", "outcome_available_ts_ms", "reason")},
                       "ownership_until_ts_ms": int(until)}
            session["outcome"] = _safe(outcome)
            terminal = {"sequence": len(session["events"]) + 1, **_safe(outcome), "kind": "TERMINAL",
                        "terminal_position": _position(loc["position"]),
                        "terminal_extremes_excluded": True,
                        "exit_prices": _safe(row["exit_prices"]),
                        "decision_available_ts_ms": int(row["outcome_available_ts_ms"]),
                        "native_order": "PENDING_OPEN_EXIT; else STOP/GAP; else TARGET; else COMPLETED_CALLBACK"}
            # No terminal high/low/close here, including open-gap stop bars.
            session["events"].append(terminal)
        elif unresolved is not None:
            session["outcome"] = {"kind": "UNRESOLVED", "entry_ts_ms": int(unresolved["entry_ts_ms"]),
                                  "ownership_until_ts_ms": int(until), "state": unresolved["state"]}
            diagnostic_position = _position(unresolved["position"])
            late = diagnostic_position.get("unresolved_reason") == "LATE_BAR_AVAILABILITY"
            if late:
                # Native updates these before its late-availability break.
                # They are not callback-time observables and cannot be credited
                # to any earlier decision or compared as an available feature.
                diagnostic_position.pop("mfe_R", None)
                diagnostic_position.pop("mae_R", None)
            completed = [e["decision_available_ts_ms"] for e in session["events"] if e["kind"] == "BAR_COMMITTED"]
            session["events"].append({"sequence": len(session["events"]) + 1, "kind": "UNRESOLVED",
                                      "position_diagnostic_not_callback_input": diagnostic_position,
                                      "last_observed_close_ts_ms": unresolved["last_observed_close_ts_ms"],
                                      "last_completed_callback_available_ts_ms": completed[-1] if completed else None,
                                      "late_bar_excursions_omitted": late,
                                      "terminal_bar_availability_ts_ms": int(loc["bar"]["available_ts_ms"]),
                                      "no_synthetic_exit": True})
        else:
            session["outcome"] = {"kind": "REJECTED", "reason": reason, "ownership_until_ts_ms": int(until)}
            session["events"].append({"sequence": len(session["events"]) + 1, "kind": "REJECTION", "reason": reason})

    def trace(self, frame, event, arg):
        code = frame.f_code
        if code is self.objective_code:
            if event == "exception":
                self.objective_exceptions.add(id(frame))
            elif event == "return" and id(frame) not in self.objective_exceptions:
                self._objective_return(frame, arg)
            elif event == "return":
                self.objective_exceptions.discard(id(frame))
            return self.trace
        if code is not self.single_code:
            return None
        if event == "call":
            self._start(frame)
        elif event == "line":
            self._line(frame)
        elif event == "return":
            self._finish(frame, arg)
        return self.trace


@contextmanager
def observation_context(observations: list, *, objective_class=None):
    """Synthetic engine fixture hook or wrapper implementation; no replay itself."""
    previous = sys.gettrace()
    if previous is not None:
        raise ValueError("PASSIVE_EXISTING_TRACE_HOOK_BUSY")
    collector = PassiveTrace(observations, objective_class)
    sys.settrace(collector.trace)
    try:
        yield collector
    finally:
        sys.settrace(previous)


def build(incumbent, *, enabled: bool = False, observations: list | None = None):
    """Wrap exact structure.ExitComparison(True) + objective_lifetime K117.

    Disabled returns the original object without validation or side effects.
    The owner harness additionally verifies all source bytes and reconstructs
    the exact K117 builder before using this interface; an identity is not an
    economic parity proof.
    """
    if type(enabled) is not bool:
        raise ValueError("PASSIVE_EXPLICIT_BOOLEAN_ENABLE_REQUIRED")
    if not enabled:
        return incumbent
    if observations is None:
        raise ValueError("PASSIVE_EXPLICIT_SINK_REQUIRED")
    if getattr(incumbent, "candidate_identity", None) != BASELINE_IDENTITY or getattr(incumbent, "single_changed_axis", None) != OBJECTIVE_AXIS:
        raise ValueError("PASSIVE_REQUIRES_BUILT_K117_NOT_K126_OR_C114")
    objective_class = incumbent.__globals__.get("_ObjectiveLifetime")
    if objective_class is None or incumbent.__globals__.get("_objective_events") is not incumbent.events:
        raise ValueError("PASSIVE_OBJECTIVE_STATE_NOT_BOUND")
    _verify_objective(objective_class)
    _verify_engine()

    @wraps(incumbent)
    def observed(*args, **kwargs):
        with observation_context(observations, objective_class=objective_class):
            return incumbent(*args, **kwargs)
    observed.passive_observer_identity = IDENTITY
    observed.native_callable = incumbent
    observed.observations = observations
    return observed


def join_all117(observations: list, saved_raw: list) -> list:
    """Coverage join only, no valuation. Distinct auxiliary calls are retained.

    An output key/terminal signature alone is insufficient when callbacks differ.
    Multiple matching sessions must have identical causal events; otherwise this
    join fails rather than selecting an outcome-favorable path.
    """
    if len(saved_raw) != 117 or len({tuple(_key(r)) for r in saved_raw}) != 117:
        raise ValueError("PASSIVE_EXACT_UNIQUE_RAW117_REQUIRED")
    grouped = {}
    for session in observations:
        if session.get("observer_identity") != IDENTITY:
            raise ValueError("PASSIVE_UNKNOWN_SESSION")
        grouped.setdefault(tuple(session["signal_key"]), []).append(session)
    joined = []
    for row in saved_raw:
        expected = {k: row[k] for k in ("entry_ts_ms", "exit_ts_ms", "outcome_available_ts_ms", "reason")}
        matching = [s for s in grouped.get(tuple(_key(row)), []) if s["outcome"] is not None
                    and s["outcome"].get("kind") == "CLOSED"
                    and (s["window"] is None or s["window"]["label"] == row.get("window_label"))
                    and all(s["outcome"].get(k) == v for k, v in expected.items())]
        if not matching:
            raise ValueError("PASSIVE_RAW117_TRACE_MISSING:" + str(_key(row)))
        for session in matching:
            binding = session["touch_binding"]
            if binding.get("status") != "BOUND_TO_ACTUAL_K117_OBJECTIVE_TOUCH":
                raise ValueError("PASSIVE_RAW117_TOUCH_ORIGIN_UNKNOWN:" + str(_key(row)))
            if not (binding["touch_open_ts_ms"] < binding["touch_close_ts_ms"] <= binding["touch_raw_available_ts_ms"]
                    <= binding["touch_feature_available_ts_ms"] <= row["signal_ts_ms"] <= row["entry_ts_ms"]):
                raise ValueError("PASSIVE_RAW117_TOUCH_CLOCK_INVALID:" + str(_key(row)))
            terminal = session["events"][-1]
            if terminal["exit_prices"] != row["exit_prices"]:
                raise ValueError("PASSIVE_RAW117_EXIT_PRICE_MISMATCH:" + str(_key(row)))
        signatures = {_sha(_encoded({"events": s["events"], "touch_binding": s["touch_binding"]})) for s in matching}
        if len(signatures) != 1:
            raise ValueError("PASSIVE_AMBIGUOUS_AUXILIARY_TRACE:" + str(_key(row)))
        joined.append({"signal_key": _key(row), "saved_raw_terminal": expected,
                       "call_sequence": matching[0]["call_sequence"],
                       "identical_matching_session_count": len(matching),
                       "causal_session_sha256": next(iter(signatures)),
                       "touch_binding": deepcopy(matching[0]["touch_binding"]),
                       "session": deepcopy(matching[0]),
                       "coverage": "EXACT_NATIVE_TERMINAL_MATCH",
                       "accounting": "RAW_INCUMBENT_ONLY; saved carry-adjusted rows separately pinned, not recomputed"})
    return joined
