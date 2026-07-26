from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.tools.r7a4d_strategy11_structure_lock import (
    EXPECTED_ROWS,
    _strict_json,
    _validate_market_frame,
    protected_diff,
    run_fixture_checks,
)


class Strategy11StructureLockTest(unittest.TestCase):
    def test_replay_fixture_is_deterministic_causal_and_metric_parity(self) -> None:
        root = Path(__file__).resolve().parents[1]
        report, blockers = run_fixture_checks(root)
        self.assertEqual(blockers, [])
        self.assertTrue(report["deterministic_replay"])
        self.assertTrue(report["next_bar_open_fill"])
        self.assertTrue(report["same_bar_sl_first"])
        self.assertTrue(report["metric_parity"])
        self.assertTrue(report["lookahead_prefix_invariant"])

    def test_market_frame_contract_rejects_gap_and_invalid_ohlc(self) -> None:
        start_ms = 1_700_000_000_000
        timestamps = [start_ms + index * 900_000 for index in range(EXPECTED_ROWS)]
        frame = pd.DataFrame({
            "timestamp_ms": timestamps,
            "open": [100.0] * EXPECTED_ROWS,
            "high": [101.0] * EXPECTED_ROWS,
            "low": [99.0] * EXPECTED_ROWS,
            "close": [100.0] * EXPECTED_ROWS,
            "volume": [1.0] * EXPECTED_ROWS,
        })
        end_ms = timestamps[-1]
        self.assertEqual(_validate_market_frame(frame, start_ms=start_ms, end_ms=end_ms, expected_rows=EXPECTED_ROWS), [])
        broken = frame.copy()
        broken.loc[100, "timestamp_ms"] += 900_000
        broken.loc[200, "high"] = 98.0
        errors = _validate_market_frame(broken, start_ms=start_ms, end_ms=end_ms, expected_rows=EXPECTED_ROWS)
        self.assertIn("DUPLICATE_TIMESTAMP", errors)
        self.assertIn("TIMESTAMP_GAP_OR_WRONG_INTERVAL", errors)
        self.assertIn("HIGH_INVARIANT_FAILED", errors)

    def test_strict_json_rejects_nonfinite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text('{"value": NaN}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                _strict_json(path)
            good = Path(temporary) / "good.json"
            good.write_text(json.dumps({"value": 1.0}), encoding="utf-8")
            self.assertEqual(_strict_json(good)["value"], 1.0)

    def test_protected_diff_detects_add_remove_and_change(self) -> None:
        before = {"a": "1", "b": "2"}
        after = {"a": "9", "c": "3"}
        self.assertEqual(protected_diff(before, after), ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
