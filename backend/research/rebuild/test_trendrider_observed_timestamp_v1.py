"""Archived PR1283 WS input plus synthetic REST; every transport is injected."""
import asyncio
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_observed_timestamp_v1 as mod

REPO = Path(__file__).resolve().parents[3]
ARCHIVED = REPO/'research/development_evidence/TRENDRIDER_UNIFIED_ACK_REPAIR_AFTER_PR1281_V1/calibration/raw'
T, H = mod.NATIVE_T, mod.HOUR_MS


class FakeClock:
    def __init__(self, start=None):
        self.start = T+2*H if start is None else start
        self.elapsed = 0.0
    def wall_ms(self):
        return self.start+round(self.elapsed*1000)
    def monotonic(self):
        return self.elapsed
    async def sleep(self, delay):
        self.elapsed += delay


def synthetic_rows(schema='object', field='time', close_delta=H-1):
    rows = [
        {'time': T-H, 'open': '76900', 'high': '77300', 'low': '76800', 'close': '77018.9', 'volume': '300'},
        {'time': T, 'open': '77018.900', 'high': '77400', 'low': '76900', 'close': '77350', 'volume': '400'},
    ]
    if schema == 'array':
        return [[r['time'], *[r[k] for k in ('open','high','low','close','volume')], r['time']+close_delta] for r in rows]
    if field != 'time':
        for row in rows:
            row[field] = row.pop('time')
    return rows


