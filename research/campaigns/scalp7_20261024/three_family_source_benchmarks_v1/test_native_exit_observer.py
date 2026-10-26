"""Synthetic native conditions and clock/resume tests; no economic replay."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

import benchmark as native
import forward_signal_only as producer
import native_exit_observer as observer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def track(rule=native.TREND, **changes):
    return {"rule_id": rule, "symbol": "BTC-USDT", "entry_ask_price": 100.0,
            "initial_risk_price": 10.0, "base_stop_price": 90.0,
            "entry_quote_ts_ms": 1, "quote_read_at_ms": 2,
            "last_quote_ts_ms": 1, "last_quote_read_at_ms": 2,
            "best_observed_R": 0.0, "signal_close_ts_ms": 0, **changes}


def event(rule=native.TREND, opening=0, **price):
    interval = observer.HALF if rule == observer.K117 else observer.FOUR
    bar = {"open_ts_ms": opening, "close_ts_ms": opening + interval,
           "available_ts_ms": opening + interval + 1,
           "open": 100.0, "high": 103.0, "low": 99.0, "close": 101.0,
           **price}
    result = {"rule_id": rule, "symbol": "BTC-USDT",
              "decision_ts_ms": opening + interval + 2,
              "native_exit_input": {"bar": bar, "source_bar_sha256": observer.digest(bar)},
              "native_exit_on_close": False}
    if rule != observer.K117:
        result["native_safety_max_hold_bars"] = native.safety(rule)[1]
    return result


def evaluate(t, e, **extra):
    return observer.evaluate_native_exit(t, e, decision_ms=e["decision_ts_ms"] + 1, **extra)


class NativeExitTests(unittest.TestCase):
    def test_partial_entry_bar_without_trigger_continues(self):
        result = evaluate(track(), event())
        self.assertIsNone(result["censor_reason"])
        self.assertIsNone(result["exit_event"])
        self.assertEqual(result["state"]["hold_bars"], 1)
        self.assertTrue(result["state"]["partial_entry_bar"])

    def test_exit_event_has_actual_later_clock_and_no_fill(self):
        e = event()
        e["native_exit_on_close"] = True
        result = evaluate(track(), e)
        notice = result["exit_event"]
        self.assertEqual(notice["reason"], "GMMA_EMA15_BELOW_EMA30_NEXT_OPEN")
        self.assertGreater(notice["decision_ts_ms"], e["decision_ts_ms"])
        self.assertTrue(notice["requires_strictly_later_observed_bid"])
        self.assertFalse(notice["native_next_open_fill_verified"])
        self.assertNotIn("exit_price", notice)

    def test_tsmom_uses_native_predicate_and_native_bar_count(self):
        e = event(native.MOM)
        e["native_exit_on_close"] = True
        self.assertEqual(evaluate(track(native.MOM), e)["exit_event"]["reason"],
                         "TSMOM_NEGATIVE_SCORE_NEXT_OPEN")
        for rule, cap in ((native.MOM, 24), (native.TREND, 48)):
            e = event(rule, (cap - 1) * observer.FOUR)
            t = track(rule, native_exit_state={"last_close_ts_ms": (cap - 1) * observer.FOUR})
            self.assertEqual(evaluate(t, e)["exit_event"]["reason"], "MAX_HOLD_NEXT_OPEN")

    def test_duplicate_is_idempotent_and_inputs_not_mutated(self):
        t, e = track(), event()
        before = json.dumps([t, e], sort_keys=True)
        result = evaluate(t, e)
        self.assertEqual(json.dumps([t, e], sort_keys=True), before)
        repeat = evaluate({**t, "native_exit_state": result["state"]}, e)
        self.assertEqual(repeat["state"], result["state"])
        self.assertIsNone(repeat["exit_event"])

    def test_source_gap_and_digest_mutation_censor(self):
        self.assertEqual(evaluate(track(), event(opening=observer.FOUR))["censor_reason"],
                         "NATIVE_COMPLETED_BAR_SOURCE_GAP")
        e = event()
        e["native_exit_input"]["bar"]["close"] = 102
        self.assertEqual(evaluate(track(), e)["censor_reason"], "NATIVE_BAR_DIGEST_MISMATCH")

    def test_actual_quote_read_not_bucket_end_controls_partial_bar(self):
        t = track(entry_quote_ts_ms=0, quote_read_at_ms=20)
        result = evaluate(t, event(low=89.0))
        self.assertEqual(result["censor_reason"], "ENTRY_BAR_STOP_PATH_AMBIGUOUS")
        self.assertIsNone(result["exit_event"])

    def test_current_native_stop_not_initial_stop_is_used(self):
        t = track(native_active_stop_price=100.0)
        self.assertEqual(evaluate(t, event(low=99.0))["censor_reason"],
                         "ENTRY_BAR_STOP_PATH_AMBIGUOUS")

    def test_postentry_fullbar_stop_has_no_ohlc_fill_credit(self):
        t = track(quote_read_at_ms=0, entry_quote_ts_ms=0)
        result = evaluate(t, event(low=89.0))
        self.assertEqual(result["censor_reason"], "NATIVE_BAR_STOP_WITHOUT_QUOTE_PATH")
        self.assertIsNone(result["exit_event"])

    def test_future_source_and_backdated_helper_are_rejected(self):
        e = event()
        e["decision_ts_ms"] -= 2
        self.assertEqual(evaluate(track(), e)["censor_reason"], "NATIVE_COMPLETED_BAR_CLOCK_INVALID")
        e = event()
        result = observer.evaluate_native_exit(track(), e, decision_ms=e["decision_ts_ms"] - 1)
        self.assertEqual(result["censor_reason"], "NATIVE_HELPER_CLOCK_BEFORE_PRODUCER")


class ProducerExitTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame([{
            "open_ts_ms": i * producer.FOUR, "close_ts_ms": (i + 1) * producer.FOUR,
            "observed_source_last_received_ms": (i + 1) * producer.FOUR + 1,
            "open": 200 - i * .2, "high": 201 - i * .2,
            "low": 199 - i * .2, "close": 200 - i * .2, "volume": 1.0,
        } for i in range(241)])

    def test_all_decisions_have_exact_native_exit_and_absolute_atr_distance(self):
        history = self.history()
        context = native.enrich(history)
        now = int(history.iloc[-1].close_ts_ms) + 10
        with patch.object(producer.time, "time", return_value=now / 1000):
            for rule in producer.FAMILIES:
                e = producer.decision_event(rule, "BTC-USDT", history, context)
                self.assertEqual(e["native_exit_on_close"], native.take_exit_on_close(rule, context.iloc[-1]))
                self.assertEqual(e["native_safety_stop_distance_price"],
                                 float(context.iloc[-1].atr14) * native.safety(rule)[0])
                self.assertEqual(e["decision_ts_ms"], now)
                self.assertEqual(e["context_first_open_ms"], 0)
                self.assertEqual(e["native_exit_input"]["source_bar_sha256"],
                                 observer.digest(e["native_exit_input"]["bar"]))
                self.assertFalse(e["native_next_open_fill_verified"])

    def status(self):
        return {
            "schema": "zel.existing_gmma_tsmom.4h.orderless_forward.v1",
            "source_identity_sha256": producer.IDENTITY_SHA,
            "native_frozen_source_sha256": producer.digest((HERE / "benchmark.py").read_bytes()),
            "native_freeze_sha256": producer.digest((HERE / "FREEZE.json").read_bytes()),
            "orders": 0, "order_calls": 0, "virtual_fills": 0, "formal_shadow": False,
            "action_symbols": list(producer.SYMBOLS), "rule_ids": list(producer.FAMILIES),
            "started_ms": 240 * producer.FOUR + 10,
            "next_expected_bar_close_ms": 242 * producer.FOUR,
            "last_complete_native_4h_close_ms": 241 * producer.FOUR,
            "signals": [{"old": "preserved_not_reissued"}],
        }

    def test_resume_keeps_original_seed_and_cursor_without_mutating_signals(self):
        s = self.status()
        before = json.dumps(s, sort_keys=True)
        self.assertEqual(producer.resume_plan(s, 241 * producer.FOUR + 5),
                         (0, 241 * producer.FOUR, 242 * producer.FOUR))
        self.assertEqual(json.dumps(s, sort_keys=True), before)

    def test_resume_rejects_moved_seed_missed_bar_and_authority_change(self):
        s = self.status()
        for changes, now in (({"context_first_open_ms": producer.FOUR}, 241 * producer.FOUR + 5),
                             ({}, 243 * producer.FOUR),
                             ({"virtual_fills": 1}, 241 * producer.FOUR + 5)):
            with self.assertRaises(RuntimeError):
                producer.resume_plan({**s, **changes}, now)

    def test_frozen_benchmark_source_unchanged(self):
        self.assertEqual(hashlib.sha256((HERE / "benchmark.py").read_bytes()).hexdigest(),
                         "e226b96e694a980ecfaa4050d5b80d3ad8f2d09f2bafbb101d18f8688400d863")


class K117FrozenCallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        relative = Path("research/campaigns/scalp7_20261022/parallel_fastfinish_v1/work_e/k117_adapter.py")
        candidates = [ROOT / relative, ROOT.parent / "k117-event-clock" / relative]
        if os.environ.get("K117_NATIVE_REPO"):
            candidates.append(Path(os.environ["K117_NATIVE_REPO"]) / relative)
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            raise unittest.SkipTest("K117 dedicated frozen adapter checkout not present")
        spec = importlib.util.spec_from_file_location("k117_native_exit_test_dependency", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.deps = module.dependencies()  # Verifies original source pins.

    def position(self, **changes):
        signal = {"side": 1, "symbol": "BTC-USDT", "signal_ts_ms": 0,
                  "invalidation_price": 95.0,
                  "meta": {"be_arm_r": 1.0, "frozen_cost_bps": 40.0}}
        source_bar = {"open_ts_ms": -observer.HALF, "close_ts_ms": 0,
                      "available_ts_ms": 1, "low": 96.0, "high": 102.0}
        return track(observer.K117, native_signal=signal,
                     native_signal_bar=source_bar, **changes)

    def call(self, t, e):
        return evaluate(t, e, k117_dependencies=self.deps)

    def test_partial_entry_without_threshold_trigger_continues(self):
        result = self.call(self.position(), event(observer.K117))
        self.assertIsNone(result["censor_reason"])
        self.assertAlmostEqual(result["state"]["mfe_lower_R"], .1)
        self.assertAlmostEqual(result["state"]["mfe_upper_R"], .3)

    def test_late_signal_receipt_preserved_with_actual_entry_clock(self):
        t = self.position(best_observed_R=2.5, last_quote_read_at_ms=10)
        source_before = dict(t["native_signal_bar"])
        result = self.call(t, event(observer.K117, high=125.0))
        self.assertIsNone(result["censor_reason"])
        self.assertEqual(t["native_signal_bar"], source_before)
        self.assertEqual(t["native_signal_bar"]["available_ts_ms"], 1)
        self.assertTrue(result["partial_event"]["entry_bar_suffix_bound_projection"])
        self.assertEqual(result["partial_event"]["actual_virtual_entry_read_at_ms"], 2)
        t["native_signal_bar"]["available_ts_ms"] = 3
        self.assertEqual(self.call(t, event(observer.K117))["censor_reason"],
                         "K117_SIGNAL_NOT_KNOWN_AT_QUOTE_ENTRY")

    def test_entry_mfe_ambiguity_censors_instead_of_inventing_partial_or_be(self):
        for high in (111.0, 125.0, 135.0):
            result = self.call(self.position(), event(observer.K117, high=high))
            self.assertEqual(result["censor_reason"], "K117_ENTRY_BAR_MFE_OR_PARTIAL_PATH_AMBIGUOUS")
            self.assertIsNone(result["partial_event"])
            self.assertIsNone(result["stop_event"])

    def test_actual_inbar_quote_confirms_partial_without_target_fill(self):
        t = self.position(best_observed_R=2.5, last_quote_read_at_ms=10)
        result = self.call(t, event(observer.K117, high=125.0))
        self.assertIsNone(result["censor_reason"])
        self.assertEqual(result["partial_event"]["partial_fraction"], .1)
        self.assertEqual(result["partial_event"]["reference_native_partial_price"], 120.0)
        self.assertNotIn("fill_price", result["partial_event"])
        self.assertAlmostEqual(result["stop_event"]["next_stop_price"], 100.42)

    def test_later_quote_cannot_confirm_earlier_entry_bar_high(self):
        t = self.position(best_observed_R=2.5, last_quote_read_at_ms=observer.HALF + 10)
        result = self.call(t, event(observer.K117, high=125.0))
        self.assertEqual(result["censor_reason"], "K117_ENTRY_BAR_MFE_OR_PARTIAL_PATH_AMBIGUOUS")

    def test_original_scratch_and_structural_exit_priority(self):
        t = self.position(native_exit_state={"last_close_ts_ms": 4 * observer.HALF})
        result = self.call(t, event(observer.K117, 4 * observer.HALF, close=94.0, low=93.0))
        self.assertEqual(result["exit_event"]["reason"], "HG_FROZEN_5BAR_MFE_SCRATCH")
        first = self.call(self.position(), event(observer.K117, close=94.0, low=93.0))
        self.assertEqual(first["exit_event"]["reason"], "K126_PULLBACK_STRUCTURE_FAILURE_NEXT_OPEN")

    def test_native_25_bar_extension_and_finite_50_bar_cap(self):
        for bars, high, expected in ((25, 115.0, "MAX_HOLD_NEXT_OPEN"),
                                     (25, 125.0, None),
                                     (50, 125.0, "MAX_HOLD_NEXT_OPEN")):
            state = {"last_close_ts_ms": (bars - 1) * observer.HALF, "remaining_intent": .9}
            result = self.call(self.position(native_exit_state=state, remaining_fraction=.9),
                               event(observer.K117, (bars - 1) * observer.HALF, high=high))
            self.assertIsNone(result["censor_reason"])
            self.assertEqual(result["exit_event"]["reason"] if result["exit_event"] else None, expected)

    def test_partial_intent_does_not_mean_actual_bid_execution(self):
        t = self.position(native_exit_state={"last_close_ts_ms": observer.HALF,
                                            "remaining_intent": .9})
        e = event(observer.K117, observer.HALF, high=125.0)
        self.assertEqual(self.call(t, e)["censor_reason"],
                         "K117_NATIVE_PARTIAL_NOT_YET_OBSERVED_AT_BID")
        t["remaining_fraction"] = .9
        result = self.call(t, e)
        self.assertIsNone(result["censor_reason"])
        self.assertIsNone(result["partial_event"])
        t["native_exit_state"]["remaining_intent"] = 1.0
        self.assertEqual(self.call(t, e)["censor_reason"],
                         "K117_NATIVE_PARTIAL_WITHOUT_PRIOR_INTENT")

    def test_native_runner_trail_and_partial_from_exact_callback(self):
        t = self.position(native_exit_state={"last_close_ts_ms": observer.HALF})
        result = self.call(t, event(observer.K117, observer.HALF, high=135.0))
        self.assertEqual(result["stop_event"]["next_stop_price"], 122.5)
        self.assertEqual(result["partial_event"]["partial_fraction"], .1)

    def test_prior_mfe_uncertainty_resolves_when_later_fullbar_dominates(self):
        t = self.position(native_exit_state={"last_close_ts_ms": observer.HALF,
                                            "mfe_lower_R": .1, "mfe_upper_R": .3})
        result = self.call(t, event(observer.K117, observer.HALF, high=105.0))
        self.assertIsNone(result["censor_reason"])
        self.assertEqual(result["state"]["mfe_lower_R"], .5)
        self.assertEqual(result["state"]["mfe_upper_R"], .5)

    def test_pins_and_full_signal_are_required(self):
        self.assertEqual(evaluate(self.position(), event(observer.K117))["censor_reason"],
                         "K117_PIN_VERIFIED_CALLBACK_REQUIRED")
        t = self.position()
        del t["native_signal"]["meta"]
        self.assertIsNotNone(self.call(t, event(observer.K117))["censor_reason"])


if __name__ == "__main__":
    unittest.main()
