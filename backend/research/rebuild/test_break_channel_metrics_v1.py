"""Synthetic accounting tests only; no historical price files or outcomes."""
from copy import deepcopy
from datetime import date, timedelta
import unittest

from backend.research.rebuild import break_channel_metrics_v1 as m

START = 1_735_689_600_000  # 2025-01-01 UTC
POLICY = {'development_interval_ms': [START, START + 180 * m.DAY]}
SYMBOLS = ['BTC', 'ETH']


def trade(i=0, net=100.0, symbol='BTC', entry=None, end=None):
    entry = START + i * 3 * m.DAY if entry is None else entry
    end = entry + m.DAY if end is None else end
    return {
        'identity': f'{symbol}-{i}', 'lane_id': 'break_and_continue_main', 'symbol': symbol,
        'signal_ts': entry - 1, 'entry_ts': entry, 'exit_ts': end,
        'side': 'long', 'gross_bps': net + 20, 'net_bps': net, 'cost2x_net_bps': net - 20,
        'cost_bps': 20, 'fee_bps': 8, 'spread_bps': 3, 'impact_bps': 2,
        'slippage_bps': 0, 'funding_bps': 5, 'frozen_floor_reserve_bps': 2,
        'funding_settlements_crossed': 3, 'hold_ms': end - entry,
        'mfe_bps': max(net + 20, 0), 'mae_bps': min(net + 20, 0),
    }


def opened(i=0, symbol='BTC', entry=None, mark=None):
    t = trade(i, symbol=symbol, entry=entry, end=mark)
    return {
        'lane_id': t['lane_id'], 'symbol': symbol, 'signal_ts': t['signal_ts'],
        'entry_ts': t['entry_ts'], 'mark_ts': t['exit_ts'], 'side': 'long',
        'hold_ms': t['hold_ms'], 'gross_mark_bps': 30,
        'modeled_funding_accrued_bps': 5, 'funding_settlements_elapsed': 3,
        'hypothetical_liquidation_cost_bps': 20,
        'hypothetical_liquidation_net_mark_bps': 10,
        'hypothetical_liquidation_cost2x_net_mark_bps': -10,
        'hypothetical_cost_components_bps': {key: t[key] for key in m.COST_FIELDS},
        'status': 'CENSORED', 'actual_exit': False,
    }


def events(trades, opens=()):
    return ([{'admission': True, 'status': 'COMPLETED', 'exclusion_reason': None} for _ in trades]
            + [{'admission': True, 'status': 'CENSORED', 'exclusion_reason': None} for _ in opens])


def summary(trades, opens=()):
    return m.summarize(trades, opens, events(trades, opens), POLICY, SYMBOLS)


def diag(trades):
    return m.diagnostics(trades, *POLICY['development_interval_ms'])


def daily(values):
    start = date(2025, 1, 1)
    return [{'date': (start + timedelta(days=i)).isoformat(), 'value': v} for i, v in enumerate(values)]


def uncertain(low=-1.0, high=1.0):
    return {'child_minus_parent_95pct_interval_bps_per_day': [low, high]}


