"""Artificial data; timing, source checks, native predicate and lifecycle reuse."""
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
from backend.research.rebuild import jc_boundary_context_v1 as c
from backend.research.rebuild import jc_repaired_v1 as r
from backend.research.rebuild import jc_gate_probe_v1 as g
from backend.research.rebuild import jc_lifecycle_v1 as n
from backend.research.rebuild.test_jc_lifecycle_v1 import setup,COST
D=n.DAY;B=n.BAR

def days(count,start=0):return [n.f.Bar((start+i)*D,100,110,90,100,6) for i in range(count)]
def rows(count=12,start=0):return [dict(bar_open_ts=(start+i)*B,bar_close_ts=(start+i+1)*B,open=100.,high=110.,low=90.,close=100.,volume=1.) for i in range(count)]
def fixture():
 ds=days(370);ds[-1]=replace(ds[-1],high=120,close=105)
 features=(ds,[{'squeeze_on':True} for _ in ds],[100.]*370,[100.]*370,[5.]*370)
 piv=[dict(index=340+8*i,known_index=342+8*i,kind=k,price=p) for i,(k,p) in enumerate(zip(['HIGH','LOW','HIGH','LOW'],[120,80,118,90]))]
 piv[-1].update(index=367,known_index=369)
 return ds,features,piv

