"""Causal clock/coverage tests; optional pinned saved126 audit uses K126_INPUT_ROOT."""
import copy
import os
from pathlib import Path
import unittest
import causal_exposure as c


def trade(symbol, entry, exit_ts, net, side=-1, window='rolling_1'):
    return {'symbol': symbol, 'side': side, 'signal_ts_ms': entry, 'entry_ts_ms': entry,
            'exit_ts_ms': exit_ts, 'outcome_available_ts_ms': exit_ts,
            'identity': c.LINEAGE_ID, 'window_label': window, 'gross_bps': net+1,
            'cost_bps': 1, 'net_bps': net, 'mfe_R': 3 if net > 0 else 0,
            'signal': {'meta': {'frozen_cost_bps': 0.5, 'feature_available_ts_ms': entry}}}


def context(rows):
    geometry = [{'key': list(c.key(t)), 'entry_price': 100, 'initial_stop': 102,
                 'initial_risk_price': 2} for t in rows]
    paths = [{'trade_key': list(c.key(t)), 'bars': [
        {'available_ts_ms': t['entry_ts_ms'], 'close': 100},
        {'available_ts_ms': t['outcome_available_ts_ms']+1, 'close': 99999}]} for t in rows]
    return geometry, paths


class ClockTests(unittest.TestCase):
    def test_four_open_not_known_and_later_reentry_knows_all(self):
        rows = [trade('EARLIER', 1, 2, -7), trade('ETH', 10, 30, -1),
                trade('SOL', 10, 30, -2), trade('LINK', 20, 40, -3),
                trade('XRP', 20, 40, -4), trade('SOL', 50, 60, 5)]
        result = c.build_stream(rows, *context(rows))
        at20 = [s for s in result['entry_snapshots'] if s['decision_ts_ms'] == 20]
        self.assertEqual(len(at20), 2)
        for s in at20:
            self.assertEqual(s['known_outcomes_strictly_earlier']['loss_count'], 1)
            self.assertEqual(len(s['existing_same_direction']), 2)
            self.assertEqual(len(s['same_time_same_direction_request_keys']), 2)
        at50 = next(s for s in result['entry_snapshots'] if s['decision_ts_ms'] == 50)
        self.assertEqual(at50['known_outcomes_strictly_earlier']['loss_count'], 5)
        self.assertEqual(at50['same_setup_reentry'], 'REQUIRED_INPUT_SETUP_INSTANCE_ID')

    def test_same_time_mixed_outcomes_excluded_but_kept_as_batch(self):
        rows = [trade('A', 10, 20, 5), trade('B', 10, 20, -2), trade('C', 20, 30, 4)]
        result = c.build_stream(rows, *context(rows))
        s = next(s for s in result['entry_snapshots'] if s['decision_ts_ms'] == 20)
        self.assertEqual(s['known_outcomes_strictly_earlier']['native_outcome_refs'], [])
        self.assertEqual(len(s['existing_same_direction']), 2)
        self.assertEqual(len(s['same_time_outcome_keys_excluded_from_decision']), 2)
        self.assertEqual(result['outcome_batches'][0]['kind'], 'MIXED_SIGNS')
        kinds = [e['kind'] for e in result['events'] if e['ts_ms'] == 20]
        self.assertEqual(kinds, ['ENTRY', 'EXIT_RECORDED', 'EXIT_RECORDED', 'OUTCOME_KNOWN', 'OUTCOME_KNOWN'])

    def test_future_path_and_final_cost_not_in_entry_fields(self):
        rows = [trade('A', 10, 40, -1), trade('B', 20, 30, 2)]
        rows[1]['cost_bps'] = 500
        result = c.build_stream(rows, *context(rows))
        s = next(s for s in result['entry_snapshots'] if s['decision_ts_ms'] == 20)
        self.assertEqual(s['entry_known']['reference_cost_bps'], 0.5)
        self.assertEqual(s['existing_same_direction'][0]['last_completed_close'], 100)
        self.assertIsNone(s['existing_same_direction'][0]['remaining_risk_quote'])

    def test_input_permutation_does_not_change_stream(self):
        rows = [trade('Z', 10, 30, -1), trade('A', 10, 20, 2), trade('B', 15, 25, 3)]
        g, p = context(rows)
        self.assertEqual(c.build_stream(rows, g, p), c.build_stream(list(reversed(rows)), g[::-1], p[::-1]))

    def test_overlap_chain_and_touching_endpoints_are_distinct(self):
        rows = [trade('A', 10, 20, 1), trade('B', 15, 30, 1),
                trade('C', 25, 40, 1), trade('D', 40, 50, -1)]
        result = c.all_directional_clusters(rows)
        self.assertEqual(result['cluster_count'], 2)
        first = result['clusters'][0]
        self.assertEqual(first['count'], 3)
        self.assertEqual(first['peak_simultaneous'], 2)
        self.assertEqual(first['post_outcome_labels_NOT_ADMISSION_FEATURES']['cohort'], 'ALL_WINNERS')

    def test_independent_window_prior_loss_preserved_as_audit_only(self):
        rows = [trade('A', 10, 20, -5), trade('B', 30, 40, 1, window='rolling_2')]
        s = c.build_stream(rows, *context(rows))['entry_snapshots'][1]
        self.assertEqual(s['known_outcomes_strictly_earlier']['loss_count'], 1)
        self.assertEqual(s['known_same_window_outcomes']['loss_count'], 0)
        self.assertEqual(len(s['earlier_window_outcome_refs_for_audit_not_automatic_policy_carry']), 1)


