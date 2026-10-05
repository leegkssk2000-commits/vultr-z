import unittest
from ops.issue1358_entry_evidence_v1 import latest_known_minute, load_effective_packet, split_evidence


def minute(stamp, received, close):
    return [stamp, '10', '11', '9', str(close), '1', received, 0, 'fixture']


class EntryEvidenceTest(unittest.TestCase):
    def test_late_receipt_not_admissible(self):
        rows = [minute(0, 61000, 10), minute(60000, 125000, 8)]
        self.assertEqual(latest_known_minute(rows, 122000)[4], '10')

    def test_decision_not_later_execution_clock(self):
        rows = [minute(0, 61000, 10), minute(60000, 126000, 8)]
        self.assertEqual(latest_known_minute(rows, 122000)[4], '10')
        self.assertEqual(latest_known_minute(rows, 180000)[4], '8')

    def test_equal_receipt_is_known(self):
        self.assertEqual(latest_known_minute([minute(0, 61000, 10)], 61000)[4], '10')

    def test_market_order_not_receipt_order(self):
        rows = [minute(60000, 122000, 11), minute(0, 125000, 10)]
        self.assertEqual(latest_known_minute(rows, 126000)[4], '11')

    def test_absent_known_input_rejects(self):
        with self.assertRaisesRegex(ValueError, 'NO_KNOWN_MINUTE'):
            latest_known_minute([minute(0, 61000, 10)], 60000)

    def test_bad_clock_rejects(self):
        with self.assertRaisesRegex(ValueError, 'SOURCE_CLOCK'):
            latest_known_minute([minute(0, 59000, 10)], 61000)

    def test_clock_bool_rejects(self):
        with self.assertRaisesRegex(ValueError, 'INTEGER_AS_OF'):
            latest_known_minute([minute(0, 61000, 10)], True)

    def test_later_fill_cannot_become_feature(self):
        r = split_evidence(9, 10, 8)
        self.assertFalse(r['known_close_below_signal_low'])
        self.assertTrue(r['later_fill_below_signal_low'])
        self.assertFalse(r['later_fill_is_decision_feature'])

    def test_changing_future_fill_does_not_change_known_state(self):
        a, b = split_evidence(9, 10, 8), split_evidence(9, 10, 11)
        self.assertEqual(a['known_close_below_signal_low'], b['known_close_below_signal_low'])

    def test_nonfinite_rejects(self):
        with self.assertRaisesRegex(ValueError, 'FINITE_POSITIVE_PRICE'):
            split_evidence(9, float('nan'), 10)


