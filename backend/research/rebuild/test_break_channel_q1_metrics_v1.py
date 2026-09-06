"""Synthetic origin and fixed-calendar accounting; no historical input access."""
from copy import deepcopy
import unittest

from backend.research.rebuild import break_channel_q1_metrics_v1 as m
from backend.research.rebuild.test_break_channel_metrics_v1 import trade, opened
from backend.research.rebuild.test_break_channel_structure_v1 import bars
from backend.research.rebuild.test_break_channel_source_v1 import COSTS, policy


def open_mark(i, net=10):
    value = opened(i)
    value.update(gross_mark_bps=net + 20,
                 hypothetical_liquidation_net_mark_bps=net,
                 hypothetical_liquidation_cost2x_net_mark_bps=net - 20)
    return value


class SymmetricOriginTests(unittest.TestCase):
    def test_all_eight_groups_close_and_mark_bridges_are_symmetric(self):
        pc = [trade(0, 100), trade(1, -50), trade(4, 40)]
        po = [open_mark(2, -30), open_mark(3, 20), open_mark(5, 10)]
        cc = [trade(0, 150), trade(2, 80), trade(6, -20)]
        co = [open_mark(1, 30), open_mark(3, -10), open_mark(7, 15)]
        original = deepcopy((pc, po, cc, co))
        result = m.symmetric_attribution(pc, po, cc, co)
        self.assertEqual(result['counts'], {key: 1 for key in m.GROUPS})
        self.assertEqual(result['closed_net_delta_bps'], 120)
        self.assertEqual(result['marked_delta_bps_not_realized'], 155)
        self.assertEqual(result['groups']['CO']['closed']['delta']['net_bps'], 50)
        self.assertEqual(result['groups']['OC']['closed']['delta']['net_bps'], 80)
        self.assertEqual(result['groups']['OC']['marked']['delta']['net_bps'], 110)
        self.assertEqual(result['groups']['OO']['marked']['delta']['net_bps'], -30)
        self.assertEqual(result['removed_completed_parent_loss_bps'], 0)
        self.assertEqual(result['removed_completed_parent_winner_bps'], 40)
        self.assertEqual(result['new_completed_net_bps'], -20)
        self.assertEqual(result['comparison_type'], 'EXIT_CHANGE')
        reverse = m.symmetric_attribution(cc, co, pc, po)
        for basis in ('closed', 'marked'):
            self.assertEqual(result['bridges'][basis]['parity'], 'PASS')
            for field in m.VALUE_FIELDS:
                self.assertAlmostEqual(result['bridges'][basis]['delta'][field],
                                       -reverse['bridges'][basis]['delta'][field])
        self.assertEqual((pc, po, cc, co), original)

    def test_parent_open_closed_child_is_common_not_new_or_removed(self):
        result = m.symmetric_attribution([], [open_mark(0, -40)], [trade(0, 60)], [])
        self.assertEqual(result['counts']['OC'], 1)
        self.assertEqual(result['counts']['new_C'], 0)
        self.assertEqual(result['counts']['removed_O'], 0)
        self.assertEqual(result['closed_net_delta_bps'], 60)
        self.assertEqual(result['marked_delta_bps_not_realized'], 100)
        self.assertEqual(result['winner']['parent_T'], 0)
        self.assertIsNone(result['winner']['amount_retention_lower'])

    def test_closed_cost_and_funding_change_bridge_is_not_gross_gain(self):
        parent = trade(0, 100)
        child = trade(0, 95)
        child.update(gross_bps=120, cost_bps=25, funding_bps=10, cost2x_net_bps=70)
        result = m.symmetric_attribution([parent], [], [child], [])
        self.assertEqual(result['closed_cost_delta_bps'], 5)
        self.assertEqual(result['common_closed_funding_delta_bps'], 5)
        self.assertEqual(result['bridges']['closed']['delta']['gross_bps'], 0)
        self.assertEqual(result['closed_net_delta_bps'], -5)
        self.assertEqual(result['resolved_common_effects']['cut_positive_winner_profit_bps'], 5)

    def test_retention_caps_large_gain_and_keeps_open_uncertainty(self):
        result = m.symmetric_attribution([trade(0, 100), trade(1, 50)], [open_mark(9, 9999)],
                                         [trade(0, 500)], [open_mark(1, 2000)])
        win = result['winner']
        self.assertEqual(win['parent_positive_bps'], 150)
        self.assertEqual(win['resolved_preserved_bps'], 100)
        self.assertEqual(win['unresolved_parent_positive_bps'], 50)
        self.assertAlmostEqual(win['amount_retention_lower'], 2 / 3)
        self.assertEqual(win['amount_retention_upper'], 1)
        self.assertEqual(win['hypothetical_mark_capped_retention'], 1)
        self.assertEqual(win['parent_open_positions_excluded_from_winner_labels_T'], 1)
        self.assertEqual(result['large_winner']['parent_T'], 1)
        self.assertEqual(result['large_winner']['resolved_preserved_bps'], 100)

    def test_truly_missing_winners_and_losses_are_not_censoring(self):
        result = m.symmetric_attribution([trade(0, -50), trade(1, 100)], [], [], [])
        self.assertEqual(result['counts']['removed_C'], 2)
        self.assertEqual(result['removed_completed_parent_loss_bps'], 50)
        self.assertEqual(result['removed_completed_parent_winner_bps'], 100)
        self.assertEqual(result['winner']['amount_retention_upper'], 0)
        self.assertEqual(result['closed_net_delta_bps'], -50)

    def test_empty_and_duplicate_cross_state_or_corrupt_costs(self):
        result = m.symmetric_attribution([], [], [], [])
        self.assertEqual(result['closed_net_delta_bps'], 0)
        self.assertEqual(result['marked_delta_bps_not_realized'], 0)
        self.assertIsNone(result['large_winner']['amount_retention_lower'])
        for args in (([trade(0), trade(0)], [], [], []), ([trade(0)], [open_mark(0)], [], []),
                     ([], [], [trade(0)], [open_mark(0)])):
            with self.subTest(args=args), self.assertRaisesRegex(RuntimeError, 'DUPLICATE'):
                m.symmetric_attribution(*args)
        corrupt = trade(0)
        corrupt['funding_bps'] += 1
        with self.assertRaisesRegex(RuntimeError, 'COST_COMPONENT_IDENTITY'):
            m.symmetric_attribution([corrupt], [], [], [])


