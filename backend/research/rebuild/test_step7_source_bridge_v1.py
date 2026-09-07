import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.research.rebuild import step7_source_bridge_v1 as s


def raw_bars(*times):
    return json.dumps({"code": 0, "data": [{"time": t, "open": "10", "high": "11", "low": "9", "close": "10", "volume": "2"} for t in times]}).encode()


class SourceTests(unittest.TestCase):
    def test_completed_bar_availability_is_receipt_not_historical_close(self):
        p = s.parse_raw(raw_bars(0, s.INTERVAL_MS), stream="ohlcv4h", received_at_ms=s.INTERVAL_MS + 1)
        self.assertEqual(len(p["rows"]), 1)
        self.assertEqual(p["available_at_ms"], s.INTERVAL_MS + 1)
        self.assertEqual(p["incomplete_rows"], 1)

    def test_duplicate_conflict_and_gap_quarantine(self):
        p = s.parse_raw(raw_bars(0, 0, 2 * s.INTERVAL_MS), stream="ohlcv4h", received_at_ms=4 * s.INTERVAL_MS)
        self.assertEqual(p["duplicate_rows"], 1)
        self.assertEqual(p["state"], "QUARANTINED_MISSING_INTERVAL")
        data = json.loads(raw_bars(0, 0)); data["data"][1]["close"] = "12"
        with self.assertRaisesRegex(ValueError, "CONFLICTING"):
            s.parse_raw(json.dumps(data).encode(), stream="ohlcv4h", received_at_ms=s.INTERVAL_MS)

    def test_stored_source_restart_dedupe_and_parse_equivalence(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = dict(stream="ohlcv4h", raw=raw_bars(0), uri="https://example.invalid", requested_at_ms=1, received_at_ms=2 * s.INTERVAL_MS, run_id="SYNTHETIC")
            first = s.ingest(Path(tmp), **args)
            second = s.ingest(Path(tmp), **args)
            self.assertTrue(first["online_offline_parse_equal"])
            self.assertEqual(second["state"], "REUSED_STORED_SOURCE")
            self.assertEqual(second["network_requests"], 0)
            self.assertEqual(len(list((Path(tmp) / "raw").iterdir())), 1)
            late = s.ingest(Path(tmp), **{**args, "raw": raw_bars(3 * s.INTERVAL_MS), "received_at_ms": 5 * s.INTERVAL_MS})
            self.assertEqual(late["parsed"]["state"], "QUARANTINED_RESTART_GAP")

    def test_signed_funding_preserved_no_position_or_fill_claim(self):
        raw = json.dumps({"code": 0, "data": [{"fundingTime": 100, "fundingRate": "-0.001"}]}).encode()
        p = s.parse_raw(raw, stream="funding", received_at_ms=200)
        self.assertEqual(p["rows"][0]["fundingRate"], "-0.001")
        self.assertEqual(p["formal_credit"], 0)
        self.assertEqual(p["settlement_coverage"], "UNBOUND_TO_POSITION_INTERVAL")

    def test_conditional_trigger_unbound_no_substitute(self):
        source = {"available_at_ms": 100, "source_sha256": "same-canonical", "state": "SNAPSHOT_ONLY"}
        ref = s.candidate_reference(source, candidate_id="Q0", decision_at_ms=101, trigger_stream=None, required_stream="conditional_sl", stale_ms=None, stale_authority=None)
        self.assertIn("TRIGGER_STREAM_UNBOUND", ref["blockers"])
        self.assertIn("SOURCE_SPECIFIC_STALE_AUTHORITY_UNBOUND", ref["blockers"])
        self.assertFalse(ref["actual_fill"])

    def test_shared_source_multiple_candidates_no_fetch(self):
        source = {"available_at_ms": 100, "source_sha256": "same-canonical", "state": "SNAPSHOT_ONLY"}
        with patch.object(s.urllib.request, "urlopen", side_effect=AssertionError("network forbidden")):
            refs = [s.candidate_reference(source, candidate_id=c, decision_at_ms=101, trigger_stream=None, required_stream="completed_bar", stale_ms=5, stale_authority="SYNTHETIC_ONLY") for c in ["KR3", "OTHER"]]
        self.assertEqual(refs[0]["source_sha256"], refs[1]["source_sha256"])
        self.assertTrue(all(x["formal_credit"] == 0 for x in refs))

    def test_future_stale_and_quarantine_fail_closed(self):
        for src, now, expected in [({"available_at_ms": 102}, 101, "SOURCE_UNAVAILABLE_AT_DECISION"), ({"available_at_ms": 1}, 101, "SOURCE_STALE"), ({"available_at_ms": 100, "state": "QUARANTINED_RESTART_GAP"}, 101, "SOURCE_INTERVAL_QUARANTINED")]:
            r = s.candidate_reference(src, candidate_id="KR3", decision_at_ms=now, trigger_stream=None, required_stream="completed_bar", stale_ms=5, stale_authority="SYNTHETIC_ONLY")
            self.assertIn(expected, r["blockers"])

    def test_one_failed_request_consumes_bundle_no_retry_or_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s.urllib.request, "urlopen", side_effect=TimeoutError("SYNTHETIC_TIMEOUT")) as request:
            first = s.capture(Path(tmp), "SYNTHETIC")
            second = s.capture(Path(tmp), "RENAMING_DOES_NOT_RESET")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(first, second)
            self.assertEqual(first["state"], "SOURCE_RUNTIME_BLOCKED")
            self.assertEqual(first["formal_credit"], 0)

    def test_parse_failure_preserves_raw_http(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s.urllib.request, "urlopen", return_value=io.BytesIO(b'{"code":109400,"msg":"synthetic"}')) as request:
            r = s.capture(Path(tmp), "SYNTHETIC")
            self.assertEqual(r["state"], "SOURCE_RUNTIME_BLOCKED")
            self.assertEqual(len(list((Path(tmp) / "raw_http").glob("depth_*.bin"))), 1)
            self.assertEqual(request.call_count, 1)

    def test_completed_exit_native_open_cannot_be_backdated_or_replaced(self):
        args = dict(decision_bar_close_ms=100, decision_available_at_ms=100, decision_at_ms=100,
                    open_event_at_ms=100, open_received_at_ms=102, source_sha256="SYNTHETIC")
        self.assertEqual(s.completed_exit_reference(**args)["state"], "TIMING_REFERENCE_READY")
        late = s.completed_exit_reference(**{**args, "decision_available_at_ms": 101, "decision_at_ms": 101})
        self.assertIn("OPEN_NOT_CAUSALLY_AVAILABLE", late["blockers"])
        replacement = s.completed_exit_reference(**{**args, "open_event_at_ms": 101})
        self.assertIn("NATIVE_NEXT_OPEN_TIME_MISMATCH", replacement["blockers"])

    def test_seven_symbol_manifest_matches_frozen_selection(self):
        selection = json.loads(s.SELECTION.read_text())
        contract = json.loads(s.SOURCE_CONTRACT.read_text())
        manifest = s.source_manifest(selection, contract)
        self.assertEqual(manifest["symbols"], selection["symbols"])
        self.assertEqual(manifest["requests_max"], 22)
        self.assertEqual(manifest["strategy_parity"], "NOT_READY")
        with self.assertRaisesRegex(ValueError, "IDENTITY|MISMATCH"):
            s.source_manifest({**selection, "symbols": selection["symbols"][:-1]}, contract)

    def test_cross_symbol_identical_raw_keeps_separate_cursors_shared_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = dict(stream="ohlcv4h", raw=raw_bars(0), uri="https://example.invalid", requested_at_ms=1, received_at_ms=2 * s.INTERVAL_MS, run_id="SYNTHETIC")
            first = s.ingest(Path(tmp), **args, symbol="SYNTHETIC_A")
            second = s.ingest(Path(tmp), **args, symbol="SYNTHETIC_B")
            self.assertEqual(first["source_sha256"], second["source_sha256"])
            state = json.loads((Path(tmp) / "cursor.json").read_text())
            self.assertEqual(set(state["streams"]), {"ohlcv4h:SYNTHETIC_A", "ohlcv4h:SYNTHETIC_B"})
            self.assertEqual(len(list((Path(tmp) / "raw").iterdir())), 1)
            self.assertEqual(len(list((Path(tmp) / "receipts").iterdir())), 2)
            third = s.ingest(Path(tmp), **args, symbol="SYNTHETIC_B")
            self.assertEqual(third["state"], "REUSED_STORED_SOURCE")


if __name__ == "__main__":
    unittest.main()
