"""Synthetic causal risk weights: no Q0 strategy or economic trial is run."""
from copy import deepcopy
import math
import statistics
import unittest

from backend.research.rebuild import q0_risk_entry_weights_v1 as risk

DAY, INTERVAL = risk.DAY, risk.structure.INTERVAL
BASE = 1_735_689_600_000  # 2025-01-01 00:00 UTC
SYMBOLS = tuple('S' + str(i) for i in range(7))


def bars(count=90, *, constant=False):
    result = {}
    for symbol_index, symbol in enumerate(SYMBOLS):
        close = 100.0 + symbol_index
        rows = []
        for day in range(count):
            if day and not constant:
                close *= 1 + (.003 if day % 2 else -.005) * (1 + day / 40)
            for part in range(6):
                stamp = BASE + day * DAY + part * INTERVAL
                rows.append(dict(bar_open_ts=stamp, bar_close_ts=stamp + INTERVAL,
                                 open=close, high=close, low=close, close=close,
                                 volume=1.0))
        result[symbol] = rows
    return result


def trade(day=60, symbol=SYMBOLS[0]):
    return dict(lane_id='break', symbol=symbol, signal_ts=BASE + day * DAY,
                entry_ts=BASE + day * DAY, side='long')


def state(rows=None, start_day=41, end_day=90):
    return risk.market_state(bars() if rows is None else rows, SYMBOLS,
                             BASE + start_day * DAY, BASE + end_day * DAY)


