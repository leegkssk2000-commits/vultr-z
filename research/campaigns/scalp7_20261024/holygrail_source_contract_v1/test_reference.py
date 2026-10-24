"""Deterministic synthetic counterexamples only. No archived prices are loaded."""
import copy
import json
from pathlib import Path
import unittest

from reference import costs, fixture_run, indicators, run


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.f = json.loads(Path(__file__).with_name("fixtures.json").read_text())

    def go(self, bars=None, ema=None, adx=None):
        return fixture_run(self.f["bars"] if bars is None else bars, self.f["tick"],
                           self.f["ema20"] if ema is None else ema,
                           self.f["adx14"] if adx is None else adx)

    def test_author_initial_adx_does_not_reject_falling_pullback_adx(self):
        result = self.go()
        self.assertEqual(len(result["trades"]), 1)
        row = result["trades"][0]
        for key, value in self.f["expected"].items():
            self.assertEqual(row[key], value, key)
        self.assertLess(self.f["adx14"][row["touch_index"]], 30)

    def test_adx_exact_threshold_is_not_strong(self):
        self.assertFalse(self.go(adx=[29, 30, 30, 29, 28, 27, 26])["events"])

    def test_adx_flat_above_threshold_does_not_arm(self):
        self.assertFalse(self.go(adx=[35] * 7)["events"])

    def test_ema_downtrend_does_not_arm(self):
        self.assertFalse(self.go(ema=[110, 109, 108, 107, 106, 105, 104])["events"])

    def test_low_at_ema_cannot_arm_and_touch_same_bar(self):
        b = copy.deepcopy(self.f["bars"])
        b[1]["low"] = 105
        r = self.go(b, adx=[29, 32, 31, 30, 29, 28, 27])
        self.assertFalse(r["events"])

    def test_first_invalid_touch_is_consumed_not_retried(self):
        b = copy.deepcopy(self.f["bars"])
        b[3]["low"] = 107
        r = self.go(b)
        invalid = [e for e in r["events"] if e["kind"] == "INVALID_CONSUMED"]
        self.assertEqual(invalid[0]["bar_index"], 3)
        self.assertFalse(r["trades"])
        self.assertFalse(any(e["kind"] == "FIRST_TOUCH" for e in r["events"]))

    def test_nonpositive_stop_is_invalid_consumed(self):
        b = copy.deepcopy(self.f["bars"])
        # Preserve valid positive OHLC while a one-tick stop would reach zero.
        b[4]["low"] = 1
        r = self.go(b)
        self.assertFalse(r["trades"])
        invalid = next(e for e in r["events"] if e["kind"] == "INVALID_CONSUMED")
        self.assertEqual(invalid["stop"], 0)

    def test_trigger_uses_bar_before_touch_not_touch_high(self):
        r = self.go()
        touch = next(e for e in r["events"] if e["kind"] == "FIRST_TOUCH")
        self.assertEqual(touch["trigger"], 119)
        self.assertNotEqual(touch["trigger"], self.f["bars"][4]["high"] + 1)

    def test_touch_bar_cannot_fill_order(self):
        b = copy.deepcopy(self.f["bars"])
        b[4]["high"] = 130
        b[5].update(open=114, high=118, low=110, close=116)
        r = self.go(b)
        self.assertFalse(r["trades"])
        self.assertTrue(any(e["kind"] == "EXPIRED_ONE_ELIGIBLE_BAR" for e in r["events"]))

    def test_entry_gap_receives_adverse_open_price(self):
        b = copy.deepcopy(self.f["bars"])
        b[5].update(open=122, high=124, low=110, close=123)
        r = self.go(b)
        self.assertEqual(r["trades"][0]["entry_price"], 122)

    def test_gap_past_target_skips_and_never_fills(self):
        b = copy.deepcopy(self.f["bars"])
        b[5].update(open=126, high=128, low=120, close=127)
        r = self.go(b)
        self.assertFalse(r["trades"])
        self.assertTrue(any(e["kind"] == "SKIP_GAP_BEYOND_TARGET" for e in r["events"]))

    def test_gap_below_stop_cancels_before_later_trigger(self):
        b = copy.deepcopy(self.f["bars"])
        b[5].update(open=105, high=126, low=104, close=122)
        r = self.go(b)
        self.assertFalse(r["trades"])
        self.assertTrue(any(e["kind"] == "CANCEL_GAP_BELOW_STOP" for e in r["events"]))

    def test_entry_bar_stop_target_collision_is_stop_first(self):
        b = copy.deepcopy(self.f["bars"])
        b[5].update(open=118, high=126, low=105, close=120)
        r = self.go(b)
        self.assertEqual(r["trades"][0]["exit_price"], 106)
        self.assertEqual(r["trades"][0]["exit_reason"], "ENTRY_BAR_STOP")

    def test_intrabar_entry_target_is_deferred(self):
        b = copy.deepcopy(self.f["bars"])
        b[5].update(open=118, high=126, low=110, close=124)
        b[6].update(open=122, high=124, low=110, close=123)
        r = self.go(b)
        self.assertFalse(r["trades"])
        self.assertEqual(r["ambiguous_entry_targets"], 1)
        self.assertEqual(r["censored"][0]["kind"], "OPEN_POSITION")
        self.assertNotIn("net1_bp", r["censored"][0])

    def test_entry_at_open_can_reach_target_same_bar(self):
        b = copy.deepcopy(self.f["bars"])
        b[5].update(open=120, high=126, low=110, close=124)
        row = self.go(b)["trades"][0]
        self.assertEqual(row["exit_index"], 5)
        self.assertEqual(row["exit_reason"], "ENTRY_AT_OPEN_TARGET")

    def test_existing_position_adverse_gap_stop(self):
        b = copy.deepcopy(self.f["bars"])
        b[6].update(open=103, high=126, low=102, close=104)
        row = self.go(b)["trades"][0]
        self.assertEqual(row["exit_price"], 103)
        self.assertEqual(row["exit_reason"], "GAP_STOP")

    def test_existing_position_collision_stop_before_target(self):
        b = copy.deepcopy(self.f["bars"])
        b[6].update(open=120, high=126, low=105, close=124)
        self.assertEqual(self.go(b)["trades"][0]["exit_price"], 106)

    def test_existing_position_target_at_open_precedes_later_stop(self):
        b = copy.deepcopy(self.f["bars"])
        b[6].update(open=127, high=129, low=105, close=110)
        row = self.go(b)["trades"][0]
        self.assertEqual(row["exit_price"], 125)
        self.assertEqual(row["exit_reason"], "GAP_TARGET")

    def test_expired_pending_never_enters_on_second_bar(self):
        b = copy.deepcopy(self.f["bars"])
        b[5].update(open=116, high=118, low=110, close=117)
        self.assertFalse(self.go(b)["trades"])

    def test_completed_trade_cannot_rearm_on_same_bar(self):
        adx = [29, 32, 40, 38, 36, 34, 35]
        r = self.go(adx=adx)
        self.assertEqual(sum(e["kind"] == "ARM" for e in r["events"]), 1)
        self.assertEqual(r["state"], "RESET_WAIT")

    def test_reset_must_be_observed_after_consumption(self):
        b = copy.deepcopy(self.f["bars"])
        b.extend([dict(open=122, high=128, low=119, close=125),
                  dict(open=124, high=130, low=120, close=127)])
        ema = self.f["ema20"] + [111, 112]
        r = self.go(b, ema, self.f["adx14"] + [29, 33])
        self.assertEqual([e["bar_index"] for e in r["events"] if e["kind"] == "RESET"], [7])
        self.assertEqual([e["bar_index"] for e in r["events"] if e["kind"] == "ARM"], [1, 8])

    def test_delayed_receipt_does_not_use_unavailable_next_open(self):
        b = copy.deepcopy(self.f["bars"])
        for i, row in enumerate(b):
            row.update(timestamp_ms=i*3600000, available_at_ms=(i+1)*3600000+1000)
        b[6].update(open=120, high=124, low=110, close=123)
        r = self.go(b)
        self.assertEqual([e["bar_index"] for e in r["events"] if e["kind"] == "ENTRY"], [6])
        self.assertTrue(any(e["kind"] == "WAIT_AVAILABILITY" and e["bar_index"] == 5 for e in r["events"]))

    def test_pending_without_eligible_future_open_is_censored(self):
        b = copy.deepcopy(self.f["bars"][:5])
        r = self.go(b, self.f["ema20"][:5], self.f["adx14"][:5])
        self.assertEqual(r["censored"][0]["kind"], "PENDING_NOT_YET_ELIGIBLE")
        self.assertFalse(r["trades"])

    def test_prefix_invariance_events_and_indicators(self):
        full = self.go()
        for n in range(1, len(self.f["bars"])+1):
            r = self.go(self.f["bars"][:n], self.f["ema20"][:n], self.f["adx14"][:n])
            self.assertEqual(r["events"], [x for x in full["events"] if x["bar_index"] < n])
        bars = [dict(open=100+i, high=101+i, low=99+i, close=100+i) for i in range(50)]
        full_ind = indicators(bars)
        for n in (14, 20, 27, 28, 31, 45):
            got = indicators(bars[:n])
            self.assertEqual(got, {k: v[:n] for k, v in full_ind.items()})

    def test_indicator_seeding_hand_calculated_ramp(self):
        bars = [dict(open=100+i, high=101+i, low=99+i, close=100+i) for i in range(50)]
        r = indicators(bars)
        self.assertEqual(r["ema20"][19], 109.5)
        self.assertEqual(r["ema20"][20], 110.5)
        self.assertIsNone(r["adx14"][26])
        self.assertEqual(r["adx14"][27:], [100.0] * 23)

    def test_flat_series_zero_direction_denominator(self):
        bars = [dict(open=100, high=100, low=100, close=100) for _ in range(40)]
        r = indicators(bars)
        self.assertEqual(r["adx14"][27:], [0.0] * 13)

    def test_directional_movement_ties_cancel_both(self):
        bars = [dict(open=100, high=101+i, low=99-i, close=100) for i in range(40)]
        self.assertEqual(indicators(bars)["adx14"][27:], [0.0] * 13)

    def test_native_warmup240_is_fixed(self):
        bars = [dict(open=100+i, high=101+i, low=99+i, close=100+i) for i in range(245)]
        # A monotone ADX is flat: native high ADX alone must never arm.
        self.assertFalse(run(bars, 0.01)["events"])
        r = fixture_run(self.f["bars"], 1, self.f["ema20"], self.f["adx14"], warmup=240)
        self.assertFalse(r["events"])

    def test_cost_one_and_two_no_double_deduction(self):
        for value in (-300.0, 0.0, 17.5, 200.0):
            c = costs(value)
            self.assertEqual(c["gross_bp"] - c["net1_bp"], 20.0)
            self.assertEqual(c["gross_bp"] - c["net2_bp"], 40.0)
            self.assertEqual(c["net1_bp"] - c["net2_bp"], 20.0)

    def test_nonfinite_and_invalid_input_fail_closed(self):
        for key, value in (("close", float("nan")), ("open", float("inf")), ("low", -1)):
            b = copy.deepcopy(self.f["bars"])
            b[2][key] = value
            with self.assertRaises(ValueError):
                self.go(b)
        with self.assertRaises(ValueError):
            fixture_run(self.f["bars"], 0, self.f["ema20"], self.f["adx14"])
        with self.assertRaises(ValueError):
            self.go(adx=[29, 32, float("nan"), 38, 28, 27, 26])

    def test_timestamp_before_close_rejected(self):
        b = copy.deepcopy(self.f["bars"])
        for i, row in enumerate(b):
            row.update(timestamp_ms=i*3600000, available_at_ms=(i+1)*3600000)
        b[4]["available_at_ms"] -= 1
        with self.assertRaises(ValueError):
            self.go(b)

    def test_prior_indicator_input_cannot_arrive_after_touch(self):
        b = copy.deepcopy(self.f["bars"])
        for i, row in enumerate(b):
            row.update(timestamp_ms=i*3600000, available_at_ms=(i+1)*3600000)
        b[3]["available_at_ms"] = b[4]["available_at_ms"] + 1
        with self.assertRaisesRegex(ValueError, "out-of-order availability"):
            self.go(b)


if __name__ == "__main__":
    unittest.main()
