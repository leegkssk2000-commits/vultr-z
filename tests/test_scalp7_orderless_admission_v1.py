"""Synthetic delayed-admission counterexamples; no quotes, HTTP, or replay."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

from ops import scalp7_orderless_shadow_v1 as runtime
from ops import scalp7_orderless_signals_v1 as signals

TF = runtime.TF
DAY = 86_400_000
BASE = 100 * DAY
SYMBOL = "BTC-USDT"
VERSION = signals.KELTNER_SUCCESSOR


def settings():
    fit = dict(train_start_ms=0, train_end_ms=90 * DAY,
               last_fit_observation_ms=90 * DAY - 3_600_000,
               train_rows=2160, training_feature_sha256="a" * 64,
               disp_q67=.01, meanabs_q85=.03, vol_q25=.8, vol_q67=1.1)
    fit["sha256"] = runtime.digest(fit)
    return dict(costs={SYMBOL: 14.}, fit=fit,
                clock=dict(max_quote_request_ms=5000, max_pair_skew_ms=5000,
                           max_quote_gap_ms=90_000), sources=[],
                nav=None, capital=None, leverage=None,
                cost_assumption="SYNTHETIC_RESERVE_ONLY")


def candles(n):
    rows = []
    fit = settings()["fit"]
    for i in range(n):
        close = 100 + i * .1 + (2 if i >= 122 else 0)
        rows.append(dict(open_ts_ms=BASE + i * TF,
            close_ts_ms=BASE + (i + 1) * TF,
            available_ts_ms=BASE + (i + 1) * TF,
            segment_id="fixture", open=close, high=close + .5,
            low=close - 1, close=close, regime="PANIC_DISPERSION",
            regime_available_ts_ms=BASE + (i + 1) * TF,
            regime_fit_end_ts_ms=fit["last_fit_observation_ms"],
            regime_spec_sha256=fit["sha256"]))
    return pd.DataFrame(rows)


def enriched(frame):
    """Only numeric features are artificial; native HG transitions stay real."""
    result = frame.copy()
    for i, n in enumerate(signals.positive.LONG_GMMA):
        result[f"g{n}"] = result.close - i * .1
    result["g20"] = result.close - .05
    result["g8"], result["g21"], result["g34"] = (
        result.close + 2, result.close + 1, result.close)
    result["atr"], result["atr20"], result["adx14"] = 2., 2., 35.
    result["hi20"], result["lo20"] = 10000., 1.
    result["feature_available_ts_ms"] = result.available_ts_ms
    result["squeeze_on"], result["momentum"] = False, 1.
    return [result]


class DelayedAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "out"
        self.source = Path(self.tmp.name) / "source"
        for item in (
            patch.object(runtime, "existing_settings", side_effect=settings),
            patch.object(runtime.time, "time", return_value=(BASE - 1) / 1000),
            patch.object(signals, "bind_causal_context", side_effect=lambda x, _: x),
            patch.object(signals.positive, "enriched_segments", side_effect=enriched),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.shadow = self.make()

    def make(self):
        value = runtime.Shadow(self.out, self.source, fixture=True)
        self.addCleanup(value.close)
        return value

    def advance(self, n, shadow=None):
        frame = candles(n)
        (shadow or self.shadow).advance({SYMBOL: frame},
            now=int(frame.iloc[-1].close_ts_ms) + 100, quotes={},
            witness={"fixture": True})

    def pending_setup(self):
        self.advance(122)
        self.advance(123)
        account = self.shadow.state["accounts"][VERSION]
        self.assertEqual(len(account["pending"]), 1)
        self.assertFalse(account["positions"] or account["trades"])

    def test_new_closed_bar_resolves_old_pending_without_double_hg_call(self):
        self.pending_setup()
        key = signals._state_key(VERSION, SYMBOL)
        prior = deepcopy(self.shadow.state["signals"][key])
        self.advance(124)
        account = self.shadow.state["accounts"][VERSION]
        current = self.shadow.state["signals"][key]
        self.assertFalse(account["pending"] or account["positions"] or account["trades"])
        self.assertIsNone(current["pending_ts_ms"])
        self.assertEqual(current["native_calls"], prior["native_calls"])
        self.assertEqual(current["last_open_ts_ms"], prior["last_open_ts_ms"])
        events = [row for row in account["events"]
                  if row["kind"] == "ENTRY_SUPERSEDED_BY_OBSERVED_DECISION_BAR"]
        self.assertEqual(len(events), 1)

        self.advance(124)
        current = self.shadow.state["signals"][key]
        self.assertEqual(current["native_calls"], prior["native_calls"] + 1)
        self.assertEqual(current["last_open_ts_ms"], BASE + 123 * TF)
        self.assertEqual(current["hg"]["stage"], 1)
        before = deepcopy(self.shadow.state)
        self.advance(124)
        self.assertEqual(self.shadow.state, before)

    def test_missing_bar_cannot_be_converted_to_admission_rejection(self):
        self.pending_setup()
        pending = deepcopy(self.shadow.state["accounts"][VERSION]["pending"])
        self.advance(125)
        account = self.shadow.state["accounts"][VERSION]
        self.assertEqual(account["pending"], pending)
        self.assertFalse(account["positions"] or account["trades"])
        self.assertFalse(any(row["kind"] == "ENTRY_SUPERSEDED_BY_OBSERVED_DECISION_BAR"
                             for row in account["events"]))
        key = signals._state_key(VERSION, SYMBOL)
        self.assertEqual(self.shadow.state["signals"][key]["halted"], "MISSING_OR_REORDERED_BAR")

    def test_restart_retains_delayed_admission_and_matches_uninterrupted_state(self):
        self.pending_setup()
        before = deepcopy(self.shadow.state)
        self.advance(124)
        expected = deepcopy(self.shadow.state)
        self.shadow.state = before
        self.shadow.save()
        self.shadow.close()
        restored = self.make()
        self.advance(124, restored)
        self.assertEqual(restored.state, expected)
        self.assertEqual(restored.report()["order_calls"], 0)


if __name__ == "__main__":
    unittest.main()
