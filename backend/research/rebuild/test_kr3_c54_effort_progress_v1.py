"""Artificial data only; preserved parent and causal participation tests."""
from copy import deepcopy
from unittest.mock import patch
import unittest
from backend.research.rebuild import kr3_c54_effort_progress_v1 as c
from backend.research.rebuild import test_kr3_c51_entry_context_v1 as fixtures
from backend.research.rebuild.test_kr3_profit_zone_exit_v1 import COST
class EffortTests(unittest.TestCase):
    def fixture(self):return fixtures.ContextTests().fixture()
    def call(self,r,b,s,e,**kw):return c.replay(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST,**kw)
    def part(self,vol=200,body=.5):
        r=[dict(open=100.,close=99.,volume=100.,bar_close_ts=(i+1)*c.BAR) for i in range(5)]
        r[4].update(volume=vol,close=100.+body)
        return c.participation(r,4,1)
    def test_high_volume_small_progress_veto(self):self.assertTrue(self.part()['veto'])
    def test_high_volume_good_progress_allowed(self):self.assertFalse(self.part(body=2)['veto'])
    def test_equal_volume_not_veto(self):self.assertFalse(self.part(vol=100)['veto'])
    def test_low_volume_not_veto(self):self.assertFalse(self.part(vol=50)['veto'])
    def test_equal_body_veto(self):self.assertTrue(self.part(body=1)['veto'])
    def test_negative_body_is_zero_bull_progress(self):self.assertTrue(self.part(body=-2)['veto'])
    def test_missing_episode_does_not_fake_pass(self):self.assertTrue(c.participation([],0,None)['veto'])
    def test_disabled_exact_C54(self):
        r,b,s,e,_=self.fixture();self.assertEqual(self.call(r,b,s,e,enabled=False),c.parent.replay(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST,mode='B'))
    def test_no_veto_keeps_full_paths_and_reference(self):
        r,b,s,e,_=self.fixture();p=self.call(r,b,s,e,enabled=False)
        with patch.object(c,'participation',return_value={'available':True,'veto':False,'reason':None}):out=self.call(r,b,s,e)
        for key in ('trades','open_positions','trace','reference_checkpoint','reference_events'):self.assertEqual(out[key],p[key])
    def test_veto_preserves_reference_and_signal_denominator(self):
        r,b,s,e,_=self.fixture();p=self.call(r,b,s,e,enabled=False)
        with patch.object(c,'participation',return_value={'available':True,'veto':True,'reason':c.VETO}):out=self.call(r,b,s,e)
        self.assertEqual(out['reference_checkpoint'],p['reference_checkpoint']);self.assertEqual(len(out['events']),len(p['events']))
        self.assertEqual(out['trades'],[]);self.assertEqual(out['open_positions'],[])
    def test_future_rows_not_read(self):
        r,b,s,e,i=self.fixture();o=c.participation(r,i,i-2);rr=deepcopy(r)
        for row in rr[i+1:]:row.update(volume=1e9,open=1000,close=500)
        self.assertEqual(o,c.participation(rr,i,i-2));self.assertEqual(o,c.participation(r[:i+1],i,i-2))
    def test_price_volume_rescaling_invariant(self):
        r,b,s,e,i=self.fixture();o=c.participation(r,i,i-2);rr=deepcopy(r)
        for row in rr:row.update(open=row['open']*10,close=row['close']*10,volume=row['volume']*1000)
        other=c.participation(rr,i,i-2);self.assertEqual(o['veto'],other['veto'])
        self.assertAlmostEqual(o['relative_volume'],other['relative_volume'])
    def test_zero_volume_unavailable(self):
        r,b,s,e,i=self.fixture()
        for row in r:row['volume']=0.
        self.assertFalse(c.participation(r,i,i-2)['available'])
    def test_input_and_hooks_unchanged_after_exception(self):
        r,b,s,e,i=self.fixture();original=deepcopy((r,b));o,a=c.parent.observations,c.parent.allowed
        with patch.object(c,'participation',side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'injected'):self.call(r,b,s,e)
        self.assertIs(o,c.parent.observations);self.assertIs(a,c.parent.allowed);self.assertEqual((r,b),original)
    def test_full_replay_repeat_checkpoint(self):
        r,b,s,e,i=self.fixture();out=self.call(r,b,s,e)
        self.assertEqual(out,self.call(r,b,s,e,reference_checkpoint=out['reference_checkpoint']))
    def test_missing_bar_rejected(self):
        r,b,s,e,i=self.fixture();r[12]['bar_open_ts']+=1
        with self.assertRaises(RuntimeError):self.call(r,b,s,e)
if __name__=='__main__':unittest.main()
