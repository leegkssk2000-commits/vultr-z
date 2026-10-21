"""Synthetic-only harness tests; no cached market prices or runtime imports."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import inspect
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("owner_harness_tested", HERE / "run_owner_observer.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def fixture():
    row = {"symbol": "SYNTH", "side": 1, "signal_ts_ms": 10,
           "entry_ts_ms": 10, "entry_prices": {"SYNTH": 101.0},
           "partition": "rolling", "signal": {"invalidation_price": 90.0,
             "stop_price": 89.0, "meta": {"atr_price": 10.0, "fallback_stop_atr_mult": 1.2}}}
    observation = {"symbol": "SYNTH", "signal_ts_ms": 10,
                   "native_event_observed": [1, 90.0],
                   "admission": {"state": "ACCEPTED", "decision_ts_ms": 10}}
    saved = {"raw_trades": [row], "unresolved": [], "boundary_excluded": []}
    result = {"trades": [deepcopy(row)], "unresolved": [], "boundary_excluded": []}
    return saved, result, observation


def synthetic_source():
    """Exact native function excerpt, checked before synthetic compilation."""
    return harness.checked_bytes(HERE / "NATIVE_SUCCESSOR_FUNCTION.txt",
        "9cab68472492d27a0a990cdce73e51ecd8009866f2ba12fc3a29b02381094252").decode()


def synthetic_successor():
    """Real fixed successor, HG/entry/stop/exit engine; pre-enriched fake bars."""
    from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
    from ops import scalp7_keltner_fresh_touch_successor_v1 as local
    pins = {"_state": "b5b9657d3fd569d68fc981090a06a938fbcec6f5706ee4c5f313be9ec97f08ac",
            "_reject_generated": "dfcd9b1978267fca82d6089bafc12fe358adf490a56c747619195bc8e7ea4950",
            "_relabel": "4e41dcf57ced4c4413685cff50ad3d9439e3ae0789b1f15c72b3e5926eba2ffd"}
    for name, pin in pins.items():
        if harness.sha(inspect.getsource(getattr(local, name)).encode()) != pin:
            raise ValueError("SYNTHETIC_NATIVE_HELPER_CHANGED:" + name)
    scope = dict(vars(local))
    scope["positive"] = SimpleNamespace(**{**vars(positive), "enriched_segments": lambda frame: [frame]})
    source = synthetic_source()
    exec(compile(source, "fixed_native_successor_synthetic_only", "exec"), scope)
    return scope["_fresh_touch_successor"], source


def synthetic_frames():
    import pandas as pd
    from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
    tf = 1_800_000
    rows = []
    for i in range(160):
        row = {"open_ts_ms": i * tf, "close_ts_ms": (i + 1) * tf,
               "available_ts_ms": (i + 1) * tf, "feature_available_ts_ms": (i + 1) * tf,
               "open": 100.0, "high": 102.0, "low": 99.0, "close": 100.0,
               "segment_id": "synthetic", "g20": 99.5 + i * .001, "adx14": 35.0,
               "atr": 1.0, "hi20": 200.0, "lo20": 50.0,
               "regime": "PANIC_DISPERSION", "regime_available_ts_ms": (i + 1) * tf,
               "regime_fit_end_ts_ms": 0, "regime_spec_sha256": "a" * 64}
        row.update({f"g{n}": 100 + len(positive.LONG_GMMA) - j + i * .001
                    for j, n in enumerate(positive.LONG_GMMA)})
        rows.append(row)
    rows[121].update(low=95.0)
    rows[122].update(high=104.0, close=103.0, regime="COMPRESSION")
    rows[123].update(high=106.0, close=105.0, atr=0.01)
    rows[124].update(low=96.0)
    rows[125].update(high=105.0, close=104.0)
    rows[126].update(open=104.0, high=105.0, low=99.0)
    # The stop and a favorable extreme coexist: the actual engine must stop first.
    rows[127].update(low=94.0, high=201.0)
    rows[128].update(low=98.0)
    rows[129].update(high=105.0, close=104.0)
    rows[130].update(open=110.0, high=111.0, low=99.0, close=100.0)
    rows[131].update(low=94.0)
    return {"SYNTH": pd.DataFrame(rows)}, {"SYNTH": 10.0}, [
        {"label": "synthetic_rolling", "partition": "rolling", "start_ms": 121 * tf, "end_ms": 160 * tf}]


class OwnerObserverTests(unittest.TestCase):
    def test_fixed_successor_real_engine_observer_off_on_full_parity(self):
        sys.path.insert(0, str(HERE))
        import observer
        successor, _ = synthetic_successor()
        frames, costs, windows = synthetic_frames()
        frozen_frames = {k: v.copy(deep=True) for k, v in frames.items()}
        expected = successor(frames, costs, windows)
        observations = []
        with observer.observation_patch():
            actual = successor(frames, costs, windows, benchmark_observations=observations)
        self.assertEqual(actual, expected)
        for symbol in frames:
            self.assertTrue(frames[symbol].equals(frozen_frames[symbol]))
        finalized = observer.finalize_observations(observations)
        branches = {r["admission"]["state"] for r in finalized}
        self.assertTrue({"REGIME_INELIGIBLE_NO_RESET", "REJECTED_RESET", "ACCEPTED"} <= branches)
        transitions = {t for r in finalized for t in r["native_transitions"]}
        self.assertIn("NATIVE_REARM_AFTER_NEW_20BAR_EXTREME", transitions)
        self.assertTrue(all(r["reason"] == "STOP_FIRST" for r in actual["trades"]))
        self.assertGreaterEqual(len(actual["trades"]), 2)
        self.assertEqual(actual["trades"][1]["entry_prices"]["SYNTH"], 110.0)

    def test_exactly_one_incumbent_call_and_patch_restored(self):
        saved, result, observation = fixture()
        counts = {"calls": 0, "active": False}
        @contextmanager
        def patch():
            counts["active"] = True
            try:
                yield
            finally:
                counts["active"] = False
        def incumbent(frames, costs, windows, benchmark_observations):
            self.assertTrue(counts["active"])
            counts["calls"] += 1
            benchmark_observations.append(deepcopy(observation))
            return result
        obs, joined = harness.observe_once(incumbent, {}, {}, [], saved, patch, deepcopy, 1)
        self.assertEqual(counts, {"calls": 1, "active": False})
        self.assertEqual(len(obs), 1)
        self.assertEqual(len(joined), 1)
        self.assertFalse(joined[0]["outcomes_used_as_conditions"])

    def test_row_value_change_rejected(self):
        saved, result, _ = fixture()
        result["trades"][0]["entry_prices"]["SYNTH"] += 1
        with self.assertRaisesRegex(ValueError, "OBSERVER_CHANGED"):
            harness.verify_parity(result, saved, 1)

    def test_unresolved_and_boundary_changes_rejected(self):
        for field in ("unresolved", "boundary_excluded"):
            saved, result, _ = fixture()
            result[field] = [{"partition": "rolling", "unresolved": True}]
            with self.assertRaisesRegex(ValueError, "OBSERVER_CHANGED"):
                harness.verify_parity(result, saved, 1)

    def test_entry_join_missing_and_duplicate_rejected(self):
        saved, _, observation = fixture()
        for records, message in (([], "INCOMPLETE"), ([observation, observation], "DUPLICATE")):
            with self.assertRaisesRegex(ValueError, message):
                harness.join_entries(records, saved["raw_trades"])

    def test_entry_join_requires_price_time_and_acceptance(self):
        for mutation, message in ((lambda r: r["admission"].update(state="REJECTED_RESET"), "NOT_ACCEPTED"),
                                  (lambda r: r["admission"].update(decision_ts_ms=11), "CLOCK_MISMATCH"),
                                  (lambda r: r.update(native_event_observed=[1, 91.0]), "PRICE_MISMATCH")):
            saved, _, observation = fixture()
            mutation(observation)
            with self.assertRaisesRegex(ValueError, message):
                harness.join_entries([observation], saved["raw_trades"])

    def test_pin_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "input"
            p.write_bytes(b"synthetic")
            self.assertEqual(harness.checked_bytes(p, harness.sha(b"synthetic")), b"synthetic")
            with self.assertRaisesRegex(ValueError, "PIN_CHANGED"):
                harness.checked_bytes(p, "0" * 64)

    def test_existing_lock_never_created_or_modified(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "existing.lock"
            with self.assertRaises(FileNotFoundError):
                with harness.existing_lock(p):
                    pass
            self.assertFalse(p.exists())
            p.write_bytes(b"owner lock")
            with harness.existing_lock(p):
                self.assertEqual(p.read_bytes(), b"owner lock")
            self.assertEqual(p.read_bytes(), b"owner lock")

    def test_capacity_busy_refuses_without_run_or_retry(self):
        for global_busy, local_busy in (([{"id": 1}], []), ([], [{"pid": 2}])):
            cap = SimpleNamespace(live_capacity=lambda: (global_busy, []),
                                  original=SimpleNamespace(local_busy=lambda: local_busy))
            with self.assertRaisesRegex(RuntimeError, "CAPACITY_BUSY_NO_WAIT_NO_REPLAY"):
                harness.require_capacity(cap)

    def test_no_owner_or_run_switch_stops_before_file_reads(self):
        for owner, run_once in (("C", True), (harness.OWNER, False)):
            with self.assertRaisesRegex(ValueError, "OWNER_ONLY"):
                harness.run(SimpleNamespace(owner_ack=owner, run_once=run_once))

    def test_output_add_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            harness.save_new(p, "receipt.json", {"synthetic": True})
            with self.assertRaises(FileExistsError):
                harness.save_new(p, "receipt.json", {"synthetic": False})


if __name__ == "__main__":
    unittest.main()