def valuation_fixture():
    rows = bars(19)
    rows[5].update(close=110, high=110)
    rows[6].update(open=120, high=120, low=119, close=120)
    rows[11].update(close=130, high=130)
    rows[12].update(open=140, high=140, low=139, close=140)
    rows[17].update(close=125, high=125)
    rows[18].update(open=999, high=999, low=999, close=999)
    closed_raw = {'signal_index': 0, 'entry_index': 0, 'exit_index': 5,
        'signal_ts': 0, 'entry_ts': 0, 'exit_ts': m.DAY, 'side': 'long',
        'entry_price': 100, 'exit_price': 110, 'gross_bps': 1000,
        'hold_ms': m.DAY, 'mfe_bps': 1000, 'mae_bps': 0}
    open_raw = {'signal_index': 5, 'entry_index': 6, 'mark_index': 17,
        'signal_ts': m.DAY, 'entry_ts': m.DAY, 'mark_ts': 3 * m.DAY, 'side': 'long',
        'entry_price': 120, 'mark_price': 125, 'gross_mark_bps': (125 / 120 - 1) * 10000,
        'hold_ms': 2 * m.DAY, 'mfe_bps': 2000, 'mae_bps': 0,
        'status': 'CENSORED', 'terminal_liquidation': False}
    closed = m.source.charge(closed_raw, 'TEST', 'SYNTHETIC', policy(), COSTS, rows)
    opened_value = m.source.charge_open(open_raw, 'TEST', 'SYNTHETIC', policy(), COSTS, rows)
    return [closed], [opened_value], {'TEST': rows}


