"""Synthetic Q0 diagnostic tests; never measures a candidate or reads DEV data."""
from copy import deepcopy
import unittest

from backend.research.rebuild import break_channel_q2_loss_analysis_v1 as m
from backend.research.rebuild.test_break_channel_q1_metrics_v1 import valuation_fixture
from backend.research.rebuild.test_break_channel_source_v1 import COSTS


def sequence(values):
    return [{'exit_ts': i * m.DAY, 'net_bps': v, 'symbol': 'TEST'}
            for i, v in enumerate(values, 1)]


def fixture():
    closed, opened, native = valuation_fixture()
    for t in closed:
        t.update(entry_stop_price=90, exit_reason='SYNTHETIC_OBSERVED_EXIT')
    # Real run accepts already sealed complete daily bars; prove daily aggregation
    # has exactly the same UTC mark prices as original native4h bars.
    daily_bars = {s: m.source.structure.aggregate_daily(rows)
                  for s, rows in native.items()}
    # Existing aggregator returns an audit wrapper; use only complete bar rows.
    daily_bars = {s: value['daily'] if isinstance(value, dict) else value
                  for s, value in daily_bars.items()}
    trades = {'P': deepcopy(closed), 'Q0': deepcopy(closed)}
    opens = {'P': deepcopy(opened), 'Q0': deepcopy(opened)}
    valuation = {s: m.source.daily_valuation(trades[s], opens[s], native, COSTS, 0, 3*m.DAY)
                 for s in trades}
    return trades, opens, daily_bars, valuation


class CloseGroupingTests(unittest.TestCase):
    def test_equal_timestamp_groups_ignore_symbol_sort_and_mask_individual_sign(self):
        trades = sequence([-30, 50, -40])
        trades[1]['exit_ts'] = trades[0]['exit_ts']
        groups = m.grouped(trades)
        reverse = m.grouped(list(reversed(trades)))
        self.assertEqual([g['net_bps'] for g in groups], [20, -40])
        self.assertEqual([g['net_bps'] for g in reverse], [20, -40])
        self.assertEqual([r['sign'] for r in m.sign_runs(groups)], ['WIN', 'LOSS'])
        self.assertEqual(len(groups[0]['trades']), 2)

    def test_small_win_ends_run_without_being_overall_profit_improvement(self):
        separated = m.sign_runs(m.grouped(sequence([-100, 1, -200])))
        joined = m.sign_runs(m.grouped(sequence([1, -100, -200])))
        self.assertEqual(max(len(r['groups']) for r in separated if r['sign']=='LOSS'), 1)
        self.assertEqual(max(len(r['groups']) for r in joined if r['sign']=='LOSS'), 2)
        self.assertEqual(sum(g['net_bps'] for r in separated for g in r['groups']), -299)
        self.assertEqual(sum(g['net_bps'] for r in joined for g in r['groups']), -299)

    def test_zero_breaks_loss_run_and_empty_input_has_no_run(self):
        self.assertEqual(m.sign_runs([]), [])
        self.assertEqual([x['sign'] for x in m.sign_runs(m.grouped(sequence([-1, 0, -1])))],
                         ['LOSS', 'ZERO', 'LOSS'])

    def test_longest_run_is_not_assumed_largest_loss_amount(self):
        r = m.ordering_sensitivity(m.grouped(sequence([-1, -1, -1, 10, -1000])))
        self.assertEqual(r['observed_max_loss_groups'], 3)
        self.assertEqual(r['observed_max_loss_bps'], 1000)

    def test_fixed_permutation_preserves_input_and_is_deterministic(self):
        groups = m.grouped(sequence([-100, 30, -200, 1, -50]))
        original = deepcopy(groups)
        a = m.ordering_sensitivity(groups)
        self.assertEqual(a, m.ordering_sensitivity(groups))
        self.assertEqual(groups, original)
        self.assertEqual(a['permutations'], 20000)
        self.assertEqual(a['seed'], 1192)
        self.assertTrue(a['not_formal_p_value'])
        self.assertFalse(a['exchangeability_assumption_verified'])
        self.assertFalse(a['new_strategy_economics_computed'])
        self.assertEqual(a['observed_max_loss_groups'], 1)
        self.assertEqual(a['observed_max_loss_bps'], 200)


class CalendarAndPathTests(unittest.TestCase):
    def test_midnight_fill_is_included_on_right_of_start_boundary(self):
        self.assertEqual(m.enclosing_calendar(m.DAY, m.DAY, 0, 3*m.DAY), (0, m.DAY))
        self.assertEqual(m.enclosing_calendar(m.DAY+1, 2*m.DAY, 0, 3*m.DAY),
                         (m.DAY, 2*m.DAY))
        with self.assertRaises(ValueError):
            m.enclosing_calendar(5*m.DAY, 5*m.DAY, 0, 3*m.DAY)

    def test_complete_daily_bars_bridge_native_path_and_open_positions(self):
        trades, opened, bars, valuation = fixture()
        original = deepcopy((trades, opened, bars, valuation))
        r = m.build(trades, opened, bars, valuation, COSTS, 0, 3*m.DAY)
        self.assertEqual((trades, opened, bars, valuation), original)
        self.assertEqual(r['summary']['Q0']['T'], 1)
        # No losing closed trades; real marked giveback still exists in open trade.
        self.assertEqual(r['summary']['loss_runs_n'], 0)
        self.assertGreater(r['marked_drawdown']['drawdown_bps'], 0)
        w = r['marked_drawdown']['worst']['stages']['Q0']
        self.assertEqual(w['parity'], 'PASS')
        self.assertAlmostEqual(w['totals']['delta']['net_bps'],
                               -r['marked_drawdown']['drawdown_bps'])
        self.assertTrue(any(t['terminal_status']=='O' for t in w['contributing_positions']))
        self.assertEqual(r['new_hypothesis_trials_consumed'], 0)
        self.assertFalse(r['new_candidate_economics_computed'])
        self.assertEqual(r['validation_rows_decoded'], 0)
        self.assertEqual(r['OOS_rows_decoded'], 0)

    def test_corrupt_sealed_daily_path_fails_parity_before_diagnosis(self):
        trades, opened, bars, valuation = fixture()
        valuation['Q0'][0]['cumulative_net_mark_bps'] += 1
        with self.assertRaises(AssertionError):
            m.build(trades, opened, bars, valuation, COSTS, 0, 3*m.DAY)

    def test_stage_and_calendar_scope_rejects_candidate_input(self):
        trades, opened, bars, valuation = fixture()
        trades['Q2'] = []
        with self.assertRaisesRegex(ValueError, 'P_Q0_ONLY'):
            m.build(trades, opened, bars, valuation, COSTS, 0, 3*m.DAY)
        del trades['Q2']
        with self.assertRaisesRegex(ValueError, 'INVALID_CALENDAR'):
            m.build(trades, opened, bars, valuation, COSTS, 1, 3*m.DAY)


if __name__ == '__main__':
    unittest.main()
