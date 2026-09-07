"""Small synthetic TPQ1 timing, complete-parent and slot-accounting checks."""
from copy import deepcopy
import unittest

from backend.research.rebuild import primary_entry_quality_v1 as q
from backend.research.rebuild.test_top5_mechanism_b_v1 import fixture
from backend.research.rebuild.test_trend_primary_combined_v1 import COST, charge


def tape_for(event, indices):
    return [dict(deepcopy(event), signal_index=i, signal_ts=(i+1)*q.parent.HOUR)
            for i in indices]


class EligibilityTests(unittest.TestCase):
    def test_long_short_adverse_aligned_and_doji(self):
        for side in ('long', 'short'):
            rows, _, event = fixture(side)
            sign = 1 if side == 'long' else -1
            for body, expected in ((-1, False), (0, True), (1, True)):
                rows[0]['close'] = rows[0]['open'] + sign*body
                self.assertIs(q.eligible(rows, event), expected)
                self.assertIs(q.eligible(rows, event, enabled=False), True)

    def test_only_signal_bar_is_read_and_future_append_cannot_change_veto(self):
        rows, _, event = fixture()
        rows[0]['close'] = 99.
        expected = q.eligible(rows[:1], event)
        changed = deepcopy(rows)
        for row in changed[1:]:
            row.update(open=99999., close=-99999., high=999999., low=-999999.)
        self.assertIs(q.eligible(changed, event), expected)
        self.assertIs(q.eligible(changed + [{'future': 'unavailable'}], event), expected)
        minimal = [{'open': 100., 'close': 99., 'bar_close_ts': event['signal_ts']}]
        self.assertIs(q.eligible(minimal, event), False)

    def test_flags_metadata_and_invalid_prices_fail_closed(self):
        rows, cache, event = fixture()
        for flag in (0, 1, None, 'true'):
            with self.assertRaisesRegex(RuntimeError, 'TPQ1_ENABLED_BOOL'):
                q.eligible(rows, event, enabled=flag)
            with self.assertRaisesRegex(RuntimeError, 'TPQ1_ENABLED_BOOL'):
                q.replay(rows, [event], cache, COST, enabled=flag)
        for altered, reason in ((dict(event, signal_ts=0), 'CLOSE_BINDING'),
                                (dict(event, side='invalid'), 'TPQ1_SIDE'),
                                (dict(event, signal_index=-1), 'SIGNAL_INDEX')):
            with self.assertRaisesRegex(RuntimeError, reason):
                q.eligible(rows, altered)
        rows[0]['open'] = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'PRICE_FINITE'):
            q.eligible(rows, event)


class ReplayTests(unittest.TestCase):
    def test_all_pass_and_off_complete_parent_raw_trace_audit_parity(self):
        for side in ('long', 'short'):
            rows, cache, event = fixture(side)
            tape = tape_for(event, (0, 1, 49, 97, 98, 99, 105))
            original = deepcopy((rows, tape, COST))
            expected = q.parent.replay(rows, tape, cache, COST)
            for enabled in (False, True):
                actual = q.replay(rows, tape, cache, COST, enabled=enabled)
                self.assertEqual(actual, expected)
                self.assertEqual(q.parent.a.old.probe.canonical(actual),
                                 q.parent.a.old.probe.canonical(expected))
            self.assertEqual((rows, tape, COST), original)
            rows[0]['close'] = 99. if side == 'long' else 101.
            self.assertEqual(q.replay(rows, tape, cache, COST, enabled=False),
                             q.parent.replay(rows, tape, cache, COST))

    def test_held_veto_does_not_create_entry_or_release_ownership(self):
        rows, cache, event = fixture()
        rows[2]['close'] = 99.
        tape = tape_for(event, (0, 1, 2, 3, 98, 99))
        out = q.replay(rows, tape, cache, COST)
        self.assertEqual([e['status'] for e in out['events']],
                         ['COMPLETED', 'EXCLUDED', 'VETOED', 'EXCLUDED', 'EXCLUDED', 'CENSORED'])
        self.assertEqual([e['signal_index'] for e in out['trades']], [0])
        self.assertEqual([e['signal_index'] for e in out['open_positions']], [99])
        self.assertEqual(out['audit']['raw_signals'], 6)
        self.assertEqual(out['audit']['entry_quality_vetoed'], 1)
        self.assertEqual(out['audit']['native_blocked'], 3)
        self.assertEqual(out['audit']['completed']+out['audit']['open']+
                         out['audit']['native_blocked']+out['audit']['entry_quality_vetoed'], 6)
        veto = out['events'][2]
        self.assertFalse(veto['admission'])
        self.assertNotIn('gross_bps', veto)
        self.assertNotIn('net_bps', veto)

    def test_vetoed_initial_entry_leaves_slot_for_next_original_signal(self):
        rows, cache, event = fixture()
        rows[0]['close'] = 99.
        tape = tape_for(event, (0, 1, 2))
        self.assertEqual([e['signal_index'] for e in q.parent.replay(rows, tape, cache, COST)['trades']], [0])
        out = q.replay(rows, tape, cache, COST)
        self.assertEqual([e['status'] for e in out['events']], ['VETOED', 'COMPLETED', 'EXCLUDED'])
        self.assertEqual([e['signal_index'] for e in out['trades']], [1])
        expected = q.parent.replay(rows, tape[1:], cache, COST)
        for key in ('trades', 'open_positions', 'trace'):
            self.assertEqual(out[key], expected[key])
        self.assertEqual(charge(out, rows)['trades'], charge(expected, rows)['trades'])

    def test_common_entry_preserves_complete_path_sltp_and_charged_cost(self):
        for side in ('long', 'short'):
            rows, cache, event = fixture(side)
            rows[1]['close'] = 99. if side == 'long' else 101.
            event['tp'] = 103.5 if side == 'long' else 96.5
            tape = tape_for(event, (0, 1))
            expected = q.parent.replay(rows, tape, cache, COST)
            out = q.replay(rows, tape, cache, COST)
            for key in ('trades', 'open_positions', 'trace'):
                self.assertEqual(out[key], expected[key])
            self.assertEqual(charge(out, rows)['trades'], charge(expected, rows)['trades'])
            self.assertEqual(out['trades'][0]['native_sl'], event['sl'])
            self.assertEqual(out['trades'][0]['native_tp'], event['tp'])

    def test_all_veto_retains_raw_intents_without_zero_profit_trades(self):
        rows, cache, event = fixture()
        for row in rows:
            row['close'] = 99.
        tape = tape_for(event, (0, 1, 2))
        out = q.replay(rows, tape, cache, COST)
        self.assertEqual(len(out['events']), len(tape))
        self.assertTrue(all(e['status']=='VETOED' for e in out['events']))
        self.assertEqual(out['trades'], [])
        self.assertEqual(out['open_positions'], [])
        self.assertEqual(out['trace'], [])
        self.assertEqual(out['audit']['completed'], 0)
        self.assertEqual(out['audit']['native_blocked'], 0)


if __name__ == '__main__':
    unittest.main()
