"""Synthetic causality/inheritance tests, no economic dataset/replay allocation."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from backend.research.rebuild import kr3_d2_failure_exit_v1 as c
from backend.research.rebuild.test_step7_kr3_mechanism_separation_v1 import tiny,core
p=c.p

class FailureExitTests(unittest.TestCase):
    def state(self):return {'status':c.SUPPRESSED,'index':9}
    def test_suppressed_first_breach_never_rearms_itself(self):
        self.assertFalse(c.additional_failure(self.state(),{'close':90},9,99,95))
    def test_only_later_below_both_can_trigger(self):
        self.assertTrue(c.additional_failure(self.state(),{'close':94},10,99,95))
        self.assertFalse(c.additional_failure(self.state(),{'close':95},10,99,95))
        self.assertFalse(c.additional_failure(self.state(),{'close':99},10,99,101))
    def test_other_states_unchanged(self):
        for state in (c.UNCHECKED,c.ALLOWED):
            self.assertFalse(c.additional_failure({'status':state,'index':9},{'close':90},10,99,95))
    def test_nonfinite_fails_closed(self):
        with self.assertRaises(ValueError):c.additional_failure(self.state(),{'close':float('nan')},10,99,95)
    def fixture(self,n=70):
        rows,b=tiny(n);b['signals']=[b['signals'][0]]
        rows[9].update(open=100.,high=101.,low=97.,close=98.)
        b['ema50'][9]=97.;b['ema20'][9]=99.
        rows[10].update(open=98.,high=99.,low=95.,close=96.)
        b['ema50'][10]=97.;b['ema20'][10]=99.
        if n>11: rows[11].update(open=95.,high=200.,low=1.,close=100.)
        return rows,b
    def run_child(self,rows,b):return c.replay_symbol(rows,b,start=0,end=len(rows)*p.BAR)
    def test_disabled_condition_matches_exact_parent(self):
        rows,b=tiny()
        with patch.object(c,'additional_failure',return_value=False):child=self.run_child(rows,b)
        parent=p.replay_symbol(rows,b,p.MODES[3],start=0,end=len(rows)*p.BAR)
        for k in ('trades','open_positions','events','trace','reference_events','reference_opportunities'):
            self.assertEqual(child[k],parent[k])
    def test_later_failure_fills_next_open(self):
        rows,b=self.fixture();r=self.run_child(rows,b);t=r['trades'][0]
        self.assertEqual(t['exit_index'],11);self.assertEqual(t['exit_price'],95.)
        self.assertEqual(t['exit_reason'],c.FAILURE_EXIT)
        self.assertEqual(t['low_exit_state']['status'],c.SUPPRESSED)
    def test_exit_open_bar_extremes_excluded(self):
        rows,b=self.fixture();t=self.run_child(rows,b)['trades'][0]
        self.assertLess(t['mfe_bps'],200);self.assertGreater(t['mae_bps'],-600)
    def test_existing_ema_exit_priority(self):
        rows,b=self.fixture();b['ema20'][10]=96.
        self.assertEqual(self.run_child(rows,b)['trades'][0]['exit_reason'],'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN')
    def test_reference_lifecycle_not_released_by_actual_exit(self):
        rows,b=self.fixture();a=self.run_child(rows,b)
        parent=p.replay_symbol(rows,b,p.MODES[3],start=0,end=len(rows)*p.BAR)
        self.assertEqual(a['reference_events'],parent['reference_events'])
        self.assertEqual(a['reference_opportunities'],parent['reference_opportunities'])
    def test_delay_original_eligibility_and_anchor_are_retained(self):
        rows,b=self.fixture();t=self.run_child(rows,b)['trades'][0]
        self.assertEqual(t['entry_index'],9);self.assertEqual(t['original_signal_index'],2)
        self.assertEqual(t['exit_anchor_index'],8)
    def test_future_suffix_does_not_change_finished_trade(self):
        rows,b=self.fixture();a=self.run_child(rows,b)
        for row in rows[12:]:row.update(open=20.,close=20.,high=21.,low=19.)
        self.assertEqual(core(a),core(self.run_child(rows,b)))
    def test_boundary_pending_not_fabricated_as_close(self):
        rows,b=self.fixture(11);a=self.run_child(rows,b)
        self.assertEqual(len(a['open_positions']),1);self.assertFalse(a['trades'])
    def test_all_origins_and_actual_slots_accounted(self):
        rows,b=tiny();r=self.run_child(rows,b)
        self.assertEqual(len(r['events']),len(b['signals']))
        last=-1
        for t in r['trades']+r['open_positions']:
            self.assertGreater(t['decision_ts'],last);last=t.get('exit_ts',t.get('mark_ts'))

if __name__=='__main__':unittest.main()
