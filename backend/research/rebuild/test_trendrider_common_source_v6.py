"""Synthetic V6 source guards and unchanged V5 decoding; no network/economics."""
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_common_source_v5 as previous
from backend.research.rebuild import trendrider_common_source_v6 as source


def contract():
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


def synthetic_semantic():
    # Source unit boundary only. Real raw-linked receipt validation is covered
    # by the observed timestamp module's independent synthetic integration.
    return {"schema": "trendrider.observed.ws.rest.timestamp.receipt.v1",
            "scope_key": source.SCOPE, "state": "PASS", "symbol": "BTC-USDT",
            "interval": "1h", "hour_ms": source.HOUR_MS,
            "timestamp_adjustment_ms": 0, "supported_canonical_lane": "OBJECT_TIME_OPEN",
            "canonical_open_transform": "IDENTITY_NATIVE_OBJECT_TIME_MS",
            "open_ts_rule": "native_T", "close_ts_rule": "open_ts + 1h",
            "provider_native_close_claim": False, "outcome_independent": True}


class SourceV6Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.contract_path = self.base / "contract.json"
        self.contract_path.write_bytes(source.canonical_bytes(contract()))
        self.semantic_path = self.base / "OBSERVED_WS_REST_TIMESTAMP_RECEIPT.json"
        self.semantic_path.write_bytes(source.canonical_bytes(synthetic_semantic()))
        self.authorization_path = self.base / "authorization.json"
        self.seal_authorization()
        self.output = self.base / "data"
        self.calls = []
        self.clock = 0.0
        def isolated_semantic(path, expected_sha):
            raw = Path(path).read_bytes()
            if source.digest_bytes(raw) != expected_sha:
                raise ValueError("SYNTHETIC_RAW_HASH")
            return json.loads(raw)
        self.semantic_patch = patch.object(source, "_calibration_validate", side_effect=isolated_semantic)
        self.semantic_patch.start()
        self.addCleanup(self.semantic_patch.stop)
        self.original_http_transport = source.http_transport
        self.network_patch = patch.object(source, "http_transport", side_effect=AssertionError("NO_NETWORK"))
        self.network_patch.start()
        self.addCleanup(self.network_patch.stop)

    def seal_authorization(self):
        value = source.authorization_template(source.digest_bytes(self.contract_path.read_bytes()),
                                              source.digest_bytes(self.semantic_path.read_bytes()))
        self.authorization_path.write_bytes(source.canonical_bytes(value))
        self.authorization_sha = source.digest_bytes(self.authorization_path.read_bytes())

    def sleep(self, seconds):
        self.clock += seconds

    def response(self, params, *, guard=True, cap=1000):
        self.assertTrue((self.output / "ATTEMPT_STARTED_V6.json").exists())
        self.calls.append(dict(params))
        upper = params["endTime"] + 1
        latest = upper if guard else upper - source.HOUR_MS
        rows = [bar(latest - i * source.HOUR_MS) for i in range(min(cap, params["limit"]))]
        return source.Response(200, {}, payload(rows))

    def transport(self, endpoint, params, headers):
        self.assertEqual(endpoint, source.ENDPOINT)
        self.assertEqual(headers, source.REQUEST_HEADERS)
        return self.response(params)

    def collect(self, transport=None):
        return source.collect(self.contract_path, self.semantic_path, self.output,
            authorization_path=self.authorization_path,
            expected_authorization_sha256=self.authorization_sha,
            transport=transport or self.transport, monotonic=lambda: self.clock, sleep=self.sleep)

    def test_inclusive_guards_and_backward_page_produce_exact1000_same_clock(self):
        result = self.collect()
        expected = list(range(source.FIRST_OPEN_MS, source.CUTOFF_MS, source.HOUR_MS))
        self.assertEqual(result["http_get_count"], 4)
        self.assertEqual(result["pages_per_symbol"], {s: 2 for s in source.SYMBOLS})
        self.assertEqual([p["limit"] for p in self.calls], [1000, 2, 1000, 2])
        self.assertEqual(result["guard_rows_economic_input"], 0)
        self.assertEqual(result["economic_runs"], 0)
        for symbol, record in result["normalized"].items():
            raw = (self.output / record["path"]).read_bytes()
            self.assertEqual(source.digest_bytes(raw), record["sha256"])
            rows = json.loads(raw)
            self.assertEqual([r["ts_ms"] for r in rows], expected)
            self.assertEqual(record["last_close_exclusive_ms"], source.CUTOFF_MS)
            self.assertEqual(record["last_close_ms"], source.CUTOFF_MS - 1)
            self.assertTrue(all(r["symbol"] == symbol for r in rows))
        self.assertEqual(result["close_ts_rule"], "open_ts + 1h")
        self.assertEqual(result["economic_close_delta_ms"], source.HOUR_MS)
        self.assertEqual(result["canonical_close_delta_ms"], source.HOUR_MS - 1)
        self.assertEqual(result["canonical_close_metadata_role"], "LEGACY_SOURCE_SERIALIZATION_ONLY")
        self.assertFalse(result["provider_native_close_claim"])

    def test_strict_and_guard_source_have_same_normalized_bytes_and_dataset_sha(self):
        guarded = self.collect()
        guarded_bytes = {s: (self.output / r["path"]).read_bytes() for s, r in guarded["normalized"].items()}
        self.output = self.base / "independent_synthetic_strict"
        strict = self.collect(lambda ep, p, h: self.response(p, guard=False))
        self.assertEqual(strict["http_get_count"], 2)
        self.assertEqual(strict["guard_rows"], 0)
        self.assertEqual(strict["dataset_sha256"], guarded["dataset_sha256"])
        for symbol, record in strict["normalized"].items():
            self.assertEqual((self.output / record["path"]).read_bytes(), guarded_bytes[symbol])

    def test_success_at_three_pages_and_failure_when_page_budget_consumed(self):
        result = self.collect(lambda ep, p, h: self.response(p, cap=401))
        self.assertEqual(result["http_get_count"], 6)
        self.assertEqual(result["pages_per_symbol"], {s: 3 for s in source.SYMBOLS})
        self.output = self.base / "independent_synthetic_exhausted"
        before = len(self.calls)
        with self.assertRaisesRegex(source.SourceIntegrityError, "PAGE_BUDGET_EXHAUSTED"):
            self.collect(lambda ep, p, h: self.response(p, cap=2))
        self.assertEqual(len(self.calls) - before, 3)
        self.assertFalse((self.output / "DATA_FREEZE_V6.json").exists())

    def test_attempt_never_resumes_or_retries(self):
        self.collect()
        with self.assertRaisesRegex(source.SourceIntegrityError, "NO_RESUME"):
            self.collect()
        self.assertEqual(len(self.calls), 4)

    def test_http_failure_is_raw_first_and_consumes_exact_one_request(self):
        def failure(ep, p, h):
            self.calls.append(dict(p))
            return source.Response(403, {}, b"synthetic denied")
        with self.assertRaisesRegex(source.SourceIntegrityError, "HTTP_STATUS:403"):
            self.collect(failure)
        self.assertEqual((self.output / "raw/BTC-USDT_00.bin").read_bytes(), b"synthetic denied")
        failure_receipt = json.loads((self.output / "FAILURE_MANIFEST_V6.json").read_bytes())
        self.assertEqual(failure_receipt["http_get_count"], 1)
        self.assertFalse(failure_receipt["retry_authorized"])
        self.assertEqual(failure_receipt["economic_runs"], 0)
        with self.assertRaisesRegex(source.SourceIntegrityError, "NO_RESUME"):
            self.collect(failure)
        self.assertEqual(len(self.calls), 1)

    def test_raw_response_metadata_exists_before_decode(self):
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

    def test_semantic_or_authority_mutation_during_pacing_blocks_following_get(self):
        original = self.semantic_path.read_bytes()
        def mutate(seconds):
            self.clock += seconds
            self.semantic_path.write_bytes(original + b" ")
        self.sleep = mutate
        with self.assertRaisesRegex(source.SourceIntegrityError, "SEMANTIC_CHANGED_DURING_FETCH"):
            self.collect()
        self.assertEqual(len(self.calls), 1)

    def test_semantic_failure_never_starts_source_attempt(self):
        updates = ({"schema": "trendrider.rest.ws.timestamp.semantic.receipt.v2"},
                   {"scope_key": previous.SCOPE}, {"state": "FAIL"},
                   {"open_ts_rule": "native_T - 1h"}, {"close_ts_rule": "native_T"},
                   {"provider_native_close_claim": True}, {"outcome_independent": False},
                   {"timestamp_adjustment_ms": True}, {"hour_ms": True},
                   {"symbol": "ETH-USDT"}, {"supported_canonical_lane": "OBJECT_OPEN_TIME_OPEN"},
                   {"canonical_open_transform": "SHIFT_MINUS_ONE_HOUR"})
        for update in updates:
            value = {**synthetic_semantic(), **update}
            self.semantic_path.write_bytes(source.canonical_bytes(value))
            self.seal_authorization()
            with self.subTest(update=update), self.assertRaisesRegex(source.SourceIntegrityError, "BLOCKED_OBSERVED"):
                self.collect()
            self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_real_semantic_validator_exception_is_fail_closed(self):
        with patch.object(source, "_calibration_validate", side_effect=ValueError("RAW_BINDING_MISMATCH")):
            with self.assertRaisesRegex(source.SourceIntegrityError, "RAW_BINDING_MISMATCH"):
                self.collect()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_old_scope_or_old_authorization_schema_rejected(self):
        for update in ({"scope_key": previous.SCOPE}, {"schema": previous.AUTHORIZATION_SCHEMA},
                       {"dataset_fetch_attempts": 2}, {"retry_authorized": True}):
            value = source.authorization_template(source.digest_bytes(self.contract_path.read_bytes()),
                                                  source.digest_bytes(self.semantic_path.read_bytes()))
            value.pop("receipt_sha256")
            value.update(update)
            self.authorization_path.write_bytes(source.canonical_bytes(source.v1._sealed(value)))
            self.authorization_sha = source.digest_bytes(self.authorization_path.read_bytes())
            with self.subTest(update=update), self.assertRaisesRegex(source.SourceIntegrityError, "AUTHORIZATION_BINDING"):
                self.collect()
        self.assertEqual(self.calls, [])

    def test_frozen_window_and_count_cannot_be_reconfigured(self):
        for key, value in (("cutoff_ms", source.CUTOFF_MS + source.HOUR_MS),
                           ("first_open_ms", source.FIRST_OPEN_MS - source.HOUR_MS),
                           ("max_pages_per_symbol", 4), ("bars_per_symbol", 999)):
            changed = contract()
            changed["source"][key] = value
            self.contract_path.write_bytes(source.canonical_bytes(changed))
            self.seal_authorization()
            with self.subTest(key=key), self.assertRaisesRegex(source.SourceIntegrityError, "SOURCE_CONTRACT_MISMATCH"):
                self.collect()
        self.assertEqual(self.calls, [])

    def test_ohlc_timestamp_pagination_parser_bytes_unchanged(self):
        for name in ("_request", "http_transport", "_native_timestamp", "_row_shape", "_admitted_prices", "decode_page"):
            with self.subTest(function=name):
                current = self.original_http_transport if name == "http_transport" else getattr(source, name)
                self.assertEqual(inspect.getsource(getattr(previous, name)), inspect.getsource(current))

    def test_guard_ohlc_not_interpreted_and_malformed_admitted_or_duplicate_rejected(self):
        last = source.CUTOFF_MS - source.HOUR_MS
        guard = {**bar(source.CUTOFF_MS), "open": "NOT_PRICE", "volume": {"quarantine": True}}
        rows, detail = source.decode_page(payload([guard, bar(last)]), "BTC-USDT", source.CUTOFF_MS,
            1000, 1000, lane="OBJECT_TIME_OPEN", close_delta_ms=source.HOUR_MS - 1)
        self.assertEqual([r["ts_ms"] for r in rows], [last])
        self.assertFalse(detail["guards"][0]["ohlc_values_interpreted"])
        for bad in ([bar(last), bar(last)], [{**bar(last), "time": True}],
                    [{**bar(last), "high": 1}], [bar(last), bar(last - 2 * source.HOUR_MS)]):
            with self.subTest(bad=bad), self.assertRaises(source.SourceIntegrityError):
                source.decode_page(payload(bad), "BTC-USDT", source.CUTOFF_MS, 1000, 1000,
                                   lane="OBJECT_TIME_OPEN", close_delta_ms=source.HOUR_MS - 1)

    def test_array_requires_its_directly_observed_native_close_delta(self):
        value = {**synthetic_semantic(), "supported_canonical_lane": "ARRAY_OPEN_CLOSE",
                 "canonical_open_transform": "IDENTITY_NATIVE_ARRAY_OPEN_MS"}
        self.semantic_path.write_bytes(source.canonical_bytes(value))
        self.seal_authorization()
        with self.assertRaisesRegex(source.SourceIntegrityError, "ARRAY_NATIVE_CLOSE"):
            self.collect()
        self.assertEqual(self.calls, [])
        value["rest_native_close_delta_ms"] = source.HOUR_MS
        self.semantic_path.write_bytes(source.canonical_bytes(value))
        self.seal_authorization()
        def arrays(ep, p, h):
            response = self.response(p)
            rows = json.loads(response.body)["data"]
            return source.Response(200, {}, payload([[r["time"], r["open"], r["high"], r["low"],
                r["close"], r["volume"], r["time"] + source.HOUR_MS] for r in rows]))
        result = self.collect(arrays)
        self.assertEqual(result["canonical_close_delta_ms"], source.HOUR_MS)
        self.assertEqual(result["economic_close_delta_ms"], source.HOUR_MS)
        self.assertFalse(result["provider_native_close_claim"])

    def test_full_source_requires_recomputed_raw_linked_observed_witness(self):
        from backend.research.rebuild.test_trendrider_observed_timestamp_v1 import write_synthetic_witness
        self.semantic_patch.stop()
        for ordinal, (schema, delta) in enumerate((("object", source.HOUR_MS - 1),
                                                  ("array", source.HOUR_MS - 1),
                                                  ("array", source.HOUR_MS))):
            with self.subTest(schema=schema, delta=delta):
                self.semantic_path = write_synthetic_witness(self.base / f"witness_{ordinal}",
                                                             schema, close_delta=delta)
                self.output = self.base / f"data_{ordinal}"
                self.seal_authorization()
                def transport(ep, params, headers):
                    response = self.response(params)
                    if schema == "object":
                        return response
                    rows = json.loads(response.body)["data"]
                    return source.Response(200, {}, payload([[r["time"], r["open"], r["high"], r["low"],
                        r["close"], r["volume"], r["time"] + delta] for r in rows]))
                result = self.collect(transport)
                self.assertEqual(result["state"], "FROZEN_COMMON_HISTORICAL_DEV")
                self.assertEqual(result["open_ts_rule"], "native_T")
                self.assertEqual(result["close_ts_rule"], "open_ts + 1h")
                self.assertEqual(result["economic_close_delta_ms"], source.HOUR_MS)
                self.assertEqual(result["timestamp_semantic_receipt_sha256"],
                                 source.digest_bytes(self.semantic_path.read_bytes()))

    def test_raw_linked_witness_mutation_before_source_blocks_without_attempt(self):
        from backend.research.rebuild.test_trendrider_observed_timestamp_v1 import write_synthetic_witness
        self.semantic_patch.stop()
        self.semantic_path = write_synthetic_witness(self.base / "raw_witness")
        self.seal_authorization()
        raw_path = self.semantic_path.parent / "raw/rest_1.bin"
        raw_path.write_bytes(raw_path.read_bytes() + b"mutation")
        with self.assertRaisesRegex(source.SourceIntegrityError, "BLOCKED_OBSERVED"):
            self.collect()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_raw_linked_witness_mutation_during_pacing_blocks_next_get(self):
        from backend.research.rebuild.test_trendrider_observed_timestamp_v1 import write_synthetic_witness
        self.semantic_patch.stop()
        self.semantic_path = write_synthetic_witness(self.base / "raw_witness")
        self.seal_authorization()
        raw_path = self.semantic_path.parent / "raw/rest_1.bin"
        def mutate(seconds):
            self.clock += seconds
            raw_path.write_bytes(raw_path.read_bytes() + b"mutation")
        self.sleep = mutate
        with self.assertRaisesRegex(source.SourceIntegrityError, "BLOCKED_OBSERVED"):
            self.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.output / "DATA_FREEZE_V6.json").exists())


if __name__ == "__main__":
    unittest.main()