class EntryRiskWeightsTests(unittest.TestCase):
    def test_basket_equal_weights_and_sample_ddof_one(self):
        market = state()
        warmup = [row['simple_return'] for row in market['returns']
                  if row['available_at'] < BASE + 41 * DAY]
        mean = math.fsum(warmup) / len(warmup)
        expected = math.sqrt(math.fsum((value - mean) ** 2 for value in warmup)
                             / (len(warmup) - 1))
        self.assertAlmostEqual(market['sigma_ref'], expected, places=15)
        self.assertNotAlmostEqual(market['sigma_ref'], statistics.pstdev(warmup),
                                  places=10)
        self.assertEqual(market['reference']['N'], 39)
        for row in market['returns']:
            self.assertEqual(row['simple_return'],
                             math.fsum(row['constituent_returns'].values()) / 7)

    def test_reference_strictly_before_boundary_and_current_close_included(self):
        rows = bars()
        market = state(rows)
        boundary = BASE + 41 * DAY
        for per_symbol in rows.values():
            for row in per_symbol:
                if row['bar_open_ts'] >= boundary - DAY:
                    for field in ('open', 'high', 'low', 'close'):
                        row[field] *= 1.10
        altered = state(rows)
        self.assertEqual(market['sigma_ref'], altered['sigma_ref'])
        self.assertLess(market['reference']['last_available_at'], boundary)
        t = trade(day=41)
        before = risk.entry_weights(market, [t])[risk.ORIGIN(t)]
        after = risk.entry_weights(altered, [t])[risk.ORIGIN(t)]
        self.assertEqual(before['available_at'], boundary)
        self.assertEqual(before['window_first_available_at'], boundary - 29 * DAY)
        self.assertNotEqual(before['sigma_t'], after['sigma_t'])

    def test_complete_future_prefix_and_future_prices_leave_entry_identical(self):
        rows = bars()
        t = trade(day=60)
        original = risk.entry_weights(state(rows), [t])
        prefix = {symbol: [row for row in per_symbol
                           if row['bar_close_ts'] <= t['signal_ts']]
                  for symbol, per_symbol in rows.items()}
        self.assertEqual(original, risk.entry_weights(state(prefix), [t]))
        for per_symbol in rows.values():
            for row in per_symbol:
                if row['bar_open_ts'] >= t['signal_ts']:
                    for field in ('open', 'high', 'low', 'close'):
                        row[field] *= 4.0
        self.assertEqual(original, risk.entry_weights(state(rows), [t]))

    def test_entry_fields_only_outcomes_and_open_status_cannot_change_weight(self):
        market, t = state(), trade()
        original = deepcopy(t)
        base = risk.entry_weights(market, [t])
        t.update(net_bps=-999_999, exit_ts=BASE + 90 * DAY,
                 exit_price=0.001, win=False, holding_days=999,
                 future_max=1e9, diagnostic_run_id='future')
        self.assertEqual(base, risk.entry_weights(market, [], [t]))
        self.assertEqual(original, {key: t[key] for key in original})
        self.assertTrue(next(iter(base.values()))['fixed_until_exit'])

    def test_simultaneous_symbols_receive_same_market_state(self):
        market = state()
        result = risk.entry_weights(market, [trade(symbol=symbol) for symbol in SYMBOLS])
        self.assertEqual(len(result), 7)
        self.assertEqual(len({row['weight'] for row in result.values()}), 1)
        self.assertEqual(len({row['sigma_t'] for row in result.values()}), 1)

    def test_cap_one_and_no_zero_or_increase(self):
        market = state()
        t = trade()
        market['sigma_ref'] = 1.0
        high = risk.entry_weights(market, [t])[risk.ORIGIN(t)]
        self.assertEqual(high['weight'], 1.0)
        market['sigma_ref'] = high['sigma_t'] / 4.0
        low = risk.entry_weights(market, [t])[risk.ORIGIN(t)]
        self.assertEqual(low['weight'], .25)

    def test_seven_symbols_and_identical_calendar_required(self):
        rows = bars()
        missing = deepcopy(rows)
        missing.pop(SYMBOLS[-1])
        with self.assertRaisesRegex(RuntimeError, 'CONSTITUENT_SET'):
            state(missing)
        with self.assertRaisesRegex(RuntimeError, 'FIXED_SEVEN'):
            risk.market_state(rows, SYMBOLS[:-1], BASE + 41 * DAY, BASE + 90 * DAY)
        shifted = deepcopy(rows)
        shifted[SYMBOLS[-1]] = shifted[SYMBOLS[-1]][6:]
        with self.assertRaisesRegex(RuntimeError, 'CALENDAR_MISMATCH'):
            state(shifted)

    def test_internal_gap_and_bad_prices_not_imputed(self):
        rows = bars()
        del rows[SYMBOLS[0]][12]
        with self.assertRaises(RuntimeError):
            state(rows)
        for bad in (0, -1, float('nan'), float('inf')):
            with self.subTest(bad=bad):
                rows = bars()
                rows[SYMBOLS[0]][12]['close'] = bad
                with self.assertRaises(RuntimeError):
                    state(rows)

    def test_partial_edge_days_remain_excluded_not_synthesized(self):
        rows = {symbol: per_symbol[2:-2] for symbol, per_symbol in bars().items()}
        market = state(rows)
        for audit in market['audit']['aggregation_by_symbol'].values():
            self.assertEqual(len(audit['partial_days']), 2)
            self.assertEqual(audit['synthetic_rows'], 0)
        self.assertEqual(market['audit']['complete_daily_first_close_ts'], BASE + 2 * DAY)
        self.assertEqual(market['audit']['complete_daily_last_close_ts'], BASE + 89 * DAY)

    def test_short_warmup_and_zero_reference_fail_without_epsilon(self):
        with self.assertRaisesRegex(RuntimeError, 'REFERENCE_SIGMA_INSUFFICIENT'):
            state(start_day=3)
        with self.assertRaisesRegex(RuntimeError, 'REFERENCE_SIGMA_ZERO_OR_INVALID'):
            state(bars(constant=True))
        with self.assertRaisesRegex(RuntimeError, '30_RETURN_HISTORY_INSUFFICIENT'):
            risk.entry_weights(state(start_day=10), [trade(day=20)])

    def test_zero_current_window_fails_without_synthetic_weight(self):
        rows = bars()
        for per_symbol in rows.values():
            for row in per_symbol:
                if row['bar_open_ts'] >= BASE + 43 * DAY:
                    for field in ('open', 'high', 'low', 'close'):
                        row[field] = 100.0
        with self.assertRaisesRegex(RuntimeError, 'ENTRY_SIGMA_ZERO_OR_INVALID'):
            risk.entry_weights(state(rows), [trade(day=80)])

    def test_unknown_origin_duplicate_and_time_leaks_fail(self):
        market = state()
        t = trade()
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_ENTRY_ORIGIN'):
            risk.entry_weights(market, [t], [t])
        for changes in ({'signal_ts': None}, {'entry_ts': t['signal_ts'] - INTERVAL},
                        {'signal_ts': BASE + DAY}, {'entry_ts': BASE + 90 * DAY}):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(RuntimeError, 'DECISION_TIME_INVALID'):
                    risk.entry_weights(market, [{**t, **changes}])
        with self.assertRaisesRegex(RuntimeError, 'SYMBOL_OR_SIDE_INVALID'):
            risk.entry_weights(market, [{**t, 'symbol': 'MISSING'}])
        with self.assertRaisesRegex(RuntimeError, 'ORIGIN_DRIFT'):
            risk.entry_weights(market, [{**t, 'origin_key': 'invented'}])
        market['reference']['last_available_at'] = market['eval_start_ms']
        with self.assertRaisesRegex(RuntimeError, 'REFERENCE_TIME_LEAK'):
            risk.entry_weights(market, [t])


if __name__ == '__main__':
    unittest.main()
