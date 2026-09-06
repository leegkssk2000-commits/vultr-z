"""Allocation, input-boundary and integration checks without historical replay."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from backend.research.rebuild import parallel_exit_dev_v1 as run


class IntegrationTests(unittest.TestCase):
    def test_original_closed_economics_mismatch_is_not_metadata(self):
        trade = dict(symbol='BTC-USDT', signal_ts=1, entry_ts=2, entry_price=100.,
                     exit_ts=3, exit_price=110., side='long', gross_bps=1000.,
                     net_bps=980., cost2x_net_bps=960., cost_bps=20., funding_bps=0., hold_ms=1)
        parent = {'trades': [trade], 'open_observations': []}
        with patch.object(run.old, 'read', return_value={}), patch.object(
                run.seen_run.original, 'load_parent', return_value=deepcopy(parent)):
            self.assertEqual(run.parent_parity('Q0', 'DEV2025', parent)['completed_T'], 1)
            changed = deepcopy(parent)
            changed['trades'][0]['funding_bps'] = 1.
            with self.assertRaisesRegex(RuntimeError, 'PARENT_ECONOMICS'):
                run.parent_parity('Q0', 'DEV2025', changed)

    def test_missing_old_parent_origin_blocks_comparison(self):
        with patch.object(run.old, 'read', return_value={}), patch.object(
                run.seen_run.original, 'load_parent', return_value={'trades': []}):
            with self.assertRaisesRegex(RuntimeError, 'PARENT_ORIGINS'):
                run.parent_parity('Q0', 'DEV2025', {
                    'trades': [{'symbol': 'BTC-USDT', 'signal_ts': 1, 'side': 'long'}],
                    'open_observations': []})

    def test_bounded_seen_loader_is_only_price_reader_and_native_prefix_is_preserved(self):
        start = run.seen.SOURCE_START
        rows = [{'bar_open_ts': start + i*run.seen.BAR,
                 'bar_close_ts': start + (i+1)*run.seen.BAR} for i in range(3748)]
        expected_end = run.CALENDARS['Q0']['SEEN2026'][1]
        c = {'data_sha256': 'data', 'cost_sha256': 'cost'}
        policy = {'cost_binding_sha256': 'cost', 'combined_data_sha256': 'data'}
        with patch.object(run.old, 'read', return_value={'frozen': True}), patch.object(
                run.seen, 'load_seen_inputs', return_value=(policy, {'cost_by_symbol': {}},
                                                            {'BTC-USDT': rows}, {'audit': True})) as loader:
            _, _, periods, access = run.load_inputs('only-approved-canonical-dir', c)
            self.assertEqual(loader.call_count, 1)
            self.assertEqual(len(periods['DEV2025']['BTC-USDT']), 2250)
            self.assertEqual(periods['SEEN2026']['BTC-USDT'][-1]['bar_close_ts'], expected_end)
            self.assertEqual(access, {'audit': True})

    def test_truncated_original_prefix_fails_instead_of_interpolation(self):
        c = {'data_sha256': 'data', 'cost_sha256': 'cost'}
        with patch.object(run.old, 'read', return_value={}), patch.object(
                run.seen, 'load_seen_inputs', return_value=(
                    {'cost_binding_sha256': 'cost', 'combined_data_sha256': 'data'},
                    {'cost_by_symbol': {}}, {'BTC-USDT': []}, {})):
            with self.assertRaisesRegex(RuntimeError, 'ORIGINAL_DEV_PREFIX'):
                run.load_inputs('only-approved-canonical-dir', c)

    def test_result_is_consumed_before_any_input_decode(self):
        with patch.object(run, 'authorize', return_value={}), patch.object(
                run.Path, 'exists', return_value=True), patch.object(run, 'load_inputs') as loader:
            with self.assertRaisesRegex(RuntimeError, 'ALLOCATIONS_CONSUMED'):
                run.run('not-read')
            loader.assert_not_called()

    def test_reproduction_requires_existing_result_before_input(self):
        with patch.object(run, 'authorize', return_value={}), patch.object(
                run.Path, 'exists', return_value=False), patch.object(run, 'load_inputs') as loader:
            with self.assertRaisesRegex(RuntimeError, 'NO_RESULTS_TO_REPRODUCE'):
                run.run('not-read', verify_only=True)
            loader.assert_not_called()

    def test_modified_authority_fails_before_preserved_file_access(self):
        c = {**run.AUTH, 'authorization': run.AUTHORIZATION, 'candidates': run.CANDIDATES,
             'calendars': run.CALENDARS, 'rules': run.RULES, 'goal': run.metrics.GOAL,
             'new_outcomes_seen_at_freeze': False, 'candidate_cumulative_before': 26,
             'allocated_new_candidates': 2, 'symbols': list(run.seen.SYMBOLS)}
        c['G6_authorized'] = True
        with patch.object(run.old, 'read', return_value=c), patch.object(run.old.probe, 'verify_seal'), patch.object(run.old, 'file_sha') as sha:
            with self.assertRaisesRegex(RuntimeError, 'AUTHORITY:G6_authorized'):
                run.authorize()
            sha.assert_not_called()


if __name__ == '__main__':
    unittest.main()
