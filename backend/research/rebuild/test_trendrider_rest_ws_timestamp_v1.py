"""Synthetic-only calibration witnesses; never open a socket or fetch a market."""
import asyncio
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_rest_ws_timestamp_v1 as mod

T = 1_789_142_400_000
T = T // mod.HOUR_MS * mod.HOUR_MS


def synthetic_authority():
    return {"scope_key": mod.SCOPE, "status": "DOCUMENT_AUTHORITY_PINNED_NOT_A_LIVE_WITNESS",
        "official_ws": {"endpoint": mod.WS_ENDPOINT, "kline_fields": {
            "data.K.t": "start timestamp in milliseconds", "data.K.T": "close timestamp in milliseconds"}},
        "official_rest": {"array_field_indices": {"open_timestamp_ms": 0, "close_timestamp_ms": 6}},
        "sources": [{"exact_utf8_git_blob_match": True, "path_at_commit_verified": True,
                     "fixture": "SYNTHETIC_ONLY_NOT_EXTERNAL_AUTHORITY"}]}


def ws_payload(t=T, close_delta=mod.HOUR_MS - 1, close="103", symbol=mod.SYMBOL, channel=mod.CHANNEL):
    return {"dataType": channel, "data": {"s": symbol, "K": {"t": t, "T": t + close_delta,
            "o": "100", "h": "110", "l": "90", "c": close, "v": "7"}}}


def ws_bytes(**kwargs):
    return gzip.compress(json.dumps(ws_payload(**kwargs)).encode())


def rest_bytes(schema="object", t=T, close_delta=mod.HOUR_MS - 1, close="103", extra=None):
    if schema == "object":
        row = {"time": t, "open": "100.0", "high": "110.00", "low": "90", "close": close, "volume": "8"}
        row.update(extra or {})
    else:
        row = [t, "100.0", "110.00", "90", close, "8", t + close_delta]
    return mod.canonical_bytes({"code": 0, "data": [row]})


class SyntheticClock(mod.Clock):
    def __init__(self, *, fast=False):
        self.elapsed = 0.0
        self.fast = fast
    def monotonic(self):
        return self.elapsed
    def wall_ms(self):
        return T + 20_000 + int(self.elapsed * 1000)
    async def sleep(self, delay):
        if self.fast:
            self.elapsed += delay
        await asyncio.sleep(0)


class FakeWS:
    def __init__(self, messages):
        self.messages = asyncio.Queue()
        for message in messages:
            self.messages.put_nowait(message)
        self.sent = []
        self.closed = False
    async def recv(self):
        return await self.messages.get()
    async def send(self, message):
        self.sent.append(message)
    async def close(self):
        self.closed = True


