import unittest
from ops.issue1358_entry_evidence_v1 import latest_known_minute, split_evidence


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
        d = json.loads(raw)
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
