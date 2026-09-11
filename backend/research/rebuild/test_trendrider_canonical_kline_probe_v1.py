"""Synthetic calibration fixtures only; no market HTTP or economic execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from backend.research.rebuild import trendrider_canonical_kline_probe_v1 as probe


def candle(stamp, convention=probe.HOUR_MS - 1):
    # Deliberately invalid numeric values prove timestamp-only interpretation.
    return [stamp, "NOT_A_PRICE", {"unused": True}, None, ["unused"], "NOT_VOLUME", stamp + convention]


def object_candle(stamp):
    return {"time": stamp, "openTime": stamp, "closeTime": stamp + probe.HOUR_MS,
            "open": "NOT_A_PRICE", "high": {}, "low": None, "close": [], "volume": "unused"}


def payload(rows):
    return probe.canonical_bytes({"code": 0, "data": rows})


class CanonicalKlineProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.authority = self.base / "authority.json"
        self.authority.write_bytes(probe.canonical_bytes({"synthetic": True, "official_array_open_index": 0}))
        self.protocol = self.base / "protocol.json"
        self.protocol.write_bytes(probe.canonical_bytes(probe.protocol_template(probe.digest_bytes(self.authority.read_bytes()))))
        self.output = self.base / "calibration"
        self.calls = []
        self.clock = 0.0
        def sleep(seconds):
            self.clock += seconds
        self.monotonic = patch.object(probe.time, "monotonic", side_effect=lambda: self.clock)
        self.sleep = patch.object(probe.time, "sleep", side_effect=sleep)
        self.no_network = patch.object(probe, "http_transport", side_effect=AssertionError("NO_MARKET_NETWORK_IN_TESTS"))
        for patcher in (self.monotonic, self.sleep, self.no_network):
            patcher.start()
            self.addCleanup(patcher.stop)

    def collect(self, transport=None):
        return probe.probe(self.protocol, self.authority, self.output,
                           transport=transport or self.transport)

    def transport(self, endpoint, params, headers):
        self.assertEqual(endpoint, probe.ENDPOINT)
        self.assertEqual(headers, probe.REQUEST_HEADERS)
        self.assertTrue((self.output / "CALIBRATION_ATTEMPT_STARTED.json").exists())
        name = "A" if not self.calls else "B"
        meta = json.loads((self.output / f"raw/probe_{name}.request.json").read_bytes())
        self.assertEqual(meta["request_headers"]["X-SOURCE-KEY"], "BX-AI-SKILL")
        self.assertEqual(meta["params"], params)
        self.assertIn("startTime=" + str(params["startTime"]), meta["query"])
        self.calls.append({"params": params, "clock": self.clock})
        return probe.Response(200, {"fixture": "synthetic"}, payload([candle(params["startTime"])]))

    def assert_blocked(self, result, reason, calls=2):
        self.assertEqual(result["state"], "BLOCKED_CANONICAL_KLINE_SCHEMA")
        self.assertIn(reason, result["reasons"])
        self.assertEqual(result["actual_http_calls"], calls)
        self.assertFalse(result["object_time_mapping_authorized"])
        self.assertFalse(result["acquisition_authorized"])
        self.assertEqual(result["economic_executions"], 0)

    def test_inclusive_native_array_passes_without_touching_ohlc(self):
        result = self.collect()
        self.assertEqual(result["state"], "PASS_CANONICAL_KLINE_ARRAY")
        self.assertEqual(result["native_close_convention"], "INCLUSIVE_LAST_MILLISECOND")
        self.assertEqual(result["actual_http_calls"], 2)
        self.assertEqual(result["supported_canonical_lane"], "ARRAY_ONLY")
        self.assertTrue(all(not item["ohlc_values_interpreted"] for item in result["probe_outcomes"]))
        self.assertGreaterEqual(self.calls[1]["clock"] - self.calls[0]["clock"], 1.1)
        for raw in result["raw_responses"]:
            self.assertEqual(raw["raw_sha256"], probe.digest_bytes((self.output / raw["raw_path"]).read_bytes()))
        unsigned = {key: value for key, value in result.items() if key != "receipt_sha256"}
        self.assertEqual(result["receipt_sha256"], probe.digest_bytes(probe.canonical_bytes(unsigned)))

    def test_exclusive_close_convention_passes(self):
        def transport(endpoint, params, headers):
            return probe.Response(200, {}, payload([candle(params["startTime"], probe.HOUR_MS)]))
        result = self.collect(transport)
        self.assertEqual(result["state"], "PASS_CANONICAL_KLINE_ARRAY")
        self.assertEqual(result["native_close_convention"], "EXCLUSIVE_NEXT_OPEN")

    def test_one_target_with_two_predeclared_guards_passes(self):
        def transport(endpoint, params, headers):
            t = params["startTime"]
            return probe.Response(200, {}, payload([candle(t + probe.HOUR_MS), candle(t), candle(t - probe.HOUR_MS)]))
        result = self.collect(transport)
        self.assertEqual(result["state"], "PASS_CANONICAL_KLINE_ARRAY")
        self.assertEqual([item["guard_count"] for item in result["probe_outcomes"]], [2, 2])
        self.assertEqual(result["guard_rows_economic_input"], 0)

    def test_close_convention_differs_between_adjacent_probes_blocks(self):
        def transport(endpoint, params, headers):
            convention = probe.HOUR_MS - (params["startTime"] == probe.PROBE_T_MS)
            return probe.Response(200, {}, payload([candle(params["startTime"], convention)]))
        self.assert_blocked(self.collect(transport), "PROBE_ADJACENT_CLOSE_CONVENTION_MISMATCH")

    def test_close_convention_mixed_within_page_blocks_but_observes_b(self):
        def transport(endpoint, params, headers):
            t = params["startTime"]
            return probe.Response(200, {}, payload([candle(t), candle(t + probe.HOUR_MS, probe.HOUR_MS)]))
        self.assert_blocked(self.collect(transport), "PROBE_NATIVE_CLOSE_CONVENTION")

    def test_object_explicit_time_open_close_is_not_cross_schema_proof(self):
        def transport(endpoint, params, headers):
            return probe.Response(200, {}, payload([object_candle(params["startTime"])]))
        result = self.collect(transport)
        self.assert_blocked(result, "OBJECT_TIME_WITHOUT_CROSS_SCHEMA_WITNESS")
        fields = result["probe_outcomes"][0]["object_timestamp_rows"][0]["timestamp_fields"]
        self.assertEqual(fields["time"], probe.PROBE_T_MS)
        self.assertEqual(fields["closeTime"], probe.PROBE_T_MS + probe.HOUR_MS)

    def test_array_one_probe_object_other_cannot_authorize_object(self):
        def transport(endpoint, params, headers):
            t = params["startTime"]
            row = candle(t) if t == probe.PROBE_T_MS else object_candle(t)
            return probe.Response(200, {}, payload([row]))
        self.assert_blocked(self.collect(transport), "OBJECT_TIME_WITHOUT_CROSS_SCHEMA_WITNESS")

    def test_mixed_schema_single_response_blocks(self):
        def transport(endpoint, params, headers):
            t = params["startTime"]
            return probe.Response(200, {}, payload([candle(t), object_candle(t)]))
        self.assert_blocked(self.collect(transport), "MIXED_OR_EMPTY_CANONICAL_KLINE_SCHEMA")

    def test_wrong_open_wrong_close_duplicate_extra_rows_all_fail(self):
        t = probe.PROBE_T_MS
        cases = [([candle(t + probe.HOUR_MS)], "PROBE_TARGET_OPEN_NOT_EXACTLY_ONCE"),
                 ([candle(t, 123)], "PROBE_NATIVE_CLOSE_CONVENTION"),
                 ([candle(t), candle(t)], "PROBE_DUPLICATE_OPEN_TIMESTAMP"),
                 ([candle(t + offset * probe.HOUR_MS) for offset in (-1, 0, 1, 2)], "PROBE_ROW_COUNT"),
                 ([candle(t), candle(t + 2 * probe.HOUR_MS)], "PROBE_OPEN_GRID_OR_GUARD_RANGE")]
        for rows, reason in cases:
            with self.subTest(reason=reason):
                result = probe.decode_timestamp_probe(payload(rows), t)
                self.assertEqual(result["state"], "FAIL_SEMANTIC")
                self.assertIn(reason, result["reasons"])

    def test_semantic_failure_observes_second_probe_without_retry(self):
        def transport(endpoint, params, headers):
            self.calls.append(dict(params))
            return probe.Response(200, {}, payload([candle(params["startTime"] + probe.HOUR_MS)]))
        self.assert_blocked(self.collect(transport), "PROBE_TARGET_OPEN_NOT_EXACTLY_ONCE")
        self.assertEqual([item["startTime"] for item in self.calls], [probe.PROBE_T_MS, probe.PROBE_T_MS + probe.HOUR_MS])

    def test_boolean_timestamp_fatal_and_no_second_probe(self):
        def transport(endpoint, params, headers):
            return probe.Response(200, {}, payload([candle(True)]))
        self.assert_blocked(self.collect(transport), "PROBE_TIMESTAMP_TYPE", calls=1)

    def test_duplicate_json_and_malformed_json_fatal(self):
        for index, raw in enumerate((b'{"code":0,"code":0,"data":[]}', b'{broken')):
            with self.subTest(raw=raw):
                self.output = self.base / str(index)
                def transport(endpoint, params, headers):
                    return probe.Response(200, {}, raw)
                result = self.collect(transport)
                self.assertEqual(result["actual_http_calls"], 1)
                self.assertEqual(result["state"], "BLOCKED_CANONICAL_KLINE_SCHEMA")
                self.assertEqual((self.output / "raw/probe_A.bin").read_bytes(), raw)

    def test_raw_and_response_metadata_saved_before_json_decode(self):
        original = probe.decode_timestamp_probe
        def observe(raw, target):
            name = "A" if target == probe.PROBE_T_MS else "B"
            prefix = self.output / ("raw/probe_" + name)
            self.assertEqual(prefix.with_suffix(".bin").read_bytes(), raw)
            metadata = json.loads(prefix.with_suffix(".response.json").read_bytes())
            self.assertTrue(metadata["saved_before_decode"])
            self.assertEqual(metadata["raw_sha256"], probe.digest_bytes(raw))
            return original(raw, target)
        with patch.object(probe, "decode_timestamp_probe", side_effect=observe):
            self.collect()

    def test_http_error_preserves_body_and_stops(self):
        def transport(endpoint, params, headers):
            return probe.Response(429, {"retry-after": "1"}, b'error response')
        result = self.collect(transport)
        self.assert_blocked(result, "PROBE_HTTP_STATUS:429", calls=1)
        self.assertEqual((self.output / "raw/probe_A.bin").read_bytes(), b'error response')

    def test_transport_error_consumes_call_without_fabricating_response(self):
        def transport(endpoint, params, headers):
            raise urllib.error.URLError("synthetic only")
        result = self.collect(transport)
        self.assert_blocked(result, "PROBE_TRANSPORT:URLError", calls=1)
        self.assertEqual(result["raw_responses"], [])
        self.assertFalse((self.output / "raw/probe_A.bin").exists())

    def test_oversized_saved_prefix_is_marked_truncated_no_length_claim(self):
        raw = b'x' * (probe.MAX_RESPONSE_BYTES + 1)
        def transport(endpoint, params, headers):
            return probe.Response(200, {}, raw)
        result = self.collect(transport)
        self.assert_blocked(result, "PROBE_RESPONSE_LIMIT", calls=1)
        metadata = result["raw_responses"][0]
        self.assertTrue(metadata["truncated"])
        self.assertFalse(metadata["full_response_length_known"])
        self.assertEqual(metadata["saved_raw_bytes"], len(raw))

    def test_attempt_exclusive_and_success_cannot_resume(self):
        self.collect()
        with self.assertRaisesRegex(probe.SourceIntegrityError, "NO_RESUME"):
            self.collect()
        self.assertEqual(len(self.calls), 2)

    def test_exclusive_marker_catches_racing_claimant(self):
        original = probe.write_once
        def race(path, raw):
            if path.name == "CALIBRATION_ATTEMPT_STARTED.json":
                path.write_bytes(b"prior claim")
            return original(path, raw)
        with patch.object(probe, "write_once", side_effect=race):
            with self.assertRaisesRegex(probe.SourceIntegrityError, "ATTEMPT_ALREADY_CONSUMED"):
                self.collect()
        self.assertEqual(self.calls, [])

    def test_changed_protocol_or_authority_rejected_before_reservation(self):
        self.authority.write_bytes(probe.canonical_bytes({"changed": True}))
        with self.assertRaisesRegex(probe.SourceIntegrityError, "PROTOCOL_OR_AUTHORITY_HASH"):
            self.collect()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_resealed_bool_and_budget_mutations_cannot_change_fixed_protocol(self):
        original = json.loads(self.protocol.read_bytes())
        for key, value in (("max_http_calls", 3), ("max_attempts", True), ("min_request_spacing_ms", 0)):
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed[key] = value
                changed.pop("receipt_sha256")
                self.protocol.write_bytes(probe.canonical_bytes(probe.v1._sealed(changed)))
                with self.assertRaisesRegex(probe.SourceIntegrityError, "PROTOCOL_OR_AUTHORITY_HASH"):
                    self.collect()
        self.assertEqual(self.calls, [])

    def test_protocol_template_headers_are_detached_from_global(self):
        template = probe.protocol_template("synthetic")
        template["request_headers"]["X-SOURCE-KEY"] = "MUTATED"
        self.assertEqual(probe.REQUEST_HEADERS["X-SOURCE-KEY"], "BX-AI-SKILL")

    def test_input_changed_during_probe_fails_closed(self):
        def transport(endpoint, params, headers):
            self.authority.write_bytes(probe.canonical_bytes({"changed_after_freeze": True}))
            return probe.Response(200, {}, payload([candle(params["startTime"])]))
        self.assert_blocked(self.collect(transport), "PROBE_PREREGISTERED_INPUT_CHANGED", calls=1)
        self.assertFalse((self.output / "raw/probe_B.request.json").exists())

    def test_input_changed_during_spacing_blocks_before_second_request(self):
        def mutate_during_spacing(seconds):
            self.clock += seconds
            self.authority.write_bytes(probe.canonical_bytes({"changed_during_spacing": True}))
        with patch.object(probe.time, "sleep", side_effect=mutate_during_spacing):
            result = self.collect()
        self.assert_blocked(result, "PROBE_PREREGISTERED_INPUT_CHANGED", calls=1)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.output / "raw/probe_B.request.json").exists())

    def test_http_transport_sends_declared_headers_has_cap_and_no_redirect(self):
        class FakeResponse:
            status = 200
            headers = {"fixture": "synthetic"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, count):
                self_outer.assertEqual(count, probe.MAX_RESPONSE_BYTES + 1)
                return b'{}'
        self_outer = self
        class FakeOpener:
            addheaders = [("User-Agent", "unexpected")]
            def open(self, request, timeout):
                self_outer.assertEqual(timeout, 30)
                self_outer.assertEqual(self.addheaders, [])
                self_outer.assertEqual(request.get_header("X-source-key"), "BX-AI-SKILL")
                self_outer.assertEqual(request.get_header("Accept"), "application/json")
                self_outer.assertEqual(request.get_header("Host"), "open-api.bingx.com")
                self_outer.assertEqual(request.get_header("User-agent"), "Python-urllib/3.12")
                self_outer.assertEqual(request.get_header("Accept-encoding"), "identity")
                return FakeResponse()
        # Restore original function locally; the opener itself is synthetic.
        self.no_network.stop()
        with patch.object(probe.urllib.request, "build_opener", return_value=FakeOpener()) as build:
            response = probe.http_transport(probe.ENDPOINT, probe.protocol_template("x")["probes"][0]["params"], probe.REQUEST_HEADERS)
        self.assertEqual(response.body, b'{}')
        self.assertIsInstance(build.call_args.args[0], probe._NoRedirect)
        self.assertIsNone(probe._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid"))


if __name__ == "__main__":
    unittest.main()
