import io
import json
from pathlib import Path
import tempfile
import signal
import time
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from backend.research.rebuild import step7_source_sequence_v1 as s


def allocation(**changes):
    selection = json.loads(s.prior.SELECTION.read_text())
    return {"allocation_id": s.ALLOCATION_ID, "status": "RESERVED", "max_batches": 1,
            "used_batches": 0, "max_http_requests": 2000, "max_raw_bytes": 1073741824,
            "max_duration_seconds": 86400, "selected_runtime_seconds": 180,
            "selected_http_plan_max": 35, "selection_sha256": s.SELECTION_SEAL,
            "symbols": selection["symbols"], **changes}


class SourceSequenceTests(unittest.TestCase):
    def test_grant_is_additional_exact_selection_and_lower_finite_cap(self):
        self.assertEqual(s.validate_allocation(allocation())["http_limit"], 35)
        for change in ({"allocation_id": "RENAMED"}, {"selection_sha256": "forged"},
                       {"symbols": ["BTC-USDT"]}, {"max_http_requests": 2001},
                       {"max_duration_seconds": 86401}, {"max_raw_bytes": 1073741825},
                       {"used_batches": 1}, {"selected_runtime_seconds": 181}):
            with self.assertRaises(ValueError):
                s.validate_allocation(allocation(**change))

    def test_fixture_dependency_cannot_enter_production_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "FIXTURE_DEPENDENCIES"):
                s.capture(Path(tmp), allocation(), "forged", opener=lambda *a, **k: None)

    def test_source_host_guard_precedes_any_http(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(s.os.environ, {}, clear=True), \
                patch.object(s.urllib.request, "urlopen") as opener:
            with self.assertRaisesRegex(ValueError, "EXISTING_ACTIONS"):
                s.capture(Path(tmp), allocation(), "not-actions")
            opener.assert_not_called()

    def test_failed_request_reservation_persisted_and_restart_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            calls = []
            def failure(*args, **kwargs):
                stored = json.loads((directory / "ATTEMPT.json").read_text())
                self.assertEqual(len(stored["requests"]), 1)
                self.assertEqual(stored["reserved_raw_bytes"], s.MAX_WIRE)
                self.assertEqual(stored["requests"][0]["state"], "RESERVED_BEFORE_HTTP")
                calls.append(1)
                raise TimeoutError("SYNTHETIC_TIMEOUT")
            first = s.capture(directory, allocation(), "fixture", fixture_mode=True, opener=failure)
            second = s.capture(directory, allocation(), "renamed", fixture_mode=True, opener=failure)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first, second)
            self.assertEqual(first["state"], "SOURCE_SEQUENCE_BLOCKED")
            self.assertEqual(first["reserved_raw_bytes"], s.MAX_WIRE)

    def test_storage_budget_stops_before_first_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            result = s.capture(Path(tmp), allocation(max_raw_bytes=s.MAX_RESPONSE - 1), "fixture",
                               fixture_mode=True, opener=lambda *a, **k: calls.append(1))
            self.assertEqual(calls, [])
            self.assertEqual(result["state"], "SOURCE_SEQUENCE_LIMIT_STOP")
            self.assertEqual(result["requests"], [])

    def test_deadline_stops_before_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            tick = [0]
            def clock():
                tick[0] += 181000
                return tick[0]
            calls = []
            result = s.capture(Path(tmp), allocation(), "fixture", fixture_mode=True,
                               clock=clock, opener=lambda *a, **k: calls.append(1))
            self.assertEqual(calls, [])
            self.assertIn("DEADLINE", result["blockers"][0])

    def test_ambiguous_interrupted_attempt_remains_spent(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            s.prior.save(directory / "ATTEMPT.json", {"state": "STARTED", "run_id": "old",
                "allocation_id": s.ALLOCATION_ID, "blockers": [], "requests": [{"state": "RESERVED_BEFORE_HTTP"}]})
            calls = []
            result = s.capture(directory, allocation(), "new", fixture_mode=True,
                               opener=lambda *a, **k: calls.append(1))
            self.assertEqual(calls, [])
            self.assertIn("PRIOR_EXECUTION_AMBIGUOUS_NO_RETRY", result["blockers"])

    def test_exchange_cursor_progress_is_not_receipt_progress(self):
        state = {}
        for received in (1, 2, 3):
            s.advance_cursor(state, "depth:BTC-USDT", None, received)
        self.assertEqual(state["depth:BTC-USDT"]["advances"], 0)
        for cursor in (100, 101, 102):
            s.advance_cursor(state, "depth:ETH-USDT", cursor, cursor + 10)
        self.assertEqual(state["depth:ETH-USDT"]["advances"], 2)
        with self.assertRaisesRegex(ValueError, "REGRESSION"):
            s.advance_cursor(state, "depth:ETH-USDT", 99, 120)

    def test_future_incomplete_bars_and_missing_intervals_never_reach_native(self):
        raw = json.dumps({"code": 0, "data": [{"time": t, "open": "1", "high": "2", "low": ".5", "close": "1", "volume": "3"}
                                                for t in (0, 2 * s.prior.INTERVAL_MS)]}).encode()
        first = s.prior.parse_raw(raw, stream="ohlcv4h", received_at_ms=s.prior.INTERVAL_MS)
        self.assertEqual(len(s.canonical_rows(first)), 1)
        later = s.prior.parse_raw(raw, stream="ohlcv4h", received_at_ms=4 * s.prior.INTERVAL_MS)
        with self.assertRaisesRegex(ValueError, "QUARANTINED"):
            s.canonical_rows(later)

    def test_finite_sequence_depth_twice_advances_native_cursor_does_not_fake_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            tick = [401 * s.prior.INTERVAL_MS]
            depths, calls = {}, []
            def clock():
                tick[0] += 10
                return tick[0]
            def opener(request, **kwargs):
                calls.append(request.full_url)
                stored = json.loads((directory / "ATTEMPT.json").read_text())
                self.assertEqual(len(stored["requests"]), len(calls))
                parsed = urlparse(request.full_url)
                symbol = parse_qs(parsed.query)["symbol"][0]
                if "klines" in parsed.path:
                    data = [{"time": i * s.prior.INTERVAL_MS, "open": "1", "high": "2", "low": ".5", "close": "1", "volume": "2"} for i in range(400)]
                elif "funding" in parsed.path:
                    data = [{"fundingTime": 400 * s.prior.INTERVAL_MS, "fundingRate": "-.001"}]
                else:
                    depths[symbol] = depths.get(symbol, 100) + 1
                    data = {"bids": [["1", "1"]], "asks": [["2", "1"]], "lastUpdateId": depths[symbol]}
                return io.BytesIO(json.dumps({"code": 0, "data": data}).encode())
            def probe(rows, available, state):
                self.assertEqual(len(rows), 7)
                self.assertTrue(all(len(rr) == 400 for rr in rows.values()))
                return {"state": {"cursor": 400 * s.prior.INTERVAL_MS},
                        "metadata": {"status": "NO_SIGNAL", "signal_count": 0}}
            result = s.capture(directory, allocation(), "SYNTHETIC", fixture_mode=True,
                               opener=opener, clock=clock, sleeper=lambda _: None, probe=probe)
            self.assertEqual(len(calls), 35)
            self.assertEqual(result["state"], "SOURCE_SEQUENCE_STOPPED")
            self.assertEqual(result["reserved_raw_bytes"], 0)
            self.assertTrue(all(c["advances"] == 2 for k, c in result["cursors"].items() if k.startswith("depth:")))
            self.assertTrue(all(c["advances"] == 0 for k, c in result["cursors"].items() if k.startswith("ohlcv4h:")))
            self.assertTrue(all(m["serialized_restart_state_equal"] for m in result["native_metadata"]))
            self.assertEqual(result["formal_credit"], 0)
            self.assertFalse(result["process_continues_after_return"])
            serialized = json.dumps(result)
            for forbidden in ('"fundingRate"', '"bids"', '"asks"', '"open"', '"close"'):
                self.assertNotIn(forbidden, serialized)

    def test_hard_deadline_interrupts_blocking_operation(self):
        previous = signal.signal(signal.SIGALRM, s.deadline_alarm)
        try:
            signal.setitimer(signal.ITIMER_REAL, .01)
            with self.assertRaisesRegex(TimeoutError, "DEADLINE_HARD_STOP"):
                time.sleep(.2)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)


if __name__ == "__main__":
    unittest.main()