class BoundaryTests(unittest.TestCase):
 def test_scope_closure_does_not_revoke_new_scope(self):
  g.scope_guard(None);g.scope_guard(dict(scope=g.SCOPE,status='PREPARED_DIAGNOSTIC'))
  for state in (dict(scope=g.SCOPE,status='REPORT_ONLY'),dict(scope='OLD_COMPLETED',status='REPORT_ONLY')):
   with self.assertRaisesRegex(RuntimeError,'CLOSED'):g.scope_guard(state)
 def test_boundary_is_not_start_warmup(self):
  rs=rows(10,2);warm=days(369,-369);bridge=days(1)[0]
  self.assertEqual(len(c.asof_context(rs,warm,bridge,2*B,start=2*B)),369)
  self.assertEqual(len(c.asof_context(rs,warm,bridge,D-1,start=2*B)),369)
  self.assertEqual(len(c.asof_context(rs,warm,bridge,D,start=2*B)),370)
 def test_future_bad_values_and_gap_do_not_change_past(self):
  rs=rows(24);changed=deepcopy(rs);changed[19]['low']=-999;changed.pop(20)
  self.assertEqual(c.asof_context(rs,[],None,2*D,start=0),c.asof_context(changed,[],None,2*D,start=0))
 def test_future_gap_preserves_prior_prepare(self):
  ds=days(370);later=ds+days(5,372)
  with patch.object(r,'setup_at',side_effect=lambda d,i,f,t,**kw:dict(setup_ts=d[i].open_ts+D,pivots=[]) if i==364 else None):
   a=r.prepare(ds,.01,0,370*D,remove_extra_wait=False)
   b=r.prepare(later,.01,0,377*D,remove_extra_wait=False)
  self.assertEqual(a,b)
 def test_coverage_does_not_bridge_future_gap(self):
  result=c.coverage(days(370)+days(5,372),0,377*D)
  self.assertEqual(result['history_qualified_calendar_days'],5)
 def test_short_hype_history_stays_ineligible(self):
  self.assertEqual(c.coverage(days(364),0,364*D)['eligible_daily_decisions'],0)
  self.assertEqual(c.coverage(days(365),0,366*D)['first_eligible_decision'],365*D)
 def test_source_binding_and_exact_mismatch(self):
  rec=dict(sha256='x',symbol='TEST',url='https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol=TEST&interval=1d')
  raw=dict(code=0,data=[dict(time=0,open='100',high='110',low='90',close='100',volume='6')])
  _,receipt=c.bind_boundary(raw,rec,rows(4,2),2*B,raw_sha256='x')
  self.assertEqual(receipt['available_at'],D)
  for key,value in [('close','100.00000001'),('volume','3.99'),('high','109'),('low','91')]:
   changed=deepcopy(raw);changed['data'][0][key]=value
   with self.assertRaisesRegex(ValueError,'MISMATCH'):c.bind_boundary(changed,rec,rows(4,2),2*B,raw_sha256='x')
  with self.assertRaisesRegex(ValueError,'HASH'):c.bind_boundary(raw,rec,rows(4,2),2*B,raw_sha256='y')
 def test_wait_only_witness_native_parity(self):
  ds,features,piv=fixture()
  with patch.object(n.f,'confirmed_pivots',return_value=piv):
   row=g.observe(ds,369,features,.01)
   self.assertTrue(row['wait_only_witness']);self.assertIsNone(n.setup_at(ds,369,features,.01))
   self.assertIsNotNone(r.setup_at(ds,369,features,.01,remove_extra_wait=True))
   self.assertIsNone(r.setup_at(ds,369,features,.01,remove_extra_wait=False))
   piv[-1]['known_index']=370
   self.assertIsNone(r.setup_at(ds,369,features,.01,remove_extra_wait=True))
 def test_other_conditions_are_not_relaxed(self):
  ds,features,piv=fixture();features[1][-2]['squeeze_on']=False
  with patch.object(n.f,'confirmed_pivots',return_value=piv):
   self.assertFalse(g.observe(ds,369,features,.01)['wait_only_witness'])
   self.assertIsNone(r.setup_at(ds,369,features,.01,remove_extra_wait=True))
 def test_old_wait_pass_returns_identical_setup(self):
  ds,features,piv=fixture();piv[-1]['known_index']=367
  with patch.object(n.f,'confirmed_pivots',return_value=piv):
   self.assertEqual(n.setup_at(ds,369,features,.01),r.setup_at(ds,369,features,.01,remove_extra_wait=True))
 def test_signal_only_never_replays_or_charges(self):
  with patch.object(n,'replay',side_effect=AssertionError),patch.object(r,'replay',side_effect=AssertionError):
   out=g.probe(days(30),.01,0,30*D)
  self.assertEqual(out['original_setups'],0);self.assertEqual(out['native_boolean_parity_checked'],30)
 def test_execution_loop_preserves_parent_and_input(self):
  rs=rows(24);before=deepcopy(rs);s=setup();prepared={D:s}
  with patch.object(n,'prepare',return_value=prepared),patch.object(r,'prepare',return_value=deepcopy(prepared)):
   old=n.replay(rs,eval_start_ms=0,eval_end_ms=4*D,warmup_days=[],tick=.01,cost_model=COST)
   new=r.replay(rs,eval_start_ms=0,eval_end_ms=4*D,warmup_days=[],boundary_day=None,tick=.01,cost_model=COST,remove_extra_wait=False)
  self.assertEqual(rs,before)
  for key in ('campaigns','pending','events'):self.assertEqual(old[key],new[key])
 def test_terminal_setup_keeps_pending(self):
  with patch.object(r,'prepare',return_value={D:setup()}):
   out=r.replay(rows(6),eval_start_ms=0,eval_end_ms=D,warmup_days=[],boundary_day=None,tick=.01,cost_model=COST,remove_extra_wait=False)
  self.assertEqual(out['campaigns'],[]);self.assertEqual(out['pending'][0]['status'],'SETUP_AT_END_NO_NEXT_OPEN')
 def test_account_hook_restored_on_error(self):
  from backend.research.rebuild import jc_lifecycle_account_v1 as a
  old=a.marks._boundary
  with patch.object(a.p.old,'metrics',side_effect=RuntimeError('fixture')):
   with self.assertRaises(RuntimeError):a.metrics(dict(trades=[],open_observations=[]),dict(rows_by={},costs={}),{})
  self.assertIs(a.marks._boundary,old)

if __name__=='__main__':unittest.main()
