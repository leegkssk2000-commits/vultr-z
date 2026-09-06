"""Synthetic-only incremental/batch parity, causality and restart regression."""
from copy import deepcopy
import json
import random
import unittest
from unittest.mock import patch

from backend.research.rebuild import q0_prospective_engine_v1 as engine
from backend.research.rebuild import break_channel_structure_v1 as q0
from backend.research.rebuild import test_break_channel_structure_v1 as fixtures
from backend.research.rebuild import test_q0_b_seen_adapter_v1 as seen

DAY, BAR = q0.DAY, q0.INTERVAL
SYMBOLS = ['BTC-USDT', 'ETH-USDT', 'BCH-USDT', 'LINK-USDT',
           'SOL-USDT', '1000PEPE-USDT', 'HYPE-USDT']


def raw_batch(rows, start, end):
    days = q0.aggregate_daily(rows, split_end_ms=end)['daily']
    bundle = q0.generate_signals(days, eval_start_ms=start, eval_end_ms=end)
    return q0.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end), bundle


def stream(rows, start, end, prefix=13, restart=False):
    state = engine.initialize({'BTC-USDT': rows[:prefix]}, ['BTC-USDT'], start, end)
    for row in rows[prefix:]:
        if row['bar_close_ts'] > end:
            break
        state = engine.advance(state, {'BTC-USDT': row})
        if restart:
            state = json.loads(json.dumps(state))
    return state, engine.snapshot(state)['BTC-USDT']


def manual_execution(rows, signals):
    """Exercise frozen fill precedence with explicit synthetic close signals."""
    s = engine._empty_symbol()
    for row in rows:
        current = [signal for signal in signals if signal['signal_index'] == s['next_index']]
        s['signals'].extend(current)
        engine._execute_bar(s, row, current)
        s['last_bar'] = deepcopy(row)
        s['next_index'] += 1
    state = {'symbols': ['BTC-USDT'], 'by_symbol': {'BTC-USDT': s},
             'cursor_close_ts': rows[-1]['bar_close_ts']}
    actual = engine.snapshot(state)['BTC-USDT']
    actual.pop('bundle')
    return actual


