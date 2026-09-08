"""Synthetic-only tests. No economic price inputs, paid calls or allocations."""
from copy import deepcopy
import json, unittest
from unittest.mock import patch
from backend.research.rebuild import kr3_whole_entry_failure_exit_v1 as c
from backend.research.rebuild.test_step7_kr3_mechanism_separation_v1 import tiny

class WholeEntryTests(unittest.TestCase):
    def fixture(self, n=70):
        rows,b=tiny(n);b['signals']=[b['signals'][0]]
        rows[3].update(open=100.,high=101.,low=97.,close=98.)
        b['ema50'][3]=97.;b['ema20'][3]=99.
        rows[4].update(open=98.,high=99.,low=95.,close=96.)
        b['ema50'][4]=97.;b['ema20'][4]=99.
        if n>5: rows[5].update(open=95.,high=200.,low=1.,close=100.)
        return rows,b
    def run_child(self,rows,b):return c.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR)
    def test_predicate_is_strictly_subsequent(self):
        st={'status':c.SUPPRESSED,'index':3}
        self.assertFalse(c.additional_failure(st,{'close':96},3,99,97))
        self.assertTrue(c.additional_failure(st,{'close':96},4,99,97))
        self.assertFalse(c.additional_failure(st,{'close':97},4,99,97))
        self.assertFalse(c.additional_failure(st,{'close':99},4,99,101))
    def test_non_suppressed_states_cannot_trigger(self):
        for status in [c.UNCHECKED,c.ALLOWED]:
            self.assertFalse(c.additional_failure({'status':status}, {'close':90},4,99,97))
    def test_nonfinite_is_not_a_false_signal(self):
        with self.assertRaises(ValueError):c.additional_failure({'status':c.SUPPRESSED,'index':3},{'close':float('nan')},4,99,97)
    def test_serialized_suppression_preserves_decision(self):
        state=json.loads(json.dumps({'status':c.SUPPRESSED,'index':3}))
        self.assertTrue(c.additional_failure(state,{'close':96},4,99,97))
    def test_suppression_then_next_open_no_wait6(self):
        rows,b=self.fixture();r=self.run_child(rows,b);t=r['trades'][0]
        self.assertEqual((t['signal_index'],t['entry_index'],t['exit_index']),(2,3,5))
        self.assertEqual((t['entry_price'],t['exit_price']),(100.,95.))
        self.assertEqual(t['frozen_signal_low'],99.)
        self.assertEqual(t['exit_reason'],c.FAILURE_EXIT)
        self.assertEqual(t['low_exit_state']['index'],3)
    def test_exit_open_bar_hlc_is_not_held(self):
        rows,b=self.fixture();t=self.run_child(rows,b)['trades'][0]
        self.assertLess(t['mfe_bps'],200);self.assertGreater(t['mae_bps'],-600)
    def test_existing_ema_exit_priority(self):
        rows,b=self.fixture();b['ema20'][4]=96.
        self.assertEqual(self.run_child(rows,b)['trades'][0]['exit_reason'],'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN')
    def test_first_allowed_low_exit_unchanged(self):
        rows,b=self.fixture();b['ema50'][3]=99.;b['ema20'][3]=100.
        p=c.parent.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR)
        self.assertEqual(self.run_child(rows,b)['trades'],p['trades'])
    def test_same_reference_not_released_by_early_exit(self):
        rows,b=self.fixture();_,many=tiny();b['signals']=many['signals']
        p=c.parent.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR)
        v=self.run_child(rows,b)
        self.assertEqual(v['reference_events'],p['reference_events'])
        self.assertEqual(v['reference_opportunities'],p['reference_opportunities'])
    def test_false_predicate_exact_parent_paths(self):
        rows,b=self.fixture()
        with patch.object(c,'additional_failure',return_value=False): v=self.run_child(rows,b)
        p=c.parent.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR)
        for k in ['trades','open_positions','events','trace','reference_events','reference_opportunities']:
            self.assertEqual(v[k],p[k],k)
    def test_disabled_matches_KR3_not_KR1_or_D(self):
        rows,b=self.fixture()
        self.assertEqual(c.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR,enabled=False),
                         c.parent.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR))
    def test_future_suffix_cannot_change_completed_trade(self):
        rows,b=self.fixture();a=self.run_child(rows,b)['trades']
        for r in rows[6:]:r.update(open=20.,close=20.,high=21.,low=19.)
        self.assertEqual(a,self.run_child(rows,b)['trades'])
    def test_pending_at_end_not_fabricated_as_close(self):
        rows,b=self.fixture(5);r=self.run_child(rows,b)
        self.assertFalse(r['trades']);self.assertEqual(len(r['open_positions']),1)
        self.assertIsNotNone(r['open_positions'][0]['pending_exit_signal_ts'])
    def test_timeout_precedes_new_same_bar_failure(self):
        rows,b=tiny();b['signals']=[b['signals'][0]]
        rows[3].update(low=97.,close=98.);b['ema50'][3]=97.
        rows[14].update(low=95.,close=96.);b['ema50'][14]=97.
        p=c.parent.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR)
        self.assertEqual(self.run_child(rows,b)['trades'],p['trades'])
    def test_all_origins_and_nonoverlap(self):
        rows,b=tiny();r=self.run_child(rows,b)
        self.assertEqual(len(r['events']),len(b['signals']))
        last=-1
        for t in r['trades']+r['open_positions']:
            self.assertGreater(t['signal_ts'],last);last=t.get('exit_ts',t.get('mark_ts'))
    def test_identical_class_parameters_and_hook_restored(self):
        rows,b=self.fixture();fn=c.parent.kr.path;self.run_child(rows,b)
        self.assertIs(c.parent.kr.path,fn);self.assertEqual(c.HOLD,12);self.assertEqual(c.BAR,14400000)
    def test_reference_clock_must_not_call_candidate_path(self):
        rows,b=tiny()
        with patch.object(c,'path',side_effect=AssertionError('FORBIDDEN')):
            clock=c.parent.parent.causal_clock(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR)
        self.assertTrue(clock['reference_events'])

if __name__=='__main__':unittest.main()