@unittest.skipUnless(os.environ.get('K126_INPUT_ROOT'), 'Set K126_INPUT_ROOT for immutable saved126 tests')
class Saved126Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = c.load_inputs(os.environ['K126_INPUT_ROOT'])
        normalizer = Path(__file__).resolve().parents[2] / 'portfolio_coverage_v1/work_d/contribution_report.py'
        cls.normalizer = c.load_reused_normalizer(normalizer)
        cls.events, cls.clusters = c.assemble(cls.values, cls.normalizer)
        cls.rows = cls.values['current/ROWS.json.gz']['trades']

    def test_pinned_all126_events_and_all_winners_included(self):
        self.assertEqual(self.events['event_counts'], {'ENTRY': 126, 'EXIT_RECORDED': 126, 'OUTCOME_KNOWN': 126})
        self.assertEqual(self.clusters['trade_coverage'], 126)
        self.assertEqual(self.clusters['winner_coverage'], 69)
        self.assertEqual(self.clusters['large_winner_coverage'], 34)
        self.assertEqual(len({e['event_id'] for e in self.events['events']}), 378)

    def test_original_native_streaks_are_preserved(self):
        for multiplier, expected in [(1, 8), (2, 13)]:
            run = longest = 0
            for t in sorted(self.rows, key=c.native_order):
                run = run+1 if t['gross_bps']-multiplier*t['cost_bps'] < 0 else 0
                longest = max(longest, run)
            self.assertEqual(longest, expected)
            self.assertEqual(self.events['source_row_loss_metrics_copied_unchanged'][f'cost{multiplier}x']['MaxLossStreak'], expected)

    def test_actual_four_overlaps_and_0830_known_loss_boundary(self):
        snapshots = self.events['entry_snapshots']
        index = self.events['native_outcome_key_index']
        at0330 = [s for s in snapshots if s['decision_ts_ms'] == 1771817400000]
        at0430 = [s for s in snapshots if s['decision_ts_ms'] == 1771821000000]
        scratch_keys = {tuple(s['trade_key']) for s in at0330+at0430}
        self.assertEqual(len(scratch_keys), 4)
        for s in at0330+at0430:
            self.assertFalse(scratch_keys & {tuple(index[i]) for i in s['known_outcomes_strictly_earlier']['native_outcome_refs']})
            self.assertGreater(s['known_outcomes_strictly_earlier']['loss_count'], 0)
        for s in at0430:
            self.assertEqual(len(s['existing_same_direction']), 2)
        later = next(s for s in snapshots if s['decision_ts_ms'] == 1771835400000)
        self.assertTrue(scratch_keys <= {tuple(index[i]) for i in later['known_outcomes_strictly_earlier']['native_outcome_refs']})
        self.assertIsNone(later['canonical_setup_id'])

    def test_all_actual_tied_outcomes_are_withheld_at_entry(self):
        self.assertEqual(len(self.events['simultaneous_entry_outcome_timestamps']), 2)
        index = self.events['native_outcome_key_index']
        for s in self.events['entry_snapshots']:
            known = {tuple(index[i]) for i in s['known_outcomes_strictly_earlier']['native_outcome_refs']}
            tied = {tuple(k) for k in s['same_time_outcome_keys_excluded_from_decision']}
            self.assertFalse(known & tied)
        mixed = [b for b in self.events['outcome_batches'] if b['kind'] == 'MIXED_SIGNS']
        self.assertEqual(len(mixed), 5)

    def test_tampered_geometry_rejected(self):
        geom = copy.deepcopy(self.values['diagnostic/ENTRY_GEOMETRY_ALL126.json'])
        geom[0]['entry_price'] += 1
        with self.assertRaises(ValueError):
            c.audit_inputs(self.values['current/ROWS.json.gz'], geom,
                           self.values['diagnostic/RAW_PATHS_ALL126.json.gz'], self.normalizer)


if __name__ == '__main__':
    unittest.main()