class SavedPacketTest(unittest.TestCase):
    def packet(self):
        import hashlib, json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        raw = (root / 'research/campaigns/scalp7_20261005/entry_edge_pilot_v1/ENTRY_EVIDENCE_COMPACT.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '35cda9bb09813a791846f1d3c5bcacc063d4b3005dda4137dadcc2b98650dc0d')
        d = load_effective_packet()
        return root, d, [dict(zip(d['columns'], r)) for r in d['rows']]

    def test_saved_packet_hash_and_clock_domains(self):
        _, d, rows = self.packet()
        self.assertEqual(len(rows), 15)
        self.assertEqual(len({(r['symbol'], r['signal_open_ms']) for r in rows}), 15)
        for r in rows:
            self.assertLessEqual(r['known_minute_received_ms'], r['decision_input_ready_ms'])
            self.assertLessEqual(r['known_minute_open_ms'] + 60000, r['decision_input_ready_ms'])
            self.assertLess(r['decision_input_ready_ms'], r['modeled_entry_ms'])
        self.assertFalse(d['later_modeled_fill_is_decision_feature'])
        self.assertEqual(d['new_model_executions'], 0)
        self.assertFalse(d['entry_candidate_selected'])
        self.assertFalse(d['profitability_improvement_measured'])

    def test_effective_packet_applies_only_exact_nontrade_fill_correction(self):
        import hashlib, json
        from ops.issue1358_entry_evidence_v1 import CORRECTION_SHA
        root, effective, rows = self.packet()
        directory = root / 'research/campaigns/scalp7_20261005/entry_edge_pilot_v1'
        raw = (directory / 'ENTRY_EVIDENCE_COMPACT.json').read_bytes()
        correction_raw = (directory / 'ENTRY_EVIDENCE_REVIEW_CORRECTION_V1.json').read_bytes()
        original = json.loads(raw)
        correction = json.loads(correction_raw)
        correction_keys = {tuple(key) for key in correction['nontrade_signal_keys']}
        self.assertEqual(hashlib.sha256(correction_raw).hexdigest(), CORRECTION_SHA)
        self.assertEqual(effective['review_correction_sha256'], CORRECTION_SHA)
        self.assertEqual(effective['raw_compact_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(effective['schema'], 'zel.issue1358.entry_evidence.effective.v1')
        self.assertIsNone(effective['full_diagnostic_sha256'])
        self.assertEqual(effective['superseded_pre_review_full_diagnostic_sha256'],
                         original['full_diagnostic_sha256'])
        self.assertEqual(effective['summary'], original['summary'])
        self.assertEqual(len(correction_keys), 6)
        self.assertEqual({(r['symbol'], r['signal_open_ms']) for r in rows
                          if r['saved_parent_net_bps'] is None}, correction_keys)
        fill_index = original['columns'].index('later_modeled_fill')
        for old, current in zip(original['rows'], effective['rows']):
            expected = old.copy()
            if (old[0], old[1]) in correction_keys:
                self.assertIsNotNone(old[fill_index])  # retain the flawed predecessor bytes
                expected[fill_index] = None
            self.assertEqual(current, expected)  # all decision fields and completed rows unchanged
        self.assertTrue(all(r['later_modeled_fill'] is None for r in rows
                            if r['saved_parent_net_bps'] is None))
        self.assertEqual((directory / 'ENTRY_EVIDENCE_COMPACT.json').read_bytes(), raw)
        self.assertEqual((directory / 'ENTRY_EVIDENCE_REVIEW_CORRECTION_V1.json').read_bytes(), correction_raw)

    def test_changed_saved_packet_or_correction_is_rejected(self):
        import tempfile
        from pathlib import Path
        from ops.issue1358_entry_evidence_v1 import EVIDENCE_DIR
        with tempfile.TemporaryDirectory() as directory:
            compact = Path(directory) / 'ENTRY_EVIDENCE_COMPACT.json'
            correction = Path(directory) / 'ENTRY_EVIDENCE_REVIEW_CORRECTION_V1.json'
            compact.write_bytes((EVIDENCE_DIR / compact.name).read_bytes())
            correction.write_bytes((EVIDENCE_DIR / correction.name).read_bytes())
            compact.write_bytes(compact.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'SAVED_COMPACT_PIN'):
                load_effective_packet(compact, correction)
            compact.write_bytes((EVIDENCE_DIR / compact.name).read_bytes())
            correction.write_bytes(correction.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'SAVED_CORRECTION_PIN'):
                load_effective_packet(compact, correction)

    def test_duplicate_or_incorrect_correction_keys_are_rejected(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from ops.issue1358_entry_evidence_v1 import EVIDENCE_DIR, digest, encoded
        original = json.loads((EVIDENCE_DIR / 'ENTRY_EVIDENCE_REVIEW_CORRECTION_V1.json').read_bytes())
        for replacement, error in ((original['nontrade_signal_keys'][1], 'SAVED_PACKET_DUPLICATE_KEY'),
                                   (['BTC-USDT', 0], 'SAVED_CORRECTION_NONTRADE_KEYS'),
                                   (None, 'SAVED_CORRECTION_NONTRADE_KEYS')):
            correction = json.loads(json.dumps(original))
            if replacement is None:
                correction['nontrade_signal_keys'].pop()
            else:
                correction['nontrade_signal_keys'][0] = replacement
            raw = encoded(correction)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'correction.json'
                path.write_bytes(raw)
                # Exercise key-set validation independently of byte-pin rejection.
                with patch('ops.issue1358_entry_evidence_v1.CORRECTION_SHA', digest(raw)):
                    with self.assertRaisesRegex(ValueError, error):
                        load_effective_packet(correction_path=path)

    def test_changed_authoritative_semantics_is_rejected(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from ops.issue1358_entry_evidence_v1 import EVIDENCE_DIR, digest, encoded
        correction = json.loads((EVIDENCE_DIR / 'ENTRY_EVIDENCE_REVIEW_CORRECTION_V1.json').read_bytes())
        correction['authoritative_semantics']['modeled_entry_price'] = 1.0
        raw = encoded(correction)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'correction.json'
            path.write_bytes(raw)
            with patch('ops.issue1358_entry_evidence_v1.CORRECTION_SHA', digest(raw)):
                with self.assertRaisesRegex(ValueError, 'SAVED_CORRECTION_SEMANTICS'):
                    load_effective_packet(correction_path=path)

    def test_duplicate_saved_signal_is_rejected(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from ops.issue1358_entry_evidence_v1 import EVIDENCE_DIR, digest, encoded
        packet = json.loads((EVIDENCE_DIR / 'ENTRY_EVIDENCE_COMPACT.json').read_bytes())
        packet['rows'].append(packet['rows'][0])
        raw = encoded(packet)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'compact.json'
            path.write_bytes(raw)
            with patch('ops.issue1358_entry_evidence_v1.COMPACT_SHA', digest(raw)):
                with self.assertRaisesRegex(ValueError, 'SAVED_PACKET_DUPLICATE_KEY'):
                    load_effective_packet(compact_path=path)

    def test_original_parent_is_bound_without_replay(self):
        import hashlib, json, lzma
        from ops.issue1358_entry_evidence_v1 import PARENT, BUNDLE_SHA, RESULT_SHA
        root, d, rows = self.packet()
        raw = (root / 'research/campaigns/scalp7_20261004/clocked_lanes_v1/RESULT_BUNDLE.json.xz').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), BUNDLE_SHA)
        original = json.loads(lzma.decompress(raw))[PARENT + '/RESULT.json'].encode()
        self.assertEqual(hashlib.sha256(original).hexdigest(), RESULT_SHA)
        parent = json.loads(original)
        keys = {(s['symbol'], s['signal_open_ts_ms']) for s in parent['signals']}
        self.assertEqual({(r['symbol'], r['signal_open_ms']) for r in rows}, keys)
        trades = {(t['symbol'], t['signal_open_ts_ms']): t for t in parent['trades']}
        for r in rows:
            t = trades.get((r['symbol'], r['signal_open_ms']))
            self.assertEqual(r['saved_parent_net_bps'], None if t is None else t['net_bps'])
        completed = [r for r in rows if r['saved_parent_net_bps'] is not None]
        self.assertEqual(len(completed), 9)
        self.assertEqual(sum(r['later_modeled_fill'] < r['signal_low'] for r in completed), 3)
        self.assertEqual(sum(r['known_minute_close'] < r['signal_low'] for r in completed), 1)


if __name__ == '__main__':
    unittest.main()
