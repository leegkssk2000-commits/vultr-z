"""Synthetic accounting/boundary checks; never loads historical DEV data."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import supertrend_flip_ab_v1 as x
from backend.research.rebuild.test_supertrend_flip_direction_dev_v1 import bars
from backend.research.rebuild.test_top5_development_repair_v1 import fixture


def policy():
    return {'development_interval_ms': [0, 30*x.INTERVAL], 'batch_id': 'SYNTHETIC',
            'receipt_sha256': 'synthetic', 'combined_data_sha256': 'synthetic',
            'cost_binding_sha256': 'synthetic', 'code_files_sha256': {},
            'uncertainty': {'method': 'SYNTHETIC_WEEK_BOOTSTRAP',
                            'seed': 1178, 'replications': 1000}}


COSTS = {'TEST': {'fee_bps': 10, 'spread_bps': 2, 'impact_bps': 1,
                  'funding_p95_per_settlement_bps': 3}}


def trade(origin, net):
    return {'lane_id': x.LANE, 'symbol': 'TEST', 'signal_ts': origin*x.INTERVAL,
            'side': 'long', 'entry_ts': origin*x.INTERVAL,
            'exit_ts': (origin+1)*x.INTERVAL, 'hold_ms': x.INTERVAL,
            'net_bps': net, 'gross_bps': net+20, 'cost2x_net_bps': net-20,
            'cost_bps': 20, 'fee_bps': 10, 'spread_bps': 2, 'impact_bps': 1,
            'slippage_bps': 0, 'funding_bps': 2, 'frozen_floor_reserve_bps': 5,
            'mfe_bps': 100, 'mae_bps': -100}


def opened(origin, net_mark=0):
    return {'lane_id': x.LANE, 'symbol': 'TEST', 'signal_ts': origin*x.INTERVAL,
            'side': 'long', 'entry_ts': origin*x.INTERVAL, 'hold_ms': x.INTERVAL,
            'gross_mark_bps': net_mark+20, 'modeled_funding_accrued_bps': 3,
            'hypothetical_liquidation_cost_bps': 20,
            'hypothetical_liquidation_net_mark_bps': net_mark,
            'hypothetical_liquidation_cost2x_net_mark_bps': net_mark-20}


class MarkCostAndSummary(unittest.TestCase):
    def test_open_charge_accrues_actual_elapsed_funding_not_roundtrip_as_accrued(self):
        rows = bars(10)
        raw = x.direction.replay_direction(rows, [0], [], split_start_ms=0,
                                          split_end_ms=10*x.INTERVAL)['open_positions']
        before = copy.deepcopy(raw)
        with patch.object(x.old.probe, 'cost_components', wraps=x.old.probe.cost_components) as spy:
            position = x.charge_open(raw, 'TEST', 'B', policy(), COSTS, rows)[0]
        self.assertEqual(spy.call_args.args[:2], (x.INTERVAL, 9*x.INTERVAL))
        self.assertEqual(position['funding_settlements_elapsed'], 4)
        self.assertEqual(position['modeled_funding_accrued_bps'], 12)
        self.assertEqual(position['hypothetical_liquidation_cost_bps'], 25)
        self.assertEqual(position['hypothetical_liquidation_net_mark_bps'], -25)
        self.assertEqual(position['hypothetical_liquidation_cost2x_net_mark_bps'], -50)
        self.assertIsNone(position['entry_side_cost_bps'])
        self.assertEqual(position['entry_side_cost_status'], 'NOT_SEPARATELY_BOUND')
        self.assertFalse(position['actual_exit'])
        self.assertFalse(set(position) & {'exit_ts', 'exit_price', 'exit_index',
                                         'gross_bps', 'net_bps', 'cost_bps'})
        self.assertEqual(raw, before)
        for key, value in x.old.probe.DEV_AUTH.items():
            self.assertEqual(position[key], value)

    def test_shared_cost_floor_is_hypothetical_not_additional_funding(self):
        rows = bars(4)
        raw = x.direction.replay_direction(rows, [0], [], split_start_ms=0,
                                          split_end_ms=4*x.INTERVAL)['open_positions']
        value = x.charge_open(raw, 'TEST', 'B', policy(), COSTS, rows)[0]
        self.assertEqual(value['funding_settlements_elapsed'], 1)
        self.assertEqual(value['modeled_funding_accrued_bps'], 3)
        self.assertEqual(value['hypothetical_liquidation_cost_bps'], 20)
        self.assertEqual(value['hypothetical_cost_components_bps']['frozen_floor_reserve_bps'], 4)

    def test_censored_events_do_not_become_exclusions_and_exposure_stays_visible(self):
        events = [{'admission': True, 'status': 'COMPLETED', 'exclusion_reason': None},
                  {'admission': True, 'status': 'CENSORED', 'exclusion_reason': None},
                  {'admission': True, 'status': 'EXCLUDED', 'exclusion_reason': 'SIGNAL_DURING_OPEN'}]
        m = x.summarize_stage([trade(1, 100)], [opened(2, -500)], events, policy(), ['TEST'])
        self.assertEqual(m['excluded'], {'SIGNAL_DURING_OPEN': 1})
        self.assertEqual((m['raw_signals'], m['admitted_signals'], m['censored_signals']), (3, 3, 1))
        self.assertEqual(m['entries_including_censored_T'], 2)
        self.assertEqual(m['base_cost']['completed_T'], 1)
        self.assertEqual(m['base_cost']['net_bps'], 100)
        self.assertAlmostEqual(m['total_exposure_symbol_days'], 8/24)
        self.assertEqual(m['closed_plus_hypothetical_terminal_mark_bps'], -400)


class CensoredAccounting(unittest.TestCase):
    def test_common_new_removed_and_unfinished_bridge_is_exact(self):
        parent = [trade(1, 100), trade(2, -70), trade(3, 40), trade(4, 30), trade(5, -20)]
        child = [trade(1, 80), trade(2, -20), trade(6, 10)]
        pending = [opened(4, -999), opened(5, 200), opened(7, 50)]
        a = x.censored_attribution(parent, child, pending)
        self.assertEqual([a[k] for k in ('common_completed_T', 'common_censored_T',
                                        'removed_T', 'new_completed_T', 'new_censored_T')], [2, 2, 1, 1, 1])
        self.assertEqual(a['common_completed_delta_bps'], 30)
        self.assertEqual(a['removed_parent_net_bps'], 40)
        self.assertEqual(a['parent_net_on_censored_origins_bps'], 10)
        self.assertEqual(a['new_completed_net_bps'], 10)
        self.assertEqual(a['closed_net_delta_bps'], -10)
        self.assertEqual(a['terminal_hypothetical_mark_bps'], -749)
        self.assertEqual(a['marked_delta_bps_not_realized'], -759)
        self.assertEqual(a['unfilled_parent_loss_bps'], 0)
        self.assertEqual(a['unfilled_parent_winner_bps'], 40)
        self.assertEqual(a['resolved_common_effects']['saved_common_loss_bps'], 50)
        self.assertAlmostEqual(a['winner']['amount_retention_lower'], 80/170)
        self.assertAlmostEqual(a['winner']['amount_retention_upper'], 110/170)

    def test_original_profit_bounds_cap_large_gains_and_exclude_open_mark_guess(self):
        p = [trade(1, 100), trade(2, 300)]
        c = [trade(1, 10000)]
        for mark in (-1e9, 1e9):
            a = x.censored_attribution(p, c, [opened(2, mark)])
            self.assertEqual(a['winner']['resolved_preserved_bps'], 100)
            self.assertEqual(a['winner']['amount_retention_lower'], .25)
            self.assertEqual(a['winner']['amount_retention_upper'], 1)
            self.assertEqual(a['large_winner']['amount_retention_lower'], 0)
            self.assertEqual(a['large_winner']['amount_retention_upper'], 1)

    def test_loser_relabeling_and_double_resolved_origin_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_OR_RESOLVED_CENSORED_ORIGIN'):
            x.censored_attribution([trade(1, 50)], [trade(1, 60)], [opened(1)])
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_OR_RESOLVED_CENSORED_ORIGIN'):
            x.censored_attribution([trade(1, 50), trade(1, -60)], [], [])

    def test_compare_uses_origin_presence_with_open_without_net_and_retains_closed_reject(self):
        p = [trade(1, 100), trade(2, -50), trade(3, 70)]
        c = [trade(1, 80), trade(2, -20)]
        pending = [opened(3, 9000)]
        pm = x.summarize_stage(p, [], [], policy(), ['TEST'])
        cm = x.summarize_stage(c, pending, [], policy(), ['TEST'])
        before = copy.deepcopy((p, c, pending, pm, cm))
        diag = {'lane_simultaneous_close_group_streaks': {'max_loss_trade_sum_bps': 50},
                'drawdown_recovery': {'closed_group_DD_trade_sum_bps': 50}}
        gate = {'minimum_closed_T': 2, 'minimum_retention_pct': 60,
                'minimum_payoff_ratio': 1, 'maximum_win_rate_harm_pp': 5}
        result = x.compare(p, c, pending, pm, cm, diag, diag, policy(), gate)
        d = result['decision']
        self.assertEqual(d['decision'], 'DEV_INCONCLUSIVE')
        self.assertEqual(d['closed_screen_decision'], 'DEV_REJECT')
        self.assertEqual(d['overall_blocker'], 'UNRESOLVED_TERMINAL_POSITIONS')
        self.assertEqual(d['origin_presence_retention_including_censored'], 1)
        self.assertEqual(d['parent_winner_origin_presence_not_profit_retention'], 1)
        self.assertEqual(d['missed_winner_bps'], 0)
        self.assertEqual(result['attribution']['parent_net_on_censored_origins_bps'], 70)
        self.assertFalse(d['formal_pass'])
        self.assertEqual((p, c, pending, pm, cm), before)


class SignalsAndAllocation(unittest.TestCase):
    def test_sealed_budget_rules_and_authorities_are_all_enforced_before_data(self):
        contract = {'budget': copy.deepcopy(x.BUDGET), 'rules': copy.deepcopy(x.RULES),
                    'new_outcomes_seen_at_freeze': False,
                    'authorization': 'EXPLICIT_USER_SUPERTREND_A_B_TWO_TRIALS_AFTER_PR1188',
                    'code_files_sha256': {}, 'preserved_files_sha256': {},
                    'validation_access': False, 'OOS_access': False,
                    'G5B_changed': False, 'operating_changed': False,
                    'G6_authorized': False, **x.old.probe.DEV_AUTH}
        sealed = x.old.seal(contract)
        with patch.object(x.old, 'read', return_value=sealed):
            self.assertEqual(x.authorize(), sealed)
        changes = [('budget', {**x.BUDGET, 'cumulative_after': 23}),
                   ('rules', {}), ('new_outcomes_seen_at_freeze', True),
                   ('authorization', 'RENAMED_BUDGET'), ('formal_credit', 1),
                   ('G5A_economic_PASS', True), ('g5b_entry_authorized', True),
                   ('execution_authority', 'LIVE'), ('order_authority', 'OPEN'),
                   ('validation_access', True), ('OOS_access', True),
                   ('G5B_changed', True), ('operating_changed', True),
                   ('G6_authorized', True)]
        for field, value in changes:
            with self.subTest(field=field):
                invalid = x.old.seal({**contract, field: value})
                with patch.object(x.old, 'read', return_value=invalid), \
                     patch.object(x.previous.prior.previous, 'load_inputs', side_effect=AssertionError('MUST_NOT_READ_DATA')):
                    with self.assertRaises(RuntimeError):
                        x.run(Path('/unused'))

    def test_flip_indicator_prefix_does_not_read_future_bars(self):
        rows = fixture(300, x.INTERVAL)
        up, down, state = x.flip_signals(rows[:270])
        changed = copy.deepcopy(rows)
        for row in changed[270:]:
            for field in ('open', 'high', 'low', 'close'):
                row[field] *= 10
        up2, down2, state2 = x.flip_signals(changed)
        self.assertEqual(up, [i for i in up2 if i < 270])
        self.assertEqual(down, [i for i in down2 if i < 270])
        for field in state:
            self.assertEqual(state[field], state2[field][:270])
        self.assertTrue(all(i >= 239 for i in up))

    def test_no_initial_state_entry_and_split_end_flip_exclusion(self):
        rows = bars(242)
        states = [-1]*242
        states[239], states[240], states[241] = 1, -1, 1
        with patch.object(x.features, 'supertrend', return_value={'direction': states}):
            up, down, _ = x.flip_signals(rows, split_end_ms=242*x.INTERVAL)
        self.assertEqual(up, [239])
        self.assertEqual(down, [240])
        with patch.object(x.features, 'supertrend', return_value={'direction': [1]*242}):
            self.assertEqual(x.flip_signals(rows)[:2], ([], []))

    def test_consumed_allocation_cannot_load_data_again_without_verify_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/x.OUTPUT
            output.mkdir(parents=True)
            (output/'receipt.json').write_text('{}')
            with patch.object(x, 'ROOT', Path(tmp)), patch.object(x, 'authorize', return_value={}), \
                 patch.object(x.previous.prior.previous, 'load_inputs', side_effect=AssertionError('MUST_NOT_READ_DATA')):
                with self.assertRaisesRegex(RuntimeError, 'ALLOCATED_TRIALS_CONSUMED_USE_VERIFY_ONLY'):
                    x.run(Path('/unused'))
        self.assertEqual(x.BUDGET['previous_applications'], 20)
        self.assertEqual(x.BUDGET['A']+x.BUDGET['B'], 2)
        self.assertEqual(x.BUDGET['cumulative_after'], 22)
        self.assertFalse(x.BUDGET['automatic_extension'])
        self.assertEqual(x.BUDGET['paid_external_AI_calls'], 0)


if __name__ == '__main__':
    unittest.main()
