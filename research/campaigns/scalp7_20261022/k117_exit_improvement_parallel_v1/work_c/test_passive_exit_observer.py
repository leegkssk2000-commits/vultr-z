"""Invented bars only: native lifecycle/terminal chronology and exact K117 build."""
import ast
from copy import deepcopy
import hashlib
import importlib.machinery
import importlib.util
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import pandas as pd
from backend.research.rebuild import scalp7_execution_v2 as engine
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
OLD = ROOT / "research/campaigns/scalp7_20261021/k126_loss_repair_parallel_v1/work_c"
sys.path[:0] = [str(HERE), str(OLD), str(ROOT)]
import passive_exit_observer as observer
TF = 1_800_000


def load_text_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def bars(items=None, count=10):
    items = items or {}
    return pd.DataFrame([{"open_ts_ms": i * TF, "close_ts_ms": (i + 1) * TF,
                         "available_ts_ms": (i + 1) * TF, "segment_id": "synthetic",
                         "open": 100., "high": 102., "low": 99., "close": 100.,
                         **items.get(i, {})} for i in range(count)])


def signal(side=1, **extra):
    return {"identity": positive.KELTNER_PARENT, "lane": "keltner_holygrail",
            "symbol": "SYNTH", "side": side, "timeframe_min": 30,
            "signal_open_ts_ms": 0, "signal_ts_ms": TF, "segment_id": "synthetic",
            "stop_price": 100. - side * 10., "invalidation_price": 100. - side * 9.,
            "max_hold_bars": 25, "take_profit_r": None,
            "partial_take_profit_r": 2., "partial_fraction": .10,
            "meta": {"be_arm_r": 1., "frozen_cost_bps": 10., "atr_price": 1.}, **extra}


def hold(position, bar, history):
    return {"exit_next_open": False, "reason": "SYNTHETIC_HOLD"}


def synthetic_k117():
    """Actual structural .build then objective .build; only market input is fake.

    Frozen native helper functions are real. Pre-enriched invented bars replace
    indicator seeding only, as in the prior committed synthetic fixture. No
    fake identity-only strategy or market replay is used for this parity test.
    """
    from test_owner_observer import synthetic_successor, synthetic_frames
    native, source = synthetic_successor()
    # inspect.getsource must resolve the exact function used by build().
    namespace = dict(native.__globals__)
    exec(compile(source, str(OLD / "NATIVE_SUCCESSOR_FUNCTION.txt"), "exec", dont_inherit=True), namespace)
    native = namespace["_fresh_touch_successor"]
    native_module_file = HERE / "K117_NATIVE_MODULE_SOURCE.txt"
    if hashlib.sha256(native_module_file.read_bytes()).hexdigest() != "e0afbe1d76c4a3c8b4470aae82b152bd3f59676339294653719c3f3a85e2f855":
        raise ValueError("SYNTHETIC_FROZEN_NATIVE_MODULE_CHANGED")
    k = SimpleNamespace(**{**namespace, "_fresh_touch_successor": native, "__file__": str(native_module_file)})
    timeout_path = ROOT / "research/campaigns/scalp7_20261017/parallel_benchmark_v1/winner_timeout_real_20261021T1142Z/winner_timeout_comparison.py"
    timeout = load_text_module("synthetic_k117_timeout", timeout_path)
    h = SimpleNamespace(k=k, timeout=timeout, positive=positive, execution=engine,
                        START=0, key=lambda s: (s["symbol"], int(s["side"]), int(s["signal_ts_ms"])))
    structure_path = HERE / "K117_STRUCTURE_SOURCE.txt"
    raw = structure_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != "a260f6461d4fd96316c3716ebb1177d802752a7e4c842f80ea1966694ff236c3":
        raise ValueError("SYNTHETIC_STRUCTURE_CHANGED")
    tree = ast.parse(raw)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ExitComparison")
    # Only skip environment-specific import/path side effects, not class code.
    scope = dict(h=h, deepcopy=deepcopy, Path=Path, SimpleNamespace=SimpleNamespace,
                 hashlib=hashlib, inspect=inspect, math=__import__("math"),
                 REASON="K126_PULLBACK_STRUCTURE_FAILURE_NEXT_OPEN")
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(structure_path), "exec"), scope)
    structure = scope["ExitComparison"](True)
    original = structure.build()
    objective = load_text_module("synthetic_k117_objective", HERE / "K117_OBJECTIVE_SOURCE.txt")
    built = objective.build(original, source_text=source, enabled=True)
    inputs = synthetic_frames()
    return built, inputs


