"""Synthetic-only source binding, causal clock and path safety regression tests."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("holy_input_gate", HERE / "input_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def minutes(start, count):
    return [{"timestamp_ms": start + i * gate.MINUTE, "open": 100., "high": 102.,
             "low": 99., "close": 101., "volume": 1.,
             "received_at_ms": start + (i + 1) * gate.MINUTE + 100}
            for i in range(count)]


class Frame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orientation):
        assert orientation == "records"
        return self.rows


class HourlyTests(unittest.TestCase):
    def setUp(self):
        self.rows = minutes(0, 60)

    def test_exact_hour_and_actual_availability(self):
        result = gate.aggregate_hourly(self.rows, 0, gate.HOUR)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["available_at_ms"], gate.HOUR + 100)
        self.assertEqual(result[0]["volume"], 60)

    def test_duplicate_rejected(self):
        self.rows[2] = self.rows[1].copy()
        with self.assertRaisesRegex(gate.GateError, "DUPLICATE"):
            gate.aggregate_hourly(self.rows, 0, gate.HOUR)

    def test_missing_minute_rejected(self):
        del self.rows[19]
        with self.assertRaisesRegex(gate.GateError, "MISSING_MINUTES"):
            gate.aggregate_hourly(self.rows, 0, gate.HOUR)

    def test_off_grid_rejected(self):
        self.rows[4]["timestamp_ms"] += 1
        with self.assertRaisesRegex(gate.GateError, "OFF_GRID"):
            gate.aggregate_hourly(self.rows, 0, gate.HOUR)

    def test_nan_rejected(self):
        self.rows[3]["close"] = float("nan")
        with self.assertRaisesRegex(gate.GateError, "NONFINITE"):
            gate.aggregate_hourly(self.rows, 0, gate.HOUR)

    def test_inverted_high_rejected(self):
        self.rows[3]["high"] = 98.
        with self.assertRaisesRegex(gate.GateError, "INVALID_OHLC"):
            gate.aggregate_hourly(self.rows, 0, gate.HOUR)

    def test_preclose_receipt_rejected(self):
        self.rows[3]["received_at_ms"] = self.rows[3]["timestamp_ms"]
        with self.assertRaisesRegex(gate.GateError, "INVALID_RECEIVED_AT"):
            gate.aggregate_hourly(self.rows, 0, gate.HOUR)

    def test_excess_receipt_latency_rejected(self):
        self.rows[59]["received_at_ms"] = 2 * gate.HOUR + 1
        with self.assertRaisesRegex(gate.GateError, "SOURCE_LATENCY"):
            gate.aggregate_hourly(self.rows, 0, gate.HOUR)

    def test_prefix_invariance(self):
        prefix = gate.aggregate_hourly(self.rows, 0, gate.HOUR)
        all_rows = self.rows + minutes(gate.HOUR, 60)
        self.assertEqual(prefix, gate.aggregate_hourly(all_rows, 0, 2 * gate.HOUR)[:1])

    def test_decreasing_hourly_availability_rejected(self):
        # First hour would become available after the second hour. The tighter
        # one-hour latency cap rejects it before the monotonicity guard.
        self.rows[59]["received_at_ms"] = 3 * gate.HOUR
        rows = self.rows + minutes(gate.HOUR, 60)
        with self.assertRaisesRegex(gate.GateError, "SOURCE_LATENCY|AVAILABILITY_OUT_OF_ORDER"):
            gate.aggregate_hourly(rows, 0, 2 * gate.HOUR)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "snapshot"
        self.snapshot.mkdir()
        self.freeze = 1_700_000_000_000
        self.lo = ((self.freeze // gate.HOUR) + 1) * gate.HOUR
        self.hi = self.lo + gate.HOUR
        self.manifest_path = self.root / "input.json"
        rule_sha = self.write(self.root / "FROZEN_SPEC.json", {"frozen_at_ms": self.freeze})
        self.fixture_rule_sha = rule_sha
        identity_sha = self.write(self.snapshot / "IDENTITY.json", {"symbols": list(gate.SYMBOLS)})
        cursor = {"identity_sha256": identity_sha, "symbols": {}}
        for symbol in gate.SYMBOLS:
            body = symbol + ".body"
            normalized = symbol + ".csv.gz"
            body_sha = self.write(self.snapshot / body, {"synthetic": True})
            normalized_sha = self.write(self.snapshot / normalized, {"synthetic": True})
            receipt = {"symbol": symbol, "body_path": body, "body_sha256": body_sha,
                       "normalized_path": normalized, "normalized_sha256": normalized_sha}
            name = symbol + ".receipt.json"
            cursor["symbols"][symbol] = [{"path": name, "sha256": self.write(self.snapshot / name, receipt)}]
        cursor_sha = self.write(self.snapshot / "CURSOR.json", cursor)
        ticks = {symbol: .01 for symbol in gate.SYMBOLS}
        tick_raw_sha = self.write(self.snapshot / "tick.raw.json", {"synthetic_tick_data": True})
        tick_sha = self.write(self.snapshot / "ticks.json", {"tick_sizes": ticks, "source_ref": "SYNTHETIC_TEST_ONLY",
            "original_raw_path": "tick.raw.json", "original_raw_sha256": tick_raw_sha})
        self.m = {"schema": "zel.holygrail.input.v1", "rule_spec_path": "FROZEN_SPEC.json",
            "rule_spec_sha256": rule_sha, "snapshot_root": str(self.snapshot),
            "source_identity_sha256": identity_sha, "source_cursor_sha256": cursor_sha,
            "snapshot_authorization_ref": "SYNTHETIC_TEST_ONLY",
            "independent_data_attestation": {"ref": "SYNTHETIC_TEST_ONLY", "asserted_by": "fixture", "asserted_at_ms": self.freeze},
            "input_freeze": {"ref": "SYNTHETIC_TEST_ONLY", "frozen_at_ms": self.freeze},
            "symbols": list(gate.SYMBOLS), "timeframe_ms": gate.HOUR, "warmup_bars": 240,
            "dev_start_ms": self.lo, "dev_end_ms": self.hi, "tick_sizes": ticks,
            "tick_metadata": {"path": "ticks.json", "sha256": tick_sha, "effective_from_ms": self.freeze,
                              "effective_to_ms": self.hi, "source_ref": "SYNTHETIC_TEST_ONLY"},
            "cost_model": {"roundtrip_bps_1x": 20, "roundtrip_bps_2x": 40, "historical_funding": None, "classification": "MODELLED_ONLY_NO_PROMOTION"}}
        frame = Frame(minutes(self.lo - 240 * gate.HOUR, 241 * 60))
        self.frames = {symbol: frame for symbol in gate.SYMBOLS}

    @staticmethod
    def write(path, obj):
        raw = json.dumps(obj, sort_keys=True).encode()
        path.write_bytes(raw)
        return gate.digest(raw)

    def run_gate(self, loader=None, expected=None):
        sha = self.write(self.manifest_path, self.m)
        with patch.object(gate, "RULE_SHA256", self.fixture_rule_sha), patch.object(gate, "_load_pinned", loader or (lambda *args: self.frames)):
            return gate.preflight(self.manifest_path, self.root, expected or sha)

    def test_complete_synthetic_binding(self):
        result = self.run_gate()
        self.assertEqual(len(result["bars_by_symbol"][gate.SYMBOLS[0]]), 241)
        self.assertIn("OWNER_ATTESTATIONS_ASSERTED_NOT_CRYPTOGRAPHIC_NOVELTY", result["limitations"])
        self.assertEqual(len(result["input_sha256"]), 64)

    def test_empty_template_blocks(self):
        self.m["snapshot_root"] = None
        with self.assertRaisesRegex(gate.GateError, "HOLD_MISSING_NEW_INPUT_BINDING"):
            self.run_gate()

    def test_wrong_manifest_hash(self):
        with self.assertRaisesRegex(gate.GateError, "MANIFEST_HASH_MISMATCH"):
            self.run_gate(expected="0" * 64)

    def test_swapped_rule_cannot_unlock_earlier_data(self):
        changed = {"frozen_at_ms": self.freeze - 365 * 24 * gate.HOUR}
        self.m["rule_spec_sha256"] = self.write(self.root / "FROZEN_SPEC.json", changed)
        with self.assertRaisesRegex(gate.GateError, "FROZEN_RULE_IDENTITY_MISMATCH"):
            self.run_gate(lambda *args: self.fail("loader called before frozen rule rejection"))

    def test_denied_path_before_any_loader(self):
        self.m["snapshot_root"] = "/not_read/benchmark_web_holygrail_rearm_v9.json"
        with self.assertRaisesRegex(gate.GateError, "DENIED_SOURCE_PATH"):
            self.run_gate(lambda *args: self.fail("loader called"))

    def test_consumed_archive_rejected(self):
        self.m["snapshot_root"] = "/not_read/canonical_postgap_20260213"
        with self.assertRaisesRegex(gate.GateError, "CONSUMED_CORPUS_PATH"):
            self.run_gate()

    def test_prefreeze_dev_rejected(self):
        self.m["dev_start_ms"] = self.lo - gate.HOUR
        with self.assertRaisesRegex(gate.GateError, "PREFREEZE"):
            self.run_gate()

    def test_cost2_must_double_cost1(self):
        self.m["cost_model"]["roundtrip_bps_2x"] = 30
        with self.assertRaisesRegex(gate.GateError, "COST_CONTRACT"):
            self.run_gate()

    def test_funding_not_silently_zero(self):
        self.m["cost_model"]["historical_funding"] = 0
        with self.assertRaisesRegex(gate.GateError, "COST_CONTRACT"):
            self.run_gate()

    def test_wrong_tick_metadata_hash(self):
        self.m["tick_metadata"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(gate.GateError, "BOUND_HASH_MISMATCH"):
            self.run_gate()

    def test_cursor_path_escape_before_loader(self):
        cursor = json.loads((self.snapshot / "CURSOR.json").read_text())
        cursor["symbols"][gate.SYMBOLS[0]][0]["path"] = "../outside.json"
        self.m["source_cursor_sha256"] = self.write(self.snapshot / "CURSOR.json", cursor)
        with self.assertRaisesRegex(gate.GateError, "PATH_OUTSIDE"):
            self.run_gate(lambda *args: self.fail("loader called"))

    def test_symlink_raw_rejected(self):
        body = self.snapshot / (gate.SYMBOLS[0] + ".body")
        original = self.snapshot / "original"
        body.rename(original)
        body.symlink_to(original)
        with self.assertRaisesRegex(gate.GateError, "SYMLINK_REJECTED"):
            self.run_gate()

    def test_cursor_changed_during_loader(self):
        def changing_loader(*args):
            (self.snapshot / "CURSOR.json").write_bytes(b"{}")
            return self.frames
        with self.assertRaisesRegex(gate.GateError, "BOUND_HASH_MISMATCH:CURSOR"):
            self.run_gate(changing_loader)

    def test_period_cap(self):
        self.m["dev_end_ms"] = self.lo + 32 * 24 * gate.HOUR
        with self.assertRaisesRegex(gate.GateError, "31_DAY_CAP"):
            self.run_gate()


if __name__ == "__main__":
    unittest.main()
