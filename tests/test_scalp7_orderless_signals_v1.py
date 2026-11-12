"""Artificial causal/state counterexamples; no market/economic replay."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import pandas as pd

from ops import scalp7_orderless_signals_v1 as adapter

TF = adapter.positive.TIMEFRAME_MS
DAY = adapter.context.DAY
BASE = 100 * DAY
SYMBOL = "BTC-USDT"


def fit():
    value = dict(train_start_ms=0, train_end_ms=90 * DAY,
                 last_fit_observation_ms=90 * DAY - 3_600_000,
                 train_rows=2160, training_feature_sha256="a" * 64,
                 disp_q67=.01, meanabs_q85=.03, vol_q25=.8, vol_q67=1.1)
    value["sha256"] = adapter._digest(value)
    return value


def candles(n=123):
    rows = []
    for i in range(n):
        close = 100 + i * .1 + (2 if i >= 122 else 0)
        rows.append(dict(open_ts_ms=BASE + i * TF,
            close_ts_ms=BASE + (i + 1) * TF,
            available_ts_ms=BASE + (i + 1) * TF,
            segment_id="fixture", open=close, high=close + .5,
            low=close - 1, close=close,
            regime="PANIC_DISPERSION", regime_available_ts_ms=BASE + (i + 1) * TF,
            regime_fit_end_ts_ms=fit()["last_fit_observation_ms"],
            regime_spec_sha256=fit()["sha256"]))
    return pd.DataFrame(rows)


def enriched(frame):
    """Supply indicator fixtures; production native transitions remain real."""
    x = frame.copy()
    for i, n in enumerate(adapter.positive.LONG_GMMA):
        x[f"g{n}"] = x.close - i * .1
    x["g20"] = x.close - .05
    x["g8"], x["g21"], x["g34"] = x.close + 2, x.close + 1, x.close
    x["atr"], x["atr20"], x["adx14"] = 2., 2., 35.
    x["hi20"], x["lo20"] = 10000., 1.
    x["feature_available_ts_ms"] = x.available_ts_ms
    x["squeeze_on"], x["momentum"] = False, 1.
    return [x]


def consume(state, frame, version=None, **kwargs):
    with patch.object(adapter.positive, "enriched_segments", side_effect=enriched):
        return adapter.on_bar(state, version=version or adapter.positive.KELTNER_PARENT,
            symbol=SYMBOL, frame=frame, cost_bps=14.,
            asof_ms=int(frame.iloc[-1].available_ts_ms),
            fit=kwargs.get("fit", fit()))


class IncrementalStateTests(unittest.TestCase):
    def test_parent_native_state_restart_and_duplicate_are_exact(self):
        initial = {}
        self.assertEqual(consume(initial, candles(122))["status"], "NO_SIGNAL")
        restarted = json.loads(json.dumps(initial, allow_nan=False))
        resumed = consume(restarted, candles(123))
        uninterrupted = consume(initial, candles(123))
        self.assertEqual(resumed, uninterrupted)
        self.assertEqual(restarted, initial)
        self.assertEqual(resumed["status"], "SIGNAL")
        before = deepcopy(initial)
        with patch.object(adapter.positive, "_hg_event", wraps=adapter.positive._hg_event) as call:
            duplicate = consume(initial, candles(123))
        self.assertEqual(duplicate["status"], "DUPLICATE")
        self.assertEqual(call.call_count, 0)
        self.assertEqual(initial, before)

    def test_parent_and_child_separate_rejection_requires_new_touch(self):
        state = {}
        for version in (adapter.positive.KELTNER_PARENT, adapter.KELTNER_SUCCESSOR):
            consume(state, candles(122), version)
            result = consume(state, candles(123), version)
            self.assertEqual(result["status"], "SIGNAL")
        adapter.decide_entry(state, version=adapter.KELTNER_SUCCESSOR,
            symbol=SYMBOL, accepted=False, decision_ts_ms=BASE + 123 * TF + 1)
        parent = state[adapter._state_key(adapter.positive.KELTNER_PARENT, SYMBOL)]
        child = state[adapter._state_key(adapter.KELTNER_SUCCESSOR, SYMBOL)]
        self.assertTrue(parent["hg"]["episode_traded"])
        self.assertFalse(child["hg"]["episode_traded"])
        self.assertEqual(child["hg"]["stage"], 0)
        self.assertIsNone(child["hg"]["pull_low"])
        self.assertIsNone(child["hg"]["pull_high"])
        # Native event on the next bar is a fresh touch, never an immediate turn.
        self.assertEqual(consume(state, candles(124), adapter.KELTNER_SUCCESSOR)["status"], "NO_SIGNAL")
        self.assertEqual(child["hg"]["stage"], 0)  # old snapshot was not mutated
        self.assertEqual(state[adapter._state_key(adapter.KELTNER_SUCCESSOR, SYMBOL)]["hg"]["stage"], 1)

    def test_pending_admission_is_not_an_inferred_rejection(self):
        state = {}
        consume(state, candles(122), adapter.KELTNER_SUCCESSOR)
        consume(state, candles(123), adapter.KELTNER_SUCCESSOR)
        before = deepcopy(state)
        result = consume(state, candles(124), adapter.KELTNER_SUCCESSOR)
        self.assertEqual(result["reason"], "UNRESOLVED_PRIOR_ENTRY_DECISION")
        self.assertEqual(result["hg_calls"], 0)
        self.assertEqual(state, before)

    def test_gap_changed_history_incomplete_and_missing_fit_fail_closed(self):
        state = {}
        consume(state, candles(122))
        self.assertEqual(consume(state, candles(124))["reason"], "MISSING_OR_REORDERED_BAR")
        self.assertEqual(consume(state, candles(123))["status"], "UNKNOWN")
        state = {}
        consume(state, candles(122))
        changed = candles(123)
        changed.loc[0, "close"] += .1
        self.assertEqual(consume(state, changed)["reason"], "HISTORY_CHANGED_OR_TRUNCATED")
        state = {}
        self.assertEqual(consume(state, candles(122), fit=None)["reason"], "CONTEXT_FIT_MISSING")
        bar = candles(122)
        bar.loc[0, "available_ts_ms"] = BASE + 1000 * TF
        self.assertEqual(consume({}, bar)["reason"], "UNAVAILABLE_OR_INCOMPLETE_BAR")

    def test_fit_tamper_future_and_squeeze_do_not_call_hg(self):
        altered = fit()
        altered["disp_q67"] = 999
        self.assertEqual(consume({}, candles(122), fit=altered)["reason"], "CONTEXT_FIT_HASH_MISMATCH")
        with self.assertRaisesRegex(ValueError, "NOT_CAUSAL"):
            adapter.verify_fit(fit(), 89 * DAY)
        with patch.object(adapter.positive, "_hg_event", side_effect=AssertionError("HG must not run")):
            result = consume({}, candles(122), adapter.positive.SQUEEZE_PARENT)
        self.assertEqual(result["status"], "NO_SIGNAL")

    def test_child_bootstrap_unknown_never_revives_old_touch(self):
        state = {}
        result = consume(state, candles(123), adapter.KELTNER_SUCCESSOR)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "HISTORICAL_HG_ADMISSION_UNKNOWN_WAIT_NATIVE_RESET")
        self.assertIsNone(result["signal"])

    def test_missing_context_retries_same_bar_before_and_after_restart(self):
        for version in adapter.VERSIONS:
            for initialized in (False, True):
                with self.subTest(version=version, initialized=initialized):
                    state = {}
                    if initialized:
                        consume(state, candles(122), version)
                    before = deepcopy(state)
                    raw = candles(123).drop(columns=[
                        "regime", "regime_available_ts_ms", "regime_fit_end_ts_ms",
                        "regime_spec_sha256"])
                    with patch.object(adapter.positive, "_hg_event",
                                      wraps=adapter.positive._hg_event) as call:
                        held = consume(state, raw, version)
                    self.assertEqual(held["reason"], "CAUSAL_CONTEXT_UNBOUND")
                    self.assertEqual(call.call_count, 0)
                    self.assertEqual(state, before)
                    restarted = json.loads(json.dumps(state, allow_nan=False))
                    recovered = consume(restarted, candles(123), version)
                    direct = consume(before, candles(123), version)
                    self.assertEqual(recovered, direct)
                    self.assertNotEqual(recovered["status"], "DUPLICATE")
                    self.assertEqual(restarted, before)
                    if initialized and version in adapter.VERSIONS[:2]:
                        self.assertEqual(recovered["status"], "SIGNAL")
                    snapshot = deepcopy(restarted)
                    self.assertEqual(consume(restarted, candles(123), version)["status"],
                                     "DUPLICATE")
                    self.assertEqual(restarted, snapshot)

    def test_invalid_fit_and_cost_do_not_consume_native_transition(self):
        altered = fit()
        altered["disp_q67"] = 999
        for bad_fit, cost, reason in (
                (None, 14., "CONTEXT_FIT_MISSING"),
                (altered, 14., "CONTEXT_FIT_HASH_MISMATCH"),
                (fit(), float("nan"), "FROZEN_COST_UNBOUND"),
                (fit(), 0., "FROZEN_COST_UNBOUND")):
            with self.subTest(reason=reason):
                state = {}
                consume(state, candles(122))
                before = deepcopy(state)
                with patch.object(adapter.positive, "enriched_segments", side_effect=enriched), \
                     patch.object(adapter.positive, "_hg_event",
                                  wraps=adapter.positive._hg_event) as call:
                    held = adapter.on_bar(state, version=adapter.positive.KELTNER_PARENT,
                        symbol=SYMBOL, frame=candles(123), cost_bps=cost,
                        asof_ms=BASE + 123 * TF, fit=bad_fit)
                self.assertEqual(held["reason"], reason)
                self.assertEqual(call.call_count, 0)
                self.assertEqual(state, before)
                self.assertEqual(consume(state, candles(123))["status"], "SIGNAL")

    def test_callback_facade_preserves_parent_and_signal_low_priority(self):
        from ops.scalp7_squeeze_signal_low_successor_v1 import BINDING
        frame = candles(123)
        raw = enriched(frame)[0].iloc[-1].to_dict()
        raw["regime"] = "TREND_DISPERSED"
        sig = adapter._squeeze_parent_signal(SYMBOL, raw, "TREND_DISPERSED",
                                             int(raw["available_ts_ms"]), 14.)
        sig = adapter.bind_signal_low(sig, frame)
        sig["identity"] = adapter.SQUEEZE_SUCCESSOR
        mod = adapter.NativeCallbacks(adapter.SQUEEZE_SUCCESSOR)
        self.assertIn("stop_price", mod.entry_update(sig, float(raw["close"])))
        bar = dict(raw)
        bar.update(open_ts_ms=raw["close_ts_ms"], close_ts_ms=raw["close_ts_ms"] + TF,
                   available_ts_ms=raw["close_ts_ms"] + TF,
                   close=sig["meta"][BINDING]["low"] - .5)
        history = pd.concat([frame, pd.DataFrame([bar])], ignore_index=True)
        position = dict(signal=sig, entry_ts_ms=int(raw["close_ts_ms"]),
                        entry_price=raw["close"], initial_risk=4., stop_price=90.,
                        side=1, mfe_R=0., hold_bars=1, remaining=1.)
        before = deepcopy(position)
        update = mod.exit_update(position, bar, history)
        self.assertEqual(update["reason"], "TREND_SIGNAL_BAR_LOW_INVALIDATION_NEXT_OPEN")
        self.assertEqual(position, before)
        self.assertEqual(sig["identity"], adapter.SQUEEZE_SUCCESSOR)


if __name__ == "__main__":
    unittest.main()
