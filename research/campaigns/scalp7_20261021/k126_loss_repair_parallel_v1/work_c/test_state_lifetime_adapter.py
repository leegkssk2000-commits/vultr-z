"""Synthetic-only native state/execution fixtures; no saved or market prices."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[4])]
import state_lifetime_adapter as a
from test_owner_observer import synthetic_frames, synthetic_successor

TF = 1_800_000


def continuation(veto="COMPRESSION"):
    """A wide-risk winner after a veto, with no later EMA touch.

    This is an intentional false-positive counterexample to the proposed rule.
    All bars are invented. The rule does not receive the eventual outcome.
    """
    frames, costs, windows = synthetic_frames()
    f = frames["SYNTH"]
    for i in range(121, len(f)):
        f.loc[i, ["open", "high", "low", "close", "atr", "adx14", "hi20"]] = (
            110., 111., 104., 110., 1., 35., 1000.)
        f.loc[i, "regime"] = "PANIC_DISPERSION"
    f.loc[121, ["open", "high", "low", "close"]] = [100., 102., 90., 100.]
    f.loc[122, ["open", "high", "low", "close", "regime"]] = [100., 104., 100., 103., veto]
    f.loc[123, ["open", "high", "low", "close"]] = [103., 106., 102., 105.]
    # Entry124: first close adverse, then recovery, with stop untouched.
    f.loc[124, ["open", "high", "low", "close"]] = [105., 106., 102., 103.]
    f.loc[125, ["open", "high", "low", "close"]] = [103., 108., 102., 107.]
    return frames, costs, windows


def mirrored_short(veto="COMPRESSION"):
    """Reflect the invented path and every directional feature, not just side."""
    frames, costs, windows = continuation(veto)
    f = frames["SYNTH"]
    before = f.copy(deep=True)
    for field in ("open", "close", "g20"):
        f[field] = 200. - before[field]
    for field in (key for key in f if key.startswith("g") and key[1:].isdigit() and key != "g20"):
        f[field] = 200. - before[field]
    f["high"], f["low"] = 200. - before["low"], 200. - before["high"]
    f["hi20"], f["lo20"] = 200. - before["lo20"], 200. - before["hi20"]
    return frames, costs, windows


class StateLifetimeTests(unittest.TestCase):
    def pair(self, fixture=None):
        native, source = synthetic_successor()
        candidate = a.build(native, source_text=source, enabled=True)
        inputs = fixture or continuation()
        before = deepcopy(inputs)
        control = native(*inputs)
        changed = candidate(*inputs)
        for key in inputs[0]:
            self.assertTrue(inputs[0][key].equals(before[0][key]))
        self.assertEqual(inputs[1:], before[1:])
        return control, changed

    def test_disabled_is_same_callable_and_full_native_parity(self):
        native, source = synthetic_successor()
        disabled = a.build(native, source_text=source)
        self.assertIs(disabled, native)
        self.assertEqual(disabled(*synthetic_frames()), native(*synthetic_frames()))

    def test_known_veto_is_reachable_without_fresh_touch_and_can_remove_winner(self):
        control, changed = self.pair()
        self.assertEqual(len(control["trades"]), 1)
        trade = control["trades"][0]
        self.assertEqual(trade["signal_ts_ms"], 124 * TF)
        self.assertGreater(trade["net_bps"], 0)
        self.assertEqual(changed["trades"], [])
        self.assertEqual(changed["unresolved"], [])
        # Intentionally demonstrate a cost of expiry, not an improvement claim.

    def test_all_four_known_context_classes_expire(self):
        for regime in sorted(a.KNOWN_INELIGIBLE):
            with self.subTest(regime=regime):
                control, changed = self.pair(continuation(regime))
                self.assertTrue(control["trades"])
                self.assertEqual(changed["trades"], [])

    def test_short_known_veto_expiry_has_real_native_mirrored_entry_and_risk(self):
        control, changed = self.pair(mirrored_short())
        self.assertEqual(len(control["trades"]), 1)
        trade = control["trades"][0]
        self.assertEqual(trade["side"], -1)
        self.assertEqual(trade["signal_ts_ms"], 124 * TF)
        self.assertEqual(trade["signal"]["invalidation_price"], 110.)
        self.assertGreater(trade["signal"]["stop_price"], trade["entry_prices"]["SYNTH"])
        self.assertGreater(trade["net_bps"], 0)
        self.assertEqual(changed["trades"], [])

    def test_short_known_eligible_and_unbound_preserve_native_full_output(self):
        for regime in ("PANIC_DISPERSION", "TREND_DISPERSED", "UNBOUND"):
            with self.subTest(regime=regime):
                control, changed = self.pair(mirrored_short(regime))
                self.assertEqual(changed, control)
                self.assertTrue(changed["trades"])
                self.assertEqual(changed["trades"][0]["side"], -1)

    def test_unbound_and_arbitrary_unknown_are_not_explicit_veto(self):
        for regime in ("UNBOUND", "UNKNOWN", "invented_class"):
            with self.subTest(regime=regime):
                control, changed = self.pair(continuation(regime))
                self.assertEqual(changed, control)

    def test_weak_normal_pullback_does_not_expire(self):
        inputs = continuation()
        inputs[0]["SYNTH"].loc[122, "adx14"] = 27.
        control, changed = self.pair(inputs)
        self.assertTrue(control["trades"])
        self.assertEqual(changed, control)

    def test_normal_strong_pullback_and_wide_risk_winner_preserved(self):
        control, changed = self.pair(continuation("PANIC_DISPERSION"))
        self.assertEqual(changed, control)
        trade = changed["trades"][0]
        self.assertGreater(trade["net_bps"], 0)
        self.assertEqual(trade["signal"]["invalidation_price"], 90.)
        self.assertEqual(trade["signal"]["meta"]["atr_price"], 1.)
        self.assertGreater(trade["entry_prices"]["SYNTH"] - trade["signal"]["stop_price"], 10.)

    def test_existing_weak_reset_still_requires_new_touch(self):
        inputs = continuation("PANIC_DISPERSION")
        f = inputs[0]["SYNTH"]
        f.loc[122, "adx14"] = 24.
        control, changed = self.pair(inputs)
        self.assertEqual(control, changed)
        self.assertEqual(changed["trades"], [])

    def test_explicit_rejection_reset_and_later_acceptance_still_native(self):
        inputs = synthetic_frames()
        control, changed = self.pair(inputs)
        self.assertEqual(control["rejections"], {"ENTRY_ATR_COST_GATE": 1})
        self.assertEqual(changed["rejections"], {})
        self.assertEqual(changed["trades"], control["trades"])
        self.assertEqual([t["signal_ts_ms"] for t in changed["trades"]], [126 * TF, 130 * TF])

    def test_later_fresh_touch_can_accept_with_new_native_extreme(self):
        inputs = continuation()
        f = inputs[0]["SYNTH"]
        f.loc[124, ["low", "high", "close"]] = [96., 106., 103.]
        f.loc[125, ["high", "close"]] = [108., 107.]
        _, changed = self.pair(inputs)
        self.assertEqual(changed["trades"][0]["signal_ts_ms"], 126 * TF)
        self.assertEqual(changed["trades"][0]["signal"]["invalidation_price"], 96.)

    def test_same_available_timestamp_touch_cannot_rearm(self):
        inputs = continuation()
        f = inputs[0]["SYNTH"]
        # Veto122 becomes available124TF; the next bar's touch is simultaneous.
        f.loc[122, ["available_ts_ms", "feature_available_ts_ms"]] = [124 * TF, 124 * TF]
        f.loc[123, "low"] = 96.
        f.loc[124, ["high", "close"]] = [109., 108.]
        # No later touch: same-time data must not count as the required renewal.
        _, changed = self.pair(inputs)
        self.assertEqual(changed["trades"], [])

    def test_next_open_gap_and_stop_first_remain_exact(self):
        control, changed = self.pair(synthetic_frames())
        self.assertEqual(changed["trades"], control["trades"])
        self.assertEqual(changed["trades"][1]["entry_prices"]["SYNTH"], 110.)
        self.assertTrue(all(t["reason"] == "STOP_FIRST" for t in changed["trades"]))

    def test_adverse_open_gap_exit_preserved_without_veto(self):
        inputs = continuation("PANIC_DISPERSION")
        f = inputs[0]["SYNTH"]
        f.loc[124, ["open", "high", "low", "close"]] = [80., 85., 75., 80.]
        control, changed = self.pair(inputs)
        self.assertEqual(changed, control)
        self.assertEqual(changed["trades"][0]["reason"], "OPEN_GAP_STOP")
        self.assertEqual(changed["trades"][0]["exit_prices"]["SYNTH"], 80.)

    def test_outcome_symbol_date_labels_not_conditions(self):
        inputs = continuation()
        for field in ("final_mfe", "final_pnl", "outcome_label"):
            inputs[0]["SYNTH"][field] = "unavailable_future_label"
        native, source = synthetic_successor()
        candidate = a.build(native, source_text=source, enabled=True)
        before = candidate(*inputs)
        for field in ("final_mfe", "final_pnl", "outcome_label"):
            inputs[0]["SYNTH"][field] = "changed_future_label"
        self.assertEqual(candidate(*inputs), before)

    def test_source_or_callable_drift_fails_closed(self):
        native, source = synthetic_successor()
        with self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"):
            a.build(native, source_text=source + "\n", enabled=True)
        with self.assertRaisesRegex(ValueError, "NOT_THE_PINNED"):
            a.build(lambda: None, source_text=source, enabled=True)

    def test_candidate_refuses_control_only_observer(self):
        native, source = synthetic_successor()
        candidate = a.build(native, source_text=source, enabled=True)
        with self.assertRaisesRegex(ValueError, "SEPARATE_INCUMBENT_ORIGIN_TRACE"):
            candidate(*continuation(), benchmark_observations=[])

    def test_build_preserves_incumbent_globals_and_execution_wrapper(self):
        native, source = synthetic_successor()
        before = dict(native.__globals__)
        candidate = a.build(native, source_text=source, enabled=True)
        self.assertEqual(native.__globals__, before)
        self.assertIs(candidate.__globals__["execution"], native.__globals__["execution"])
        self.assertIs(candidate.__globals__["positive"], native.__globals__["positive"])
        self.assertEqual(candidate.candidate_identity, a.IDENTITY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