class IncrementalQ0ParityTests(unittest.TestCase):
    def assert_parity(self, rows, start=4 * DAY, prefix=13):
        end = rows[-1]['bar_close_ts']
        expected, bundle = raw_batch(rows, start, end)
        state, actual = stream(rows, start, end, prefix, restart=True)
        self.assertEqual(actual.pop('bundle'), bundle)
        self.assertEqual(actual, expected)
        return state, actual

    def test_channel_to_fills_stop_reentry_full_ledger_exact_batch_parity(self):
        rows = seen.prices([100, 100.2, 101, 102, 103, 104, 99, 99,
                            99, 101, 102, 105, 105, 104, 103, 102,
                            102, 102, 104, 106, 103, 101])
        state, actual = self.assert_parity(rows)
        self.assertGreaterEqual(len(actual['trades']), 2)
        self.assertTrue(any(t['exit_reason'] == 'PROTECTIVE_STOP_GAP_OPEN'
                            for t in actual['trades']))
        self.assertEqual(state['formal_credit'], 0)
        self.assertEqual(state['execution'], 'NONE')

    def test_partial_source_prefix_keeps_original_global_indices(self):
        rows = seen.prices([100, 100, 100.2, 101, 102, 103, 103, 99, 99, 104])[2:]
        _, actual = self.assert_parity(rows, start=5 * DAY)
        expected = raw_batch(rows, 5 * DAY, 10 * DAY)[0]
        self.assertEqual(actual['trades'][0]['signal_index'], expected['trades'][0]['signal_index'])
        self.assertEqual(actual['trades'][0]['signal_index'], 27)

    def test_future_extension_cannot_change_completed_trades_or_signal_prefix(self):
        rows = seen.prices([100, 100.2, 101, 102, 103, 98, 98, 100, 100,
                            103, 104, 110, 112, 90, 90, 90])
        state = engine.initialize({'BTC-USDT': rows[:13]}, ['BTC-USDT'], 4 * DAY, 16 * DAY)
        for row in rows[13:54]:
            state = engine.advance(state, {'BTC-USDT': row})
        checkpoint = deepcopy(state)
        prior = engine.snapshot(checkpoint)['BTC-USDT']
        for row in rows[54:]:
            state = engine.advance(state, {'BTC-USDT': row})
        final = engine.snapshot(state)['BTC-USDT']
        self.assertEqual(prior['trades'], final['trades'][:len(prior['trades'])])
        self.assertEqual(prior['bundle']['signals'], final['bundle']['signals'][:len(prior['bundle']['signals'])])
        self.assertEqual(checkpoint, json.loads(json.dumps(checkpoint)))

    def test_channel_pending_attempt_survives_bootstrap_and_json_restart(self):
        rows = seen.prices([100, 100.2, 101, 102, 103, 103, 103, 103])
        state = engine.initialize({'BTC-USDT': rows[:18]}, ['BTC-USDT'], 4 * DAY, 8 * DAY)
        self.assertIsNotNone(state['by_symbol']['BTC-USDT']['attempts']['UP'])
        self.assertIsNone(state['by_symbol']['BTC-USDT']['position'])
        self.assertIsNone(state['by_symbol']['BTC-USDT']['pending_entry'])
        state = json.loads(json.dumps(state))
        for row in rows[18:24]:
            state = engine.advance(state, {'BTC-USDT': row})
        self.assertEqual(state['by_symbol']['BTC-USDT']['signals'][0]['signal_ts'], 4 * DAY)
        self.assertIsNotNone(state['by_symbol']['BTC-USDT']['pending_entry'])
        self.assertIsNone(state['by_symbol']['BTC-USDT']['position'])
        state = engine.advance(json.loads(json.dumps(state)), {'BTC-USDT': rows[24]})
        opened = engine.snapshot(state)['BTC-USDT']['open_positions'][0]
        self.assertEqual(opened['entry_ts'], 4 * DAY)
        self.assertEqual(opened['mark_ts'], 4 * DAY + BAR)

    def test_warmup_signals_and_economic_history_are_not_carried(self):
        rows = seen.prices([100, 100.2, 101, 102, 103, 103, 103, 103])
        state = engine.initialize({'BTC-USDT': rows[:29]}, ['BTC-USDT'], 6 * DAY, 8 * DAY)
        for field in ('signals', 'events', 'trades'):
            self.assertEqual(state['by_symbol']['BTC-USDT'][field], [])
        for row in rows[29:]:
            state = engine.advance(state, {'BTC-USDT': row})
        self.assertEqual(engine.snapshot(state)['BTC-USDT']['open_positions'], [])

    def test_utc_end_marks_open_position_without_new_signal_or_force_close(self):
        rows = seen.prices([100, 100.2, 101, 102, 103, 104, 104, 105])
        state, actual = self.assert_parity(rows)
        self.assertEqual(len(actual['open_positions']), 1)
        self.assertFalse(actual['open_positions'][0]['terminal_liquidation'])
        self.assertEqual(actual['open_positions'][0]['mark_ts'], 8 * DAY)
        self.assertTrue(all(s['signal_ts'] < 8 * DAY for s in state['by_symbol']['BTC-USDT']['signals']))
        with self.assertRaisesRegex(RuntimeError, 'AFTER_FROZEN_END'):
            engine.advance(state, {'BTC-USDT': seen.prices([100] * 9)[-6]})

    def test_terminal_confirmation_is_suppressed(self):
        rows = seen.prices([100, 100.2, 101, 102])
        _, actual = self.assert_parity(rows, start=3 * DAY)
        self.assertEqual(actual['events'], [])

    def test_exact_day_emission_and_seven_symbol_batch(self):
        rows = seen.prices([100, 100.2, 101, 102, 103])
        state = engine.initialize({s: deepcopy(rows[:13]) for s in SYMBOLS}, SYMBOLS, 4 * DAY, 5 * DAY)
        self.assertEqual(len(state['by_symbol'][SYMBOLS[0]]['partial_day']), 1)
        for index in range(13, len(rows)):
            state = engine.advance(state, {s: deepcopy(rows[index]) for s in SYMBOLS})
            self.assertEqual(bool(state['last_daily_bars']), (index + 1) % 6 == 0)
            if state['last_daily_bars']:
                self.assertEqual(set(state['last_daily_bars']), set(SYMBOLS))
                self.assertEqual(state['last_daily_bars'][SYMBOLS[0]]['source_last_index'], index)

    def test_updates_do_not_invoke_full_signal_generation_or_economic_replay(self):
        rows = seen.prices([100, 100.2, 101, 102, 103, 99, 99, 99])
        with patch.object(q0, 'generate_signals', side_effect=AssertionError('historical signals')):
            with patch.object(q0, 'replay', side_effect=AssertionError('historical economics')):
                stream(rows, 4 * DAY, 8 * DAY, restart=True)

    def test_current_position_keeps_only_its_own_causal_geometry(self):
        rows = seen.prices([100, 100.2, 101, 102, 103, 103, 103, 103])
        state, _ = stream(rows, 4 * DAY, 8 * DAY)
        symbol = state['by_symbol']['BTC-USDT']
        self.assertEqual(len(symbol['previous_days']), 2)
        self.assertEqual(symbol['partial_day'], [])
        self.assertEqual(symbol['position']['geometry_rows'][0]['bar_close_ts'], 4 * DAY)
        self.assertNotIn('rows', symbol)

    def test_bounded_synthetic_mixed_paths_match_all_transitions(self):
        # Synthetic fixtures exercise many cancellations and direction changes;
        # they neither read market data nor consume a research hypothesis slot.
        rng = random.Random(1194)
        for case in range(4):
            value, closes = 100., [100., 100.2]
            for _ in range(55):
                value *= rng.choice((.96, .995, .999, 1.0, 1.001, 1.005, 1.04))
                closes.append(value)
            with self.subTest(case=case):
                self.assert_parity(seen.prices(closes))

    def test_interim_snapshot_is_symmetric_and_cannot_close_live_state(self):
        rows = seen.prices([100, 100.2, 101, 102, 103, 104, 103, 103])
        state, marked = stream(rows[:30], 4 * DAY, 8 * DAY)
        saved = deepcopy(state)
        self.assertEqual(marked['events'][0]['status'], 'CENSORED')
        self.assertEqual(state['by_symbol']['BTC-USDT']['events'][0]['status'], 'PENDING')
        self.assertFalse(marked['open_positions'][0]['terminal_liquidation'])
        self.assertEqual(engine.snapshot(state)['BTC-USDT'], marked)
        self.assertEqual(state, saved)