class AccountingTests(unittest.TestCase):
    def test_shared_completed_metrics_exact_and_open_costs_separate(self):
        ts = [trade(0, 100), trade(1, -40)]
        os = [opened(3, 'ETH')]
        inputs = deepcopy((ts, os))
        result = summary(ts, os)
        original = m.shared.metrics(ts, events(ts), POLICY, SYMBOLS)
        self.assertEqual(result['base_cost'], original['base_cost'])
        self.assertEqual(result['cost2x'], original['cost2x'])
        self.assertEqual(result['base_cost']['completed_T'], 2)
        self.assertEqual(result['base_cost']['net_bps'], 60)
        self.assertEqual(result['closed_plus_hypothetical_terminal_mark_bps'], 70)
        self.assertEqual(result['closed_cost_totals_bps']['fee_bps'], 16)
        self.assertEqual(result['closed_cost_totals_bps']['funding_bps'], 10)
        self.assertEqual(result['open_observations']['modeled_funding_accrued_bps'], 5)
        self.assertEqual(result['open_observations']['hypothetical_cost_totals_bps']['fee_bps'], 8)
        self.assertIsNone(result['open_observations']['entry_side_cost_bps'])
        self.assertEqual(result['entries_including_censored_T'], 3)
        self.assertEqual(result['censored_signals'], 1)
        self.assertEqual(result['total_exposure_symbol_days'], 3)
        self.assertEqual((ts, os), inputs)
        self.assertNotIn('net_bps', os[0])
        self.assertNotIn('exit_ts', os[0])

    def test_no_trade_is_zero_reference_not_failed_strategy(self):
        zero = m.no_trade_baseline(POLICY, SYMBOLS)
        self.assertEqual(zero['base_cost']['completed_T'], 0)
        self.assertIsNone(zero['base_cost']['PF'])
        self.assertIsNone(zero['base_cost']['expectancy_bps_per_trade'])
        self.assertEqual(zero['base_cost']['net_bps'], 0)
        self.assertEqual(zero['total_exposure_symbol_days'], 0)
        self.assertEqual(zero['exposure']['max_simultaneous_positions'], 0)
        self.assertEqual(zero['exposure']['calendar_days_by_simultaneous_symbols'], {'0': 180})
        self.assertEqual(zero['hypothesis_allocation_consumed'], 0)
        result = m.decide(zero, zero, None, None, None)
        self.assertEqual(result['decision'], 'REFERENCE_ONLY')
        self.assertFalse(result['formal_pass'])

    def test_exposure_half_open_atomic_and_distinct_symbol_union(self):
        ts = [trade(0, entry=START, end=START + 2 * m.DAY),
              trade(1, entry=START + 2 * m.DAY, end=START + 3 * m.DAY),
              trade(2, 0, 'ETH', START + m.DAY, START + 3 * m.DAY)]
        result = m.exposure_summary(ts, [])
        self.assertEqual(result['max_simultaneous_positions'], 2)
        self.assertEqual(result['max_simultaneous_symbols'], 2)
        self.assertEqual(result['position_days'], 5)
        self.assertEqual(result['symbol_days_union'], 5)
        self.assertEqual(result['calendar_days_with_any_exposure'], 3)
        overlapping = [trade(0, entry=START, end=START + 2 * m.DAY),
                       trade(1, entry=START + m.DAY, end=START + 3 * m.DAY)]
        result = m.exposure_summary(overlapping, [])
        self.assertEqual(result['max_simultaneous_positions'], 2)
        self.assertEqual(result['max_simultaneous_symbols'], 1)
        self.assertEqual(result['position_days'], 4)
        self.assertEqual(result['symbol_days_union'], 3)

    def test_exposure_rejects_broken_duration_or_calendar(self):
        broken = trade()
        broken['hold_ms'] += 1
        with self.assertRaisesRegex(ValueError, 'DURATION_MISMATCH'):
            m.exposure_summary([broken], [])
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_CALENDAR'):
            m.exposure_summary([trade()], [], start_ms=START + 1)

    def test_exit_month_and_profit_concentration_are_not_net_shares(self):
        ts = [trade(0, 40), trade(1, -10, 'ETH'), trade(11, 20, 'ETH')]
        result = summary(ts)
        self.assertEqual(result['by_exit_month']['2025-01']['net_bps'], 30)
        self.assertEqual(result['by_exit_month']['2025-02']['net_bps'], 20)
        self.assertEqual(result['by_exit_month']['2025-03']['net_bps'], 0)
        self.assertEqual(result['by_exit_month']['2025-03']['closed_T'], 0)
        c = result['concentration']
        self.assertEqual(c['top_one_symbol_by_positive_trade_profit'], 'BTC')
        self.assertAlmostEqual(c['top_one_symbol_profit_share'], 2 / 3)
        self.assertAlmostEqual(c['top_decile_winners_share'], 2 / 3)
        self.assertEqual(c['top_decile_winner_T'], 1)
        self.assertEqual(c['by_symbol_closed_net_bps'], {'BTC': 40, 'ETH': 10})

    def test_censored_origin_is_not_removed_or_avoided_loss(self):
        parent = [trade(0, -50), trade(1, 100), trade(2, 20)]
        child = [trade(1, 60), trade(3, -10)]
        result = m.attribution(parent, child, [opened(0)])
        self.assertEqual(result['common_censored_T'], 1)
        self.assertEqual(result['removed_T'], 1)
        self.assertEqual(result['unfilled_parent_loss_bps'], 0)
        self.assertEqual(result['unfilled_parent_winner_bps'], 20)
        self.assertEqual(result['parent_net_on_censored_origins_bps'], -50)
        self.assertEqual(result['closed_net_delta_bps'], -20)
        self.assertEqual(result['marked_delta_bps_not_realized'], -10)
        self.assertFalse(result['source_overlap_is_economic_gate'])

    def test_diagnostics_reuses_existing_grouped_risk(self):
        ts = [trade(0, -50), trade(1, 20), trade(2, -70)]
        self.assertEqual(diag(ts), m.existing_risk.diagnostics(ts, *POLICY['development_interval_ms'])[0])


