"""Synthetic incremental/batch B parity; no market or economic trial is run."""
from copy import deepcopy
from datetime import datetime, timezone
import statistics
import unittest

from . import q0_b_seen_adapter_v1 as adapter
from . import q0_prospective_weights_v1 as incremental
from . import q0_risk_entry_weights_v1 as frozen

DAY, BAR = frozen.DAY, frozen.structure.INTERVAL
START = int(datetime(2024, 12, 20, tzinfo=timezone.utc).timestamp() * 1000)
SYMBOLS = adapter.SYMBOLS


def bars(count=110):
    signs = [1.0 if day % 2 else -1.0 for day in range(1, 39)]
    scale = adapter.REFERENCE['sigma_ref'] / statistics.stdev(signs)
    result = {}
    for index, symbol in enumerate(SYMBOLS):
        close = 100.0 + index
        rows = []
        for day in range(count):
            if day:
                magnitude = 1.0 if day <= 38 else (0.6 if day < 70 else 2.0)
                close *= 1 + (1.0 if day % 2 else -1.0) * scale * magnitude
            for part in range(6):
                stamp = START + day * DAY + part * BAR
                rows.append({'bar_open_ts': stamp, 'bar_close_ts': stamp + BAR,
                             'open': close, 'high': close, 'low': close,
                             'close': close, 'volume': 1.0})
        result[symbol] = rows
    return result


def prefix(rows, days):
    return {symbol: deepcopy(value[:6 * days]) for symbol, value in rows.items()}


def daily(rows, day):
    return {symbol: frozen.structure.aggregate_daily(value[day * 6:(day + 1) * 6])['daily'][0]
            for symbol, value in rows.items()}


class IncrementalBWeightsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = bars()

    def test_initial_reference_is_original_38_returns_and_scalar(self):
        state = incremental.initialize(prefix(self.rows, 65), SYMBOLS)
        self.assertEqual(state['reference'], adapter.REFERENCE)
        self.assertEqual(state['sigma_ref'], 0.03290943045427639)
        self.assertEqual(len(state['returns']), 30)
        self.assertEqual(state['last_daily_close_ts'], START + 65 * DAY)
        self.assertFalse(state['reference_reestimated'])
        self.assertEqual(state['reference']['N'], 38)

    def test_incremental_matches_sealed_batch_every_daily_window(self):
        state = incremental.initialize(prefix(self.rows, 65), SYMBOLS)
        market = adapter.frozen_market_state(self.rows, SYMBOLS, adapter.ORIGINAL_START,
                                              START + 110 * DAY)
        observed = []
        for day in range(65, 105):
            before = deepcopy(state)
            next_state = incremental.advance(state, daily(self.rows, day))
            self.assertEqual(state, before)
            state = next_state
            signal = START + (day + 1) * DAY
            trade = dict(lane_id='Q0', symbol=SYMBOLS[0], side='long',
                         signal_ts=signal, entry_ts=signal)
            expected = frozen.entry_weights(market, [trade])[frozen.ORIGIN(trade)]
            actual = incremental.observation(state, signal)
            self.assertEqual(actual, {key: expected[key] for key in actual})
            self.assertEqual(state['returns'], [row for row in market['returns']
                                               if signal - 29 * DAY <= row['available_at'] <= signal])
            self.assertEqual(len(state['returns']), 30)
            self.assertEqual(len(state['last_closes']), 7)
            observed.append(actual['weight'])
        self.assertEqual(max(observed), 1.0)
        self.assertLess(min(observed), 1.0)
        self.assertEqual(state['incremental_days'], 40)

    def test_same_day_weight_excludes_future_and_preserves_existing_snapshot(self):
        state = incremental.initialize(prefix(self.rows, 80), SYMBOLS)
        signal = START + 80 * DAY
        before = deepcopy(state)
        locked = incremental.observation(state, signal)
        next_state = incremental.advance(state, daily(self.rows, 80))
        self.assertEqual(state, before)
        self.assertEqual(locked, incremental.observation(state, signal))
        with self.assertRaisesRegex(RuntimeError, 'LATEST_COMPLETE_DAY'):
            incremental.observation(next_state, signal)
        with self.assertRaisesRegex(RuntimeError, 'LATEST_COMPLETE_DAY'):
            incremental.observation(state, signal + DAY)

    def test_original_reference_cannot_be_replaced_or_retuned(self):
        rows = prefix(self.rows, 65)
        with self.assertRaisesRegex(RuntimeError, 'INITIAL_DEFINITION_DRIFT'):
            incremental.initialize(rows, SYMBOLS, adapter.ORIGINAL_START + DAY)
        for symbol in SYMBOLS:
            for row in rows[symbol][6:12]:
                for key in ('open', 'high', 'low', 'close'):
                    row[key] *= 1.2
        with self.assertRaisesRegex(RuntimeError, 'ORIGINAL_REFERENCE_SIGMA'):
            incremental.initialize(rows, SYMBOLS)

    def test_fixed_period_ddof_reference_and_symbols_cannot_drift(self):
        state = incremental.initialize(prefix(self.rows, 65), SYMBOLS)
        for change in ({'window_returns': 29}, {'ddof': 0}, {'sigma_ref': .04},
                       {'symbols': list(reversed(SYMBOLS))}, {'reference_verified': False}):
            with self.subTest(change=change):
                with self.assertRaisesRegex(RuntimeError, 'FROZEN_DEFINITION_DRIFT'):
                    incremental.observation({**state, **change}, state['last_daily_close_ts'])

    def test_missing_symbol_bad_close_and_gap_fail_without_mutation(self):
        state = incremental.initialize(prefix(self.rows, 65), SYMBOLS)
        initial = deepcopy(state)
        incomplete = daily(self.rows, 65)
        del incomplete[SYMBOLS[0]]
        with self.assertRaisesRegex(RuntimeError, 'CONSTITUENTS_MISSING'):
            incremental.advance(state, incomplete)
        with self.assertRaisesRegex(RuntimeError, 'GAP_OR_INCOMPLETE'):
            incremental.advance(state, daily(self.rows, 66))
        for bad in (None, 0, -1, float('nan'), float('inf')):
            incomplete = daily(self.rows, 65)
            incomplete[SYMBOLS[0]]['close'] = bad
            with self.assertRaisesRegex(RuntimeError, 'NEXT_CLOSE_INVALID'):
                incremental.advance(state, incomplete)
        self.assertEqual(state, initial)

    def test_incomplete_utc_day_and_duplicate_day_are_rejected(self):
        state = incremental.initialize(prefix(self.rows, 65), SYMBOLS)
        incomplete = daily(self.rows, 65)
        incomplete[SYMBOLS[0]]['bar_close_ts'] -= BAR
        with self.assertRaisesRegex(RuntimeError, 'GAP_OR_INCOMPLETE'):
            incremental.advance(state, incomplete)
        next_state = incremental.advance(state, daily(self.rows, 65))
        with self.assertRaisesRegex(RuntimeError, 'GAP_OR_INCOMPLETE'):
            incremental.advance(next_state, daily(self.rows, 65))

    def test_outcome_labels_cannot_affect_allocation(self):
        state = incremental.initialize(prefix(self.rows, 65), SYMBOLS)
        complete = daily(self.rows, 65)
        expected = incremental.advance(state, complete)
        for row in complete.values():
            row.update(final_pnl=-10000, future_max=1000000, eventual_winner=False,
                       c_ex_post_weight=.12)
        self.assertEqual(expected, incremental.advance(state, complete))

    def test_zero_window_sigma_is_not_replaced_with_epsilon_or_weight(self):
        state = incremental.initialize(prefix(self.rows, 65), SYMBOLS)
        for day in range(65, 95):
            complete = {symbol: {'bar_open_ts': START + day * DAY,
                         'bar_close_ts': START + (day + 1) * DAY,
                         'close': state['last_closes'][symbol]} for symbol in SYMBOLS}
            state = incremental.advance(state, complete)
        with self.assertRaisesRegex(RuntimeError, 'ENTRY_SIGMA_ZERO_OR_INVALID'):
            incremental.observation(state, state['last_daily_close_ts'])

    def test_partial_seed_edge_is_not_a_completed_daily_close(self):
        rows = {symbol: deepcopy(value[:65 * 6 + 3]) for symbol, value in self.rows.items()}
        state = incremental.initialize(rows, SYMBOLS)
        expected = incremental.initialize(prefix(self.rows, 65), SYMBOLS)
        self.assertEqual(state, expected)


if __name__ == '__main__':
    unittest.main()