class IncrementalExecutionPrecedenceTests(unittest.TestCase):
    def parity(self, rows, signals):
        self.assertEqual(manual_execution(rows, signals),
                         q0.replay(rows, {'signals': signals}, eval_start_ms=0,
                                   eval_end_ms=rows[-1]['bar_close_ts']))

    def test_gap_stop_precedes_confirmed_exit(self):
        rows = fixtures.bars()
        rows[12].update(open=97., high=98., low=96., close=97.)
        self.parity(rows, [fixtures.signal(), fixtures.signal(11, 'DOWN')])

    def test_next_open_exit_ignores_later_same_bar_extrema(self):
        rows = fixtures.bars()
        rows[12].update(open=120., high=900., low=1., close=110.)
        self.parity(rows, [fixtures.signal(), fixtures.signal(11, 'DOWN')])

    def test_intrabar_stop_including_entry_bar_and_terminal_bar(self):
        for index in (6, 7, 35):
            rows = fixtures.bars()
            rows[index].update(low=97., high=150.)
            with self.subTest(index=index):
                self.parity(rows, [fixtures.signal()])

    def test_bad_entry_gap_is_cancelled_and_not_rescheduled(self):
        rows = fixtures.bars()
        rows[6].update(open=97., high=98., low=96., close=97.)
        self.parity(rows, [fixtures.signal()])

    def test_occupied_signal_and_simultaneous_priority(self):
        rows = fixtures.bars()
        rows[13]['low'] = 97.
        self.parity(rows, [fixtures.signal(), fixtures.signal(11), fixtures.signal(17)])
        self.parity(fixtures.bars(), [fixtures.signal(), fixtures.signal(11, 'DOWN'), fixtures.signal(11)])


class IncrementalIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.rows = seen.prices([100, 100.2, 101, 102, 103, 99])
        self.state = engine.initialize({'BTC-USDT': self.rows[:13]}, ['BTC-USDT'], 4 * DAY, 6 * DAY)

    def test_gap_duplicate_out_of_order_and_nonfinite_leave_state_unchanged(self):
        original = deepcopy(self.state)
        bad = deepcopy(self.rows[13]); bad['close'] = float('nan')
        for row in (self.rows[12], self.rows[14], bad):
            with self.assertRaises(RuntimeError):
                engine.advance(self.state, {'BTC-USDT': row})
            self.assertEqual(self.state, original)

    def test_missing_or_extra_symbol_fails_before_consumption(self):
        for rows in ({}, {'ETH-USDT': self.rows[13]},
                     {'BTC-USDT': self.rows[13], 'ETH-USDT': self.rows[13]}):
            with self.assertRaisesRegex(RuntimeError, 'STATE_SCOPE'):
                engine.advance(self.state, rows)

    def test_invalid_warmup_or_nonflat_authority_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'WARMUP_MUST_PRECEDE_T0'):
            engine.initialize({'BTC-USDT': self.rows[:24]}, ['BTC-USDT'], 4 * DAY, 6 * DAY)
        for field, value in (('formal_credit', 1), ('execution', 'LIVE'), ('operating_adoption', True)):
            altered = deepcopy(self.state); altered[field] = value
            with self.assertRaisesRegex(RuntimeError, 'STATE_SCOPE'):
                engine.advance(altered, {'BTC-USDT': self.rows[13]})


if __name__ == '__main__':
    unittest.main()
