"""Native source reuse, activation controls; no market/economic rerun."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import benchmark as native
import forward_signal_only as f


class TestOrderlessForward(unittest.TestCase):
    def test_native_rule_delegation_and_minimum_240_warmup(self) -> None:
        frame = pd.DataFrame([{"close": 100.0}] * 241)
        with patch.object(native, "signal_for", return_value=True) as mocked:
            self.assertTrue(f.classify(native.TREND, frame))
            mocked.assert_called_once()
            self.assertEqual(mocked.call_args.args[0], native.TREND)
            self.assertEqual(mocked.call_args.args[2], 240)
        with self.assertRaisesRegex(RuntimeError, "WARMUP"):
            f.classify(native.MOM, frame.iloc[:240])

    def test_cannot_read_future_or_unaligned_bars(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "SOURCE_CLOCK"):
            f.load_period(Path("/no/market"), 0, f.FOUR, 0)
        with self.assertRaisesRegex(RuntimeError, "SOURCE_CLOCK"):
            f.load_period(Path("/no/market"), f.FOUR, f.FOUR + 1, f.FOUR + 1)

    def test_receipt_path_traversal_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "SOURCE_PATH_ESCAPE"):
                f.guarded_path(Path(tmp), "../credentials.json")

    def test_status_fails_closed_on_real_orders_or_fake_fills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = {
                "orders": 0,
                "order_calls": 0,
                "virtual_fills": 0,
                "formal_shadow": False,
                "phase": "WAIT_SIGNAL",
            }
            f.atomic_status(Path(tmp), baseline)
            self.assertTrue((Path(tmp) / "STATUS.json").exists())
            for field, value in (
                ("orders", 1),
                ("virtual_fills", 1),
                ("formal_shadow", True),
            ):
                with self.assertRaisesRegex(RuntimeError, "ZERO_ORDER"):
                    f.atomic_status(Path(tmp), {**baseline, field: value})


if __name__ == "__main__":
    unittest.main()