def prepare_inputs(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    protocol = root/'protocol.json'
    protocol.write_bytes(mod.canonical_bytes(mod.protocol_template()))
    return protocol, ARCHIVED/'ws_0002.bin', ARCHIVED/'ws_0002.meta.json', ARCHIVED/'ws_0001.bin', ARCHIVED/'ws_0001.meta.json'


def write_synthetic_witness(root, schema='object', *, field='time', close_delta=H-1, rows=None):
    """Public fixture: authentic archived prefix, fake closed REST response only."""
    root = Path(root)
    inputs = prepare_inputs(root)
    async def rest(params):
        assert params == mod.rest_params(1)
        return mod.base.Response(200, {'content-type': 'application/json'}, mod.canonical_bytes(
            {'code': 0, 'data': synthetic_rows(schema, field, close_delta) if rows is None else rows}))
    receipt = asyncio.run(mod.run_witness(root/'witness', *inputs, rest=rest, clock=FakeClock()))
    if receipt['state'] != 'PASS':
        raise AssertionError(receipt)
    return root/'witness'/mod.RECEIPT_NAME


class WitnessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_responses(self, payloads, *, status=200, clock=None, before=None):
        inputs = prepare_inputs(self.root)
        calls = []
        async def rest(params):
            ordinal = len(calls)+1
            calls.append(deepcopy(params))
            path = self.root/'witness'/f'raw/rest_{ordinal}.request.json'
            self.assertTrue(path.exists(), 'request persisted before transport')
            if before:
                before(ordinal)
            raw = payloads[ordinal-1]
            if isinstance(raw, Exception):
                raise raw
            return mod.base.Response(status, {}, raw)
        receipt = asyncio.run(mod.run_witness(self.root/'witness', *inputs, rest=rest, clock=clock or FakeClock()))
        return receipt, calls

    def test_object_actual_archived_prefix_and_offline_recompute(self):
        path = write_synthetic_witness(self.root)
        with patch.object(mod.old, 'live_rest', side_effect=AssertionError('network forbidden')):
            receipt = mod.validate_receipt(path, mod.digest_bytes(path.read_bytes()))
        self.assertEqual(receipt['ack_to_kline_chronology']['ack_to_kline_ms'], 390)
        self.assertEqual(receipt['open_ts_rule'], 'native_T')
        self.assertEqual(receipt['close_ts_rule'], 'open_ts + 1h')
        self.assertFalse(receipt['provider_native_close_claim'])
        self.assertEqual(receipt['counts']['rest_requests'], 1)
        self.assertEqual(receipt['supported_canonical_lane'], 'OBJECT_TIME_OPEN')

    def test_array_and_open_time_native_shapes(self):
        for i, (schema, field, delta) in enumerate((('array','time',H-1), ('array','time',H), ('object','openTime',H-1))):
            with self.subTest(schema=schema, field=field, delta=delta):
                path = write_synthetic_witness(self.root/str(i), schema, field=field, close_delta=delta)
                self.assertEqual(mod.validate_receipt(path)['T_row']['native_time'], T)

    def test_second_request_only_deterministic_incomplete_coverage(self):
        rows = synthetic_rows()
        receipt, calls = self.run_responses([mod.canonical_bytes({'code':0,'data':[rows[1]]}),
                                            mod.canonical_bytes({'code':0,'data':rows})])
        self.assertEqual(receipt['state'], 'PASS')
        self.assertEqual(calls, [mod.rest_params(1), mod.rest_params(2)])
        self.assertEqual(mod.validate_receipt(self.root/'witness'/mod.RECEIPT_NAME)['counts']['rest_requests'],2)

    def test_unused_upper_guard_quarantined(self):
        rows = synthetic_rows()
        guard = dict(rows[1], time=T+H)
        path = write_synthetic_witness(self.root, rows=rows+[guard])
        receipt = mod.validate_receipt(path)
        self.assertEqual(len(receipt['guard_rows_quarantined']), 1)
        self.assertEqual(receipt['guard_economic_rows'], 0)

    def test_duplicate_and_ambiguous_native_rows_fail(self):
        rows = synthetic_rows()
        invalid = [rows+[rows[0]], [dict(rows[0],openTime=T-H), rows[1]],
                   [dict(rows[0],timestamp=T-H), rows[1]], [dict(rows[0],time=True),rows[1]],
                   [dict(rows[0],time=T-H+1),rows[1]], [dict(rows[0],symbol='ETH-USDT'),rows[1]],
                   [dict(rows[0],open='NaN'),rows[1]], [dict(rows[0],high='70000'),rows[1]]]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(mod.SourceIntegrityError):
                    mod.decode_rest(mod.canonical_bytes({'code':0,'data':payload}))

    def test_consistency_fail_aborts_without_second_request(self):
        for i, field in enumerate(('open','high','low')):
            rows = synthetic_rows()
            rows[1][field] = {'open':'77019','high':'77280','low':'76970'}[field]
            if field == 'high':
                rows[1]['close']='77250'
            temp = self.root/str(i)
            inputs = prepare_inputs(temp)
            calls=[]
            async def rest(params):
                calls.append(params)
                return mod.base.Response(200,{},mod.canonical_bytes({'code':0,'data':rows}))
            r=asyncio.run(mod.run_witness(temp/'witness',*inputs,rest=rest,clock=FakeClock()))
            self.assertEqual(r['state'],'BLOCKED_OBSERVED_WS_REST_TIMESTAMP_WITNESS')
            self.assertEqual(len(calls),1)

    def test_indistinguishable_adjacent_candle_blocks(self):
        rows = synthetic_rows()
        rows[0] = dict(rows[1],time=T-H)
        receipt,calls=self.run_responses([mod.canonical_bytes({'code':0,'data':rows})])
        self.assertEqual(receipt['failure'],'OBSERVED_TIMESTAMP_WITNESS_CONSISTENCY')
        self.assertEqual(len(calls),1)

    def test_advisory_volume_not_false_semantic_gate(self):
        rows=synthetic_rows()
        rows[1]['volume']='1'
        path=write_synthetic_witness(self.root,rows=rows)
        r=mod.validate_receipt(path)
        self.assertFalse(r['volume_check']['snapshot_le_final'])
        self.assertFalse(r['volume_check']['required'])

    def test_raw_saved_before_parser_and_malformed_no_retry(self):
        original = mod.decode_rest
        def checked(raw):
            self.assertTrue((self.root/'witness/raw/rest_1.bin').exists())
            self.assertTrue((self.root/'witness/raw/rest_1.response.json').exists())
            return original(raw)
        with patch.object(mod,'decode_rest',side_effect=checked):
            receipt,calls=self.run_responses([b'not-json'])
        self.assertEqual(len(calls),1)
        self.assertEqual(receipt['state'],'BLOCKED_OBSERVED_WS_REST_TIMESTAMP_WITNESS')
        self.assertEqual((self.root/'witness/raw/rest_1.bin').read_bytes(),b'not-json')

    def test_http_failure_and_transport_failure_no_retry(self):
        receipt,calls=self.run_responses([b'HTTP unavailable'],status=503)
        self.assertEqual(len(calls),1)
        self.assertEqual(receipt['counts']['rest_requests'],1)
        self.assertEqual((self.root/'witness/raw/rest_1.bin').read_bytes(),b'HTTP unavailable')

    def test_preclose_is_zero_network_and_no_resume(self):
        receipt,calls=self.run_responses([],clock=FakeClock(T+H-1))
        self.assertEqual(calls,[])
        self.assertEqual(receipt['failure'],'OBSERVED_CANDLE_NOT_CLOSED')
        with self.assertRaises(mod.SourceIntegrityError):
            asyncio.run(mod.run_witness(self.root/'witness',*prepare_inputs(self.root),rest=None,clock=FakeClock()))

    def test_resealed_report_lie_fails_recomputation(self):
        path=write_synthetic_witness(self.root)
        receipt=mod.base._decode_json(path.read_bytes())
        receipt.pop('receipt_sha256')
        receipt['provider_native_close_claim']=True
        path.write_bytes(mod.canonical_bytes(mod.sealed(receipt)))
        with self.assertRaisesRegex(mod.SourceIntegrityError,'RECOMPUTE'):
            mod.validate_receipt(path)

    def test_raw_tamper_and_unlisted_evidence_fail(self):
        path=write_synthetic_witness(self.root/'raw')
        raw=path.parent/'raw/rest_1.bin'
        raw.write_bytes(raw.read_bytes()+b' ')
        with self.assertRaises(mod.SourceIntegrityError):
            mod.validate_receipt(path)
        path2=write_synthetic_witness(self.root/'extra')
        (path2.parent/'raw/rest_2.request.json').write_text('{}')
        with self.assertRaisesRegex(mod.SourceIntegrityError,'UNLISTED'):
            mod.validate_receipt(path2)

    def test_closed_row_changes_across_second_response_fail(self):
        rows=synthetic_rows()
        changed=deepcopy(rows)
        changed[1]['close']='77400'
        receipt,calls=self.run_responses([mod.canonical_bytes({'code':0,'data':[rows[1]]}),
                                         mod.canonical_bytes({'code':0,'data':changed})])
        self.assertEqual(len(calls),2)
        self.assertEqual(receipt['failure'],'OBSERVED_REST_CLOSED_ROW_CHANGED')

    def test_protocol_tamper_network_zero(self):
        inputs=prepare_inputs(self.root)
        protocol=mod.base._decode_json(inputs[0].read_bytes())
        protocol.pop('receipt_sha256')
        protocol['first_rest_params']['startTime']=T
        inputs[0].write_bytes(mod.canonical_bytes(mod.sealed(protocol)))
        with self.assertRaisesRegex(mod.SourceIntegrityError,'PROTOCOL_CHANGED'):
            asyncio.run(mod.run_witness(self.root/'witness',*inputs,rest=None,clock=FakeClock()))


if __name__ == '__main__':
    unittest.main()
