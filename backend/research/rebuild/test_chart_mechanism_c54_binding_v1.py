"""Full repository C54/cost integration; artificial candles only."""
from copy import deepcopy
from unittest.mock import patch
import unittest
from backend.research.rebuild import chart_mechanism_execution_v1 as c
from backend.research.rebuild import chart_mechanism_integration_v1 as integration
from backend.research.rebuild import kr3_c51_entry_context_v1 as parent
from backend.research.rebuild import test_kr3_c51_entry_context_v1 as fixtures
from backend.research.rebuild.test_kr3_profit_zone_exit_v1 import COST
from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,soup_fixture,rows_of
BINDING=dict(basis='BASE_VOLUME',source_ref='SYNTHETIC_ONLY',source_sha256='a'*64)
class BindingTests(unittest.TestCase):
    def fixture(self):return fixtures.ContextTests().fixture()
    def call(self,r,b,s,e,variant='T1',**kwargs):
        return c.replay_trend(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST,variant=variant,volume_binding=BINDING,**kwargs)
    def test_disabled_all_three_exact_C54(self):
        r,b,s,e,_=self.fixture();p=parent.replay(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST,mode='B')
        for v in ('T1','F1','F0'):self.assertEqual(self.call(r,b,s,e,v,enabled=False),p)
    def test_accept_all_same_fills_exits_cost_state_and_reference(self):
        r,b,s,e,_=self.fixture();p=parent.replay(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST,mode='B');self.assertTrue(p['trades'])
        for v in ('T1','F1','F0'):
            with patch.object(c,'trend_context',return_value=dict(eligible=True,reason=None)):out=self.call(r,b,s,e,v)
            for k in ('trades','open_positions','trace','reference_events','reference_checkpoint'):self.assertEqual(out[k],p[k])
    def test_veto_keeps_reference_and_denominator(self):
        r,b,s,e,_=self.fixture();p=self.call(r,b,s,e,enabled=False)
        with patch.object(c,'trend_context',return_value=dict(eligible=False,reason='AVWAP_CONTEXT_VETO')):out=self.call(r,b,s,e)
        self.assertFalse(out['trades']);self.assertFalse(out['open_positions']);self.assertEqual(len(p['events']),len(out['events']))
        self.assertEqual(p['reference_checkpoint'],out['reference_checkpoint'])
    def test_hook_and_inputs_restored_after_exception(self):
        r,b,s,e,_=self.fixture();before=deepcopy((r,b));o,a=parent.observations,parent.allowed
        with patch.object(c,'trend_context',side_effect=RuntimeError('synthetic')):
            with self.assertRaisesRegex(RuntimeError,'synthetic'):self.call(r,b,s,e)
        self.assertIs(o,parent.observations);self.assertIs(a,parent.allowed);self.assertEqual(before,(r,b))
    def test_unknown_volume_refuses_only_trend_lane(self):
        r,b,s,e,_=self.fixture()
        with self.assertRaises(c.UnverifiedVolume):c.replay_trend(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST)
    def test_reference_checkpoint_reapplication(self):
        r,b,s,e,_=self.fixture()
        with patch.object(c,'trend_context',return_value=dict(eligible=True,reason=None)):
            out=self.call(r,b,s,e);again=self.call(r,b,s,e,reference_checkpoint=out['reference_checkpoint'])
        self.assertEqual(out,again)
    def test_unfinished_parent_tail_remains_tail(self):
        r,b,s,e,i=self.fixture();r=r[:i+3];b={k:(v[:i+3] if k in ('ema20','ema50') else v) for k,v in b.items()};e=len(r)*c.BAR
        with patch.object(c,'trend_context',return_value=dict(eligible=True,reason=None)):out=self.call(r,b,s,e)
        self.assertEqual(out['open_positions'],self.call(r,b,s,e,enabled=False)['open_positions'])
    def test_independent_complete_and_open_cost_binding(self):
        for variant,cases in [('M1',[momentum_fixture(),momentum_fixture(33)]),('R1',[soup_fixture(),soup_fixture(22)])]:
            for bars in cases:
                rows=rows_of(bars);end=len(rows)*c.BAR;raw=c.replay_independent(rows,eval_start_ms=0,eval_end_ms=end,variant=variant)
                packet=dict(rows_by={'TEST-USDT':rows},costs={'TEST-USDT':COST},policy={'batch_id':'SYNTHETIC','combined_data_sha256':'a'*64,'receipt_sha256':'b'*64,'code_files_sha256':{},'cost_binding_sha256':'c'*64})
                result=integration.charge_and_mark({'TEST-USDT':raw},variant,packet,{'start_ms':0,'runoff_end_ms':end})
                self.assertEqual(len(result['trades']),len(raw['trades']));self.assertEqual(len(result['open_observations']),len(raw['open_positions']))
                for t in result['trades']:
                    self.assertAlmostEqual(t['net_bps'],t['gross_bps']-t['cost_bps']);self.assertAlmostEqual(t['cost2x_net_bps'],t['gross_bps']-2*t['cost_bps']);self.assertGreaterEqual(t['cost_bps'],20.)
                self.assertAlmostEqual(result['metrics']['terminal_net_bps'],sum(t['net_bps'] for t in result['trades'])+sum(t['hypothetical_liquidation_net_mark_bps'] for t in result['open_observations']))
if __name__=='__main__':unittest.main()
