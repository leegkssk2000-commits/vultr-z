"""Synthetic-only smoke tests against the unmodified Freqtrade 2026.7 engine.

No canonical/archive/native economic files are opened. These test prices are
generated analytically and are not benchmark FULL runs.
"""
from pathlib import Path
import json
import tempfile
import unittest

import pandas as pd

from D2Independent import D2Independent
from offline_engine import BAR, external_class, run_frame
from run_benchmark import encoded


HERE = Path(__file__).parent
VENDOR = HERE.parent / "external-checkpoint/vendor/hlhb.py"


def synthetic_frame():
    dates = pd.date_range("2003-01-01", periods=360, freq="4h", tz="UTC")
    close = [100 + j * .08 + (2 if j % 9 == 0 else -2 if j % 9 == 1 else 0)
             for j in range(360)]
    return pd.DataFrame({"date": dates, "open": close, "close": close,
                         "high": [x + 1 for x in close], "low": [x - 1 for x in close],
                         "volume": [100.0] * len(close)})


class RealFreqtradeSmoke(unittest.TestCase):
    def setUp(self):
        self.df = synthetic_frame()
        self.start = int(self.df.date.iloc[0].timestamp() * 1000)
        self.end = self.start + len(self.df) * BAR

    def execute(self, strategy):
        with tempfile.TemporaryDirectory(prefix="zel-synth-ft-") as work:
            bundle = run_frame(strategy, {"SYNTH/USDT": self.df}, self.start, self.end, work)
            result, signals, audit, resolved, config, markets = bundle
            trades = result["results"]
            raw = trades.astype(object).where(trades.notna(), None).to_dict(orient="records")
            persisted = encoded({"trades": raw, "resolved": resolved, "config": config,
                                 "metadata": markets, "audit": audit})
            self.assertEqual(len(json.loads(persisted)["trades"]), len(trades))
            if audit is not None:
                self.assertEqual(audit["callback_errors"], [])
                self.assertEqual(len(audit["entries"]), len(trades))
            return bundle

    def test_d2_callbacks_with_unmodified_engine(self):
        result, signals, audit, resolved, config, markets = self.execute(D2Independent)
        self.assertGreater(sum(signals["SYNTH/USDT"]["enter_long"]), 0)
        self.assertGreater(len(audit["entries"]), 0)
        self.assertGreater(len(audit["exits"]), 0)
        self.assertGreater(len(audit["trace"]), 0)
        self.assertEqual(audit["callback_errors"], [])
        self.assertEqual(resolved["stoploss"], -1.0)
        self.assertEqual(resolved["minimal_roi"], {})
        self.assertFalse(resolved["trailing_stop"])
        self.assertFalse(resolved["engine_position_stacking"])
        trades = result["results"]
        self.assertGreater(len(trades), 0)
        self.assertFalse(trades["exit_reason"].str.contains("stop_loss").any())
        receipt = {"synthetic_only": True, "full_economic_runs": 0, "market_reads": 0,
                   "entry_callbacks": len(audit["entries"]), "exit_callbacks": len(audit["exits"]),
                   "trace_events": len(audit["trace"]), "trade_count": len(trades),
                   "exit_reasons": trades["exit_reason"].value_counts().to_dict(),
                   "resolved": resolved}
        HERE.joinpath("SYNTHETIC_D2_ENGINE_SMOKE.json").write_text(json.dumps(receipt, indent=2) + "\n")

    def test_unchanged_hlhb_resolved_contract(self):
        source = external_class(VENDOR)
        result, signals, audit, resolved, config, markets = self.execute(source)
        self.assertEqual(resolved["minimal_roi"], {0: .6225, 703: .2187, 2849: .0363, 5520: 0})
        self.assertEqual(resolved["stoploss"], -.3211)
        self.assertTrue(resolved["trailing_stop"])
        self.assertEqual(resolved["trailing_stop_positive"], .0117)
        self.assertEqual(resolved["trailing_stop_positive_offset"], .0186)
        self.assertTrue(resolved["trailing_only_offset_is_reached"])
        self.assertEqual(resolved["order_types"], source.order_types)
        self.assertEqual(resolved["order_time_in_force"], source.order_time_in_force)
        self.assertEqual(resolved["source_position_stacking"], "True")
        self.assertFalse(resolved["engine_position_stacking"])
        self.assertEqual(resolved["engine_required_startup"], 30)
        receipt = {"synthetic_only": True, "full_economic_runs": 0, "market_reads": 0,
                   "trade_count": len(result["results"]), "resolved": resolved,
                   "source_class_position_stacking_is_not_an_engine_config_override": True}
        HERE.joinpath("SYNTHETIC_HLHB_ENGINE_SMOKE.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