class PassiveExitTests(unittest.TestCase):
    def pair(self, frame=None, sig=None, callback=positive.exit_update):
        frame, sig = frame if frame is not None else bars(), sig or signal()
        records, index = engine._frame_records(frame, 30)
        expected = engine._single(deepcopy(sig), frame.copy(deep=True), deepcopy(records), dict(index), 10., callback)
        saved_frame, saved_sig, saved_records = frame.copy(deep=True), deepcopy(sig), deepcopy(records)
        sessions = []
        with observer.observation_context(sessions):
            actual = engine._single(sig, frame, records, index, 10., callback)
        self.assertEqual(actual, expected)
        self.assertEqual(sig, saved_sig)
        self.assertEqual(records, saved_records)
        self.assertTrue(frame.equals(saved_frame))
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(sys.gettrace())
        return actual, sessions[0]

    def test_long_scratch_scheduling_and_terminal_clock(self):
        result, session = self.pair()
        self.assertEqual(result[0]["reason"], "HG_FROZEN_5BAR_MFE_SCRATCH")
        scheduled = [e for e in session["events"] if e.get("scratch_scheduled")]
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]["decision_available_ts_ms"], 6 * TF)
        self.assertEqual(session["events"][-1]["kind"], "TERMINAL")
        self.assertEqual(session["events"][-1]["exit_ts_ms"], 6 * TF)
        self.assertEqual(session["events"][0]["position"]["initial_risk"], 10.)

    def test_short_scratch_native_parity(self):
        f = bars({i: {"high": 101., "low": 98.} for i in range(10)})
        result, session = self.pair(f, signal(-1))
        self.assertEqual(result[0]["reason"], "HG_FROZEN_5BAR_MFE_SCRATCH")
        self.assertEqual(session["events"][0]["position"]["initial_stop"], 110.)

    def test_normal_adverse_then_recovery_not_early_exit(self):
        f = bars({1: {"low": 92., "high": 102., "close": 96.},
                  2: {"low": 95., "high": 106., "close": 105.}})
        result, session = self.pair(f, signal(max_hold_bars=7))
        self.assertEqual(result[0]["reason"], "MAX_HOLD_NEXT_OPEN")
        self.assertFalse(any(e.get("scratch_scheduled") for e in session["events"]))

    def test_big_runner_partial_remaining_and_tightened_stop(self):
        f = bars({1: {"high": 132., "low": 99., "close": 130.},
                  2: {"open": 131., "high": 140., "low": 121., "close": 135.},
                  3: {"open": 134., "high": 160., "low": 126., "close": 130.}})
        result, session = self.pair(f)
        self.assertEqual(result[0]["reason"], "STOP_FIRST")
        committed = [e for e in session["events"] if e["kind"] == "BAR_COMMITTED"]
        self.assertEqual(committed[0]["position"]["remaining"], .9)
        self.assertTrue(committed[0]["runner_action"])
        self.assertGreater(committed[1]["position"]["stop_price"], committed[0]["position"]["stop_price"])
        self.assertEqual(result[0]["mfe_R"], 4.)  # terminal high160 is excluded

    def test_short_runner_and_partial_are_native(self):
        f = bars({1: {"high": 101., "low": 68., "close": 70.},
                  2: {"open": 69., "high": 79., "low": 60., "close": 65.},
                  3: {"open": 66., "high": 74., "low": 40., "close": 70.}})
        result, session = self.pair(f, signal(-1))
        self.assertEqual(result[0]["mfe_R"], 4.)
        self.assertEqual(session["events"][-1]["terminal_position"]["remaining"], .9)

    def test_stop_first_bar_never_donates_extremes_or_callback(self):
        result, session = self.pair(bars({1: {"high": 200., "low": 89.}}))
        self.assertEqual(result[0]["reason"], "STOP_FIRST")
        self.assertEqual(result[0]["mfe_R"], 0.)
        self.assertFalse(any(e["kind"].startswith("CALLBACK") for e in session["events"]))
        self.assertTrue(all("completed_bar" not in e for e in session["events"]))

    def test_open_gap_stop_uses_open_not_terminal_range(self):
        result, session = self.pair(bars({2: {"open": 85., "high": 200., "low": 80., "close": 100.}}))
        self.assertEqual(result[0]["reason"], "OPEN_GAP_STOP")
        self.assertEqual(session["events"][-1]["exit_prices"], {"SYNTH": 85.})
        self.assertEqual(session["events"][-1]["decision_available_ts_ms"], 2 * TF)

    def test_pending_scratch_exit_precedes_newbar_gap_stop(self):
        result, session = self.pair(bars({6: {"open": 85., "high": 200., "low": 80., "close": 100.}}))
        self.assertEqual(result[0]["reason"], "HG_FROZEN_5BAR_MFE_SCRATCH")
        self.assertEqual(result[0]["exit_prices"], {"SYNTH": 85.})
        self.assertEqual(session["events"][-2]["pending_from_prior_completed_bar"], result[0]["reason"])

    def test_stop_and_target_same_bar_remains_stop_first(self):
        result, session = self.pair(bars({1: {"high": 130., "low": 89.}}), signal(take_profit_r=2.))
        self.assertEqual(result[0]["reason"], "STOP_FIRST")
        self.assertFalse(any(e["kind"] == "CALLBACK_PRE" for e in session["events"]))

    def test_target_terminal_extremes_excluded(self):
        result, session = self.pair(bars({1: {"high": 130., "low": 99.}}), signal(take_profit_r=2.))
        self.assertEqual(result[0]["reason"], "TARGET")
        self.assertEqual(result[0]["mfe_R"], 0.)
        self.assertTrue(session["events"][-1]["terminal_extremes_excluded"])

    def test_gap_unresolved_owns_position_without_synthetic_exit(self):
        f = bars().drop(index=3).reset_index(drop=True)
        result, session = self.pair(f, callback=hold)
        self.assertIsNone(result[0])
        self.assertEqual(result[2], 2**63 - 1)
        self.assertEqual(session["outcome"]["kind"], "UNRESOLVED")

    def test_end_unresolved_and_late_available_no_callback(self):
        for f in (bars(count=2), bars({1: {"available_ts_ms": 2 * TF + 1}}, count=3)):
            result, session = self.pair(f, callback=hold)
            self.assertIsNotNone(result[1])
        self.assertFalse(any(e["kind"] == "CALLBACK_PRE" for e in session["events"]))
        terminal = session["events"][-1]
        self.assertTrue(terminal["late_bar_excursions_omitted"])
        self.assertNotIn("mfe_R", terminal["position_diagnostic_not_callback_input"])
        self.assertNotIn("mae_R", terminal["position_diagnostic_not_callback_input"])
        self.assertIsNone(terminal["last_completed_callback_available_ts_ms"])

    def test_late_signal_refused_and_unknown_touch_explicit(self):
        result, session = self.pair(sig=signal(signal_ts_ms=TF + 1))
        self.assertEqual(result[3], "LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL")
        self.assertEqual(session["touch_binding"]["status"], "UNKNOWN_NOT_BOUND")

    def test_future_prefix_refused_and_trace_restored(self):
        frame = bars()
        records, index = engine._frame_records(frame, 30)
        frame.loc[0, "available_ts_ms"] = 100 * TF
        with self.assertRaisesRegex(ValueError, "FUTURE_PREFIX"):
            with observer.observation_context([]):
                engine._single(signal(), frame, records, index, 10., hold)
        self.assertIsNone(sys.gettrace())

    def test_callback_error_restores_trace_and_does_not_swallow_exception(self):
        def broken(*args):
            raise RuntimeError("synthetic_callback_failure")
        frame = bars()
        records, index = engine._frame_records(frame, 30)
        with self.assertRaisesRegex(RuntimeError, "synthetic_callback_failure"):
            with observer.observation_context([]):
                engine._single(signal(), frame, records, index, 10., broken)
        self.assertIsNone(sys.gettrace())

    def test_existing_trace_hook_not_displaced(self):
        def existing(*args):
            return None
        sys.settrace(existing)
        try:
            with self.assertRaisesRegex(ValueError, "TRACE_HOOK_BUSY"):
                with observer.observation_context([]):
                    pass
            self.assertIs(sys.gettrace(), existing)
        finally:
            sys.settrace(None)

    def test_duplicate_signals_are_observed_separately_not_deduplicated(self):
        frame = bars()
        records, index = engine._frame_records(frame, 30)
        sink = []
        with observer.observation_context(sink):
            first = engine._single(signal(), frame, records, index, 10., positive.exit_update)
            second = engine._single(signal(), frame, records, index, 10., positive.exit_update)
        self.assertEqual(first, second)
        self.assertEqual([s["call_sequence"] for s in sink], [1, 2])

    def test_disabled_returns_exact_object_and_does_no_work(self):
        sentinel = object()
        self.assertIs(observer.build(sentinel, enabled=False), sentinel)
        with self.assertRaisesRegex(ValueError, "BOOLEAN"):
            observer.build(sentinel, enabled=1)

    def test_old_identity_cannot_masquerade_as_k117(self):
        def old():
            pass
        with self.assertRaisesRegex(ValueError, "BUILT_K117"):
            observer.build(old, enabled=True, observations=[])

    def test_exact_native_k117_builder_state_and_results_preserved(self):
        control, inputs = synthetic_k117()
        observed_native, other_inputs = synthetic_k117()
        old_scope = dict(observed_native.__globals__)
        before_frames = {k: v.copy(deep=True) for k, v in other_inputs[0].items()}
        expected = control(*inputs)
        sink = []
        observed = observer.build(observed_native, enabled=True, observations=sink)
        actual = observed(*other_inputs)
        self.assertEqual(actual, expected)
        self.assertEqual(observed_native.events, control.events)
        self.assertEqual(observed_native.__globals__, old_scope)
        self.assertTrue(actual["trades"])
        self.assertTrue(sink)
        self.assertTrue(any(s["touch_binding"]["status"] == "BOUND_TO_ACTUAL_K117_OBJECTIVE_TOUCH" for s in sink))
        for key, frame in other_inputs[0].items():
            self.assertTrue(frame.equals(before_frames[key]))
        self.assertIs(observer.build(observed_native, enabled=False), observed_native)

    def test_actual_k117_objective_expiry_and_later_entry_preserved(self):
        control, inputs = synthetic_k117()
        native, traced_inputs = synthetic_k117()
        for data in (inputs, traced_inputs):
            # Frozen objective103 touched before/at the known-veto event122.
            # The exact K117 rule must expire it, then allow a later fresh touch.
            data[0]["SYNTH"].loc[121, "hi20"] = 103.
        expected = control(*inputs)
        sink = []
        actual = observer.build(native, enabled=True, observations=sink)(*traced_inputs)
        self.assertTrue(control.events)
        self.assertEqual(actual, expected)
        self.assertEqual(native.events, control.events)
        self.assertEqual(control.events[0]["reason"], "KNOWN_VETO_WITH_OBJECTIVE_ALREADY_COMPLETE")
        self.assertTrue(actual["trades"])
        self.assertTrue(all(s["touch_binding"].get("touch_feature_available_ts_ms", 0) > control.events[0]["expired_ts_ms"]
                            for s in sink if s["outcome"].get("kind") == "CLOSED"))

    def test_full117_join_bound_trace_and_identical_auxiliary_count(self):
        sessions, rows = self.join_fixture()
        sessions.append(deepcopy(sessions[0]))
        sessions[-1]["call_sequence"] = 118
        result = observer.join_all117(sessions, rows)
        self.assertEqual(len(result), 117)
        self.assertEqual(result[0]["identical_matching_session_count"], 2)
        self.assertIn("events", result[0]["session"])

    def test_full117_join_rejects_unknown_touch_or_price_or_missing_session(self):
        for mutation, message in (
            (lambda s, r: s[0]["touch_binding"].update(status="UNKNOWN_NOT_BOUND"), "TOUCH_ORIGIN_UNKNOWN"),
            (lambda s, r: s[0]["touch_binding"].update(touch_feature_available_ts_ms=10**15), "TOUCH_CLOCK_INVALID"),
            (lambda s, r: s[0]["events"][-1]["exit_prices"].update({"S0": 0}), "EXIT_PRICE_MISMATCH"),
            (lambda s, r: s.pop(0), "TRACE_MISSING"),
        ):
            sessions, rows = self.join_fixture()
            mutation(sessions, rows)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                observer.join_all117(sessions, rows)

    def test_full117_join_does_not_select_between_conflicting_auxiliary_traces(self):
        sessions, rows = self.join_fixture()
        duplicate = deepcopy(sessions[0])
        duplicate["events"][0]["position"]["initial_risk"] += 1
        sessions.append(duplicate)
        with self.assertRaisesRegex(ValueError, "AMBIGUOUS"):
            observer.join_all117(sessions, rows)

    def test_new_native_invocation_cannot_reuse_stale_touch_binding(self):
        native, inputs = synthetic_k117()
        sink = []
        with observer.observation_context(sink, objective_class=native.__globals__["_ObjectiveLifetime"]):
            result = native(*inputs)
            old = result["trades"][0]
            frame = inputs[0][old["symbol"]]
            records, index = engine._frame_records(frame, 30)
            # Outside the K117 call stack, the same symbol/time cannot borrow
            # ancestry. This auxiliary raw call is explicitly UNKNOWN.
            sig = deepcopy(old["signal"])
            sig["identity"] = positive.KELTNER_PARENT
            engine._single(sig, frame, records, index, 10., positive.exit_update)
        self.assertEqual(sink[-1]["touch_binding"]["status"], "UNKNOWN_NOT_BOUND")

    def test_future_outcome_labels_do_not_change_execution_trace(self):
        f = bars()
        result, clean = self.pair(f)
        f["final_pnl"] = "UNAVAILABLE_FUTURE_LABEL"
        f["final_mfe"] = 10**12
        result2, decorated = self.pair(f)
        self.assertEqual(result2, result)
        self.assertEqual(decorated, clean)

    @staticmethod
    def join_fixture():
        native, inputs = synthetic_k117()
        sink = []
        output = observer.build(native, enabled=True, observations=sink)(*inputs)
        row = output["trades"][0]
        matching = next(s for s in sink if s["signal_key"] == [row["symbol"], row["side"], row["signal_ts_ms"]]
                        and s["outcome"].get("exit_ts_ms") == row["exit_ts_ms"])
        sessions, rows = [], []
        for i in range(117):
            name = f"S{i}"
            trade, session = deepcopy(row), deepcopy(matching)
            trade["symbol"] = name
            trade["exit_prices"] = {name: next(iter(row["exit_prices"].values()))}
            session["signal_key"][0] = name
            session["call_sequence"] = i + 1
            session["events"][-1]["exit_prices"] = deepcopy(trade["exit_prices"])
            sessions.append(session)
            rows.append(trade)
        return sessions, rows


if __name__ == "__main__":
    unittest.main(verbosity=2)
