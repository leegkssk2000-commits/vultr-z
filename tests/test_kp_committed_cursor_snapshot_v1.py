"""Temporary metadata fixtures; no real market replay or runtime mutation."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from ops import kp_committed_cursor_snapshot_v1 as s


def encode(d):
    return (json.dumps(d, sort_keys=True, indent=2) + '\n').encode()


def fixture(root):
    identity = {'schema': 'scalp7.fresh_source.v2', 'source': s.SOURCE, 'interval': '1m',
                'timeZone': 0, 'order_authority': 'BLOCKED', 'synthetic_fill': False,
                'start_ms': 0, 'symbols': list(s.SYMBOLS)}
    raw = encode(identity); (root / 'IDENTITY.json').write_bytes(raw)
    cursor = {'identity_sha256': s.sha(raw), 'symbols': {symbol: [] for symbol in s.SYMBOLS}}
    for symbol in s.SYMBOLS:
        append(root, cursor, symbol)
    (root / 'CURSOR.json').write_bytes(encode(cursor))
    return cursor


def append(root, cursor, symbol, *, gap=False):
    seq = len(cursor['symbols'][symbol]); start = seq * 60000; end = start + 60000
    stem = f'requests/{symbol}/{seq}'
    r = {'symbol': symbol, 'start_ms': start, 'end_exclusive_ms': end,
         'received_at_ms': end + 2, 'requested_at_ms': end + 1, 'http_status': 200,
         'source': s.SOURCE, 'url': s.SOURCE + '?fixed',
         'query': {'symbol': symbol, 'interval': '1m', 'timeZone': 0, 'startTime': start, 'endTime': end-1},
         'synthetic_fill': False, 'missing_minutes': [start] if gap else [], 'rows': 0 if gap else 1,
         'state': 'GAP_PRESERVED' if gap else 'COMPLETE', 'volume_units': 'UNKNOWN',
         'body_path': stem + '.body', 'body_sha256': 'a'*64,
         'normalized_path': stem + '.csv.gz', 'normalized_sha256': 'b'*64}
    p = root / (stem + '.receipt.json'); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(encode(r)); cursor['symbols'][symbol].append({'path': str(p.relative_to(root)), 'sha256': s.sha(p.read_bytes())})


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.cursor = fixture(self.root)
        self.pin = self.cursor['identity_sha256']
    def run_capture(self, hook=None):
        return s.capture(self.root, self.pin, after_capture=hook)
    def mutate(self, change):
        d = json.loads((self.root/'CURSOR.json').read_bytes()); change(d)
        tmp = self.root/'next.json'; tmp.write_bytes(encode(d)); tmp.replace(self.root/'CURSOR.json')
    def edit_receipt(self, changes):
        ref = self.cursor['symbols'][s.SYMBOLS[0]][0]; p = self.root/ref['path']
        r = json.loads(p.read_bytes()); r.update(changes); p.write_bytes(encode(r))
        self.mutate(lambda c: c['symbols'][s.SYMBOLS[0]][0].update(sha256=s.sha(p.read_bytes())))
    def test_unchanged_six_symbols(self):
        r = self.run_capture(); self.assertTrue(r['metadata_snapshot_pass']); self.assertEqual(r['receipt_metadata_verified'], 6)
        self.assertFalse(r['cursor_changed']); self.assertEqual(r['raw_price_bodies_opened'], 0)
    def test_append_during_read_retains_only_captured_prefix(self):
        def hook():
            c = copy.deepcopy(self.cursor); append(self.root, c, s.SYMBOLS[0])
            self.mutate(lambda d: d.update(c))
        r = self.run_capture(hook)
        self.assertTrue(r['cursor_changed']); self.assertEqual(r['appended_records_excluded'][s.SYMBOLS[0]], 1)
        self.assertEqual(r['receipt_metadata_verified'], 6)
        self.assertEqual(r['symbols'][0]['end_exclusive_ms'], 60000)
    def test_rewritten_prefix_rejected(self):
        with self.assertRaisesRegex(s.SnapshotError, 'COMMITTED_PREFIX_REWRITTEN'):
            self.run_capture(lambda: self.mutate(lambda d: d['symbols'][s.SYMBOLS[0]][0].update(sha256='c'*64)))
    def test_reorder_rejected(self):
        c = copy.deepcopy(self.cursor); append(self.root, c, s.SYMBOLS[0]); self.mutate(lambda d: d.update(c))
        with self.assertRaisesRegex(s.SnapshotError, 'COMMITTED_PREFIX_REWRITTEN'):
            self.run_capture(lambda: self.mutate(lambda d: d['symbols'][s.SYMBOLS[0]].reverse()))
    def test_shrink_rejected(self):
        c = copy.deepcopy(self.cursor); append(self.root,c,s.SYMBOLS[0]); self.mutate(lambda d:d.update(c))
        with self.assertRaisesRegex(s.SnapshotError, 'COMMITTED_PREFIX_REWRITTEN'):
            self.run_capture(lambda:self.mutate(lambda d:d['symbols'][s.SYMBOLS[0]].pop()))
    def test_identity_changed_rejected(self):
        with self.assertRaisesRegex(s.SnapshotError, 'IDENTITY_CHANGED_DURING'):
            self.run_capture(lambda:(self.root/'IDENTITY.json').write_bytes(encode({'bad': True})))
    def test_receipt_changed_rejected(self):
        with self.assertRaisesRegex(s.SnapshotError, 'RECEIPT_HASH_CHANGED'):
            self.run_capture(lambda:(self.root/self.cursor['symbols'][s.SYMBOLS[0]][0]['path']).write_bytes(b'{}'))
    def test_symlink_receipt_rejected(self):
        p = self.root/self.cursor['symbols'][s.SYMBOLS[0]][0]['path']; other = self.root/'other'
        p.rename(other); p.symlink_to(other)
        with self.assertRaises(OSError): self.run_capture()
    def test_symlink_parent_rejected(self):
        p = self.root/'requests'/s.SYMBOLS[0]; other = self.root/'otherdir'; p.rename(other); p.symlink_to(other,target_is_directory=True)
        with self.assertRaises(OSError): self.run_capture()
    def test_traversal_rejected(self):
        self.mutate(lambda c:c['symbols'][s.SYMBOLS[0]][0].update(path='requests/'+s.SYMBOLS[0]+'/../bad.receipt.json'))
        with self.assertRaisesRegex(s.SnapshotError, 'TRAVERSAL'): self.run_capture()
    def test_duplicate_reference_rejected(self):
        self.mutate(lambda d:d['symbols'][s.SYMBOLS[0]].append(d['symbols'][s.SYMBOLS[0]][0]))
        with self.assertRaisesRegex(s.SnapshotError, 'DUPLICATE_RECEIPT_REFERENCE'): self.run_capture()
    def test_wrong_pin_rejected(self):
        with self.assertRaisesRegex(s.SnapshotError,'SOURCE_IDENTITY_PIN'): s.capture(self.root,'0'*64)
    def test_gap_preserved_not_filled(self):
        c=copy.deepcopy(self.cursor);append(self.root,c,s.SYMBOLS[0],gap=True);self.mutate(lambda d:d.update(c))
        r=self.run_capture();self.assertEqual(r['symbols'][0]['explicit_missing_minutes'],1)
        self.assertEqual(r['symbols'][0]['reported_rows'],1)
    def test_row_mismatch_rejected(self):
        self.edit_receipt({'rows':2})
        with self.assertRaisesRegex(s.SnapshotError,'ROW_ACCOUNTING'): self.run_capture()
    def test_future_clock_rejected(self):
        self.edit_receipt({'received_at_ms':9999999999999})
        with self.assertRaisesRegex(s.SnapshotError,'IDENTITY_WINDOW_OR_CLOCK'):self.run_capture()
    def test_discontinuous_window_rejected(self):
        self.edit_receipt({'start_ms':60000})
        with self.assertRaisesRegex(s.SnapshotError,'IDENTITY_WINDOW_OR_CLOCK'):self.run_capture()
    def test_duplicate_json_rejected(self):
        with self.assertRaisesRegex(s.SnapshotError,'DUPLICATE_JSON_KEY'):s.load(b'{"x":1,"x":2}')
    def test_no_source_body_exists_and_still_only_metadata(self):
        r=self.run_capture();self.assertFalse(r['body_hashes_verified']);self.assertFalse(r['unused_data_certified'])
        self.assertFalse(r['market_execution_ready']);self.assertFalse(r['existing_frozen_reader_replaced'])
        self.assertEqual(r['strategy_invocations'],0)
    def test_budget_failure_not_fake_success(self):
        with self.assertRaisesRegex(s.SnapshotError,'TIME_BUDGET'):s.capture(self.root,self.pin,time_budget_s=0)
    def test_non_regular_rejected_without_blocking(self):
        p=self.root/self.cursor['symbols'][s.SYMBOLS[0]][0]['path'];p.unlink();os.mkfifo(p)
        with self.assertRaisesRegex(s.SnapshotError,'REGULAR_FILE_REQUIRED'):self.run_capture()


class FrozenReaderRegression(unittest.TestCase):
    def test_exact_old_frame_builder_rejects_append_only_publication(self):
        from backend.research.rebuild import scalp7_fresh_forward_v2 as old
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=fixture(root)
            def loader(_):
                newer=copy.deepcopy(c);append(root,newer,s.SYMBOLS[0])
                p=root/'next';p.write_bytes(encode(newer));p.replace(root/'CURSOR.json')
                return {symbol:None for symbol in s.SYMBOLS}
            config={'sources':[{'path':str(root),'identity_sha256':c['identity_sha256']}]}
            with patch.object(old,'load_observed_minutes',side_effect=loader),patch.object(old,'sha_file',return_value=c['identity_sha256']):
                with self.assertRaisesRegex(old.FreshForwardError,'SOURCE_SNAPSHOT_CHANGED_RETRY_WITHOUT_ADVANCING'):
                    old.build_current_frames(config,999999)

if __name__ == '__main__': unittest.main()
