"""Archived PR1281/1283 raw regression and synthetic mutations; network zero."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import unittest

from backend.research.rebuild import trendrider_observed_ws_schema_v1 as mod
from backend.research.rebuild.test_trendrider_rest_ws_timestamp_v2 import ws_bytes

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "research/development_evidence"
PR1281 = EVIDENCE / "TRENDRIDER_UNIFIED_REST_WS_TIMESTAMP_AFTER_PR1279_V1/calibration/raw"
PR1283 = EVIDENCE / "TRENDRIDER_UNIFIED_ACK_REPAIR_AFTER_PR1281_V1/calibration/raw"
FIXTURES = (
    (PR1281, "ws_0001", "c2a99fa6fbc419b920094c7d7c82c005be42b55707687f076935ad6e23d61eaa"),
    (PR1283, "ws_0001", "175220f1fcaf3e6ba8d7164600953ebc1e61125fae8859364241b20483b97bde"),
    (PR1283, "ws_0002", "b0d5a0ec106e93a65432e5ebe23b79fc5a29003edc705c13e66a07e63ad8dfde"),
)


def fixture(index):
    directory, name, expected_sha = FIXTURES[index]
    raw = (directory / (name + ".bin")).read_bytes()
    meta = json.loads((directory / (name + ".meta.json")).read_bytes())
    if hashlib.sha256(raw).hexdigest() != expected_sha or meta["raw_sha256"] != expected_sha:
        raise AssertionError("immutable archived wire fixture changed")
    if meta["raw_bytes"] != len(raw) or meta["binary"] is not True:
        raise AssertionError("immutable archived wire metadata changed")
    return raw, meta


def observed_payload():
    return json.loads(gzip.decompress(fixture(2)[0]))


def wire(payload):
    return gzip.compress(json.dumps(payload).encode(), mtime=0)


class ObservedSchemaTests(unittest.TestCase):
    def test_actual_acks_then_actual_observed_kline(self):
        for index in (0, 1):
            raw, meta = fixture(index)
            decision = mod.decode_ws(raw, True, expected_request_id=meta["session_id"])
            self.assertEqual(decision, mod.legacy.decode_ws(
                raw, True, expected_request_id=meta["session_id"]))
            self.assertEqual(decision["classification"], "SUBSCRIPTION_ACK_OK")
        raw, meta = fixture(2)
        decision = mod.decode_ws(raw, True)
        self.assertEqual(decision["schema"], mod.OBSERVED_SCHEMA)
        self.assertEqual(decision["candles"], [{"native_T": 1789153200000,
            "ohlc": {"open": "77018.9", "high": "77295.6", "low": "76965.5", "close": "77227.9"},
            "volume": "299.0320"}])
        self.assertEqual(meta["received_at_ms"] - fixture(1)[1]["received_at_ms"], 390)
        self.assertFalse({"open_ms", "close_ms", "open_ts", "close_ts"} & set(decision))
        self.assertFalse({"open_ms", "close_ms", "open_ts", "close_ts"} & set(decision["candles"][0]))

    def test_wrong_root_identity_and_code_fail(self):
        for mutation in ({"s": "ETH-USDT"}, {"s": None}, {"dataType": "BTC-USDT@kline_5m"},
                         {"dataType": None}, {"code": True}, {"code": "0"}, {"code": 0.0}, {"code": 1}):
            with self.subTest(mutation=mutation), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire({**observed_payload(), **mutation}), True)
        for key in ("s", "code", "dataType"):
            payload = observed_payload()
            del payload[key]
            with self.subTest(missing=key), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire(payload), True)

    def test_data_shape_fails_as_a_whole(self):
        for data in (None, {}, "", [], [None], [[]], [0], [observed_payload()["data"][0], None]):
            with self.subTest(data=data), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire({**observed_payload(), "data": data}), True)

    def test_missing_each_ohlcv_or_T_fails(self):
        for key in ("o", "h", "l", "c", "v", "T"):
            payload = observed_payload()
            del payload["data"][0][key]
            with self.subTest(key=key), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire(payload), True)

    def test_non_integer_or_off_grid_T_fails(self):
        for value in (True, False, "1789153200000", 1789153200000.0, None, -3600000, 1789153200001):
            payload = observed_payload()
            payload["data"][0]["T"] = value
            with self.subTest(value=value), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire(payload), True)

    def test_duplicate_T_fails_and_distinct_native_times_stay_native(self):
        payload = observed_payload()
        payload["data"].append(deepcopy(payload["data"][0]))
        with self.assertRaises(mod.SourceIntegrityError):
            mod.decode_ws(wire(payload), True)
        payload["data"][1]["T"] += mod.HOUR_MS
        decision = mod.decode_ws(wire(payload), True)
        self.assertEqual([row["native_T"] for row in decision["candles"]],
                         [1789153200000, 1789156800000])

    def test_malformed_numeric_and_ohlc_bounds_fail(self):
        cases = [(key, value) for key in ("o", "h", "l", "c", "v")
                 for value in (None, True, "NaN", "Infinity", "-Infinity", "-1", [], "x")]
        cases += [(key, "0") for key in ("o", "h", "l", "c")]
        cases += [("h", "77000"), ("l", "77300")]
        for key, value in cases:
            payload = observed_payload()
            payload["data"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire(payload), True)

    def test_finite_json_number_and_zero_volume_accepted(self):
        payload = observed_payload()
        payload["data"][0]["o"] = 77018.9
        payload["data"][0]["v"] = 0
        result = mod.decode_ws(wire(payload), True)["candles"][0]
        self.assertEqual(result["ohlc"]["open"], "77018.9")
        self.assertEqual(result["volume"], "0")

    def test_mixed_ack_kline_or_nested_shape_fails(self):
        for mutation in ({"id": mod.SESSION_ID}, {"msg": ""}, {"K": {}}, {"reqType": "sub"}):
            with self.subTest(mutation=mutation), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire({**observed_payload(), **mutation}), True)
        for key, value in (("K", {}), ("id", mod.SESSION_ID), ("t", 1789153200000)):
            payload = observed_payload()
            payload["data"][0][key] = value
            with self.subTest(item_extra=key), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire(payload), True)

    def test_ack_strict_fields_preserved(self):
        payload = json.loads(gzip.decompress(fixture(1)[0]))
        for mutation in ({"id": "wrong"}, {"code": True}, {"code": 1}, {"msg": None},
                         {"data": []}, {"dataType": mod.CHANNEL}, {"s": mod.SYMBOL}):
            with self.subTest(mutation=mutation), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(wire({**payload, **mutation}), True)
        for data_present in (False, True):
            for type_present in (False, True):
                modified = deepcopy(payload)
                if not data_present:
                    del modified["data"]
                if not type_present:
                    del modified["dataType"]
                self.assertEqual(mod.decode_ws(wire(modified), True),
                                 mod.legacy.decode_ws(wire(modified), True))

    def test_existing_nested_fixture_semantics_unchanged(self):
        for delta in (mod.HOUR_MS - 1, mod.HOUR_MS):
            raw = ws_bytes(close_delta=delta)
            self.assertEqual(mod.decode_ws(raw, True), mod.legacy.decode_ws(raw, True))
        for raw in (ws_bytes(symbol="ETH-USDT"), ws_bytes(close_delta=1), ws_bytes(close="NaN")):
            with self.subTest(raw=raw), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(raw, True)

    def test_prefix_decisions_survive_appended_or_mutated_future_frames(self):
        prefix_raw = [fixture(i)[0] for i in (1, 2)]
        prefix = [mod.decode_ws(raw, True) for raw in prefix_raw]
        frozen = json.dumps(prefix, sort_keys=True)
        malformed = observed_payload()
        malformed["data"][0]["T"] = True
        future_frames = [wire(observed_payload()), wire(malformed), b"invalid gzip", gzip.compress(b"Ping", mtime=0)]
        for future in future_frames:
            decisions = [mod.decode_ws(raw, True) for raw in prefix_raw]
            try:
                decisions.append(mod.decode_ws(future, True))
            except mod.SourceIntegrityError:
                pass
            self.assertEqual(json.dumps(decisions[:2], sort_keys=True), frozen)
            self.assertEqual(json.dumps(prefix, sort_keys=True), frozen)

    def test_wire_bounds_duplicate_keys_and_ping(self):
        plain = gzip.decompress(fixture(2)[0])
        self.assertEqual(mod.decode_ws(plain, False), mod.decode_ws(fixture(2)[0], True))
        for raw, binary in ((plain.replace(b'"T":', b'"T":0,"T":'), False),
                            (b"invalid gzip", True), (b"\xff", False), (b"[]", False),
                            (b"x" * (mod.MAX_BYTES + 1), False),
                            (gzip.compress(b" " * (mod.MAX_BYTES + 1), mtime=0), True)):
            with self.subTest(binary=binary, length=len(raw)), self.assertRaises(mod.SourceIntegrityError):
                mod.decode_ws(raw, binary)
        self.assertEqual(mod.decode_ws(b"Ping", False), {"kind": "ping"})


if __name__ == "__main__":
    unittest.main()
