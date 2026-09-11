"""Synthetic transport only; never calls a market endpoint or a policy runner."""
import json
import io
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch

from backend.research.rebuild import trendrider_common_source_v1 as source


def contract():
    return {"source": {"endpoint": source.ENDPOINT, "symbols": list(source.SYMBOLS),
                       "interval": "1h", "cutoff_ms": source.CUTOFF_MS,
                       "bars_per_symbol": 1000, "page_limit": 1000,
                       "max_pages_per_symbol": 10}}


def bar(stamp):
    return {"time": stamp, "open": "100", "high": "102", "low": "99",
            "close": "101", "volume": "10"}


def payload(rows):
    return source.canonical_bytes({"code": 0, "data": rows})


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.contract_path = self.base / "contract.json"
        self.contract_path.write_bytes(source.canonical_bytes(contract()))
        self.output = self.base / "data"
        self.calls = []
        self.original_http_transport = source.http_transport
        self.real_network = patch.object(source, "http_transport", side_effect=AssertionError("NO_NETWORK"))
        self.real_network.start()
        self.addCleanup(self.real_network.stop)

    def transport(self, endpoint, params):
        self.assertTrue((self.output / "ATTEMPT_STARTED.json").exists())
        self.assertEqual(endpoint, source.ENDPOINT)
        self.calls.append(dict(params))
        last = params["endTime"] // source.HOUR_MS * source.HOUR_MS
        rows = [bar(last - i * source.HOUR_MS) for i in range(params["limit"])]
        return source.Response(200, {"Date": "Fri, 11 Sep 2026 18:00:00 GMT"}, payload(rows))

    def test_exact_grid_and_deterministic_normalized_bytes(self):
        result = source.collect(self.contract_path, self.output, transport=self.transport)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([x["symbol"] for x in self.calls], list(source.SYMBOLS))
        self.assertEqual(result["state"], "FROZEN_COMMON_HISTORICAL_DEV")
        for symbol, info in result["normalized"].items():
            raw = (self.output / info["path"]).read_bytes()
            self.assertEqual(info["sha256"], source.digest_bytes(raw))
            rows = json.loads(raw)
            self.assertEqual(len(rows), 1000)
            self.assertEqual(rows[0]["ts_ms"], source.FIRST_OPEN_MS)
            self.assertEqual(rows[-1]["ts_ms"] + source.HOUR_MS, source.CUTOFF_MS)
            self.assertTrue(all(row["symbol"] == symbol for row in rows))

    def test_second_call_cannot_resume_or_refetch(self):
        source.collect(self.contract_path, self.output, transport=self.transport)
        with self.assertRaisesRegex(source.SourceIntegrityError, "NO_RESUME"):
            source.collect(self.contract_path, self.output, transport=self.transport)
        self.assertEqual(len(self.calls), 2)

    def test_short_page_advances_once_without_retry(self):
        def short(endpoint, params):
            first = params["endTime"] == source.CUTOFF_MS - 1
            response = self.transport(endpoint, params)
            rows = json.loads(response.body)["data"]
            return source.Response(200, {}, payload(rows[:600] if first else rows))
        result = source.collect(self.contract_path, self.output, transport=short)
        self.assertEqual(result["http_get_count"], 4)
        self.assertEqual([x["limit"] for x in self.calls], [1000, 400, 1000, 400])
        self.assertEqual(self.calls[1]["endTime"], source.CUTOFF_MS - 600 * source.HOUR_MS - 1)

    def test_raw_and_metadata_saved_before_json_decode(self):
        original = source.decode_page
        def observing(raw, symbol, latest, remaining):
            path = self.output / f"raw/{symbol}_00.bin"
            self.assertEqual(path.read_bytes(), raw)
            meta = json.loads(path.with_suffix(".response.json").read_text())
            self.assertEqual(meta["raw_sha256"], source.digest_bytes(raw))
            return original(raw, symbol, latest, remaining)
        with patch.object(source, "decode_page", side_effect=observing):
            source.collect(self.contract_path, self.output, transport=self.transport)

    def test_http403_preserves_raw_and_consumes_attempt(self):
        def denied(endpoint, params):
            self.calls.append(dict(params))
            return source.Response(403, {"Content-Type": "text/html"}, b"blocked")
        with self.assertRaisesRegex(source.SourceIntegrityError, "HTTP_STATUS:403"):
            source.collect(self.contract_path, self.output, transport=denied)
        self.assertEqual((self.output / "raw/BTC-USDT_00.bin").read_bytes(), b"blocked")
        failure = json.loads((self.output / "FAILURE_MANIFEST.json").read_text())
        self.assertEqual(failure["state"], "BLOCKED_DATA")
        self.assertEqual(failure["economic_runs"], 0)
        with self.assertRaisesRegex(source.SourceIntegrityError, "NO_RESUME"):
            source.collect(self.contract_path, self.output, transport=denied)
        self.assertEqual(len(self.calls), 1)

    def test_transport_exception_has_no_retry(self):
        def disconnected(endpoint, params):
            self.calls.append(dict(params))
            raise TimeoutError("synthetic timeout")
        with self.assertRaises(source.SourceIntegrityError):
            source.collect(self.contract_path, self.output, transport=disconnected)
        failure = json.loads((self.output / "FAILURE_MANIFEST.json").read_text())
        self.assertEqual(failure["http_response_count"], 0)
        self.assertEqual(failure["error_type"], "TimeoutError")
        self.assertEqual(len(self.calls), 1)

    def test_malformed_json_failure_preserves_raw(self):
        def malformed(endpoint, params):
            return source.Response(200, {}, b"{broken")
        with self.assertRaisesRegex(source.SourceIntegrityError, "JSON_INVALID"):
            source.collect(self.contract_path, self.output, transport=malformed)
        self.assertEqual((self.output / "raw/BTC-USDT_00.bin").read_bytes(), b"{broken")
        self.assertFalse((self.output / "DATA_FREEZE.json").exists())

    def test_endpoint_allowlist_rejected_before_any_transport(self):
        value = contract()
        value["source"]["endpoint"] = "https://example.com/klines"
        self.contract_path.write_bytes(source.canonical_bytes(value))
        with self.assertRaisesRegex(source.SourceIntegrityError, "CONTRACT_MISMATCH:endpoint"):
            source.collect(self.contract_path, self.output, transport=self.transport)
        self.assertEqual(self.calls, [])

    def test_invalid_window_interval_symbol_and_budget_contracts(self):
        for key, value in (("cutoff_ms", source.CUTOFF_MS + source.HOUR_MS),
                           ("interval", "4h"), ("symbols", ["BTC-USDT"]),
                           ("bars_per_symbol", 999), ("max_pages_per_symbol", 11)):
            with self.subTest(key=key):
                item = contract()
                item["source"][key] = value
                with self.assertRaises(source.SourceIntegrityError):
                    source.validate_contract(item)

    def test_page_budget_exhaustion_fails_without_second_symbol(self):
        def tiny(endpoint, params):
            self.calls.append(dict(params))
            last = params["endTime"] // source.HOUR_MS * source.HOUR_MS
            return source.Response(200, {}, payload([bar(last)]))
        with self.assertRaisesRegex(source.SourceIntegrityError, "PAGE_BUDGET_EXHAUSTED"):
            source.collect(self.contract_path, self.output, transport=tiny)
        self.assertEqual(len(self.calls), 10)
        self.assertTrue(all(x["symbol"] == "BTC-USDT" for x in self.calls))

    def test_contract_mutation_during_fetch_blocks_success(self):
        def mutate(endpoint, params):
            result = self.transport(endpoint, params)
            self.contract_path.write_bytes(self.contract_path.read_bytes() + b" ")
            return result
        with self.assertRaisesRegex(source.SourceIntegrityError, "CONTRACT_CHANGED"):
            source.collect(self.contract_path, self.output, transport=mutate)
        self.assertFalse((self.output / "DATA_FREEZE.json").exists())

    def test_invalid_rows_are_not_dropped(self):
        stamp = source.CUTOFF_MS - source.HOUR_MS
        cases = {
            "duplicate": [bar(stamp), bar(stamp)],
            "gap": [bar(stamp), bar(stamp - 2 * source.HOUR_MS)],
            "offgrid": [bar(stamp + 1)],
            "future": [bar(source.CUTOFF_MS)],
            "missing_volume": [{key: value for key, value in bar(stamp).items() if key != "volume"}],
            "negative_volume": [{**bar(stamp), "volume": -1}],
            "nonfinite": [{**bar(stamp), "open": "NaN"}],
            "bad_ohlc": [{**bar(stamp), "high": 50}],
            "wrong_symbol": [{**bar(stamp), "symbol": "OTHER"}],
            "bad_shape": [[]],
            "wrong_end": [bar(stamp - source.HOUR_MS)],
            "alias_conflict": [{**bar(stamp), "openTime": stamp - source.HOUR_MS}],
            "fraction_timestamp": [{**bar(stamp), "time": float(stamp) + .5}],
        }
        for name, rows in cases.items():
            with self.subTest(name=name), self.assertRaises(source.SourceIntegrityError):
                source.decode_page(payload(rows), "BTC-USDT", stamp, 1000)

    def test_array_schema_is_lossless_and_clock_sorted(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        rows = [[last, "100", "102", "99", "101", "10"],
                [last - source.HOUR_MS, "100", "102", "99", "101", "10"]]
        result = source.decode_page(payload(rows), "BTC-USDT", last, 1000)
        self.assertEqual([x["ts_ms"] for x in result], [last - source.HOUR_MS, last])

    def test_api_error_empty_rows_and_duplicate_json_keys_rejected(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        cases = (b'{"code":0,"code":0,"data":[]}', payload([]),
                 source.canonical_bytes({"code": 109400, "msg": "error", "data": []}),
                 source.canonical_bytes({"code": False, "data": []}),
                 source.canonical_bytes([]))
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(source.SourceIntegrityError):
                source.decode_page(raw, "BTC-USDT", last, 1000)

    def test_redirect_retains_original_error_response_without_followup_get(self):
        self.assertIsNone(source._NoRedirect().redirect_request(
            None, None, 302, "redirect", {}, "https://other.invalid"))
        body = b"synthetic original redirect response"
        error = urllib.error.HTTPError(source.ENDPOINT, 302, "Found",
                                       {"Location": "https://other.invalid"}, io.BytesIO(body))
        opener = Mock()
        opener.open.side_effect = error
        with patch.object(source.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(source.SourceIntegrityError, "HTTP_STATUS:302"):
                source.collect(self.contract_path, self.output, transport=self.original_http_transport)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual((self.output / "raw/BTC-USDT_00.bin").read_bytes(), body)
        meta = json.loads((self.output / "raw/BTC-USDT_00.response.json").read_text())
        self.assertEqual(meta["http_status"], 302)
        self.assertEqual(meta["response_headers"]["Location"], "https://other.invalid")
        self.assertFalse((self.output / "DATA_FREEZE.json").exists())


if __name__ == "__main__":
    unittest.main()
