"""Synthetic prospective accounting; no historical or external market reads."""
from copy import deepcopy
import unittest

from backend.research.rebuild import q0_prospective_accounting_v1 as module
from backend.research.rebuild import q0_prospective_engine_v1 as engine
from backend.research.rebuild import test_q0_b_seen_adapter_v1 as fixture

DAY, BAR = module.DAY, module.BAR
SYMBOL = 'BTC-USDT'


def inputs(closes=None, count=None, weight=.5):
    closes = closes or [100, 100.2, 101, 102, 103, 110, 111, 112]
    rows = fixture.prices(closes)
    count = len(rows) if count is None else count
    start, end = 4 * DAY, len(closes) * DAY
    state = engine.initialize({SYMBOL: rows[:13]}, [SYMBOL], start, end)
    for row in rows[13:count]:
        state = engine.advance(state, {SYMBOL: row})
    raw = engine.snapshot(state)
    observations = {}
    for trade in raw[SYMBOL]['trades'] + raw[SYMBOL]['open_positions']:
        key = module.accounting.ORIGIN(dict(trade, symbol=SYMBOL, lane_id=module.source.LANE))
        observations[key] = {'origin_key': key, 'weight': weight,
                             'entry_ts': trade['entry_ts'], 'signal_ts': trade['signal_ts'],
                             'available_at': trade['signal_ts'], 'fixed_until_exit': True}
    policy = {**fixture.POLICY, 'development_interval_ms': [start, end]}
    return [raw, {SYMBOL: rows[:count]}, deepcopy(fixture.COSTS), observations,
            [SYMBOL], start, rows[count-1]['bar_close_ts'], end], policy


def report(closes=None, count=None, weight=.5):
    args, policy = inputs(closes, count, weight)
    return module.build(*args, policy=policy)


