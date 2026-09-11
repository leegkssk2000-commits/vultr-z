"""Synthetic timestamp/transport fixtures only; no market or economic execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_common_source_v4 as source
from backend.research.rebuild.test_trendrider_rest_ws_timestamp_v1 import write_synthetic_calibration


def decode_page(raw, symbol, upper, remaining, limit, **kwargs):
    return source.decode_page(raw, symbol, upper, remaining, limit,
                              lane=kwargs.get("lane", "OBJECT_TIME_OPEN"),
                              close_delta_ms=kwargs.get("close_delta_ms", source.HOUR_MS - 1))


def contract(semantic_raw):
    return {"source": {
        "endpoint": source.ENDPOINT, "symbols": list(source.SYMBOLS), "interval": "1h",
        "cutoff_ms": source.CUTOFF_MS, "first_open_ms": source.FIRST_OPEN_MS,
        "bars_per_symbol": source.BAR_COUNT, "page_limit": source.BAR_COUNT,
        "max_pages_per_symbol": source.MAX_PAGES,
    }}


def bar(stamp):
    return {"time": stamp, "open": "100", "high": "102", "low": "99",
            "close": "101", "volume": "10"}


def payload(rows):
    return source.canonical_bytes({"code": 0, "data": rows})


class SourceV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.contract_path = self.base / "contract.json"
        self.semantic_path = write_synthetic_calibration(self.base / "witness")
        self.semantic_receipt = json.loads(self.semantic_path.read_bytes())
        self.contract_path.write_bytes(source.canonical_bytes(contract(self.semantic_path.read_bytes())))
        self.authorization_path = self.base / "authorization.json"
        self.seal_authorization()
        self.output = self.base / "data"
        self.calls = []
        self.monotonic_value = 0.0
        self.real_network = patch.object(source, "http_transport", side_effect=AssertionError("NO_NETWORK"))
        self.real_network.start()
        self.addCleanup(self.real_network.stop)

    def seal_authorization(self):
        value = source.authorization_template(source.digest_bytes(self.contract_path.read_bytes()),
                                              source.digest_bytes(self.semantic_path.read_bytes()))
        self.authorization_path.write_bytes(source.canonical_bytes(value))
        self.authorization_sha = source.digest_bytes(self.authorization_path.read_bytes())

    def sleep(self, seconds):
        self.monotonic_value += seconds

    def collect(self, transport=None):
        return source.collect(self.contract_path, self.semantic_path, self.output,
                              authorization_path=self.authorization_path,
                              expected_authorization_sha256=self.authorization_sha,
                              transport=transport or self.inclusive_transport,
                              monotonic=lambda: self.monotonic_value, sleep=self.sleep)

    def response(self, params, inclusive=True, cap=None):
        self.assertTrue((self.output / "ATTEMPT_STARTED_V4.json").exists())
        self.calls.append(dict(params))
        logical_upper = params["endTime"] + 1
        latest = logical_upper if inclusive else logical_upper - source.HOUR_MS
        count = min(params["limit"], cap or params["limit"])
        rows = [bar(latest - index * source.HOUR_MS) for index in range(count)]
        return source.Response(200, {"fixture": "synthetic"}, payload(rows))

    def inclusive_transport(self, endpoint, params, headers):
        self.assertEqual(headers, source.REQUEST_HEADERS)
        self.assertEqual(endpoint, source.ENDPOINT)
        return self.response(params)

    def strict_transport(self, endpoint, params, headers):
        self.assertEqual(headers, source.REQUEST_HEADERS)
        self.assertEqual(endpoint, source.ENDPOINT)
        return self.response(params, inclusive=False)

    def assert_exact_clocks(self, result):
        expected = list(range(source.FIRST_OPEN_MS, source.CUTOFF_MS, source.HOUR_MS))
        clocks = []
        for symbol in source.SYMBOLS:
            info = result["normalized"][symbol]
            raw = (self.output / info["path"]).read_bytes()
            self.assertEqual(info["sha256"], source.digest_bytes(raw))
            rows = json.loads(raw)
            clocks.append([row["ts_ms"] for row in rows])
            self.assertEqual(clocks[-1], expected)
            self.assertEqual(info["last_close_ms"], source.CUTOFF_MS - 1)
            self.assertEqual(info["last_close_exclusive_ms"], source.CUTOFF_MS)
            self.assertTrue(all(row["symbol"] == symbol for row in rows))
            self.assertEqual(set(rows[0]), {"symbol", "ts_ms", "open", "high", "low", "close", "volume"})
        self.assertEqual(clocks[0], clocks[1])

    def test_inclusive_upper_guard_repair_uses_two_pages_and_exact_clock(self):
        result = self.collect()
        self.assertEqual(result["pages_per_symbol"], {"BTC-USDT": 2, "ETH-USDT": 2})
        self.assertEqual(result["http_get_count"], 4)
        self.assertEqual(result["raw_rows"], 2004)
        self.assertEqual(result["admitted_rows"], 2000)
        self.assertEqual(result["guard_rows"], 4)
        self.assertEqual(result["guard_rows_economic_input"], 0)
        self.assertEqual([call["limit"] for call in self.calls], [1000, 2, 1000, 2])
        self.assertEqual(self.calls[1]["endTime"], source.FIRST_OPEN_MS + source.HOUR_MS - 1)
        first, second = result["pages"][:2]
        self.assertEqual(first["guards"][0]["native_open_ms"], source.CUTOFF_MS)
        self.assertEqual(second["guards"][0]["native_open_ms"], min(first["admitted_native_timestamps"]))
        self.assert_exact_clocks(result)

    def test_strict_endpoint_needs_no_guard_or_second_page(self):
        result = self.collect(self.strict_transport)
        self.assertEqual(result["http_get_count"], 2)
        self.assertEqual(result["guard_rows"], 0)
        self.assertEqual(result["admitted_rows"], 2000)
        self.assert_exact_clocks(result)

    def test_guard_and_no_guard_have_identical_normalized_bytes(self):
        inclusive = self.collect()
        raw1 = {symbol: (self.output / info["path"]).read_bytes()
                for symbol, info in inclusive["normalized"].items()}
        self.output = self.base / "second_independent_synthetic_fixture"
        strict = self.collect(self.strict_transport)
        for symbol, info in strict["normalized"].items():
            self.assertEqual(raw1[symbol], (self.output / info["path"]).read_bytes())
        self.assertEqual(inclusive["dataset_sha256"], strict["dataset_sha256"])

    def test_short_strict_page_final_lower_guard_is_bounded_extra(self):
        def short(endpoint, params, headers):
            return self.response(params, inclusive=False, cap=600 if params["limit"] == 1000 else None)
        result = self.collect(short)
        self.assertEqual([call["limit"] for call in self.calls], [1000, 401, 1000, 401])
        self.assertEqual(result["http_get_count"], 4)
        guards = [guard for page in result["pages"] for guard in page["guards"]]
        self.assertTrue(all(guard["reason"] == "LOWER_BOUNDARY_EXTRA_GUARD" for guard in guards))
        self.assertTrue(all(guard["native_open_ms"] == source.FIRST_OPEN_MS - source.HOUR_MS for guard in guards))
        self.assert_exact_clocks(result)

    def test_success_at_exact_three_page_budget(self):
        def short(endpoint, params, headers):
            return self.response(params, inclusive=True, cap=401)
        result = self.collect(short)
        self.assertEqual(result["http_get_count"], 6)
        self.assertEqual(result["pages_per_symbol"], {"BTC-USDT": 3, "ETH-USDT": 3})
        self.assert_exact_clocks(result)

    def test_attempt_is_exclusive_success_cannot_resume(self):
        self.collect()
        with self.assertRaisesRegex(source.SourceIntegrityError, "NO_RESUME"):
            self.collect()
        self.assertEqual(len(self.calls), 4)

    def test_attempt_open_xb_handles_concurrent_claim(self):
        original = source.write_once
        def race(path, raw):
            if path.name == "ATTEMPT_STARTED_V4.json":
                path.write_bytes(b"other claimant")
            return original(path, raw)
        with patch.object(source, "write_once", side_effect=race):
            with self.assertRaisesRegex(source.SourceIntegrityError, "ATTEMPT_ALREADY_CONSUMED"):
                self.collect()
        self.assertEqual(self.calls, [])

    def test_raw_and_response_metadata_persist_before_page_decode(self):
        original = source.decode_page
        def observing(raw, symbol, upper, remaining, limit, **kwargs):
            index = 0 if upper == source.CUTOFF_MS else 1
            stem = self.output / f"raw/{symbol}_{index:02d}"
            self.assertEqual(stem.with_suffix(".bin").read_bytes(), raw)
            meta = json.loads(stem.with_suffix(".response.json").read_bytes())
            self.assertEqual(meta["raw_sha256"], source.digest_bytes(raw))
            self.assertTrue(meta["saved_before_decode"])
            return original(raw, symbol, upper, remaining, limit, **kwargs)
        with patch.object(source, "decode_page", side_effect=observing):
            self.collect()

    def test_guard_numeric_ohlc_is_never_interpreted(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        guard = {**bar(source.CUTOFF_MS), "open": "NOT_A_PRICE", "close": {"unused": True}}
        admitted, detail = decode_page(payload([guard, bar(last)]),
                                             "BTC-USDT", source.CUTOFF_MS, 1000, 1000)
        self.assertEqual([row["ts_ms"] for row in admitted], [last])
        self.assertEqual(detail["guards"][0]["ohlc_values_interpreted"], False)
        self.assertEqual(detail["guard_rows_economic_input"], 0)

    def test_guard_shape_and_aliases_still_fail_closed(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        for guard in ({"time": source.CUTOFF_MS},
                      {**bar(source.CUTOFF_MS), "openTime": last},
                      {**bar(source.CUTOFF_MS), "symbol": "OTHER"}):
            with self.subTest(guard=guard), self.assertRaises(source.SourceIntegrityError):
                decode_page(payload([guard, bar(last)]), "BTC-USDT", source.CUTOFF_MS, 1000, 1000)

    def test_semantic_failure_is_before_attempt_and_get(self):
        original = copy.deepcopy(self.semantic_receipt)
        updates = ({"state": "BLOCKED_REST_WS_TIMESTAMP_WITNESS"},
                   {"canonical_open_transform": "SHIFT_MINUS_ONE_HOUR"},
                   {"supported_canonical_lane": "ALIASED_ANY"},
                   {"canonical_close_rule": "ARBITRARY_CURSOR"},
                   {"timestamp_adjustment_ms": True},
                   {"symbol": "ETH-USDT"})
        for update in updates:
            value = {key: val for key, val in original.items() if key != "receipt_sha256"}
            value.update(update)
            raw = source.canonical_bytes(source.v1._sealed(value))
            self.semantic_path.write_bytes(raw)
            self.seal_authorization()
            with self.subTest(update=update), self.assertRaisesRegex(source.SourceIntegrityError, "BLOCKED_REST_WS_TIMESTAMP_WITNESS"):
                self.collect()
            self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_semantic_raw_sha_and_internal_sha_both_required(self):
        raw = self.semantic_path.read_bytes()
        self.semantic_path.write_bytes(raw + b" ")
        with self.assertRaisesRegex(source.SourceIntegrityError, "AUTHORIZATION_BINDING_OR_SEAL_MISMATCH"):
            self.collect()
        value = copy.deepcopy(self.semantic_receipt)
        value["receipt_sha256"] = "0" * 64
        self.semantic_path.write_bytes(source.canonical_bytes(value))
        self.seal_authorization()
        with self.assertRaisesRegex(source.SourceIntegrityError, "RECEIPT_HASH|SEAL"):
            self.collect()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_contradictory_sealed_pass_cannot_authorize_attempt_or_get(self):
        original = copy.deepcopy(self.semantic_receipt)
        for update in ({"ws_close_ms": original["witness"]["ws_open_ms"] + source.HOUR_MS + 1},
                       {"ohlc_exact_match": False}, {"ws_open_ms": True}):
            value = {key: item for key, item in original.items() if key != "receipt_sha256"}
            value["witness"] = {**value["witness"], **update}
            self.semantic_path.write_bytes(source.canonical_bytes(source.v1._sealed(value)))
            self.seal_authorization()
            with self.subTest(update=update), self.assertRaisesRegex(source.SourceIntegrityError, "BLOCKED_REST_WS_TIMESTAMP_WITNESS"):
                self.collect()
            self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_invalid_contracts_block_before_attempt(self):
        original = contract(self.semantic_path.read_bytes())
        for key, value in (("cutoff_ms", source.CUTOFF_MS + source.HOUR_MS),
                           ("first_open_ms", source.FIRST_OPEN_MS - source.HOUR_MS),
                           ("interval", "4h"), ("symbols", ["BTC-USDT"]),
                           ("max_pages_per_symbol", 4), ("bars_per_symbol", 999),
                           ("endpoint", "https://unapproved.invalid"),
                           ("page_limit", 1001)):
            changed = copy.deepcopy(original)
            changed["source"][key] = value
            self.contract_path.write_bytes(source.canonical_bytes(changed))
            with self.subTest(key=key), self.assertRaises(source.SourceIntegrityError):
                self.collect()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_contract_and_semantic_mutation_prevents_next_get(self):
        for path in (self.contract_path, self.semantic_path, self.authorization_path):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                self.output = self.base / path.stem
                calls_before = len(self.calls)
                def mutate(endpoint, params, headers):
                    result = self.inclusive_transport(endpoint, params, headers)
                    path.write_bytes(original + b" ")
                    return result
                with self.assertRaisesRegex(source.SourceIntegrityError, "CHANGED_DURING_FETCH"):
                    self.collect(mutate)
                self.assertEqual(len(self.calls) - calls_before, 1)
                self.assertFalse((self.output / "DATA_FREEZE_V4.json").exists())
                path.write_bytes(original)

    def test_http_error_preserves_raw_and_forbids_retry(self):
        def denied(endpoint, params, headers):
            self.calls.append(dict(params))
            return source.Response(403, {"Content-Type": "text/html"}, b"synthetic denial")
        with self.assertRaisesRegex(source.SourceIntegrityError, "HTTP_STATUS:403"):
            self.collect(denied)
        self.assertEqual((self.output / "raw/BTC-USDT_00.bin").read_bytes(), b"synthetic denial")
        failure = json.loads((self.output / "FAILURE_MANIFEST_V4.json").read_bytes())
        self.assertEqual(failure["http_get_count"], 1)
        self.assertEqual(failure["transport_retries"], 0)
        self.assertEqual(failure["economic_runs"], 0)
        with self.assertRaisesRegex(source.SourceIntegrityError, "NO_RESUME"):
            self.collect(denied)
        self.assertEqual(len(self.calls), 1)

    def test_transport_timeout_consumes_single_get_and_no_retry(self):
        def disconnected(endpoint, params, headers):
            self.calls.append(dict(params))
            raise TimeoutError("synthetic timeout")
        with self.assertRaisesRegex(source.SourceIntegrityError, "ACQUISITION_FAILED:TimeoutError"):
            self.collect(disconnected)
        failure = json.loads((self.output / "FAILURE_MANIFEST_V4.json").read_bytes())
        self.assertEqual(failure["http_get_count"], 1)
        self.assertEqual(failure["http_response_count"], 0)
        self.assertEqual(failure["error_type"], "TimeoutError")
        self.assertEqual(len(self.calls), 1)

    def test_page_budget_exhaustion_stops_at_three_first_symbol_gets(self):
        def tiny(endpoint, params, headers):
            return self.response(params, inclusive=True, cap=2)
        with self.assertRaisesRegex(source.SourceIntegrityError, "PAGE_BUDGET_EXHAUSTED"):
            self.collect(tiny)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all(call["symbol"] == "BTC-USDT" for call in self.calls))
        self.assertFalse((self.output / "DATA_FREEZE_V4.json").exists())

    def test_guard_only_page_fails_stall_without_retry(self):
        def stalled(endpoint, params, headers):
            self.calls.append(dict(params))
            return source.Response(200, {}, payload([bar(params["endTime"] + 1)]))
        with self.assertRaisesRegex(source.SourceIntegrityError, "PAGINATION_STALLED"):
            self.collect(stalled)
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_same_conflicting_and_guard_timestamps_all_fail(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        cases = ([bar(last), bar(last)],
                 [bar(last), {**bar(last), "close": "100"}],
                 [bar(source.CUTOFF_MS), bar(source.CUTOFF_MS), bar(last)])
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaisesRegex(source.SourceIntegrityError, "DUPLICATE_TIMESTAMP"):
                decode_page(payload(rows), "BTC-USDT", source.CUTOFF_MS, 1000, 1000)

    def test_malformed_and_off_window_rows_are_not_dropped(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        cases = {
            "gap": [bar(last), bar(last - 2 * source.HOUR_MS)],
            "offgrid": [bar(last + 1)],
            "future_not_guard": [bar(source.CUTOFF_MS + source.HOUR_MS), bar(last)],
            "too_old_not_guard": [bar(source.FIRST_OPEN_MS - 2 * source.HOUR_MS), bar(last)],
            "unbounded_lower_guard": [bar(source.FIRST_OPEN_MS - source.HOUR_MS), bar(last)],
            "missing_volume": [{key: value for key, value in bar(last).items() if key != "volume"}],
            "negative_volume": [{**bar(last), "volume": -1}],
            "nonfinite": [{**bar(last), "open": "NaN"}],
            "bad_ohlc": [{**bar(last), "high": 50}],
            "wrong_symbol": [{**bar(last), "symbol": "OTHER"}],
            "bad_shape": [[]],
            "wrong_end": [bar(last - source.HOUR_MS)],
            "alias_conflict": [{**bar(last), "openTime": last - source.HOUR_MS}],
            "fraction_timestamp": [{**bar(last), "time": float(last) + .5}],
        }
        for name, rows in cases.items():
            with self.subTest(name=name), self.assertRaises(source.SourceIntegrityError):
                decode_page(payload(rows), "BTC-USDT", source.CUTOFF_MS, 1000, 1000)

    def test_api_shape_json_and_page_count_errors(self):
        cases = (b"{broken", b'{"code":0,"code":0,"data":[]}', payload([]),
                 source.canonical_bytes({"code": 1, "data": []}),
                 source.canonical_bytes({"code": False, "data": []}),
                 source.canonical_bytes([]), b'{"code":0,"data":[NaN]}',
                 payload([bar(source.CUTOFF_MS - i * source.HOUR_MS) for i in range(1001)]))
        for raw in cases:
            with self.subTest(raw=raw[:60]), self.assertRaises(source.SourceIntegrityError):
                decode_page(raw, "BTC-USDT", source.CUTOFF_MS, 1000, 1000)

    def test_array_schema_preserves_native_open_and_explicit_close(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        for delta in (source.HOUR_MS - 1, source.HOUR_MS):
            rows = [[source.CUTOFF_MS, "unused", "unused", "unused", "unused", "unused", source.CUTOFF_MS + delta],
                    [last, "100", "102", "99", "101", "10", last + delta]]
            normalized, detail = decode_page(payload(rows), "BTC-USDT", source.CUTOFF_MS, 1000, 1000,
                                             lane="ARRAY_OPEN_CLOSE", close_delta_ms=delta)
            self.assertEqual(normalized[0]["ts_ms"], last)
            self.assertEqual(normalized[0]["close"], 101.0)
            self.assertEqual(detail["canonical_timestamp_offset_ms"], 0)

    def test_native_lane_never_falls_back_to_other_schema_or_alias(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        array = [last, "100", "102", "99", "101", "10", last + source.HOUR_MS - 1]
        cases = [(array, "OBJECT_TIME_OPEN"), (bar(last), "ARRAY_OPEN_CLOSE"),
                 ({**bar(last), "openTime": last}, "OBJECT_TIME_OPEN"),
                 ({**bar(last), "timestamp": last}, "OBJECT_TIME_OPEN"),
                 ({**bar(last), "vol": "10"}, "OBJECT_TIME_OPEN")]
        for row, lane in cases:
            with self.subTest(row=row), self.assertRaises(source.SourceIntegrityError):
                decode_page(payload([row]), "BTC-USDT", source.CUTOFF_MS, 1000, 1000, lane=lane)

    def test_array_close_malformed_or_wrong_convention_blocks_even_guard(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        for closed in (True, "bad", source.CUTOFF_MS + source.HOUR_MS, "001", None):
            guard = [source.CUTOFF_MS, "unused", "unused", "unused", "unused", "unused", closed]
            row = [last, "100", "102", "99", "101", "10", last + source.HOUR_MS - 1]
            with self.subTest(closed=closed), self.assertRaises(source.SourceIntegrityError):
                decode_page(payload([guard, row]), "BTC-USDT", source.CUTOFF_MS, 1000, 1000,
                            lane="ARRAY_OPEN_CLOSE")

    def test_combined_hash_uses_v1_compact_sorted_json_newline(self):
        result = self.collect()
        expected = source.v1.digest_bytes(source.v1.canonical_bytes(result["normalized"]))
        pretty = (json.dumps(result["normalized"], sort_keys=True, indent=2) + "\n").encode()
        self.assertEqual(result["dataset_sha256"], expected)
        self.assertNotEqual(result["dataset_sha256"], source.digest_bytes(pretty))

    def test_authorization_raw_hash_seal_and_budget_must_match(self):
        original = self.authorization_path.read_bytes()
        for alteration in ({"max_http_requests": 7}, {"retry_authorized": True},
                           {"contract_sha256": "0" * 64}, {"dataset_fetch_attempts": 2}):
            value = json.loads(original)
            value.pop("receipt_sha256")
            value.update(alteration)
            self.authorization_path.write_bytes(source.canonical_bytes(source.v1._sealed(value)))
            self.authorization_sha = source.digest_bytes(self.authorization_path.read_bytes())
            with self.subTest(alteration=alteration), self.assertRaisesRegex(source.SourceIntegrityError, "AUTHORIZATION_BINDING_OR_SEAL_MISMATCH"):
                self.collect()
        self.authorization_sha = "0" * 64
        with self.assertRaisesRegex(source.SourceIntegrityError, "AUTHORIZATION_RAW_SHA_MISMATCH"):
            self.collect()
        self.assertEqual(self.calls, [])

    def test_mutation_during_spacing_blocks_following_http(self):
        original = self.authorization_path.read_bytes()
        def sleeping(seconds):
            self.monotonic_value += seconds
            self.authorization_path.write_bytes(original + b" ")
        self.sleep = sleeping
        with self.assertRaisesRegex(source.SourceIntegrityError, "AUTHORIZATION_CHANGED_DURING_FETCH"):
            self.collect()
        self.assertEqual(len(self.calls), 1)
        failure = json.loads((self.output / "FAILURE_MANIFEST_V4.json").read_bytes())
        self.assertEqual(failure["http_get_count"], 1)

    def test_request_metadata_and_count_reserved_before_transport(self):
        def check(endpoint, params, headers):
            matches = list((self.output / "raw").glob("*.request.json"))
            self.assertEqual(len(matches), len(self.calls) + 1)
            self.assertEqual(headers, source.REQUEST_HEADERS)
            for path in matches:
                request = json.loads(path.read_bytes())
                self.assertEqual(request["request_headers"], source.REQUEST_HEADERS)
                self.assertEqual(request["method"], "GET")
            return self.inclusive_transport(endpoint, params, headers)
        result = self.collect(check)
        self.assertEqual(result["http_get_count"], 4)
        self.assertGreaterEqual(self.monotonic_value, 3 * source.MIN_REQUEST_SPACING_MS / 1000)

    def test_transport_enforces_explicit_wire_headers_and_no_redirect(self):
        params = {"symbol": "BTC-USDT", "interval": "1h", "limit": 1000,
                  "endTime": source.CUTOFF_MS - 1}
        request = source._request(source.ENDPOINT, params, source.REQUEST_HEADERS)
        self.assertEqual({key.lower(): value for key, value in request.header_items()},
                         {key.lower(): value for key, value in source.REQUEST_HEADERS.items()})
        for changed in ({**params, "limit": 1001}, {**params, "startTime": 0},
                        {**params, "symbol": "OTHER"}, {**params, "endTime": source.CUTOFF_MS}):
            with self.subTest(params=changed), self.assertRaises(source.SourceIntegrityError):
                source._request(source.ENDPOINT, changed, source.REQUEST_HEADERS)
        with self.assertRaises(source.SourceIntegrityError):
            source._request(source.ENDPOINT, params, {"Accept": "application/json"})
        self.assertIsNone(source.v1._NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_truncated_raw_is_retained_and_never_decoded(self):
        raw = b"x" * (source.MAX_RESPONSE_BYTES + 1)
        def oversized(endpoint, params, headers):
            self.calls.append(dict(params))
            return source.Response(200, {}, raw)
        with self.assertRaisesRegex(source.SourceIntegrityError, "SOURCE_PAGE_PARAMETERS_INVALID"):
            self.collect(oversized)
        meta = json.loads((self.output / "raw/BTC-USDT_00.response.json").read_bytes())
        self.assertTrue(meta["response_truncated"])
        self.assertEqual((self.output / "raw/BTC-USDT_00.bin").read_bytes(), raw)
        self.assertEqual(len(self.calls), 1)
    def test_raw_linked_witness_mutation_before_attempt_blocks_all_source(self):
        witness = self.semantic_receipt["witness"]
        raw_path = self.semantic_path.parent / witness["ws_raw_path"]
        raw_path.write_bytes(raw_path.read_bytes() + b"mutation")
        with self.assertRaisesRegex(source.SourceIntegrityError, "REST_WS_ARTIFACT_HASH"):
            self.collect()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_raw_linked_witness_mutation_during_pacing_blocks_next_get(self):
        raw_path = self.semantic_path.parent / self.semantic_receipt["witness"]["rest_raw_path"]
        def sleeping(seconds):
            self.monotonic_value += seconds
            raw_path.write_bytes(raw_path.read_bytes() + b"mutation")
        self.sleep = sleeping
        with self.assertRaisesRegex(source.SourceIntegrityError, "REST_WS_ARTIFACT_HASH"):
            self.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.output / "DATA_FREEZE_V4.json").exists())

    def test_raw_linked_witness_mutation_after_fetch_preserves_raw_and_blocks_decode(self):
        raw_path = self.semantic_path.parent / self.semantic_receipt["witness"]["rest_raw_path"]
        def mutating(endpoint, params, headers):
            response = self.inclusive_transport(endpoint, params, headers)
            raw_path.write_bytes(raw_path.read_bytes() + b"mutation")
            return response
        with patch.object(source, "decode_page", side_effect=AssertionError("NO_SOURCE_DECODE")):
            with self.assertRaisesRegex(source.SourceIntegrityError, "REST_WS_ARTIFACT_HASH"):
                self.collect(mutating)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue((self.output / "raw/BTC-USDT_00.bin").exists())
        self.assertTrue((self.output / "raw/BTC-USDT_00.response.json").exists())

    def test_object_exclusive_native_ws_close_uses_inclusive_canonical_close(self):
        self.semantic_path = write_synthetic_calibration(self.base / "exclusive_object_witness",
                                                        close_delta=source.HOUR_MS)
        self.seal_authorization()
        result = self.collect()
        self.assertEqual(result["native_ws_close_delta_ms"], source.HOUR_MS)
        self.assertEqual(result["canonical_close_delta_ms"], source.HOUR_MS - 1)
        self.assert_exact_clocks(result)

    def test_full_array_source_requires_actual_raw_linked_array_witness(self):
        for delta in (source.HOUR_MS - 1, source.HOUR_MS):
            with self.subTest(delta=delta):
                self.semantic_path = write_synthetic_calibration(self.base / ("array_" + str(delta)),
                                                                schema="array", close_delta=delta)
                self.output = self.base / ("array_source_" + str(delta))
                self.seal_authorization()
                def arrays(endpoint, params, headers):
                    response = self.inclusive_transport(endpoint, params, headers)
                    rows = json.loads(response.body)["data"]
                    return source.Response(200, {}, payload([[r["time"], r["open"], r["high"], r["low"],
                                                              r["close"], r["volume"], r["time"] + delta]
                                                             for r in rows]))
                result = self.collect(arrays)
                self.assertEqual(result["native_ws_close_delta_ms"], delta)
                self.assertEqual(result["canonical_close_delta_ms"], delta)
                self.assertEqual(result["supported_canonical_lane"], "ARRAY_OPEN_CLOSE")
                for symbol, info in result["normalized"].items():
                    rows = json.loads((self.output / info["path"]).read_bytes())
                    self.assertEqual([r["ts_ms"] for r in rows],
                                     list(range(source.FIRST_OPEN_MS, source.CUTOFF_MS, source.HOUR_MS)))
                    self.assertEqual(info["last_close_ms"], source.CUTOFF_MS - source.HOUR_MS + delta)


if __name__ == "__main__":
    unittest.main()
