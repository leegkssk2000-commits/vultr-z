import gzip
import json
import unittest
from ops import kp_price_input_export_v1 as p


class PriceInputTests(unittest.TestCase):
    def fixture(self):
        receipt = {'start_ms': 60000, 'end_exclusive_ms': 180000, 'received_at_ms': 180100,
                   'missing_minutes': [], 'rows': 2}
        body = {'code': 0, 'data': [
            {'time': 60000, 'open': '1.00', 'high': '2', 'low': '0.5', 'close': '1.5', 'volume': '0'},
            {'time': 120000, 'open': '1.5', 'high': '2.5', 'low': '1', 'close': '2', 'volume': '10.0'}]}
        return receipt, body

    def test_real_named_schema_and_precision(self):
        r, b = self.fixture(); rows, normalized = p.normalize_body(json.dumps(b).encode(), r)
        self.assertEqual(rows[0]['open'], '1.00')
        self.assertEqual(normalized.decode().splitlines()[0], ','.join(p.FIELDS))
        self.assertEqual(len(rows), 2)

    def test_order_is_normalized_not_synthesized(self):
        r,b=self.fixture();b['data'].reverse()
        rows,_=p.normalize_body(json.dumps(b).encode(),r)
        self.assertEqual([x['timestamp_ms'] for x in rows],[60000,120000])

    def test_invalid_values_fail_closed(self):
        for key, val in [('open','NaN'),('close','Infinity'),('low',-1),('volume',-1),('high',True),('time',True),('time',61000)]:
            r,b=self.fixture();b['data'][0][key]=val
            with self.subTest(key=key,val=val), self.assertRaises(Exception): p.normalize_body(json.dumps(b).encode(),r)

    def test_no_missing_or_duplicate_minutes(self):
        r,b=self.fixture();b['data'].pop()
        with self.assertRaisesRegex(Exception,'BODY_RECEIPT_ACCOUNTING'): p.normalize_body(json.dumps(b).encode(),r)
        r,b=self.fixture();b['data'][1]=b['data'][0]
        with self.assertRaisesRegex(Exception,'DUPLICATE_MINUTE'): p.normalize_body(json.dumps(b).encode(),r)

    def test_explicit_gap_is_preserved(self):
        r,b=self.fixture();b['data'].pop();r.update(missing_minutes=[120000],rows=1)
        rows,_=p.normalize_body(json.dumps(b).encode(),r)
        self.assertEqual(len(rows),1)

    def test_no_unclosed_or_alias_conflict(self):
        r,b=self.fixture();r['received_at_ms']=179999
        with self.assertRaisesRegex(Exception,'BAR_CLOCK'): p.normalize_body(json.dumps(b).encode(),r)
        r,b=self.fixture();b['data'][0]['openTime']=120000
        with self.assertRaisesRegex(Exception,'TIMESTAMP_ALIASES'): p.normalize_body(json.dumps(b).encode(),r)

    def test_ohlc_geometry_and_mapping(self):
        r,b=self.fixture();b['data'][0]['high']='0.8'
        with self.assertRaisesRegex(Exception,'OHLC_GEOMETRY'): p.normalize_body(json.dumps(b).encode(),r)
        r,b=self.fixture();b['data'][0]=[60000,1,2,0.5,1.5,0]
        with self.assertRaisesRegex(Exception,'NAMED_CANDLE'): p.normalize_body(json.dumps(b).encode(),r)

    def test_gzip_limit(self):
        self.assertEqual(p.bounded_gunzip(gzip.compress(b'ab'),2),b'ab')
        with self.assertRaisesRegex(Exception,'DECOMPRESSED_SIZE_LIMIT'): p.bounded_gunzip(gzip.compress(b'abc'),2)

    def test_snapshot_hash_rejected_before_host_io(self):
        with self.assertRaisesRegex(Exception,'PINNED_SNAPSHOT_BYTES_CHANGED'): p.export_prices(b'{}',{})

    def test_mutable_config_cannot_repin_its_own_inputs(self):
        with self.assertRaisesRegex(Exception,'PRECOMMITTED_FORWARD_CONFIG_CHANGED'):
            p.frozen_config(b'{"historical_context":{},"new_parameters":true}')

    def test_source_paths_are_not_arbitrary(self):
        with self.assertRaisesRegex(Exception,'UNAPPROVED_ROOT'): p.saved_file('/etc/passwd')


if __name__=='__main__':unittest.main()