def prepare_inputs(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    authority = root / "authority.json"
    authority.write_bytes(mod.canonical_bytes(synthetic_authority()))
    protocol = root / "protocol.json"
    protocol.write_bytes(mod.canonical_bytes(mod.protocol_template(mod.digest_bytes(authority.read_bytes()))))
    return protocol, authority


def write_synthetic_calibration(root, schema="object", close_delta=mod.HOUR_MS - 1):
    """Create real raw-linked PASS via fake transports; return semantic receipt Path."""
    root = Path(root)
    protocol, authority = prepare_inputs(root)
    async def run():
        websocket = FakeWS([ws_bytes(close_delta=close_delta)])
        async def connect():
            return websocket
        async def rest(params):
            assert params == mod.rest_params(T)
            return mod.base.Response(200, {"fixture": "SYNTHETIC"}, rest_bytes(schema, close_delta=close_delta))
        return await mod.run_calibration(root / "calibration", protocol, authority,
                                          connect=connect, rest=rest, clock=SyntheticClock(fast=True))
    result = asyncio.run(run())
    if result["state"] != "PASS":
        raise AssertionError(result)
    return root / "calibration" / "REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"


class SchemaTests(unittest.TestCase):
    def test_decimal_exact_equality_accepts_format_only_difference(self):
        ws = mod.decode_ws(ws_bytes(), True)
        row = mod.decode_rest(rest_bytes(), T)[0]
        self.assertTrue(mod.exact_match(row, ws))
    def test_decimal_tiny_difference_never_tolerated(self):
        ws = mod.decode_ws(ws_bytes(), True)
        row = mod.decode_rest(rest_bytes(close="103.000000000000000000000001"), T)[0]
        self.assertFalse(mod.exact_match(row, ws))
    def test_array_native_open_close_required(self):
        ws = mod.decode_ws(ws_bytes(), True)
        row = mod.decode_rest(rest_bytes("array"), T)[0]
        self.assertTrue(mod.exact_match(row, ws))
        row["close_ms"] += 1
        self.assertFalse(mod.exact_match(row, ws))
    def test_object_native_exclusive_close_preserved_canonical_open_identity(self):
        ws = mod.decode_ws(ws_bytes(close_delta=mod.HOUR_MS), True)
        self.assertTrue(mod.exact_match(mod.decode_rest(rest_bytes(), T)[0], ws))
    def test_object_time_equal_ws_close_rejected(self):
        with self.assertRaises(mod.SourceIntegrityError):
            mod.decode_rest(rest_bytes(t=T + mod.HOUR_MS - 1), T)
    def test_time_shift_and_continuity_do_not_match(self):
        ws = mod.decode_ws(ws_bytes(t=T + mod.HOUR_MS), True)
        self.assertFalse(mod.exact_match(mod.decode_rest(rest_bytes(), T)[0], ws))
    def test_ws_wrong_symbol_or_interval_rejected(self):
        for kw in ({"symbol": "ETH-USDT"}, {"channel": "BTC-USDT@kline_5m"}):
            with self.subTest(kw=kw), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(ws_bytes(**kw), True)
    def test_rest_contradictory_explicit_identity_rejected(self):
        for extra in ({"symbol": "ETH-USDT"}, {"interval": "5m"}):
            with self.subTest(extra=extra), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_rest(rest_bytes(extra=extra), T)
    def test_ws_timestamp_fields_mandatory_without_undocumented_flags(self):
        p = ws_payload()
        self.assertEqual(mod.decode_ws(gzip.compress(json.dumps(p).encode()), True)["kind"], "kline")
        del p["data"]["K"]["T"]
        with self.assertRaises(mod.SourceIntegrityError):
            mod.decode_ws(gzip.compress(json.dumps(p).encode()), True)
    def test_duplicate_json_timestamp_keys_rejected(self):
        raw = json.dumps(ws_payload()).replace('"t": ' + str(T), '"t": 0, "t": ' + str(T)).encode()
        with self.assertRaises(mod.SourceIntegrityError):
            mod.decode_ws(gzip.compress(raw), True)
        raw = rest_bytes().replace(b'"time":', b'"time":0,"time":')
        with self.assertRaises(mod.SourceIntegrityError):
            mod.decode_rest(raw, T)
    def test_malformed_gzip_and_decompression_bomb_rejected(self):
        for raw in (b"not gzip", gzip.compress(b" " * (mod.MAX_BYTES + 1))):
            with self.subTest(size=len(raw)), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(raw, True)
    def test_nonfinite_or_negative_ohlc_volume_rejected(self):
        for close in ("NaN", "Infinity", "-1", "0"):
            with self.subTest(close=close), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_rest(rest_bytes(close=close), T)
    def test_ambiguous_duplicate_candle_rejected(self):
        p = json.loads(rest_bytes())
        p["data"].append(p["data"][0])
        with self.assertRaises(mod.SourceIntegrityError):
            mod.decode_rest(mod.canonical_bytes(p), T)
    def test_protocol_authority_mutation_fails_before_network(self):
        authority = mod.canonical_bytes(synthetic_authority())
        raw = mod.canonical_bytes(mod.protocol_template(mod.digest_bytes(authority)))
        mod.validate_protocol(raw, authority)
        with self.assertRaises(mod.SourceIntegrityError):
            mod.validate_protocol(raw, authority + b" ")
    def test_ping_is_application_control_not_subscription(self):
        self.assertEqual(mod.decode_ws(gzip.compress(b"Ping"), True), {"kind": "ping"})
    def test_secret_bearing_transport_error_redacted(self):
        self.assertEqual(mod.safe_error(RuntimeError("https://user:secret@proxy")), "RuntimeError")


class ReceiptTests(unittest.TestCase):
    def test_object_exclusive_ws_close_retains_distinct_canonical_close(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = mod.validate_semantic_receipt(write_synthetic_calibration(d, "object", mod.HOUR_MS))
            self.assertEqual(receipt["native_ws_close_delta_ms"], mod.HOUR_MS)
            self.assertEqual(receipt["canonical_close_delta_ms"], mod.HOUR_MS - 1)
    def test_object_raw_linked_receipt_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_synthetic_calibration(d)
            receipt = mod.validate_semantic_receipt(path, mod.digest_bytes(path.read_bytes()))
            self.assertEqual(receipt["supported_canonical_lane"], "OBJECT_TIME_OPEN")
            self.assertFalse(receipt["witness"]["volume_exact_match"])
    def test_array_raw_linked_both_native_conventions(self):
        for delta in (mod.HOUR_MS - 1, mod.HOUR_MS):
            with self.subTest(delta=delta), tempfile.TemporaryDirectory() as d:
                receipt = mod.validate_semantic_receipt(write_synthetic_calibration(d, "array", delta))
                self.assertEqual(receipt["canonical_close_rule"], "IDENTITY_NATIVE_ARRAY_CLOSE_MS")
    def test_receipt_expected_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(mod.SourceIntegrityError):
                mod.validate_semantic_receipt(write_synthetic_calibration(d), "0" * 64)
    def test_raw_witness_mutation_detected(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_synthetic_calibration(d)
            receipt = json.loads(path.read_bytes())
            raw = path.parent / receipt["witness"]["ws_raw_path"]
            raw.write_bytes(ws_bytes(close="104"))
            with self.assertRaises(mod.SourceIntegrityError):
                mod.validate_semantic_receipt(path)
    def test_self_resealed_false_witness_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_synthetic_calibration(d)
            receipt = json.loads(path.read_bytes())
            receipt.pop("receipt_sha256")
            receipt["witness"]["rest_timestamp_ms"] += mod.HOUR_MS
            path.write_bytes(mod.canonical_bytes(mod.sealed(receipt)))
            with self.assertRaises(mod.SourceIntegrityError):
                mod.validate_semantic_receipt(path)


class OwnerTests(unittest.IsolatedAsyncioTestCase):
    async def run_fixture(self, d, messages, rest_callback, clock=None, connect_error=None):
        protocol, authority = prepare_inputs(d)
        ws = FakeWS(messages)
        async def connect():
            if connect_error:
                raise connect_error
            return ws
        result = await mod.run_calibration(Path(d) / "calibration", protocol, authority,
            connect=connect, rest=rest_callback, clock=clock or SyntheticClock(fast=True))
        return result, ws
    async def test_raw_before_ws_decode_and_rest_decode(self):
        with tempfile.TemporaryDirectory() as d:
            original_ws, original_rest = mod.decode_ws, mod.decode_rest
            def decode_ws(raw, binary):
                self.assertTrue((Path(d) / "calibration/raw/ws_0001.bin").is_file())
                self.assertTrue((Path(d) / "calibration/raw/ws_0001.meta.json").is_file())
                return original_ws(raw, binary)
            def decode_rest(raw, target):
                for name in ("rest_1.request.json", "rest_1.bin", "rest_1.response.json"):
                    self.assertTrue((Path(d) / "calibration/raw" / name).is_file())
                return original_rest(raw, target)
            async def rest(params):
                return mod.base.Response(200, {}, rest_bytes())
            with patch.object(mod, "decode_ws", decode_ws), patch.object(mod, "decode_rest", decode_rest):
                result, ws = await self.run_fixture(d, [ws_bytes()], rest)
            self.assertEqual(result["state"], "PASS")
            self.assertEqual(len(ws.sent), 1)
            self.assertEqual(result["actual_rest_requests"], 1)
    async def test_ping_pong_subscription_counts_separate(self):
        with tempfile.TemporaryDirectory() as d:
            async def rest(params):
                return mod.base.Response(200, {}, rest_bytes())
            result, ws = await self.run_fixture(d, [gzip.compress(b"Ping"), ws_bytes()], rest)
            self.assertEqual(result["state"], "PASS")
            self.assertEqual(result["counts"]["application_pongs"], 1)
            self.assertEqual(result["actual_ws_subscriptions"], 1)
            self.assertIn("Pong", ws.sent)
    async def test_handshake_failure_terminal_no_rest_no_retry(self):
        with tempfile.TemporaryDirectory() as d:
            async def rest(params):
                self.fail("REST not permitted without WS")
            result, _ = await self.run_fixture(d, [], rest, connect_error=OSError("secret proxy"))
            self.assertEqual(result["state"], "BLOCKED_REST_WS_TIMESTAMP_WITNESS")
            self.assertEqual(result["actual_rest_requests"], 0)
            self.assertEqual(result["actual_ws_sessions"], 1)
            self.assertNotIn("secret", json.dumps(result))
            self.assertTrue((Path(d) / "calibration/WS_HANDSHAKE_FAILURE.json").exists())
    async def test_second_rest_only_at_60_seconds_after_first_and_stop_on_match(self):
        with tempfile.TemporaryDirectory() as d:
            clock = SyntheticClock(fast=True)
            calls = []
            async def rest(params):
                calls.append(clock.monotonic())
                return mod.base.Response(200, {}, rest_bytes(close="104" if len(calls) == 1 else "103"))
            result, _ = await self.run_fixture(d, [ws_bytes()], rest, clock)
            self.assertEqual(result["state"], "PASS")
            self.assertEqual(len(calls), 2)
            self.assertGreaterEqual(calls[1] - calls[0], 60)
    async def test_rest_failure_abort_remaining_calls(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            async def rest(params):
                calls.append(params)
                return mod.base.Response(502, {}, b"upstream failure")
            result, _ = await self.run_fixture(d, [ws_bytes()], rest)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["state"], "BLOCKED_REST_WS_TIMESTAMP_WITNESS")
            self.assertTrue((Path(d) / "calibration/raw/rest_1.bin").exists())
    async def test_previous_hour_allowed_but_stale_or_future_not(self):
        for offset, expected in ((-mod.HOUR_MS, 1), (-2 * mod.HOUR_MS, 0), (mod.HOUR_MS, 0)):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as d:
                calls = []
                async def rest(params):
                    calls.append(params)
                    return mod.base.Response(200, {}, rest_bytes(t=T + offset))
                result, _ = await self.run_fixture(d, [ws_bytes(t=T + offset)], rest)
                self.assertEqual(len(calls), expected)
                self.assertEqual(result["state"] == "PASS", expected == 1)
    async def test_nonempty_output_refuses_second_session(self):
        with tempfile.TemporaryDirectory() as d:
            async def rest(params):
                return mod.base.Response(200, {}, rest_bytes())
            await self.run_fixture(d, [ws_bytes()], rest)
            with self.assertRaises(mod.SourceIntegrityError):
                await self.run_fixture(d, [ws_bytes()], rest)
    async def test_guard_candle_match_cannot_replace_frozen_first_target(self):
        with tempfile.TemporaryDirectory() as d:
            async def rest(params):
                rows = json.loads(rest_bytes(close="104"))["data"] + json.loads(rest_bytes(t=T + mod.HOUR_MS))["data"]
                return mod.base.Response(200, {}, mod.canonical_bytes({"code": 0, "data": rows}))
            result, _ = await self.run_fixture(d, [ws_bytes(), ws_bytes(t=T + mod.HOUR_MS)], rest)
            self.assertEqual(result["state"], "BLOCKED_REST_WS_TIMESTAMP_WITNESS")
            self.assertIsNone(result["witness"])
    async def test_partial_http_response_raw_preserved_before_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            async def rest(params):
                raise mod.PartialRESTFailure(mod.base.Response(200, {"Content-Type": "application/json"}, b'{"code":'), TimeoutError())
            result, _ = await self.run_fixture(d, [ws_bytes()], rest)
            self.assertEqual(result["state"], "BLOCKED_REST_WS_TIMESTAMP_WITNESS")
            self.assertEqual((Path(d) / "calibration/raw/rest_1.bin").read_bytes(), b'{"code":')
            meta = json.loads((Path(d) / "calibration/raw/rest_1.response.json").read_bytes())
            self.assertEqual(meta["status"], 200)
            self.assertFalse(meta["body_read_complete"])
            self.assertEqual(result["actual_rest_requests"], 1)
    async def test_duplicate_handshake_headers_are_preserved(self):
        class Headers:
            def raw_items(self):
                return [("set-cookie", "a=1"), ("set-cookie", "b=2")]
            def items(self):
                raise AssertionError("collapsing duplicate headers is forbidden")
        class Response:
            status_code = 101
            headers = Headers()
        with tempfile.TemporaryDirectory() as d:
            protocol, authority = prepare_inputs(d)
            websocket = FakeWS([ws_bytes()])
            websocket.response = Response()
            async def connect():
                return websocket
            async def rest(params):
                return mod.base.Response(200, {}, rest_bytes())
            result = await mod.run_calibration(Path(d) / "calibration", protocol, authority,
                connect=connect, rest=rest, clock=SyntheticClock(fast=True))
            self.assertEqual(result["state"], "PASS")
            saved = json.loads((Path(d) / "calibration/WS_HANDSHAKE_RESPONSE.json").read_bytes())
            self.assertEqual(saved["headers"], [["set-cookie", "a=1"], ["set-cookie", "b=2"]])
    async def test_receiver_keeps_collecting_exact_snapshot_during_rest(self):
        with tempfile.TemporaryDirectory() as d:
            protocol, authority = prepare_inputs(d)
            websocket = FakeWS([ws_bytes()])
            async def connect():
                return websocket
            async def rest(params):
                websocket.messages.put_nowait(ws_bytes(close="104"))
                await asyncio.sleep(0)
                return mod.base.Response(200, {}, rest_bytes(close="104"))
            result = await mod.run_calibration(Path(d) / "calibration", protocol, authority,
                connect=connect, rest=rest, clock=SyntheticClock(fast=True))
            self.assertEqual(result["state"], "PASS")
            self.assertEqual(result["witness"]["ws_raw_path"], "raw/ws_0002.bin")
            self.assertEqual(result["actual_rest_requests"], 1)
    async def test_fatal_ws_during_rest_drains_and_archives_started_response(self):
        with tempfile.TemporaryDirectory() as d:
            protocol, authority = prepare_inputs(d)
            websocket = FakeWS([ws_bytes()])
            calls = []
            async def connect():
                return websocket
            async def rest(params):
                calls.append(params)
                websocket.messages.put_nowait(b"malformed gzip after HTTP dispatch")
                for _ in range(8):
                    await asyncio.sleep(0)
                return mod.base.Response(200, {}, rest_bytes())
            result = await mod.run_calibration(Path(d) / "calibration", protocol, authority,
                connect=connect, rest=rest, clock=SyntheticClock(fast=True))
            self.assertEqual(result["state"], "BLOCKED_REST_WS_TIMESTAMP_WITNESS")
            self.assertEqual(len(calls), 1)
            self.assertEqual((Path(d) / "calibration/raw/rest_1.bin").read_bytes(), rest_bytes())
            self.assertTrue((Path(d) / "calibration/raw/rest_1.response.json").is_file())
    async def test_mutation_during_second_request_spacing_blocks_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            class MutatingClock(SyntheticClock):
                async def sleep(self, delay):
                    if delay == 0 and self.elapsed >= 60:
                        path = Path(d) / "authority.json"
                        path.write_bytes(path.read_bytes() + b" ")
                    await super().sleep(delay)
            calls = []
            async def rest(params):
                calls.append(params)
                return mod.base.Response(200, {}, rest_bytes(close="104"))
            result, _ = await self.run_fixture(d, [ws_bytes()], rest, MutatingClock(fast=True))
            self.assertEqual(result["state"], "BLOCKED_REST_WS_TIMESTAMP_WITNESS")
            self.assertEqual(len(calls), 1)
            self.assertFalse((Path(d) / "calibration/raw/rest_2.request.json").exists())
    async def test_frozen_authority_changed_after_first_call_blocks_second(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            async def rest(params):
                calls.append(params)
                path = Path(d) / "authority.json"
                path.write_bytes(path.read_bytes() + b" ")
                return mod.base.Response(200, {}, rest_bytes(close="104"))
            result, _ = await self.run_fixture(d, [ws_bytes()], rest)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["state"], "BLOCKED_REST_WS_TIMESTAMP_WITNESS")


if __name__ == "__main__":
    unittest.main()
