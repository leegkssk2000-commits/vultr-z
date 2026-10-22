"""Synthetic harness invocation/gate/parity tests; no real price replay."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("tested_k117_owner_harness", HERE / "run_owner_exit_observer.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def fixture():
    row = {"symbol": "SYNTH", "side": 1, "signal_ts_ms": 10,
           "entry_ts_ms": 10, "partition": "rolling", "exit_ts_ms": 20,
           "entry_prices": {"SYNTH": 100.0}}
    native = [{"synthetic_native_transition": "ACCEPTED"}]
    objective = [{"synthetic_objective_transition": "EXPIRED"}]
    saved = {"raw_trades": [row], "unresolved": [], "boundary_excluded": [],
             "native_traces": native, "objective_expiry_events": objective}
    result = {"trades": [deepcopy(row)], "unresolved": [], "boundary_excluded": [],
              "traces": deepcopy(native)}
    return saved, result, objective


class OwnerExitHarnessTests(unittest.TestCase):
    def test_actual_built_k117_single_invocation_complete117_trace_join(self):
        """117 invented entries, including an actual objective-expiry transition."""
        sys.path.insert(0, str(HERE))
        from test_passive_exit_observer import synthetic_k117, observer
        control, inputs = synthetic_k117()
        observed_native, _ = synthetic_k117()
        one_frame = inputs[0]["SYNTH"]
        frames = {f"SYNTH_{i:02}": one_frame.copy(deep=True) for i in range(59)}
        # The final synthetic instrument has only the first of two entries.
        frames["SYNTH_58"] = frames["SYNTH_58"].iloc[:129].copy(deep=True)
        # Veto + completed touch-time objective expires a real K117 episode.
        # This is a fixture price relationship, never an implemented new rule.
        frames["SYNTH_00"].loc[121, "hi20"] = 104.0
        costs = {name: 10.0 for name in frames}
        before = {name: frame.copy(deep=True) for name, frame in frames.items()}
        expected = control(frames, costs, inputs[2])
        raw = [r for r in expected["trades"] if r["partition"] == "rolling"]
        self.assertEqual(len(raw), 117)
        self.assertTrue(control.events)
        self.assertTrue(expected["traces"])
        saved = {"raw_trades": raw,
                 "unresolved": [r for r in expected["unresolved"] if r["partition"] == "rolling"],
                 "boundary_excluded": [r for r in expected["boundary_excluded"] if r["partition"] == "rolling"],
                 "native_traces": expected["traces"], "objective_expiry_events": control.events}
        sessions, entries = h.observe_once(observed_native, frames, costs, inputs[2], saved, observer)
        self.assertEqual(len(entries), 117)
        self.assertGreaterEqual(len(sessions), 117)
        self.assertEqual(observed_native.events, control.events)
        self.assertTrue(all(e["coverage"] == "EXACT_NATIVE_TERMINAL_MATCH" for e in entries))
        self.assertIsNone(sys.gettrace())
        for name, frame in frames.items():
            self.assertTrue(frame.equals(before[name]))

    def test_observe_once_invokes_only_one_k117_callable_without_benchmark_hook(self):
        saved, result, objective = fixture()
        calls = []
        def baseline(frames, costs, windows):
            calls.append((frames, costs, windows))
            baseline.events.extend(deepcopy(objective))
            return deepcopy(result)
        baseline.events = []
        def build(fn, *, enabled, observations):
            if not enabled:
                return fn
            def wrapped(*args):
                observations.append({"synthetic": True})
                return fn(*args)
            return wrapped
        passive = SimpleNamespace(build=build, join_all117=lambda sessions, rows: deepcopy(rows))
        sessions, joined = h.observe_once(baseline, {}, {}, [], saved, passive, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(joined, saved["raw_trades"])
        self.assertEqual(baseline.events, objective)
        with self.assertRaisesRegex(ValueError, "ALREADY_USED"):
            h.observe_once(baseline, {}, {}, [], saved, passive, 1)
        self.assertEqual(len(calls), 1)

    def test_disabled_identity_drift_refuses_before_baseline_run(self):
        baseline = lambda *args: self.fail("must not invoke")
        baseline.events = []
        passive = SimpleNamespace(build=lambda *args, **kwargs: lambda: None)
        with self.assertRaisesRegex(ValueError, "DISABLED_NOT_IDENTICAL"):
            h.observe_once(baseline, {}, {}, [], {}, passive)

    def test_parity_rejects_full_row_or_order_drift(self):
        saved, result, objective = fixture()
        result["trades"][0]["entry_prices"]["SYNTH"] += 0.1
        with self.assertRaisesRegex(ValueError, "trades"):
            h.verify_parity(result, objective, saved, 1)
        saved, result, objective = fixture()
        second = deepcopy(saved["raw_trades"][0]); second["signal_ts_ms"] = 30
        saved["raw_trades"].append(second)
        result["trades"].insert(0, deepcopy(second))
        with self.assertRaisesRegex(ValueError, "trades"):
            h.verify_parity(result, objective, saved, 2)

    def test_parity_rejects_native_or_objective_state_change(self):
        for field in ("traces", "events"):
            saved, result, objective = fixture()
            if field == "traces":
                result[field].append({"unexpected": "reset"})
            else:
                objective = []
            with self.assertRaisesRegex(ValueError, "PARITY_FAILED"):
                h.verify_parity(result, objective, saved, 1)

    def test_unresolved_and_boundary_must_match(self):
        for field in ("unresolved", "boundary_excluded"):
            saved, result, objective = fixture()
            result[field].append({"partition": "rolling", "synthetic": True})
            with self.assertRaisesRegex(ValueError, field):
                h.verify_parity(result, objective, saved, 1)

    def test_original_symbol_order_required_not_just_set(self):
        h.require_order(h.ORDER, dict.fromkeys(h.ORDER))
        for order in (tuple(reversed(h.ORDER)), tuple(sorted(h.ORDER))):
            with self.assertRaisesRegex(ValueError, "ORDER_CHANGED"):
                h.require_order(order)
        with self.assertRaisesRegex(ValueError, "ORDER_CHANGED"):
            h.require_order(h.ORDER, dict.fromkeys(reversed(h.ORDER)))

    def test_owner_ack_and_run_once_required_before_runtime_reads(self):
        for ack, once in (("C", True), (h.OWNER, False), (None, True)):
            args = SimpleNamespace(bind_only=False, owner_ack=ack, run_once=once, output_dir=Path("/tmp/x"))
            with patch.object(h, "bind_runtime", side_effect=AssertionError("must not bind")):
                with self.assertRaisesRegex(ValueError, "A_OWNER_ACK"):
                    h.run(args)

    def test_bind_only_cannot_write_or_start(self):
        for once, output in ((True, None), (False, Path("/tmp/x"))):
            args = SimpleNamespace(bind_only=True, run_once=once, output_dir=output)
            with patch.object(h, "bind_runtime", side_effect=AssertionError("must not bind")):
                with self.assertRaisesRegex(ValueError, "BIND_ONLY_CANNOT"):
                    h.run(args)

    def test_pin_check_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "synthetic"
            p.write_bytes(b"synthetic")
            self.assertEqual(h.checked(p, h.sha(b"synthetic")), b"synthetic")
            with self.assertRaisesRegex(ValueError, "PIN_CHANGED"):
                h.checked(p, "0" * 64)


if __name__ == "__main__":
    unittest.main()
