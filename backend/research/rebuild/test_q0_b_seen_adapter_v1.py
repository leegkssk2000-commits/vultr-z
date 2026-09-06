"""Synthetic boundary checks; real prices only via explicit DEV parity command."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from backend.research.rebuild import q0_b_seen_adapter_v1 as adapter
from backend.research.rebuild import test_q0_risk_entry_weights_v1 as fixtures

DAY, BAR = adapter.DAY, adapter.BAR
SYMBOL = 'BTC-USDT'
COSTS = {SYMBOL: {'fee_bps': 10.0, 'spread_bps': 1.0, 'impact_bps': 1.0,
                  'funding_p95_per_settlement_bps': .25}}
POLICY = {'batch_id': 'SYNTHETIC', 'receipt_sha256': 'synthetic',
          'combined_data_sha256': 'synthetic', 'cost_binding_sha256': 'synthetic',
          'code_files_sha256': {}, 'development_interval_ms': [0, 8 * DAY]}


def prices(closes):
    rows = []
    for day, close in enumerate(closes):
        for part in range(6):
            stamp = day * DAY + part * BAR
            rows.append({'bar_open_ts': stamp, 'bar_close_ts': stamp + BAR,
                         'open': float(close), 'close': float(close),
                         'high': float(close) + .1, 'low': float(close) - .1,
                         'volume': 1.0})
    return rows


def replay(rows, start=0, end=None, evidence_type=None):
    return adapter.replay_q0({SYMBOL: rows}, COSTS, POLICY, [SYMBOL], start,
                             end or rows[-1]['bar_close_ts'], evidence_type=evidence_type)


def bound_state(rows=None, start_day=60, end_day=90, reference=None):
    rows = fixtures.bars() if rows is None else rows
    base = adapter.weights.market_state(fixtures.bars(), fixtures.SYMBOLS,
                                         fixtures.BASE + 41 * DAY,
                                         fixtures.BASE + 90 * DAY)
    ref = {k: base['reference'][k] for k in ('N', 'ddof', 'first_available_at', 'last_available_at')}
    ref['sigma_ref'] = base['sigma_ref']
    if reference is not None:
        ref.update(reference)
    return adapter._bound_market_state(rows, fixtures.SYMBOLS,
                                      fixtures.BASE + start_day * DAY,
                                      fixtures.BASE + end_day * DAY,
                                      fixtures.BASE + 41 * DAY, ref)


class SeenInputTests(unittest.TestCase):
    def test_prefix_does_not_decode_next_object_or_need_valid_future_prices(self):
        rows = prices([100, 101, 102])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'rows.json'
            path.write_text(json.dumps(rows)[:-1] + ', {BROKEN_FUTURE_OBJECT]')
            self.assertEqual(adapter._prefix(path, 0, 3 * DAY), rows)
            with self.assertRaises(RuntimeError):
                adapter._prefix(path, 0, 3 * DAY + BAR)

    def test_prefix_missing_duplicate_gap_and_wrong_first_time_fail(self):
        original = prices([100, 101, 102])
        cases = [original[:-1], original[1:], original[:7] + original[8:],
                 original[:7] + [original[6]] + original[8:]]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'rows.json'
            for rows in cases:
                path.write_text(json.dumps(rows))
                with self.subTest(count=len(rows)), self.assertRaises(RuntimeError):
                    adapter._prefix(path, 0, 3 * DAY)

    def test_access_counts_record_used_holdout_and_warmup_honestly(self):
        rows = prices([100] * 8)
        splits = {'development': [0, 2 * DAY],
                  'validation': [3 * DAY, 5 * DAY], 'purged_OOS': [6 * DAY, 9 * DAY]}
        audit = adapter._partition_access(rows, splits, 7 * DAY, 8 * DAY)
        self.assertEqual(audit['original_partition_decoded_rows'],
                         {'development': 12, 'validation': 12, 'purged_OOS': 12, 'embargo': 12})
        self.assertEqual((audit['warmup_rows'], audit['evaluation_rows']), (42, 6))
        self.assertEqual(audit['decoded_OOS_rows'], 12)
        self.assertFalse(audit['independent'])


class SeenFrozenReferenceTests(unittest.TestCase):
    def test_later_calendar_does_not_reestimate_reference(self):
        state = bound_state()
        naive = adapter.weights.market_state(fixtures.bars(), fixtures.SYMBOLS,
                                              fixtures.BASE + 60 * DAY, fixtures.BASE + 90 * DAY)
        self.assertNotEqual(state['sigma_ref'], naive['sigma_ref'])
        self.assertEqual(state['reference']['N'], 39)
        self.assertEqual(state['eval_start_ms'], fixtures.BASE + 60 * DAY)
        self.assertFalse(state['reference_binding']['reestimated_from_new_warmup'])

    def test_post_reference_prices_only_affect_rolling_sigma(self):
        rows = fixtures.bars()
        original = bound_state(rows)
        for items in rows.values():
            for row in items:
                if row['bar_open_ts'] >= fixtures.BASE + 59 * DAY:
                    for field in ('open', 'high', 'low', 'close'):
                        row[field] *= 1.10
        altered = bound_state(rows)
        self.assertEqual(original['sigma_ref'], altered['sigma_ref'])
        trade = fixtures.trade(day=60)
        before = adapter.weights.entry_weights(original, [trade])
        after = adapter.weights.entry_weights(altered, [trade])
        self.assertNotEqual(before, after)
        self.assertEqual(next(iter(after.values()))['available_at'], trade['entry_ts'])

    def test_mismatched_reference_value_or_38_return_lineage_fails(self):
        for changes in ({'sigma_ref': .0001}, {'N': 38}, {'last_available_at': fixtures.BASE}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                bound_state(reference=changes)

    def test_future_extension_leaves_existing_weights_unchanged(self):
        short = fixtures.bars(count=75)
        long = fixtures.bars(count=90)
        trade = fixtures.trade(day=65)
        before = adapter.weights.entry_weights(bound_state(short, end_day=75), [trade])
        after = adapter.weights.entry_weights(bound_state(long), [trade])
        self.assertEqual(before, after)
        origin = next(iter(before))
        self.assertEqual(before[origin]['window_N'], 30)
        self.assertLessEqual(before[origin]['weight'], 1.0)
        self.assertGreater(before[origin]['weight'], 0.0)


class SeenExecutionTests(unittest.TestCase):
    def test_flat_start_does_not_inherit_earlier_filled_position(self):
        rows = prices([100, 100.2, 101, 102, 103, 103, 103, 103])
        early = replay(rows)
        later = replay(rows, start=5 * DAY)
        self.assertTrue(early['open_observations'])
        self.assertFalse(later['open_observations'])
        self.assertFalse(later['trades'])
        self.assertTrue(all(t['signal_ts'] >= 5 * DAY for t in later['events']))

    def test_confirmation_at_start_keeps_prior_preparation_and_next_open(self):
        rows = prices([100, 100.2, 101, 102, 103, 103, 103, 103])
        result = replay(rows, start=4 * DAY)
        opened = result['open_observations'][0]
        self.assertEqual((opened['signal_ts'], opened['entry_ts']), (4 * DAY, 4 * DAY))
        self.assertEqual(opened['entry_signal_metadata']['prior_start_ts'], 0)
        self.assertLess(opened['channel_anchor_ts'], opened['entry_ts'])

    def test_end_close_is_a_mark_never_new_entry_or_forced_close(self):
        rows = prices([100, 100.2, 101, 102, 103, 103, 103, 103])
        no_entry = replay(rows, end=4 * DAY)
        self.assertFalse(no_entry['events'])
        marked = replay(rows, end=6 * DAY)
        self.assertEqual(len(marked['open_observations']), 1)
        opened = marked['open_observations'][0]
        self.assertEqual(opened['mark_ts'], 6 * DAY)
        self.assertFalse(opened['terminal_liquidation'])
        self.assertNotIn('exit_ts', opened)
        self.assertFalse(marked['trades'])
        self.assertAlmostEqual(marked['daily_valuation'][-1]['cumulative_net_mark_bps'],
                               opened['hypothetical_liquidation_net_mark_bps'])

    def test_unfinished_holding_funding_and_cost_floor_keep_original_convention(self):
        rows = prices([100, 100.2, 101, 102, 103, 103, 103, 103])
        opened = replay(rows, end=8 * DAY)['open_observations'][0]
        self.assertEqual(opened['funding_settlements_elapsed'], 12)
        self.assertEqual(opened['modeled_funding_accrued_bps'], 3.0)
        self.assertEqual(opened['hypothetical_liquidation_cost_bps'], 20.0)
        self.assertAlmostEqual(opened['hypothetical_liquidation_net_mark_bps'] -
                               opened['hypothetical_liquidation_cost2x_net_mark_bps'], 20.0)
        self.assertIsNone(opened['entry_side_cost_bps'])

    def test_same_calendar_future_extension_keeps_all_economics_identical(self):
        short = prices([100, 100.2, 101, 102, 103, 103, 103, 103])
        long = prices([100, 100.2, 101, 102, 103, 103, 103, 103, 1, 900])
        first, second = replay(short, end=8 * DAY), replay(long, end=8 * DAY)
        for key in ('trades', 'open_observations', 'events', 'daily_valuation'):
            self.assertEqual(first[key], second[key])

    def test_new_evidence_relabels_new_objects_and_preserves_economic_values(self):
        rows = prices([100, 100.2, 101, 102, 103, 103, 99, 99])
        original_rows = deepcopy(rows)
        a, b = replay(rows), replay(rows, evidence_type=adapter.EVIDENCE_TYPE)
        self.assertEqual(rows, original_rows)
        for old_row, new_row in zip(a['trades'], b['trades']):
            for field in ('entry_ts', 'entry_price', 'exit_ts', 'exit_price', 'cost_bps', 'net_bps', 'origin_key'):
                self.assertEqual(old_row[field], new_row[field])
            self.assertEqual(new_row['split'], adapter.EVIDENCE_TYPE)
            self.assertFalse(new_row['independent'])
            self.assertEqual(new_row['formal_credit'], 0)
            self.assertNotEqual(old_row['trade_sha256'], new_row['trade_sha256'])
        self.assertTrue(b['trades'])

    def test_incomplete_end_day_fails_instead_of_shortening_calendar(self):
        rows = prices([100, 100.2, 101, 102, 103, 103, 103, 103])[:-1]
        with self.assertRaisesRegex(RuntimeError, 'COMPLETE_TERMINAL_DAY'):
            replay(rows, end=8 * DAY)


if __name__ == '__main__':
    unittest.main()
