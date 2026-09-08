"""Post-result synthetic boundary checks; no economic allocation or market inputs.

These tests were added after candidate 50 evaluations 79/80. They supplement
the original frozen tests and do not retrospectively become pre-freeze evidence.
"""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from backend.research.rebuild import kr3_whole_entry_failure_exit_v1 as c


class WholeEntryBoundaryTests(unittest.TestCase):
    def fixture(self):
        # All rows and features are artificial. A long preparation prefix makes
        # rebasing the original signal index to the evaluation window observable.
        n, origin, start = 350, 242, 240 * c.BAR
        rows = [dict(bar_open_ts=i*c.BAR, bar_close_ts=(i+1)*c.BAR,
                     open=100., high=101., low=99., close=100., volume=10.)
                for i in range(n)]
        bundle = dict(signals=[dict(signal_index=origin,
                                   signal_ts=rows[origin]['bar_close_ts'])],
                      ema20=[100.]*n, ema50=[99.]*n, audit={})
        rows[origin+1].update(open=100., high=101., low=97., close=98.)
        rows[origin+2].update(open=98., high=99., low=95., close=96.)
        for index in (origin+1, origin+2):
            bundle['ema20'][index] = 99.
            bundle['ema50'][index] = 97.
        rows[origin+3].update(open=95., high=200., low=1., close=100.)
        return rows, bundle, start, n*c.BAR, origin

    def test_nonzero_start_keeps_preparation_and_original_coordinates(self):
        rows, bundle, start, end, origin = self.fixture()
        got = c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end)
        self.assertEqual(len(got['trades']), 1)
        trade = got['trades'][0]
        self.assertEqual((trade['signal_index'], trade['entry_index'],
                          trade['exit_index']), (origin, origin+1, origin+3))
        self.assertEqual(trade['entry_ts'], (origin+1)*c.BAR)
        self.assertGreaterEqual(trade['entry_ts'], start)
        self.assertEqual(trade['frozen_signal_low'], rows[origin]['low'])
        self.assertEqual(trade['exit_trigger']['ema50'], bundle['ema50'][origin+2])
        self.assertEqual(trade['exit_reason'], c.FAILURE_EXIT)
        self.assertEqual(trade['exit_price'], 95.)
        self.assertEqual(trade['low_exit_state']['index'], origin+1)
        self.assertLess(trade['mfe_bps'], 200.)
        self.assertGreater(trade['mae_bps'], -600.)

    def test_disabled_exact_KR3_with_nonzero_start(self):
        rows, bundle, start, end, _ = self.fixture()
        self.assertEqual(
            c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end,
                     enabled=False),
            c.parent.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end))

    def test_serialized_reference_checkpoint_restarts_without_duplicates(self):
        rows, bundle, start, end, origin = self.fixture()
        partial = c.parent.parent.causal_clock(
            rows, bundle, eval_start_ms=start, eval_end_ms=end,
            stop_after_index=origin+1)
        restored = json.loads(json.dumps(partial))
        checkpoint_before = deepcopy(restored)
        resumed = c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end,
                           reference_checkpoint=restored)
        fresh = c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end)
        self.assertEqual(resumed, fresh)
        self.assertEqual(restored, checkpoint_before)
        self.assertTrue(resumed['reference_events'])
        self.assertEqual(len(resumed['reference_opportunities']), 1)
        again = c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end,
                        reference_checkpoint=json.loads(json.dumps(
                            resumed['reference_checkpoint'])))
        self.assertEqual(again, fresh)

    def test_inputs_are_immutable_after_enabled_and_disabled_replay(self):
        rows, bundle, start, end, _ = self.fixture()
        before = deepcopy((rows, bundle))
        for enabled in (True, False):
            c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end,
                     enabled=enabled)
            self.assertEqual((rows, bundle), before)

    def test_exception_restores_both_hooks_and_preserves_inputs(self):
        rows, bundle, start, end, _ = self.fixture()
        before = deepcopy((rows, bundle))
        kr_hook, geometry_hook = c.parent.kr.path, c.d._path
        with patch.object(c, 'additional_failure',
                          side_effect=RuntimeError('SYNTHETIC_INTERRUPTION')):
            with self.assertRaisesRegex(RuntimeError, 'SYNTHETIC_INTERRUPTION'):
                c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end)
        self.assertIs(c.parent.kr.path, kr_hook)
        self.assertIs(c.d._path, geometry_hook)
        self.assertEqual((rows, bundle), before)
        # The restored implementation remains usable after the exception.
        self.assertEqual(c.replay(rows, bundle, eval_start_ms=start,
                                  eval_end_ms=end)['trades'][0]['exit_reason'],
                         c.FAILURE_EXIT)

    def test_present_outside_next_bar_is_rejected_and_prefix_stays_pending(self):
        rows, bundle, start, _, origin = self.fixture()
        end = (origin+3)*c.BAR
        self.assertEqual(rows[origin+3]['bar_open_ts'], end)
        before = deepcopy((rows, bundle))
        # The public replay contract requires the last input close == end.
        # A supplied future suffix must be rejected, never silently consumed.
        with self.assertRaises((RuntimeError, ValueError)):
            c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end)
        self.assertEqual((rows, bundle), before)
        prefix = rows[:origin+3]
        prefix_bundle = deepcopy(bundle)
        for key in ('ema20', 'ema50'):
            prefix_bundle[key] = prefix_bundle[key][:origin+3]
        got = c.replay(prefix, prefix_bundle, eval_start_ms=start, eval_end_ms=end)
        self.assertEqual(got['trades'], [])
        self.assertEqual(len(got['open_positions']), 1)
        pending = got['open_positions'][0]
        self.assertFalse(pending['terminal_liquidation'])
        self.assertEqual(pending['pending_exit_signal_ts'], end)
        self.assertTrue(pending['pending_exit_trigger']['post_suppression_failure'])
        self.assertEqual(pending['mark_ts'], end)
        self.assertEqual(pending['mark_index'], origin+2)
        self.assertNotIn('exit_price', pending)
        self.assertFalse(any(t['kind'] == c.FAILURE_EXIT for t in got['trace']))


if __name__ == '__main__':
    unittest.main()
