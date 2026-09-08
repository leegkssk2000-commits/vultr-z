"""Changed-boundary tests only: synthetic OHLCV, no DEV execution/allocation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import step7_kr3_winner_repair_v1 as e
from backend.research.rebuild import step7_kr3_mechanism_separation_v1 as b


def fixture(n=40, origins=(2,)):
    rows = [dict(bar_open_ts=i*b.BAR, bar_close_ts=(i+1)*b.BAR,
                 open=100., high=101., low=99., close=100., volume=10.)
            for i in range(n)]
    bundle = dict(signals=[dict(signal_index=i, signal_ts=rows[i]['bar_close_ts'])
                           for i in origins if i < n-1],
                  ema20=[100.]*n, ema50=[99.]*n, audit={})
    return rows, bundle


def breakout(rows, i, close=102.):
    rows[i].update(close=close, high=close+1.)


def run(rows, bundle):
    return e.replay_symbol(rows, bundle, start=0, end=len(rows)*b.BAR)


def event(out, origin=2):
    return next(x for x in out['events'] if x['original_signal_index']==origin)


def position(out, origin=2):
    return next(x for x in out['trades']+out['open_positions']
                if x['original_signal_index']==origin)


class WinnerRepairTests(unittest.TestCase):
    def test_original_ineligible_never_repaired_and_ghost_clock_preserved(self):
        rows, bundle = fixture(); rows[2].update(high=104.)
        breakout(rows, 3, 106.)
        got = run(rows, bundle)
        parent = b.replay_symbol(rows, bundle, b.MODES[1], start=0, end=len(rows)*b.BAR)
        self.assertFalse(event(got)['admission'])
        self.assertEqual(got['reference_opportunities'], parent['reference_opportunities'])
        self.assertEqual(got['reference_events'], parent['reference_events'])
        self.assertTrue(got['reference_opportunities'])

    def test_first_confirmation_is_completed_close_then_next_open(self):
        rows, bundle = fixture(); breakout(rows, 3)
        got = run(rows, bundle); p = position(got)
        self.assertEqual(p['decision_index'], 3)
        self.assertEqual(p['entry_index'], 4)
        self.assertEqual(p['entry_ts'], rows[3]['bar_close_ts'])
        self.assertEqual(p['waiting_observed_bars'], 1)
        entry = next(x for x in got['trace'] if x['kind']=='ENTRY_NEXT_OPEN')
        self.assertEqual(entry['feature_available_ts'], rows[3]['bar_close_ts'])
        self.assertGreaterEqual(entry['ts'], entry['feature_available_ts'])

    def test_equal_origin_high_is_not_breakout_and_no_second_bar_retry(self):
        rows, bundle = fixture(); rows[3].update(close=101., high=102.)
        breakout(rows, 4, 105.)
        got = run(rows, bundle)
        self.assertEqual(position(got)['decision_index'], 8)
        self.assertEqual(position(got)['waiting_observed_bars'], 6)

    def test_upper_half_required_even_when_breakout_and_trend_pass(self):
        rows, bundle = fixture(); rows[3].update(close=102., high=110.)
        self.assertEqual(position(run(rows, bundle))['decision_index'], 8)

    def test_first_close_above_fast_ema_is_required(self):
        rows, bundle = fixture(); breakout(rows, 3)
        bundle['ema20'][3] = 102.
        self.assertEqual(position(run(rows, bundle))['decision_index'], 8)

    def test_early_entry_survives_later_sixth_bar_recheck_failure(self):
        rows, bundle = fixture(); breakout(rows, 3); rows[8].update(high=110.)
        got = run(rows, bundle)
        self.assertTrue(event(got)['admission'])
        self.assertEqual(position(got)['decision_index'], 3)
        self.assertEqual(len(got['trades'])+len(got['open_positions']), 1)

    def test_reference_ema_exit_blocks_first_confirmation_and_cannot_revive(self):
        rows, bundle = fixture(); breakout(rows, 3); bundle['ema20'][3] = 98.
        got = run(rows, bundle)
        self.assertFalse(event(got)['admission'])
        self.assertFalse(got['trades']+got['open_positions'])
        self.assertIn(event(got)['exclusion_reason'],
                      ('WAIT_REFERENCE_EXIT_ALREADY_OBSERVED', 'WAIT_REFERENCE_EXPIRED'))

    def test_actual_runner_occupancy_cancels_early_opportunity_without_sixth_retry(self):
        rows, bundle = fixture(origins=(2,15)); breakout(rows, 3)
        for i in range(13,26): breakout(rows, i)
        breakout(rows, 16, 104.)
        got = run(rows, bundle)
        self.assertTrue(event(got, 2)['admission'])
        self.assertFalse(event(got, 15)['admission'])
        self.assertEqual(event(got, 15)['decision_ts'], rows[16]['bar_close_ts'])
        self.assertIn('OCCUPIED', event(got, 15)['exclusion_reason'])
        self.assertTrue(event(got, 15)['reference_created'])
        self.assertEqual(len(got['trades'])+len(got['open_positions']), 1)

    def test_original_low_timeout_and_extension_decision_anchor_preserved(self):
        rows, bundle = fixture(); rows[2]['low'] = 90.; breakout(rows, 3)
        got = run(rows, bundle); p = position(got)
        self.assertEqual(p['exit_anchor_index'], 2)
        self.assertEqual(p['exit_index'], 14)
        entry = next(x for x in got['trace'] if x['kind']=='ENTRY_NEXT_OPEN')
        self.assertEqual(entry['frozen_signal_low'], 90.)
        decisions = [x for x in got['trace'] if x['kind']==b.DECISION]
        self.assertEqual([x['index'] for x in decisions], [13])
        self.assertIsNone(p['initial_protective_sl'])
        self.assertIsNone(p['tp']); self.assertIsNone(p['risk_R'])

    def test_early_actual_low_exit_does_not_release_origin_reference(self):
        rows, bundle = fixture(origins=(2,7)); breakout(rows, 3)
        rows[5].update(close=98., low=97.)
        got = run(rows, bundle)
        parent = b.replay_symbol(rows, bundle, b.MODES[1], start=0, end=len(rows)*b.BAR)
        self.assertEqual(position(got)['exit_index'], 6)
        self.assertFalse(event(got, 7)['admission'])
        self.assertEqual(event(got, 7)['exclusion_reason'], b.reservation.REFERENCE_VETO_REASON)
        self.assertEqual(got['reference_opportunities'], parent['reference_opportunities'])
        self.assertEqual(got['reference_events'], parent['reference_events'])

    def test_waiting_low_breach_is_not_carried_into_actual_trade_state(self):
        rows, bundle = fixture(); rows[3].update(close=98., low=97.)
        p = position(run(rows, bundle))
        self.assertEqual(p['entry_index'], 9)
        self.assertEqual(p['low_exit_state']['status'], b.UNCHECKED)

    def test_confirmation_bar_extreme_not_in_held_excursions(self):
        rows, bundle = fixture(); breakout(rows, 3, 1001.); rows[3]['low'] = 1.
        p = position(run(rows, bundle))
        self.assertLess(p['mfe_bps'], 101.)
        self.assertGreater(p['mae_bps'], -101.)

    def test_future_suffix_changes_no_earlier_confirmation(self):
        rows, bundle = fixture(); breakout(rows, 3)
        changed = deepcopy(rows)
        for row in changed[8:]: row.update(open=80., low=79., close=80., high=120.)
        left, right = run(rows, bundle), run(changed, bundle)
        fields = ('admission', 'decision_index', 'decision_ts', 'exclusion_reason')
        self.assertEqual({k:event(left).get(k) for k in fields},
                         {k:event(right).get(k) for k in fields})
        self.assertEqual(position(left)['entry_ts'], position(right)['entry_ts'])
        # Subsequent exits/profits intentionally need not match changed prices.

    def test_tail_confirmation_without_fill_is_pending_not_censored_trade(self):
        rows, bundle = fixture(n=4); breakout(rows, 3)
        got = run(rows, bundle)
        self.assertFalse(event(got)['admission'])
        self.assertFalse(got['trades']+got['open_positions'])
        self.assertEqual(got['audit']['raw_signals'], 1)
        self.assertEqual(got['audit']['excluded'], 1)

    def test_actual_tail_position_remains_marked_not_forced_fill(self):
        rows, bundle = fixture(n=10); breakout(rows, 3)
        got = run(rows, bundle)
        self.assertEqual(len(got['open_positions']), 1)
        self.assertFalse(got['open_positions'][0]['terminal_liquidation'])
        self.assertFalse(got['trades'])

    def test_durable_claim_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'ATTEMPT.json'
            e.parent.write_new(path, b'claim only, not completed')
            with self.assertRaises(FileExistsError): e.parent.write_new(path, b'retry')
            self.assertEqual(path.read_bytes(), b'claim only, not completed')

    def test_failed_claim_consumes_once_without_false_completion_or_retry(self):
        # Isolated fixture allocation, never the campaign ledger or market data.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); spec = {'receipt_sha256':'SYNTHETIC_ONLY'}
            budget = {'cumulative_actual_evaluations':60, 'cumulative_actual':44,
                      'new_candidate_runs':0, 'trials':[],
                      'kr3_winner_repair_allocation':{
                          'scope_key':e.SCOPE, 'specification_sha256':'SYNTHETIC_ONLY',
                          'runs':list(e.RUNS), 'used':0, 'max_executions':3}}
            (root/'BUDGET.json').write_text(json.dumps(budget))
            with patch.object(e, 'ROOT', root), patch.object(e, 'OUTPUT', 'scope'), \
                 patch.object(e, 'BUDGET', 'BUDGET.json'), patch.object(e, 'verify'), \
                 patch.object(e, 'run_one', side_effect=RuntimeError('synthetic pre-replay failure')) as call:
                with self.assertRaisesRegex(RuntimeError, 'synthetic pre-replay failure'):
                    e.execute({}, spec, root/'scope')
                self.assertFalse((root/'scope/RESULT_INDEX.json').exists())
                self.assertFalse((root/'scope/E-DEV2025/RECEIPT.json').exists())
                failure=json.loads((root/'scope/E-DEV2025/FAILURE.json').read_text())
                self.assertEqual(failure['status'], 'FAILED_CONSUMED')
                claimed=json.loads((root/'BUDGET.json').read_text())
                self.assertEqual(claimed['cumulative_actual_evaluations'], 61)
                self.assertEqual(claimed['cumulative_actual'], 45)
                with self.assertRaises(FileExistsError): e.execute({}, spec, root/'scope')
                self.assertEqual(call.call_count, 1)


if __name__=='__main__': unittest.main()
