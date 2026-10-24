"""Synthetic raw->normalized->pinned reader->hourly preflight, no economics."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))
from backend.research.rebuild import economic7_canonical_history_v1 as history
from backend.research.rebuild import scalp7_fresh_source_v2 as source
sys.path.remove(str(REPO))
spec = importlib.util.spec_from_file_location("holy_gate_integration", HERE / "input_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class SourceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.snapshot = cls.root / "synthetic_snapshot"
        cls.snapshot.mkdir()
        cls.freeze = 1_700_000_000_000
        cls.lo = (cls.freeze // gate.HOUR + 1) * gate.HOUR
        cls.hi = cls.lo + gate.HOUR
        cls.start = cls.lo - 240 * gate.HOUR
        cls.rule_sha = cls.write(cls.root / "FROZEN_SPEC.json", {"frozen_at_ms": cls.freeze})
        identity = {"source": source.SOURCE, "interval": "1m", "timeZone": 0,
                    "symbols": list(gate.SYMBOLS), "start_ms": cls.start}
        identity_sha = cls.write(cls.snapshot / "IDENTITY.json", identity)
        cursor = {"identity_sha256": identity_sha, "symbols": {}}
        for symbol in gate.SYMBOLS:
            records = []
            for hour in range(241):
                start = cls.start + hour * gate.HOUR
                end = start + gate.HOUR
                rows = [{"time": start + minute * gate.MINUTE, "open": "100.00",
                         "high": "102.00", "low": "99.00", "close": "101.00", "volume": "1.00"}
                        for minute in range(60)]
                stem = f"requests/{symbol}/{hour}"
                raw = history.json_bytes({"code": 0, "data": rows})
                body_sha = cls.write_bytes(cls.snapshot / (stem + ".body"), raw)
                normalized = history.csv_gzip([history.normalize_row(row) for row in rows])
                normalized_sha = cls.write_bytes(cls.snapshot / (stem + ".csv.gz"), normalized)
                receipt = {"source": source.SOURCE, "url": source.SOURCE,
                           "query": {"symbol": symbol, "interval": "1m", "timeZone": 0,
                                     "startTime": start, "endTime": end - 1},
                           "symbol": symbol, "start_ms": start, "end_exclusive_ms": end,
                           "requested_at_ms": end, "received_at_ms": end + 100,
                           "body_path": stem + ".body", "body_sha256": body_sha,
                           "normalized_path": stem + ".csv.gz", "normalized_sha256": normalized_sha,
                           "http_status": 200, "rows": 60, "missing_minutes": [],
                           "state": "COMPLETE", "volume_units": "UNKNOWN", "synthetic_fill": False,
                           "test_fixture_only": True}
                name = stem + ".receipt.json"
                records.append({"path": name, "sha256": cls.write(cls.snapshot / name, receipt)})
            cursor["symbols"][symbol] = records
        cursor_sha = cls.write(cls.snapshot / "CURSOR.json", cursor)
        ticks = {symbol: .01 for symbol in gate.SYMBOLS}
        tick_raw_sha = cls.write(cls.snapshot / "tick.raw.json", {"synthetic_only": True})
        tick_sha = cls.write(cls.snapshot / "ticks.json", {"tick_sizes": ticks, "source_ref": "SYNTHETIC_ONLY",
            "original_raw_path": "tick.raw.json", "original_raw_sha256": tick_raw_sha})
        cls.manifest = {"schema": "zel.holygrail.input.v1", "rule_spec_path": "FROZEN_SPEC.json",
            "rule_spec_sha256": cls.rule_sha, "snapshot_root": str(cls.snapshot),
            "source_identity_sha256": identity_sha, "source_cursor_sha256": cursor_sha,
            "snapshot_authorization_ref": "SYNTHETIC_TEST_ONLY",
            "independent_data_attestation": {"ref": "SYNTHETIC_TEST_ONLY", "asserted_by": "fixture", "asserted_at_ms": cls.freeze},
            "input_freeze": {"ref": "SYNTHETIC_TEST_ONLY", "frozen_at_ms": cls.freeze},
            "symbols": list(gate.SYMBOLS), "timeframe_ms": gate.HOUR, "warmup_bars": 240,
            "dev_start_ms": cls.lo, "dev_end_ms": cls.hi, "tick_sizes": ticks,
            "tick_metadata": {"path": "ticks.json", "sha256": tick_sha, "effective_from_ms": cls.freeze,
                              "effective_to_ms": cls.hi, "source_ref": "SYNTHETIC_ONLY"},
            "cost_model": {"roundtrip_bps_1x": 20, "roundtrip_bps_2x": 40,
                           "historical_funding": None, "classification": "MODELLED_ONLY_NO_PROMOTION"}}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def write_bytes(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return gate.digest(raw)

    @classmethod
    def write(cls, path, value):
        return cls.write_bytes(path, history.json_bytes(value))

    def run_real_gate(self, manifest=None):
        manifest = manifest or self.manifest
        path = self.root / "input.json"
        sha = self.write(path, manifest)
        no_network = AssertionError("NETWORK_OR_COLLECTOR_CALL_FORBIDDEN_IN_FIXTURE")
        with patch.object(gate, "RULE_SHA256", self.rule_sha), \
             patch.object(source, "public_fetch", side_effect=no_network), \
             patch.object(history, "public_fetch", side_effect=no_network), \
             patch.object(source, "collect_once", side_effect=no_network), \
             patch("urllib.request.urlopen", side_effect=no_network):
            return gate.preflight(path, REPO, sha)

    def test_real_pinned_loader_accepts_full_synthetic_chain(self):
        result = self.run_real_gate()
        self.assertEqual(set(result["bars_by_symbol"]), set(gate.SYMBOLS))
        for bars in result["bars_by_symbol"].values():
            self.assertEqual(len(bars), 241)
            self.assertEqual(bars[0]["timestamp_ms"], self.start)
            self.assertEqual(bars[-1]["close_ts_ms"], self.hi)
            self.assertEqual(bars[-1]["available_at_ms"], self.hi + 100)
            self.assertEqual(bars[-1]["volume"], 60)
        self.assertGreater(len(result["snapshot_file_hashes"]), 4300)

    def test_raw_tamper_rejected_before_loading(self):
        path = self.snapshot / "requests/BTC-USDT/0.body"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b" ")
            with self.assertRaisesRegex(gate.GateError, "BOUND_HASH_MISMATCH"):
                self.run_real_gate()
        finally:
            path.write_bytes(original)

    def test_rehashed_raw_change_fails_true_normalized_parity(self):
        body_path = self.snapshot / "requests/BTC-USDT/0.body"
        receipt_path = self.snapshot / "requests/BTC-USDT/0.receipt.json"
        cursor_path = self.snapshot / "CURSOR.json"
        originals = {path: path.read_bytes() for path in (body_path, receipt_path, cursor_path)}
        try:
            body = json.loads(originals[body_path])
            body["data"][0]["close"] = "100.50"
            receipt = json.loads(originals[receipt_path])
            receipt["body_sha256"] = self.write(body_path, body)
            cursor = json.loads(originals[cursor_path])
            cursor["symbols"]["BTC-USDT"][0]["sha256"] = self.write(receipt_path, receipt)
            manifest = copy.deepcopy(self.manifest)
            manifest["source_cursor_sha256"] = self.write(cursor_path, cursor)
            with self.assertRaisesRegex(gate.GateError, "PINNED_SOURCE_REJECTED:SourceDataError"):
                self.run_real_gate(manifest)
        finally:
            for path, raw in originals.items():
                path.write_bytes(raw)


if __name__ == "__main__":
    unittest.main()
