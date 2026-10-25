"""Evidence integrity, causal execution and literal source-pinned parameters."""

from __future__ import annotations
import json
import gzip
import hashlib
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import screen


class SourceAndNativeCostProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(__file__).resolve().parent
        cls.freeze = json.loads((cls.base / "FREEZE.json").read_text())
        cls.result = json.loads((cls.base / "RESULT.json").read_text())
        cls.census = json.loads((cls.base / "SOURCE_CENSUS.json").read_text())
        cls.trades = json.loads(
            gzip.decompress((cls.base / "TRADES.json.gz").read_bytes())
        )

    def test_upstream_copied_three_exact_sources(self):
        import zipfile

        with zipfile.ZipFile(self.base / "UPSTREAM_GPL3_ORIGINALS.zip") as originals:
            for name, pin in self.freeze["original_source_pins"].items():
                self.assertEqual(
                    hashlib.sha256(originals.read(name)).hexdigest(),
                    pin["sha256"],
                )
            self.assertEqual(
                hashlib.sha256(originals.read("LICENSE")).hexdigest(),
                self.freeze["license_sha256"],
            )
        self.assertEqual(self.freeze["license"], "GPL-3.0")

    def test_single_bound_60day_source(self):
        for sym in self.freeze["symbols"]:
            self.assertEqual(self.census["days_by_symbol"][sym], 60)
            self.assertEqual(self.census["missing_dates_by_symbol"][sym], [])
            self.assertEqual(self.census["integrity_failure_days"][sym], [])
        self.assertEqual(len(self.freeze["symbols"]), 6)

    def test_immutable_freeze_digest(self):
        self.assertEqual(
            hashlib.sha256((self.base / "FREEZE.json").read_bytes()).hexdigest(),
            self.result["freeze_sha256"],
        )

    def test_exact_published_roi_timeframes_and_stops(self):
        c = self.freeze["strategies"]
        self.assertEqual(c["BbandRsi"]["roi_schedule_minutes"], {"0": 0.1})
        self.assertEqual(c["BbandRsi"]["stoploss"], -0.25)
        self.assertEqual(c["ClucMay72018"]["roi_schedule_minutes"], {"0": 0.01})
        self.assertEqual(c["ClucMay72018"]["stoploss"], -0.05)
        self.assertEqual(
            c["MACDStrategy_crossed"]["roi_schedule_minutes"],
            {"0": 0.05, "20": 0.04, "30": 0.03, "60": 0.01},
        )
        self.assertEqual(c["MACDStrategy_crossed"]["stoploss"], -0.3)

    def test_close_signal_delayed_to_next_actual_open(self):
        for name, rows in self.trades.items():
            interval = 3_600_000 if name == "BbandRsi" else 300_000
            for t in rows:
                self.assertGreaterEqual(t["entry_ts"], t["signal_ts"] + interval)
                self.assertGreaterEqual(t["exit_ts"], t["entry_ts"])
                self.assertAlmostEqual(t["net20_bps"], t["gross_bps"] - 20, places=8)
                self.assertAlmostEqual(t["net40_bps"], t["gross_bps"] - 40, places=8)

    def test_no_simultaneous_same_symbol_positions_in_one_strategy(self):
        for name, rows in self.trades.items():
            by_symbol = {}
            for t in rows:
                by_symbol.setdefault(t["symbol"], []).append(t)
            for sym, subset in by_symbol.items():
                ordered = sorted(subset, key=lambda x: x["entry_ts"])
                for prev, cur in zip(ordered, ordered[1:]):
                    self.assertGreaterEqual(
                        cur["entry_ts"], prev["exit_ts"], (name, sym)
                    )

    def test_source_signal_uses_last_completed_candle(self):
        n = 220
        base = np.full(n, 100.0)
        frame = pd.DataFrame(
            {
                "timestamp_ms": np.arange(n, dtype=np.int64) * 300000,
                "open": base,
                "high": base + 1,
                "low": base - 1,
                "close": base,
                "volume": np.ones(n),
            }
        )
        for name in ("BbandRsi", "ClucMay72018", "MACDStrategy_crossed"):
            signal, sell = screen.signals(frame, name)
            self.assertFalse(signal[:200].any())
            self.assertFalse(sell[:200].any())

    def test_conservative_stop_wins_when_both_stop_and_tp_touch(self):
        n = 220
        frame = pd.DataFrame(
            {
                "timestamp_ms": np.arange(n, dtype=np.int64) * 300000,
                "open": np.ones(n) * 100,
                "high": np.ones(n) * 100,
                "low": np.ones(n) * 100,
                "close": np.ones(n) * 100,
                "volume": np.ones(n),
            }
        )
        frame.loc[201, "open"] = 100.0
        frame.loc[201, "high"] = 103.0
        frame.loc[201, "low"] = 93.0
        original = screen.signals
        try:

            def toy(data, name):
                a = np.zeros(n, dtype=bool)
                e = np.zeros(n, dtype=bool)
                a[200] = True
                return a, e

            screen.signals = toy
            rows, _ = screen.simulate(
                frame,
                "BTC-USDT",
                "ClucMay72018",
                {
                    "timeframe": "5m",
                    "roi_schedule_minutes": {"0": 0.01},
                    "stoploss": -0.05,
                },
            )
        finally:
            screen.signals = original
        self.assertTrue(rows)
        self.assertEqual(rows[0]["reason"], "STOP_INTRABAR_FIRST")
        self.assertAlmostEqual(rows[0]["gross_bps"], -500.0)

    def test_no_account_nav_or_production_credit(self):
        self.assertFalse(self.result["account_NAV_return"])
        self.assertFalse(self.result["funding_actual"])
        self.assertFalse(self.result["not_unseen_OOS"] is False)
        self.assertEqual(self.result["orders"], 0)


if __name__ == "__main__":
    unittest.main()
