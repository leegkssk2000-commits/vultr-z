"""Causal state/cohort checks; these tests execute no strategy hypothesis."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

from backend.research.rebuild import break_channel_q2_observability_v1 as obs

DAY = obs.DAY
BASE = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def signal(day, upper, *, direction='UP', close=None):
    return dict(direction=direction, signal_index=day * 6 - 1,
                signal_ts=BASE + day * DAY, upper=upper, lower=upper * .99,
                confirmation_close=upper * 1.01 if close is None else close,
                channel_width_fraction=.003, anchor_daily_index=0)


def event(sig, *, status='COMPLETED', symbol='S'):
    return dict(symbol=symbol, signal_index=sig['signal_index'],
                signal_ts=sig['signal_ts'], comparison_stage='Q', status=status,
                exclusion_reason='SIGNAL_DURING_OPEN' if status == 'EXCLUDED' else None)


def trade(sig, net, *, exit_day=None, symbol='S', reason='PROTECTIVE_STOP_INTRABAR'):
    return dict(symbol=symbol, signal_index=sig['signal_index'],
                entry_ts=sig['signal_ts'], exit_ts=BASE + (exit_day or (sig['signal_index'] + 1) // 6 + 1) * DAY,
                net_bps=net, gross_bps=net + 20, exit_reason=reason,
                channel_upper=sig['upper'], trade_sha256='sealed-parent-row',
                comparison_stage='Q')


def classify(signals, trades=(), events=None):
    events = events or [event(s) for s in signals if s['direction'] == 'UP']
    daily = {'S': [dict(bar_open_ts=BASE, close=100)]}
    return obs._build_from_native(daily, {'S': signals}, list(trades), events,
                                  BASE, BASE + 366 * DAY)


def causal(row):
    return {k: v for k, v in row.items() if k != 'diagnostic_label'}


class ObservabilityTests(unittest.TestCase):
    def test_initial_unknown_history_is_not_false(self):
        s = signal(2, 100)
        r = classify([s], [trade(s, -100)])
        self.assertEqual(r['feature_rows'][0]['states'], dict.fromkeys(obs.STATES))
        for state in obs.STATES:
            c = r['cohort_state_counts'][state]['all_closed']
            self.assertEqual((c['N'], c['true'], c['false'], c['unknown']), (1, 0, 0, 1))

    def test_held_signal_remains_previous_native_up(self):
        a, held, b = signal(2, 100), signal(4, 120), signal(6, 110)
        r = classify([a, held, b], [trade(a, 50, exit_day=5), trade(b, -50)],
                     [event(a), event(held, status='EXCLUDED'), event(b)])
        f = r['feature_rows'][-1]
        self.assertTrue(f['states']['prepared_up_upper_nonascending'])
        self.assertEqual(f['lineage']['previous_up_upper'], 120)
        self.assertEqual(r['cohort_state_counts'][obs.STATES[1]]['occupied_excluded_UP']['N'], 1)

    def test_future_pnl_run_labels_do_not_enter_features(self):
        a, b, future = signal(2, 100), signal(4, 110), signal(6, 105)
        ts = [trade(a, -20, exit_day=3), trade(b, -40, exit_day=7), trade(future, 80, exit_day=9)]
        x = classify([a, b, future], ts)
        changed = deepcopy(ts)
        changed[0]['net_bps'] = 9999
        changed[1]['net_bps'] = -9999
        changed[2]['net_bps'] = -20000
        y = classify([a, b, future], changed)
        self.assertEqual([causal(r) for r in x['feature_rows']],
                         [causal(r) for r in y['feature_rows']])
        self.assertNotEqual(x['all_parent_loss_runs'], y['all_parent_loss_runs'])

    def test_exit_after_signal_is_not_previous_realized_stop(self):
        a, b = signal(2, 110), signal(4, 100)
        t = trade(a, -100, exit_day=5)
        x = classify([a, b], [t])['feature_rows'][-1]
        self.assertIsNone(x['states']['prior_stop_same_or_lower_channel'])
        t['exit_ts'] = b['signal_ts']
        y = classify([a, b], [t])['feature_rows'][-1]
        self.assertTrue(y['states']['prior_stop_same_or_lower_channel'])
        self.assertEqual(y['lineage']['prior_position_exit_ts'], b['signal_ts'])

    def test_simultaneous_close_group_membership_differs_from_trade_win(self):
        a, b, c, d = [signal(i, 100 + i) for i in (2, 4, 6, 8)]
        ts = [trade(a, -100, exit_day=9), trade(b, 20, exit_day=9),
              trade(c, 100, exit_day=10), trade(d, -20, exit_day=10)]
        r = classify([a, b, c, d], ts)
        labels = [v['diagnostic_label'] for v in r['feature_rows']]
        self.assertTrue(labels[1]['win'])
        self.assertIsNotNone(labels[1]['parent_loss_run_id'])
        self.assertFalse(labels[3]['win'])
        self.assertIsNone(labels[3]['parent_loss_run_id'])
        counts = r['cohort_state_counts'][obs.STATES[0]]
        self.assertEqual(counts['positive_exit_groups']['N'], 2)
        self.assertEqual(counts['closed_wins']['N'], 2)
        self.assertEqual(r['all_parent_loss_runs']['1']['groups'], 1)
        self.assertEqual(r['all_parent_loss_runs']['1']['net_bps'], -80)

    def test_zero_group_breaks_run_without_being_positive(self):
        a, b, c = signal(2, 100), signal(4, 110), signal(6, 120)
        r = classify([a, b, c], [trade(a, -30), trade(b, 0), trade(c, -40)])
        self.assertEqual(len(r['all_parent_loss_runs']), 2)
        counts = r['cohort_state_counts'][obs.STATES[0]]
        self.assertEqual(counts['zero_exit_groups']['N'], 1)
        self.assertEqual(counts['closed_losses']['N'], 2)
        self.assertEqual(counts['closed_zeros']['N'], 1)
        self.assertEqual(counts['positive_exit_groups']['N'], 0)

    def test_quarters_use_signal_time_with_unknown_full_denominator(self):
        a, b = signal(89, 100), signal(90, 105)  # Mar31 / Apr1 UTC
        r = classify([a, b], [trade(a, -10, exit_day=92), trade(b, 20, exit_day=93)])
        q1 = r['quarter_state_counts']['2025Q1'][obs.STATES[1]]['all_closed']
        q2 = r['quarter_state_counts']['2025Q2'][obs.STATES[1]]['all_closed']
        self.assertEqual((q1['N'], q1['unknown']), (1, 1))
        self.assertEqual((q2['N'], q2['unknown']), (1, 0))

    def test_public_build_signal_prefix_and_future_prices(self):
        prices = [100, 100, 101, 102, 101, 100, 100, 101, 102,
                  100, 99, 99, 100, 101, 102, 104, 103, 103, 104, 105]
        rows = []
        for i, close in enumerate(prices):
            for j in range(6):
                stamp = BASE + i * DAY + j * obs.structure.INTERVAL
                rows.append(dict(bar_open_ts=stamp,
                                 bar_close_ts=stamp + obs.structure.INTERVAL,
                                 open=close, high=close * 1.001, low=close * .999,
                                 close=close, volume=100))
        end = BASE + len(prices) * DAY
        daily = obs.structure.aggregate_daily(rows, split_end_ms=end)['daily']
        signals = obs.structure.generate_signals(daily, eval_start_ms=BASE,
                  eval_end_ms=end, require_preparation=True)['signals']
        events = [event(s, status='EXCLUDED') for s in signals if s['direction'] == 'UP']
        self.assertGreater(len(events), 1)
        full = obs.build({'S': rows}, [], events, eval_start_ms=BASE, eval_end_ms=end)
        cut = events[1]['signal_ts']
        prefix = obs.build({'S': [r for r in rows if r['bar_close_ts'] <= cut]}, [],
                           [e for e in events if e['signal_ts'] <= cut],
                           eval_start_ms=BASE, eval_end_ms=cut + DAY)
        self.assertTrue(full['causality_audit']['checks_passed'])
        self.assertTrue(prefix['causality_audit']['checks_passed'])
        self.assertEqual([causal(r) for r in prefix['feature_rows']],
                         [causal(r) for r in full['feature_rows'] if r['signal_ts'] <= cut])
        self.assertEqual(full['hypotheses_consumed'], 0)


if __name__ == '__main__':
    unittest.main()
