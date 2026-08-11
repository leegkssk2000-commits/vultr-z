import json
import tempfile
import unittest
from pathlib import Path

from backend.research.p3_prospective_native_coverage_gate import evaluate


REQUIRED_SPAN = 1_814_340_000


def contract():
    return {
        "schema_version": "zel.p3.carry_flow.prospective_native.v1",
        "state": "FROZEN_PROSPECTIVE_SOURCE_ACQUISITION",
        "family": "carry_flow",
        "research_only": True,
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "frozen_window_contract": {
            "source_pull_request": 605,
            "w1_start_ms": 1_782_549_000_000,
            "w2_end_ms": 1_784_276_940_000,
            "history_pre_roll_ms": 86_400_000,
            "required_capture_span_ms": REQUIRED_SPAN,
        },
        "native_sources": {
            "flow": {"status": "SOURCE_NOT_BOUND"},
        },
    }


def row(feature, symbol, collected_at_ms, source_timestamp_ms, suffix):
    return {
        "schema_version": "zel.p3.prospective_native_feature_record.v1",
        "feature": feature,
        "symbol": symbol,
        "source_timestamp_ms": source_timestamp_ms,
        "collected_at_ms": collected_at_ms,
        "source_payload_sha256": (suffix * 64)[:64],
        "prospective_only": True,
        "historical_coverage_claim": False,
        "signal_generation_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }


def write_history(root: Path, span_ms: int):
    for feature in ("premium_index", "open_interest"):
        for symbol in ("BTC-USDT", "ETH-USDT"):
            path = root / f"{feature}__{symbol.replace('-', '')}.ndjson"
            rows = [
                row(feature, symbol, 10_000_000_000_000, 9_000_000_000_000, "a"),
                row(feature, symbol, 10_000_000_000_000 + span_ms, 9_000_000_000_000 + span_ms, "b"),
            ]
            path.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in rows), encoding="utf-8")


class CoverageGateTests(unittest.TestCase):
    def test_short_history_stays_accumulating_and_never_replays(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_history(root, REQUIRED_SPAN - 1)
            result = evaluate(root, contract())
            self.assertEqual(result["state"], "HOLD_P3_PROSPECTIVE_HISTORY_ACCUMULATING")
            self.assertFalse(result["basis_oi_duration_gate_pass"])
            self.assertFalse(result["flow_source_bound"])
            self.assertFalse(result["replay_allowed"])
            self.assertEqual(result["execution_authority"], "NONE")

    def test_exact_frozen_span_marks_basis_oi_ready_but_flow_still_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_history(root, REQUIRED_SPAN)
            result = evaluate(root, contract())
            self.assertEqual(result["state"], "PASS_P3_BASIS_OI_COVERAGE_READY_FLOW_BLOCKED")
            self.assertTrue(result["basis_oi_duration_gate_pass"])
            self.assertFalse(result["flow_source_bound"])
            self.assertEqual(result["minimum_coverage_progress_ratio"], 1.0)
            self.assertFalse(result["replay_allowed"])
            self.assertFalse(result["signal_generation_enabled"])

    def test_duplicate_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_history(root, REQUIRED_SPAN)
            path = root / "premium_index__BTCUSDT.ndjson"
            first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(first, sort_keys=True) + "\n")
            with self.assertRaisesRegex(RuntimeError, "COVERAGE_DUPLICATE_IDENTITY"):
                evaluate(root, contract())


if __name__ == "__main__":
    unittest.main()
