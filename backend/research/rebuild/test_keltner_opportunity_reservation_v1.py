import unittest
from pathlib import Path
from unittest.mock import patch

from backend.research.rebuild import keltner_opportunity_reservation_v1 as r


class IntegrationTests(unittest.TestCase):
    def test_consumed_candidate_stops_before_data_or_execution(self):
        with patch.object(r, 'authorize', return_value={}), patch.object(Path, 'exists', return_value=True), \
             patch.object(r, 'load_stored') as stored, patch.object(r.prior.previous, 'load_inputs') as data:
            with self.assertRaisesRegex(RuntimeError, 'CONSUMED'):
                r.run(Path('/not-read'))
            stored.assert_not_called(); data.assert_not_called()

    def test_missing_reproduction_stops_before_data(self):
        with patch.object(r, 'authorize', return_value={}), patch.object(Path, 'exists', return_value=False), \
             patch.object(r.prior.previous, 'load_inputs') as data:
            with self.assertRaisesRegex(RuntimeError, 'MISSING'):
                r.run(Path('/not-read'), verify_only=True)
            data.assert_not_called()

    def test_new_budget_and_unchanged_formal_authority(self):
        c = {**r.AUTH, 'authorization': r.AUTHORIZATION, 'candidate_id': r.CANDIDATE,
             'candidate_cumulative_before': 29, 'allocated_new_candidates': 1,
             'rule': r.RULE, 'goal': r.metrics.GOAL, 'new_M_replay_completed_at_freeze': False,
             'expected_common_D_result_previously_seen': True, 'order_authority': 'OPEN'}
        with patch.object(r.old, 'read', return_value=c), patch.object(r.old.probe, 'verify_seal'), \
             patch.object(r.old, 'file_sha') as sha:
            with self.assertRaisesRegex(RuntimeError, 'AUTHORITY:order_authority'):
                r.authorize()
            sha.assert_not_called()

    def test_reservation_passes_only_prices_original_features_to_adapter(self):
        raw = {'trades': [], 'open_positions': [], 'events': [], 'trace': [], 'audit': {},
               'reference_events': [{'kind': 'REFERENCE_RESERVED_AT_SIGNAL_CLOSE'}],
               'reference_opportunities': [{'model_selected': False}],
               'reference_checkpoint': {'phase': 'HELD'}}
        charged = {'trades': [], 'open_observations': [], 'events': [], 'trace': [], 'audit': {}}
        rows, bundle = [{'bar_open_ts': 0}], {'signals': []}
        with patch.object(r.adapter, 'replay', return_value=raw) as execution, \
             patch.object(r.prior, 'charge', return_value=charged) as costs:
            value = r.replay({'S': rows}, {'S': bundle}, {}, {}, 0, 1)
        execution.assert_called_once_with(rows, bundle, eval_start_ms=0, eval_end_ms=1, enabled=True)
        self.assertEqual(value['trades'], [])
        self.assertEqual(value['reference_opportunities'], [{'model_selected': False, 'symbol': 'S'}])
        self.assertEqual(value['reference_states']['S'], {'phase': 'HELD'})
        self.assertEqual(costs.call_args.args[0]['trades'], [])

    def test_regression_common_list_is_comparison_not_forced_match(self):
        expected = {'trades': [{'origin_key': 'old'}], 'open_observations': []}
        actual = {'trades': [], 'open_observations': []}
        with patch.object(r.adapter, 'replay') as execution:
            answer = r.comparison_only_common_parity(actual, expected)
            execution.assert_not_called()
        self.assertEqual(answer['status'], 'DIFFERENCE_REQUIRES_SEMANTIC_REVIEW')
        self.assertFalse(answer['historical_common_list_used_for_execution'])
        self.assertEqual(actual['trades'], [])

    def test_same_window_labels_use_global_origin_identity(self):
        view = lambda ids: {'trades': [{'origin_key': i} for i in ids], 'open_observations': []}
        item = lambda key, value: {'origin_key': key, 'delta': {'net_bps': value}}
        cmp = {'same_calendar_windows': [{'start_ms': 0, 'end_ms': 1, 'labels': ['WINDOW'],
            'parent': {'position_contributions': [item('c', -4), item('removed', -3)]},
            'child': {'position_contributions': [item('restored', -1)]},
            'child_minus_parent': {'net_bps': 6}}]}
        result = r.annotated_windows(cmp, view(['c', 'restored']), view(['c', 'removed']), view(['c', 'restored']))
        self.assertEqual(result[0]['groups'], {'COMMON': 4, 'REMOVED_N': 3, 'RESTORED_D': -1, 'OTHER_NEW_M': 0})
        self.assertTrue(result[0]['overlapping_windows_must_not_be_summed'])

    def test_report_starts_economics_and_separates_virtual_reference(self):
        result = {'results': {'SEEN2026': {'table': [{'metric': 'closed_net_bps', 'P': -4., 'D': -3.,
            'N': -1., 'M': -1., 'M_minus_N': 0., 'M_minus_D': 2., 'M_minus_P': 3.}],
            'questions': {}, 'common_D_regression': {'status': 'MATCH'}, 'funnel_by_symbol': {},
            'comparisons': {'N_to_M': {'net_decomposition': {}, 'uncertainty': {},
                 'decision': {'absolute_economic_decision': 'REJECT', 'incremental_decision': 'UNCHANGED'}}}}},
            'decision': {'decision': 'REJECT', 'partial_workcopy_retained': True}}
        text = r.report(result).decode()
        self.assertIn('| -4.0000 | -3.0000 | -1.0000 | -1.0000 | 0.0000 | 2.0000 | 3.0000 |', text)
        self.assertIn('UNCHANGED', text); self.assertIn('zero money', text)


if __name__ == '__main__':
    unittest.main()