class ProspectiveAccountingTests(unittest.TestCase):
    def test_pre_t0_and_boundary_pending_do_not_fabricate_performance(self):
        before = report(count=13)
        self.assertEqual(before['status'], 'WAIT_T0')
        self.assertIsNone(before['unit_metrics'])
        self.assertEqual(before['control']['status'], 'NOT_DEFINED_ZERO_HOLD')
        self.assertEqual(before['stages'], {})
        boundary = report(count=24)
        self.assertEqual(boundary['invariants']['pending_entry_T'], 1)
        self.assertEqual(boundary['invariants']['open_T'], 0)
        self.assertEqual(boundary['invariants']['closed_T'], 0)
        self.assertIsNone(boundary['unit_metrics'])

    def test_no_signal_zero_exposure_c_is_undefined_not_one(self):
        value = report(closes=[100] * 8, count=31)
        self.assertEqual(value['control']['k'], None)
        self.assertEqual(value['control']['status'], 'NOT_DEFINED_ZERO_HOLD')
        self.assertEqual(set(value['stages']), {'A_Q0', 'B_RISK'})
        self.assertEqual(value['unit_metrics']['base_cost']['completed_T'], 0)
        self.assertIsNone(value['unit_metrics']['base_cost']['expectancy_bps_per_trade'])
        self.assertEqual(value['stages']['A_Q0']['daily'][0]['value'], 0.)

    def test_open_full_roundtrip_floor_funding_and_cost2_preserved(self):
        value = report(count=25)
        unit = value['unit_execution']['open_observations'][0]
        self.assertFalse(unit['actual_exit'])
        self.assertNotIn('exit_ts', unit)
        self.assertEqual(unit['hold_ms'], BAR)
        self.assertEqual(unit['hypothetical_liquidation_cost_bps'], 20.)
        self.assertAlmostEqual(unit['hypothetical_liquidation_net_mark_bps'] -
                               unit['hypothetical_liquidation_cost2x_net_mark_bps'], 20.)
        b = value['stages']['B_RISK']['metrics']
        self.assertAlmostEqual(b['terminal_net_amount_bps'],
                               .5 * unit['hypothetical_liquidation_net_mark_bps'])
        self.assertEqual(value['stages']['A_Q0']['daily'], [])
        self.assertEqual(value['control']['k'], .5)
        self.assertFalse(value['independent'])
        self.assertEqual(unit['evidence_type'], 'PROSPECTIVE_RESEARCH_OBSERVATION')

    def test_midnight_mark_deferred_then_uses_next_open_and_stays_immutable(self):
        at_midnight = report(count=30)
        self.assertEqual(at_midnight['stages']['A_Q0']['daily'], [])
        next_bar = report(count=31)
        day = next_bar['stages']['A_Q0']['daily'][0]
        self.assertEqual(day['mark_ts'], 5 * DAY)
        self.assertEqual(day['valuation_phase'], 'AFTER_OPEN_ORDERS')
        self.assertAlmostEqual(day['cumulative_net_mark_bps'], (110. / 103. - 1) * 10000 - 20.)
        later = report(count=37)
        for stage in ('A_Q0', 'B_RISK'):
            self.assertEqual(next_bar['stages'][stage]['daily'], later['stages'][stage]['daily'][:1])
            self.assertTrue(later['stages'][stage]['daily_history_immutable'])
        self.assertFalse(later['stages']['C_FIXED']['daily_history_immutable'])

    def test_terminal_close_retained_without_next_open_and_old_accounting_parity(self):
        args, policy = inputs()
        value = module.build(*args, policy=policy)
        self.assertEqual(value['status'], 'WINDOW_ENDED_REVIEW_REQUIRED')
        self.assertEqual(value['daily_marking']['immutable_A_B_last_mark_ts'], 8 * DAY)
        trades = value['unit_execution']['trades']
        opened = value['unit_execution']['open_observations']
        events = value['unit_execution']['events']
        p = {**policy, 'development_interval_ms': [4 * DAY, 8 * DAY]}
        old = module.accounting.build(trades, opened, events, args[1], args[2], p,
                                      args[4], args[5], args[6], args[3])
        for stage in ('A_Q0', 'B_RISK', 'C_FIXED'):
            self.assertEqual(value['stages'][stage]['metrics'], old['stages'][stage]['metrics'])
            self.assertEqual(value['stages'][stage]['daily'], old['stages'][stage]['daily'])
            self.assertEqual(value['stages'][stage]['daily'][-1]['valuation_phase'], 'FINAL_CLOSE_NO_FUTURE_OPEN')
            self.assertTrue(value['stages'][stage]['daily_history_immutable'])
        self.assertEqual(value['attribution'], old['attribution'])
        self.assertEqual(value['economic_adoption'], 'NOT_GRANTED')

    def test_closed_winner_loss_attribution_and_shared_metrics(self):
        value = report(closes=[100, 100.2, 101, 102, 103, 110, 111, 99, 99], weight=.7)
        self.assertEqual(value['invariants']['closed_T'], 1)
        self.assertEqual(value['invariants']['open_T'], 0)
        a, b = value['stages']['A_Q0']['metrics'], value['stages']['B_RISK']['metrics']
        self.assertEqual(a['base_cost']['win_rate'], b['base_cost']['win_rate'])
        self.assertAlmostEqual(b['terminal_net_amount_bps'], .7 * a['terminal_net_amount_bps'])
        attribution = value['attribution']['B_minus_A']
        self.assertAlmostEqual(attribution['closed_delta']['net_bps'],
                               attribution['loss_amount_reduction_bps_signed'] -
                               attribution['foregone_winner_amount_bps_signed'])
        self.assertTrue(attribution['cost_saving_already_in_net_sign_bridge'])

    def test_a_absolute_uncertainty_is_not_b_minus_c_interval(self):
        value = report()
        absolute = value['uncertainty']['A_absolute_vs_no_trade']
        relative = value['uncertainty']['B_minus_C']
        self.assertEqual(absolute['parent_marked_delta_sum_bps'], 0.)
        self.assertNotEqual(absolute['child_minus_parent_marked_delta_sum_bps'],
                            relative['child_minus_parent_marked_delta_sum_bps'])
        self.assertIsNone(value['dependence']['N_effective'])
        self.assertFalse(value['dependence']['clusters_are_independent_samples'])

    def test_missing_or_future_weight_is_rejected_without_input_mutation(self):
        args, policy = inputs(count=25)
        original = deepcopy(args)
        key = next(iter(args[3]))
        for modification in ('missing', 'future', 'identity'):
            changed = deepcopy(args)
            if modification == 'missing':
                changed[3] = {}
            elif modification == 'future':
                changed[3][key]['available_at'] += BAR
            else:
                changed[3][key]['entry_ts'] += BAR
            with self.subTest(modification=modification), self.assertRaises(RuntimeError):
                module.build(*changed, policy=policy)
        self.assertEqual(args, original)

    def test_conflicting_watermark_and_post_end_data_are_rejected(self):
        args, policy = inputs(count=25)
        changed = deepcopy(args); changed[6] += BAR
        with self.assertRaisesRegex(RuntimeError, 'WATERMARK'):
            module.build(*changed, policy=policy)
        changed = deepcopy(args); changed[6] = changed[7] + BAR
        with self.assertRaisesRegex(RuntimeError, 'SCOPE'):
            module.build(*changed, policy=policy)

    def test_every_tick_multi_symbol_closed_open_transitions_preserve_daily_prefix(self):
        symbols = ['BTC-USDT', 'ETH-USDT', 'BCH-USDT']
        sequences = [
            [100, 100.2, 101, 102, 103, 110, 111, 99, 99, 99, 101, 103, 103, 103],
            [100, 100.2, 101, 102, 103.7, 103.6, 103.5, 103.4, 105, 101, 101, 104, 105, 101],
            [100, 100.2, 101, 102, 103.1, 103.2, 103.1, 103.2, 103.1, 103.2, 103.1, 103.2, 103.1, 103.2],
        ]
        prices = {symbol: fixture.prices(values) for symbol, values in zip(symbols, sequences)}
        costs = {symbol: deepcopy(fixture.COSTS[SYMBOL]) for symbol in symbols}
        state = engine.initialize({s: prices[s][:13] for s in symbols}, symbols, 4 * DAY, 14 * DAY)
        observations, old_daily = {}, {'A_Q0': [], 'B_RISK': []}
        previous_closed = {}
        for index in range(13, 84):
            state = engine.advance(state, {s: prices[s][index] for s in symbols})
            snapshot = engine.snapshot(state)
            for symbol in symbols:
                for trade in snapshot[symbol]['trades'] + snapshot[symbol]['open_positions']:
                    origin = module.accounting.ORIGIN(dict(trade, symbol=symbol, lane_id=module.source.LANE))
                    observations.setdefault(origin, {
                        'origin_key': origin, 'weight': .612312 + .027 * symbols.index(symbol),
                        'entry_ts': trade['entry_ts'], 'signal_ts': trade['signal_ts'],
                        'available_at': trade['signal_ts'], 'fixed_until_exit': True})
            current = module.build(snapshot, {s: prices[s][:index+1] for s in symbols}, costs,
                                   observations, symbols, 4 * DAY, (index + 1) * BAR, 14 * DAY,
                                   policy=fixture.POLICY)
            for name, old in old_daily.items():
                if name not in current['stages']:
                    continue
                daily = current['stages'][name]['daily']
                self.assertEqual(old, daily[:len(old)], (name, index))
                old_daily[name] = deepcopy(daily)
            closed = {row['origin_key']: row for row in current['unit_execution']['trades']}
            for key, old in previous_closed.items():
                self.assertEqual(old, closed[key])
            previous_closed = closed
        self.assertGreater(len(previous_closed), 1)


if __name__ == '__main__':
    unittest.main()
