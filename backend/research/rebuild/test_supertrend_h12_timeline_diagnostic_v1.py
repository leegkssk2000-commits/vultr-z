"""Meaningful leakage and partition checks using small synthetic prefixes."""
import copy
import unittest
from backend.research.rebuild import supertrend_h12_timeline_diagnostic_v1 as d


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.binding = {'fee_bps': 10., 'spread_bps': 2., 'impact_bps': 1., 'funding_p95_per_settlement_bps': 1.}
        self.rows = [{'bar_open_ts': k*d.BAR, 'bar_close_ts': (k+1)*d.BAR, 'open': 100.,
                      'close': 100., 'high': 999., 'low': 1.} for k in range(13)]
        self.trade = {'side': 'long', 'native_interval_ms': d.BAR, 'signal_index': 0,
                      'entry_index': 1, 'exit_index': 12, 'entry_ts': d.BAR, 'exit_ts': 13*d.BAR,
                      'entry_price': 100., 'exit_price': 100., 'gross_bps': 0., 'cost_bps': 20.,
                      'net_bps': -20., 'origin_key': 'a', 'symbol': 'BTC-USDT'}

    def diag(self):
        return d.diagnostic_trade(self.trade, self.rows, self.binding, 14*d.BAR, set())

    def test_exit_hlc_never_feature_and_prefix_stable(self):
        self.rows[2]['close'] = 102.
        baseline = self.diag()['states']
        self.rows[12].update(close=80., low=.001, high=99999.)
        self.trade.update(exit_price=80., gross_bps=-2000., net_bps=-2020., mfe_bps=999999.)
        self.assertEqual(baseline, self.diag()['states'])
        partial = d.causal_states(self.trade, self.rows[1:5], self.binding)
        self.rows[5]['close'] = 999.
        self.assertEqual(partial, self.diag()['states'][:4])

    def test_partition_cost_and_giveback(self):
        self.assertEqual(self.diag()['postoutcome_label'], 'NO_FAVORABLE_CLOSE')
        self.rows[2]['close'] = 101.
        result = self.diag()
        self.assertEqual(result['postoutcome_label'], 'GIVEBACK')
        self.assertEqual(result['states'][2]['first_return_nonpositive_k_so_far'], 3)
        self.rows[12]['close'] = 100.1
        self.trade.update(exit_price=100.1, gross_bps=10., net_bps=-10.)
        self.assertEqual(self.diag()['postoutcome_label'], 'COST_FLIPPED')

    def test_exit_row_rejected_and_cost_is_current_only(self):
        with self.assertRaisesRegex(RuntimeError, 'EXIT_ROW_OR_FUTURE'):
            d.causal_states(self.trade, self.rows[1:], self.binding)
        states = self.diag()['states']
        mutated = copy.deepcopy(self.trade)
        mutated['funding_bps'] = 999999.
        self.assertEqual(states, d.causal_states(mutated, self.rows[1:12], self.binding))
        self.assertTrue(all(s['available_at'] < self.trade['exit_ts'] for s in states))


if __name__ == '__main__':
    unittest.main()