class DailyUncertaintyTests(unittest.TestCase):
    def test_paired_constant_increment_preserves_zero_calendar_days(self):
        parent = daily([0] * 60)
        child = daily([2] * 60)
        saved = deepcopy((parent, child))
        result = m.paired_daily_uncertainty(parent, child)
        self.assertEqual(result['calendar_days'], 60)
        self.assertEqual(result['approximate_calendar_blocks'], 2)
        self.assertEqual(result['child_minus_parent_95pct_interval_bps_per_day'], [2, 2])
        self.assertEqual(result['child_minus_parent_95pct_interval_calendar_sum_bps'], [120, 120])
        self.assertIsNone(result['N_effective'])
        self.assertEqual(result['resamples'], 1000)
        self.assertEqual((parent, child), saved)

    def test_identical_paths_have_zero_paired_interval_and_repeat_exactly(self):
        values = [(-1) ** i * (i % 7) for i in range(65)]
        parent = daily(values)
        child = daily([v + (i % 4) for i, v in enumerate(values)])
        first = m.paired_daily_uncertainty(parent, child)
        self.assertEqual(first, m.paired_daily_uncertainty(parent, child))
        same = m.paired_daily_uncertainty(parent, parent)
        self.assertEqual(same['child_minus_parent_95pct_interval_bps_per_day'], [0, 0])
        self.assertEqual(same['child_minus_parent_95pct_interval_calendar_sum_bps'], [0, 0])

    def test_missing_duplicate_unpaired_nonfinite_days_rejected(self):
        valid = daily([0] * 40)
        cases = [valid[:5] + valid[6:], valid + [valid[-1]],
                 valid[:-1] + [{'date': valid[-1]['date'], 'value': float('nan')}]]
        for broken in cases:
            with self.subTest(case=len(broken)):
                with self.assertRaises(ValueError):
                    m.paired_daily_uncertainty(valid, broken)
        with self.assertRaisesRegex(ValueError, 'UNPAIRED'):
            m.paired_daily_uncertainty(valid, valid[:-1])

    def test_short_calendar_does_not_shorten_preregistered_block(self):
        result = m.paired_daily_uncertainty(daily([0] * 29), daily([1] * 29))
        self.assertEqual(result['status'], 'INSUFFICIENT_CALENDAR')
        self.assertEqual(result['block_days'], 30)
        self.assertEqual(result['child_minus_parent_95pct_interval_bps_per_day'], [None, None])

    def test_marked_drawdown_and_recovery_include_initial_underwater_days(self):
        recovered = m.daily_mark_diagnostics(daily([10, -5, -7, 15]))
        self.assertEqual(recovered['marked_DD_trade_sum_bps'], 12)
        self.assertEqual(recovered['max_completed_recovery_days'], 3)
        self.assertFalse(recovered['unrecovered_at_end'])
        unresolved = m.daily_mark_diagnostics(daily([-2, -3, -4]))
        self.assertEqual(unresolved['marked_DD_trade_sum_bps'], 9)
        self.assertEqual(unresolved['open_underwater_days'], 3)


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.parent = [trade(i, net) for i, net in enumerate([-100, 80, 80, 80, 80, 80])]
        self.child = [trade(i + 10, net) for i, net in enumerate([-50, 150, 150, 150, 150, 150])]
        self.pm = summary(self.parent)
        self.cm = summary(self.child)
        self.pd = diag(self.parent)
        self.cd = diag(self.child)

    def test_distinct_signals_and_higher_exposure_do_not_create_overlap_reject(self):
        self.cm['total_exposure_symbol_days'] = self.pm['total_exposure_symbol_days'] + 50
        result = m.decide(self.pm, self.cm, self.pd, self.cd, uncertain(1, 3))
        self.assertEqual(result['decision'], 'DEV_PROMISING')
        self.assertFalse(result['source_overlap_is_economic_gate'])
        self.assertTrue(result['risk_tradeoffs']['exposure_increased'])
        self.assertFalse(result['risk_tradeoffs']['exposure_increase_is_automatic_reject'])
        self.assertFalse(result['formal_pass'])
        self.assertFalse(result['operating_adoption'])

    def test_absolute_negative_less_loss_is_not_economic_adoption(self):
        p = [trade(i, net) for i, net in enumerate([-200, -200, -200, 50, 50, 50])]
        c = [trade(i + 10, net) for i, net in enumerate([-100, -100, -100, 50, 50, 50])]
        result = m.decide(summary(p), summary(c), diag(p), diag(c), uncertain(1, 3))
        self.assertEqual(result['decision'], 'DEV_REJECT')
        self.assertEqual(result['economic_interpretation'], 'LOSS_REDUCTION')
        self.assertGreater(result['closed_calendar_net_delta_bps'], 0)

    def test_cost2_stress_is_absolute_failure_even_with_positive_net(self):
        self.cm['cost2x']['net_bps'] = -1
        result = m.decide(self.pm, self.cm, self.pd, self.cd, uncertain(1, 3))
        self.assertEqual(result['decision'], 'DEV_REJECT')
        self.assertIn('positive_cost2x_net', result['failed_checks'])

    def test_uncertain_increment_or_risk_tradeoff_is_inconclusive_not_universal_badness(self):
        result = m.decide(self.pm, self.cm, self.pd, self.cd, uncertain())
        self.assertEqual(result['decision'], 'DEV_INCONCLUSIVE')
        self.assertEqual(result['economic_interpretation'], 'POSITIVE_CLOSED_ECONOMICS')
        self.cd['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'] = 10000
        result = m.decide(self.pm, self.cm, self.pd, self.cd, uncertain(1, 3))
        self.assertEqual(result['decision'], 'DEV_INCONCLUSIVE')
        self.assertIn('grouped_loss_run_not_worse', result['failed_checks'])

    def test_small_sample_undefined_pf_and_open_overall_are_distinct(self):
        self.cm['base_cost']['completed_T'] = 5
        result = m.decide(self.pm, self.cm, self.pd, self.cd, uncertain(1, 3))
        self.assertEqual(result['decision'], 'INSUFFICIENT')
        self.cm['open_observations']['T'] = 1
        result = m.decide(self.pm, self.cm, self.pd, self.cd, uncertain(1, 3))
        self.assertEqual(result['closed_screen_decision'], 'INSUFFICIENT')
        self.assertEqual(result['decision'], 'DEV_INCONCLUSIVE')
        self.assertEqual(result['overall_blocker'], 'UNRESOLVED_TERMINAL_POSITIONS')
        self.cm['open_observations']['T'] = 0
        self.cm['base_cost']['completed_T'] = 6
        self.cm['base_cost']['PF'] = None
        self.assertEqual(m.decide(self.pm, self.cm, self.pd, self.cd, uncertain(1, 3))['decision'], 'INSUFFICIENT')


if __name__ == '__main__':
    unittest.main()