class FixedCalendarWindowTests(unittest.TestCase):
    def test_same_boundaries_bridge_source_after_open_and_final_close(self):
        closed, opened_values, prices = valuation_fixture()
        original = deepcopy((closed, opened_values, prices))
        daily = m.source.daily_valuation(closed, opened_values, prices, COSTS, 0, 3 * m.DAY)
        result = m.window_contributions(closed, opened_values, prices, COSTS, 0, 3 * m.DAY,
                                        m.DAY, 3 * m.DAY, daily=daily)
        self.assertEqual(result['parity'], 'PASS')
        self.assertAlmostEqual(result['totals']['start']['gross_bps'], 1000)
        self.assertAlmostEqual(result['totals']['end']['gross_bps'], 1000 + (125 / 120 - 1) * 10000)
        self.assertAlmostEqual(result['totals']['delta']['funding_bps'], 18)
        self.assertEqual(result['totals']['delta']['cost_bps'], 11)
        target = opened_values[0]['hypothetical_liquidation_net_mark_bps'] + 20
        self.assertAlmostEqual(result['daily_net_increment_sum_bps'], target)
        old_trade = next(t for t in result['position_contributions'] if t['terminal_status'] == 'C')
        self.assertEqual(old_trade['delta']['net_bps'], 0)
        self.assertEqual(old_trade['start']['state'], 'COMPLETED')
        self.assertEqual((closed, opened_values, prices), original)

    def test_adjacent_windows_telescope_and_initial_baseline_is_zero(self):
        closed, opened_values, prices = valuation_fixture()
        call = lambda a, b: m.window_contributions(closed, opened_values, prices, COSTS,
                                                  0, 3 * m.DAY, a, b)
        whole, first, second = call(0, 3 * m.DAY), call(0, m.DAY), call(m.DAY, 3 * m.DAY)
        self.assertEqual(whole['totals']['start']['cost_bps'], 0)
        self.assertEqual(whole['totals']['start']['net_bps'], 0)
        for field in m.VALUE_FIELDS:
            self.assertAlmostEqual(whole['totals']['delta'][field],
                                   first['totals']['delta'][field] + second['totals']['delta'][field])
        target = closed[0]['net_bps'] + opened_values[0]['hypothetical_liquidation_net_mark_bps']
        self.assertAlmostEqual(whole['totals']['end']['net_bps'], target)

    def test_intermediate_uses_observed_open_and_ignores_future_terminal_open(self):
        closed, opened_values, prices = valuation_fixture()
        call = lambda: m.window_contributions(closed, opened_values, prices, COSTS,
                                              0, 3 * m.DAY, 2 * m.DAY, 3 * m.DAY)
        result = call()
        self.assertAlmostEqual(result['totals']['start']['gross_bps'], 1000 + (140 / 120 - 1) * 10000)
        prices['TEST'][18].update(open=1, close=1, high=100000, low=.0001)
        self.assertEqual(result, call())

    def test_no_position_is_true_zero_calendar_reference(self):
        result = m.window_contributions([], [], {}, {}, 0, 3 * m.DAY, m.DAY, 2 * m.DAY)
        self.assertEqual(result['position_contributions'], [])
        self.assertEqual(result['daily_net_increment_sum_bps'], 0)
        self.assertEqual(result['parity'], 'PASS')

    def test_stored_terminal_open_economics_must_match_independent_mark(self):
        closed, opened_values, prices = valuation_fixture()
        for field in ('gross_mark_bps', 'hypothetical_liquidation_net_mark_bps',
                      'hypothetical_liquidation_cost2x_net_mark_bps'):
            opened_values[0][field] += 1
        with self.assertRaisesRegex(RuntimeError, 'TERMINAL_OPEN_MARK_PARITY'):
            m.window_contributions(closed, opened_values, prices, COSTS, 0, 3 * m.DAY,
                                   m.DAY, 3 * m.DAY)

    def test_bad_window_missing_price_and_incorrect_daily_bridge_fail(self):
        closed, opened_values, prices = valuation_fixture()
        with self.assertRaisesRegex(ValueError, 'NONDAILY_WINDOW'):
            m.window_contributions(closed, opened_values, prices, COSTS, 0, 3 * m.DAY, 1, 2 * m.DAY)
        daily = m.source.daily_valuation(closed, opened_values, prices, COSTS, 0, 3 * m.DAY)
        daily[0]['cumulative_net_mark_bps'] += 1
        with self.assertRaisesRegex(RuntimeError, 'DAILY_WINDOW_START_BRIDGE'):
            m.window_contributions(closed, opened_values, prices, COSTS, 0, 3 * m.DAY,
                                   m.DAY, 3 * m.DAY, daily=daily)
        with self.assertRaisesRegex(RuntimeError, 'DAILY_BRIDGE_CALENDAR_MISMATCH'):
            m.window_contributions(closed, opened_values, prices, COSTS, 0, 3 * m.DAY,
                                   m.DAY, 3 * m.DAY, daily=daily[:-1])
        prices['TEST'] = [r for r in prices['TEST'] if r['bar_close_ts'] != 3 * m.DAY]
        with self.assertRaisesRegex(RuntimeError, 'MISSING_DAILY_VALUATION_PRICE'):
            m.window_contributions(closed, opened_values, prices, COSTS, 0, 3 * m.DAY,
                                   m.DAY, 3 * m.DAY)


if __name__ == '__main__':
    unittest.main()
