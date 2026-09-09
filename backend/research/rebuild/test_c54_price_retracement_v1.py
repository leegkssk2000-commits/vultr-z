from copy import deepcopy
from unittest.mock import patch
import unittest
from backend.research.rebuild import c54_price_retracement_v1 as c

class FeatureTests(unittest.TestCase):
    def fixture(self):
        # Confirmed low2/most recent high8, recovery12 after pre-pullback q8.
        prices=[102,101,100,104,110,120,115,116,117,113,110,111,114,115,116]
        rows=[dict(bar_open_ts=i*c.BAR,bar_close_ts=(i+1)*c.BAR,open=v,close=v,high=v+.5,low=v-.5) for i,v in enumerate(prices)]
        return rows,dict(signal_index=12,trend_index=8)
    def test_fib_signal_exists_without_volume(self):
        r,o=self.fixture();x=c.context(r,o,'FIB');self.assertTrue(x['eligible']);self.assertEqual(x['anchor']['low']['index'],2);self.assertEqual(x['anchor']['high']['index'],8)
    def test_volume_cannot_change_output(self):
        r,o=self.fixture();x=c.context(r,o,'FIB')
        for row in r:row['volume']='UNVERIFIED_DO_NOT_USE'
        self.assertEqual(x,c.context(r,o,'FIB'))
    def test_after_signal_cannot_change_context(self):
        r,o=self.fixture();x=c.context(r,o,'FIB')
        for row in r[13:]:row.update(close=100000,high=-5,low=0,open=0)
        self.assertEqual(x,c.context(r,o,'FIB'));self.assertEqual(x,c.context(r[:13],o,'FIB'))
    def test_signal_low_excluded_from_pullback(self):
        r,o=self.fixture();x=c.context(r,o,'FIB');r[12]['low']=1
        y=c.context(r,o,'FIB');self.assertEqual(x['depth'],y['depth']);self.assertEqual(x['anchor'],y['anchor'])
    def test_pivots_known_before_decision(self):
        r,o=self.fixture();x=c.context(r,o,'FIB');self.assertLessEqual(x['anchor']['known_at'],r[12]['bar_open_ts'])
    def test_no_anchor_rejects(self):
        r,o=self.fixture()
        for i,row in enumerate(r):row.update(open=100+i,close=100+i,high=100.5+i,low=99.5+i)
        self.assertFalse(c.context(r,o,'FIB')['eligible'])
    def test_no_episode_rejects(self):
        r,o=self.fixture();o['trend_index']=None;self.assertFalse(c.context(r,o,'FIB')['eligible'])
    def test_same_width_original_zones(self):
        self.assertAlmostEqual(.618-.382,.586-.350)
        for m,a,b in [('FIB',.382,.618),('SHIFTED',.350,.586)]:
            self.assertTrue(c.f.in_zone(a,m));self.assertTrue(c.f.in_zone(b,m));self.assertFalse(c.f.in_zone(a-1e-6,m));self.assertFalse(c.f.in_zone(b+1e-6,m))
    def test_shift_is_not_fib(self):
        self.assertFalse(c.f.in_zone(.36,'FIB'));self.assertTrue(c.f.in_zone(.36,'SHIFTED'))
        self.assertTrue(c.f.in_zone(.60,'FIB'));self.assertFalse(c.f.in_zone(.60,'SHIFTED'))
    def test_input_immutable(self):
        r,o=self.fixture();old=deepcopy((r,o));c.context(r,o,'FIB');self.assertEqual(old,(r,o))

class IntegrationTests(unittest.TestCase):
    def fixture(self):
        from backend.research.rebuild.test_kr3_c51_entry_context_v1 import ContextTests
        from backend.research.rebuild.test_kr3_profit_zone_exit_v1 import COST
        from backend.research.rebuild import kr3_c51_entry_context_v1 as p
        r,b,s,e,i=ContextTests().fixture();return r,b,dict(eval_start_ms=s,eval_end_ms=e,cost_model=COST),p
    def test_disabled_exact_C54(self):
        r,b,k,p=self.fixture();self.assertEqual(c.replay(r,b,enabled=False,**k),p.replay(r,b,mode='B',**k))
    def test_accept_all_same_paths_and_reference(self):
        r,b,k,p=self.fixture();parent=p.replay(r,b,mode='B',**k)
        for m in c.MODES:
            with patch.object(c,'context',return_value={'eligible':True,'reason':None}):x=c.replay(r,b,mode=m,**k)
            for field in ('trades','open_positions','trace','reference_events','reference_checkpoint'):self.assertEqual(x[field],parent[field])
    def test_reject_all_keeps_virtual_reservations(self):
        r,b,k,p=self.fixture();parent=p.replay(r,b,mode='B',**k)
        with patch.object(c,'context',return_value={'eligible':False,'reason':'NO_CONFIRMED_PRICE_ANCHOR'}):x=c.replay(r,b,**k)
        self.assertEqual(x['trades'],[]);self.assertEqual(x['open_positions'],[])
        self.assertEqual(x['reference_checkpoint'],parent['reference_checkpoint']);self.assertEqual(len(x['events']),len(parent['events']))
    def test_hooks_restored_after_error(self):
        r,b,k,p=self.fixture();old=(p.observations,p.allowed)
        with patch.object(c,'context',side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'injected'):c.replay(r,b,**k)
        self.assertEqual(old,(p.observations,p.allowed))
    def test_resume_keeps_original_reference(self):
        r,b,k,p=self.fixture();x=c.replay(r,b,**k);self.assertEqual(x,c.replay(r,b,reference_checkpoint=x['reference_checkpoint'],**k))
if __name__=='__main__':unittest.main()
