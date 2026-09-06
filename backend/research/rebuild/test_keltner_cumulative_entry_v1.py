"""Research allocation, identity and report integration without price replay."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from backend.research.rebuild import keltner_cumulative_entry_v1 as run


class IntegrationTests(unittest.TestCase):
    def test_disabled_parity_rejects_funding_change(self):
        trade = {'origin_key': 'a', 'signal_index': 0, 'entry_index': 1, 'entry_ts': 1,
                 'entry_price': 100., 'hold_ms': 2, 'side': 'long', 'exit_index': 2,
                 'exit_ts': 3, 'exit_price': 110., 'gross_bps': 1000., 'net_bps': 980.,
                 'cost_bps': 20., 'funding_bps': 0., 'cost2x_net_bps': 960.}
        view = {'trades': [trade], 'open_observations': [], 'events': []}
        run.assert_D_parity(view, deepcopy(view))
        altered = deepcopy(view); altered['trades'][0]['funding_bps'] = 1.
        with self.assertRaisesRegex(RuntimeError, 'ECONOMIC_PARITY:funding'):
            run.assert_D_parity(altered, view)

    def test_missing_open_origin_is_not_zero_profit_or_dropped(self):
        with self.assertRaisesRegex(RuntimeError, 'ORIGIN_PARITY:open'):
            run.assert_D_parity({'trades': [], 'open_observations': [], 'events': []},
                               {'trades': [], 'open_observations': [{'origin_key': 'tail'}], 'events': []})

    def test_old_excluded_opportunity_cannot_disappear(self):
        event = {'symbol': 's', 'signal_ts': 1, 'status': 'EXCLUDED', 'exclusion_reason': 'SIGNAL_DURING_OPEN'}
        with self.assertRaisesRegex(RuntimeError, 'OPPORTUNITY_PARITY'):
            run.assert_D_parity({'trades': [], 'open_observations': [], 'events': []},
                               {'trades': [], 'open_observations': [], 'events': [event]})

    def test_consumed_result_blocks_input_reads(self):
        with patch.object(run, 'authorize', return_value={}), patch.object(run.Path, 'exists', return_value=True), patch.object(run, 'load_stored') as read:
            with self.assertRaisesRegex(RuntimeError, 'CONSUMED_OR_MISSING'):
                run.run('never-read')
            read.assert_not_called()

    def test_reproduction_requires_existing_result(self):
        with patch.object(run, 'authorize', return_value={}), patch.object(run.Path, 'exists', return_value=False), patch.object(run, 'load_stored') as read:
            with self.assertRaisesRegex(RuntimeError, 'CONSUMED_OR_MISSING'):
                run.run('never-read', verify_only=True)
            read.assert_not_called()

    def test_new_authority_cannot_relax_formal_boundary(self):
        c = {**run.AUTH, 'authorization': run.AUTHORIZATION, 'candidate_id': run.CANDIDATE,
             'rule': run.RULE, 'goal': run.metrics.GOAL, 'candidate_cumulative_before': 28,
             'allocated_new_candidates': 1, 'new_N_outcomes_seen_at_freeze': False,
             'calendars': run.previous.CALENDARS['KELTNER'], 'G6_authorized': True}
        with patch.object(run.old, 'read', return_value=c), patch.object(run.old.probe, 'verify_seal'), patch.object(run.old, 'file_sha') as sha:
            with self.assertRaisesRegex(RuntimeError, 'AUTHORITY:G6_authorized'):
                run.authorize()
            sha.assert_not_called()

    def test_report_uses_three_reference_deltas_and_not_code_pass(self):
        r = {'results': {'DEV2025': {'table': [{'metric': 'closed_net_bps', 'P': -10.,
             'D': -5., 'N': -2., 'N_minus_D': 3., 'N_minus_P': 8.}],
             'comparisons': {'D_to_N': {'decision': {'decision': 'REJECT'},
               'net_decomposition': {}, 'uncertainty': {}}},
             'questions': {'original_P_opportunity_effects': {'per_original_origin': ['ROW_DETAIL_SENTINEL']}}}}}
        text = run.report(r).decode()
        self.assertIn('| -10.0000 | -5.0000 | -2.0000 | 3.0000 | 8.0000 |', text)
        self.assertIn('REJECT', text)
        self.assertIn('independent=false', text)
        self.assertNotIn('ROW_DETAIL_SENTINEL', text)


if __name__ == '__main__':
    unittest.main()
