"""Synthetic local files only; no market fetch, economic run or runtime credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import k117_adapter as k
import k117_development_observer as o

T = 1792796400000


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')))


class ConsumerFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.b = self.root / 'B'
        self.source = self.b / 'source'
        self.out = self.b / 'old_output'
        self.pointer = self.b / 'ACTIVE_RUNTIME.json'
        self.consumer = self.root / 'k117_development'
        self.ident = {'source': o.SOURCE, 'interval': '1m', 'timeZone': 0,
                      'synthetic_fill': False, 'symbols': list(o.SYMBOLS), 'volume_units': 'UNKNOWN'}
        write(self.source / 'IDENTITY.json', self.ident)
        self.identity_sha = o.file_hash(self.source / 'IDENTITY.json')
        cursor = {'identity_sha256': self.identity_sha, 'symbols': {}}
        for sym in o.SYMBOLS:
            raw = json.dumps({'code': 0, 'data': []}).encode()
            body = self.source / (sym + '.json')
            body.write_bytes(raw)
            normalized = self.source / (sym + '.csv.gz')
            normalized.write_bytes(b'synthetic-local-fixture-only')
            rec = {'source': o.SOURCE, 'symbol': sym, 'http_status': 200,
                   'received_at_ms': T + 1000, 'start_ms': T - 60000,
                   'end_exclusive_ms': T, 'missing_minutes': [],
                   'body_path': body.name, 'body_sha256': o.file_hash(body),
                   'normalized_path': normalized.name, 'normalized_sha256': o.file_hash(normalized)}
            rp = self.source / (sym + '.receipt.json')
            write(rp, rec)
            cursor['symbols'][sym] = [{'path': rp.name, 'sha256': o.file_hash(rp)}]
        write(self.source / 'CURSOR.json', cursor)
        self.state = {'fixture': False, 'source_identity_sha256': self.identity_sha,
                      'order_calls': 0, 'market': [], 'market_keys': {}}
        write(self.pointer, {'out': str(self.out), 'source': str(self.source), 'pid': 99999999})
        self.save_b()
        self.opened = []

    def tearDown(self):
        for obj in self.opened:
            obj.close()
        self.temp.cleanup()

    def save_b(self):
        body = deepcopy(self.state)
        digest = k.digest(body)
        write(self.out / 'STATE.json', {**body, 'state_sha256': digest})
        write(self.out / 'STATUS.json', {'state_sha256': digest, 'state': 'DEVELOPMENT_OBSERVATION'})

    def batch(self, close=T):
        for sym in o.SYMBOLS:
            row = {'symbol': sym, 'open_ts_ms': close-k.TF, 'close_ts_ms': close,
                   'available_ts_ms': close+1000, 'received_at_ms': close+1000,
                   'processed_at_ms': close+2000, 'open': 100., 'high': 101.,
                   'low': 99., 'close': 100., 'segment_id': '0',
                   'evidence_kind': 'ACTUAL_PUBLIC_CLOSED_30M',
                   'witness': {'identity_sha256': self.identity_sha,
                               'issues': {sym: {'minute_gaps': []}}}}
            self.state['market'].append(row)
            value = {name: row[name] for name in ('open_ts_ms', 'close_ts_ms', 'available_ts_ms',
                     'open', 'high', 'low', 'close', 'segment_id')}
            self.state['market_keys'][sym+':'+str(close)] = k.digest(value)
        self.save_b()

    def receipt_missing(self, symbol, missing):
        path = self.source / (symbol + '.receipt.json')
        receipt = json.loads(path.read_text())
        receipt['missing_minutes'] = missing
        write(path, receipt)
        cursor = json.loads((self.source / 'CURSOR.json').read_text())
        cursor['symbols'][symbol][-1]['sha256'] = o.file_hash(path)
        write(self.source / 'CURSOR.json', cursor)

    def observer(self, start=T-1):
        obj = o.Observer(development=True, pointer=self.pointer, out=self.consumer,
                         started_at_ms=start, check_process=False)
        self.opened.append(obj)
        return obj

    def test_default_off_and_b_path_forbidden(self):
        with self.assertRaisesRegex(ValueError, 'DEFAULT_OFF'):
            o.Observer(pointer=self.pointer, out=self.consumer)
        with self.assertRaisesRegex(ValueError, 'B_SOURCE_OUTPUT'):
            o.Observer(development=True, pointer=self.pointer, out=self.b / 'new')

    def test_first_fresh_batch_calls_actual_adapter_unknown_volume(self):
        self.batch()
        before = {str(p): o.file_hash(p) for p in self.b.rglob('*') if p.is_file()}
        obj = self.observer()
        self.assertEqual(obj.step(T+5000), 6)
        self.assertEqual(len(obj.state['adapter']['events']), 6)
        self.assertTrue(all(d['result']['reason'] == 'VOLUME_UNIT_UNKNOWN' for d in obj.state['decisions']))
        self.assertTrue(all(r['native_evaluation'] == 'NOT_RUN' for r in obj.state['observations']))
        self.assertFalse(obj.state['fixture'])
        self.assertFalse(obj.state['adapter']['fixture'])
        self.assertFalse(obj.state['formal_active'])
        self.assertEqual(obj.report()['virtual_fills'], 0)
        self.assertIsNone(obj.state['NAV'])
        self.assertEqual(before, {str(p): o.file_hash(p) for p in self.b.rglob('*') if p.is_file()})

    def test_pre_epoch_bar_not_replayed(self):
        self.batch()
        obj = self.observer(start=T)
        self.assertEqual(obj.step(T+5000), 0)
        self.assertEqual(obj.state['observations'], [])
        self.assertEqual(obj.state['decisions'], [])

    def test_duplicate_restart_leaves_same_hash(self):
        self.batch(); obj = self.observer()
        self.assertEqual(obj.step(T+5000), 6)
        digest = o.file_hash(self.consumer / 'STATE.json')
        self.assertEqual(obj.step(T+6000), 0)
        self.assertEqual(o.file_hash(self.consumer / 'STATE.json'), digest)
        obj.close()
        restarted = self.observer(start=T+100000)
        self.assertEqual(restarted.state['started_at_ms'], T-1)
        self.assertEqual(restarted.step(T+7000), 0)
        self.assertEqual(o.file_hash(self.consumer / 'STATE.json'), digest)

    def test_state_hash_corruption_holds_no_observation(self):
        self.batch()
        raw = json.loads((self.out / 'STATE.json').read_text())
        raw['order_calls'] = 1
        write(self.out / 'STATE.json', raw)
        obj = self.observer()
        self.assertEqual(obj.step(T+5000), 0)
        self.assertIn('B_ATOMIC_STATE_HASH_MISMATCH', obj.state['last_reason'])
        self.assertEqual(obj.state['observations'], [])

    def test_source_payload_corruption_holds(self):
        self.batch()
        (self.source / 'BTC-USDT.json').write_text('{"code":0,"data":[1]}')
        obj = self.observer()
        self.assertEqual(obj.step(T+5000), 0)
        self.assertIn('SOURCE_PAYLOAD_HASH_MISMATCH', obj.state['last_reason'])

    def test_producer_epoch_change_holds(self):
        self.batch(); obj = self.observer(); obj.step(T+5000)
        p = json.loads(self.pointer.read_text()); p['pid'] += 1; write(self.pointer, p)
        self.assertEqual(obj.step(T+6000), 0)
        self.assertIn('B_PRODUCER_EPOCH_OR_IDENTITY_CHANGED', obj.state['last_reason'])

    def test_missing_live_producer_never_uses_stale_status(self):
        self.batch()
        with self.assertRaisesRegex(ValueError, 'B_SOURCE_WRITER_NOT_LIVE'):
            o.read_snapshot(self.pointer, T+5000)

    def test_single_writer_and_explicit_stop(self):
        self.batch(); obj = self.observer()
        with self.assertRaisesRegex(ValueError, 'WRITER_ALREADY_ACTIVE'):
            self.observer()
        obj.stop('BOUNDED_TIME_COMPLETE')
        self.assertEqual(obj.report()['state'], 'STOPPED')
        with self.assertRaisesRegex(ValueError, 'OBSERVER_ALREADY_STOPPED'):
            obj.step(T+5000)

    def test_incomplete_batch_waits_for_all_six(self):
        self.batch()
        removed = self.state['market'].pop()
        self.state['market_keys'].pop(removed['symbol']+':'+str(T))
        self.save_b(); obj = self.observer()
        self.assertEqual(obj.step(T+5000), 0)
        self.assertEqual(obj.state['observations'], [])

    def test_changed_source_identity_holds(self):
        self.batch()
        self.ident['volume_units'] = 'BASE_ASSET'
        write(self.source / 'IDENTITY.json', self.ident)
        obj = self.observer()
        self.assertEqual(obj.step(T+5000), 0)
        self.assertIn('SOURCE_IDENTITY_MISMATCH', obj.state['last_reason'])

    def test_received_after_processed_holds(self):
        self.batch()
        self.state['market'][0]['received_at_ms'] = T + 3000
        self.save_b(); obj = self.observer()
        self.assertEqual(obj.step(T + 5000), 0)
        self.assertIn('B_MARKET_CLOCK_OR_SOURCE_INVALID', obj.state['last_reason'])

    def test_symbol_history_must_be_monotonic(self):
        self.batch(T - k.TF); self.batch()
        self.state['market'].reverse()
        self.save_b(); obj = self.observer()
        self.assertEqual(obj.step(T + 5000), 0)
        self.assertIn('B_MARKET_SYMBOL_ORDER_INVALID', obj.state['last_reason'])

    def test_relevant_receipt_minute_gap_holds_without_adapter_call(self):
        self.batch(); self.receipt_missing('BTC-USDT', [T - 60000])
        obj = self.observer()
        self.assertEqual(obj.step(T + 5000), 0)
        self.assertIn('SOURCE_CANDIDATE_MINUTE_GAP', obj.state['last_reason'])
        self.assertEqual(obj.state['observations'], [])
        self.assertEqual(obj.adapter.state['events'], [])
        evidence = obj.state['events'][-1]['body']['source_quality']
        self.assertEqual(evidence['receipt_missing_minutes'], [T - 60000])

    def test_relevant_witness_minute_gap_holds_and_preserves_evidence(self):
        self.batch()
        gap = {'start_ms': T - 60000, 'end_exclusive_ms': T, 'missing_minutes': 1}
        self.state['market'][0]['witness']['issues']['BTC-USDT']['minute_gaps'] = [gap]
        self.save_b(); obj = self.observer()
        self.assertEqual(obj.step(T + 5000), 0)
        self.assertIn('SOURCE_CANDIDATE_MINUTE_GAP', obj.state['last_reason'])
        self.assertEqual(obj.state['events'][-1]['body']['source_quality']['witness_minute_gaps'], [gap])

    def test_absent_gap_evidence_is_unknown_not_zero(self):
        self.batch()
        self.state['market'][0]['witness'].pop('issues')
        self.save_b(); obj = self.observer()
        self.assertEqual(obj.step(T + 5000), 0)
        self.assertIn('SOURCE_CANDIDATE_GAP_EVIDENCE_UNKNOWN', obj.state['last_reason'])
        self.assertIsNone(obj.state['events'][-1]['body']['source_quality']['witness_minute_gaps'])

    def test_historical_segment_gap_is_preserved_not_candidate_gap(self):
        self.batch(T - 2 * k.TF); self.batch()
        gap = {'start_ms': T - 2 * k.TF, 'end_exclusive_ms': T - k.TF,
               'missing_minutes': k.TF // 60000}
        for row in self.state['market'][-6:]:
            row['witness']['issues'][row['symbol']]['minute_gaps'] = [gap]
        self.receipt_missing('BTC-USDT', [T - 2 * k.TF])
        self.save_b(); obj = self.observer()
        self.assertEqual(obj.step(T + 5000), 6)
        evidence = obj.state['observations'][0]['source_quality']
        self.assertEqual(evidence['receipt_missing_minutes'], [T - 2 * k.TF])
        self.assertEqual(evidence['witness_minute_gaps'], [gap])
        self.assertEqual(evidence['history_30m_gaps'][0]['missing_30m_bars'], 1)
        self.assertEqual(evidence['relevant_witness_minute_gaps'], [])
        self.assertEqual(evidence['candidate_gap_check'], 'NO_REPORTED_CANDIDATE_GAP')

    def test_failed_adapter_initialization_releases_lock(self):
        def failed(**kwargs):
            raise ValueError('TEST_INITIALIZATION_FAILURE')
        with self.assertRaisesRegex(ValueError, 'TEST_INITIALIZATION_FAILURE'):
            o.Observer(development=True, pointer=self.pointer, out=self.consumer,
                       check_process=False, adapter_factory=failed)
        self.observer()

    def test_cli_requires_bounded_time(self):
        args = ['--development', '--b-pointer', str(self.pointer), '--out', str(self.consumer)]
        for cap in ('0', '86401'):
            with self.assertRaisesRegex(SystemExit, 'BOUNDED_RUNTIME_REQUIRED'):
                o.main(args + ['--max-seconds', cap])

    def test_network_and_producer_write_fence_in_subprocess(self):
        program = r'''
import json, socket, tempfile
from pathlib import Path
import k117_development_observer as o
import k117_adapter as k
root=Path(tempfile.mkdtemp()); out=root/'own'; out.mkdir()
protected=root/'producer.json';protected.write_text('unchanged')
counts=k.install_boundary();o.install_write_boundary(out, counts)
result={}
try: protected.write_text('bad')
except ValueError as e: result['write']=str(e)
try: socket.create_connection(('127.0.0.1',9))
except ValueError as e: result['network']=str(e)
try: (root/'credentials.json').read_text()
except ValueError as e: result['credentials']=str(e)
o.atomic(out/'STATE.json',{'allowed':True})
result['protected']=protected.read_text();result['own']=json.loads((out/'STATE.json').read_text())
result['counts']=counts
print(json.dumps(result))
'''
        result = subprocess.run([sys.executable, '-B', '-c', program],
                                cwd=Path(o.__file__).parent, capture_output=True, text=True, check=True)
        value = json.loads(result.stdout)
        self.assertEqual(value['write'], 'READ_ONLY_B_SOURCE_WRITE_BLOCKED')
        self.assertEqual(value['network'], 'CODE_ONLY_EXTERNAL_IO_BLOCKED')
        self.assertEqual(value['credentials'], 'CREDENTIAL_FILE_BLOCKED')
        self.assertEqual(value['protected'], 'unchanged')
        self.assertTrue(value['own']['allowed'])
        self.assertEqual(value['counts']['public_get_calls'], 0)
        self.assertEqual(value['counts']['order_calls'], 0)
        self.assertEqual(value['counts']['write_blocked_calls'], 1)


if __name__ == '__main__':
    unittest.main()
