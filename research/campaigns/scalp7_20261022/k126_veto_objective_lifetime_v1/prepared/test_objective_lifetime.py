"""Synthetic decision-time tests; no market replay and no return selection."""
import sys,unittest,inspect,math
from pathlib import Path
from dataclasses import asdict
S=Path(__file__).resolve().parent
C=Path('/home/z/z/runtime/k126_c_veto_consume_20261022_v1/work_c_exact')
sys.path.insert(0,str(S));sys.path.insert(0,str(C));sys.path.insert(0,'/home/z/z/runtime/k126_pullback_structure_failure_20261021_v1')
import structural_failure as structure
from objective_lifetime import ObjectiveLifetime,build,IDENTITY
State=structure.h.positive.HolyGrailState

def row(t,side=1,hit=False):
 return {'feature_available_ts_ms':t,'close_ts_ms':t,'hi20':110.,'lo20':90.,'high':111. if hit and side==1 else 105.,'low':89. if hit and side==-1 else 95.}

def arm(side=1,hit=False):
 events=[];p=ObjectiveLifetime(events);s=State(side=side)
 b=asdict(s);s.stage=1;s.pull_low=95.;s.pull_high=105.
 p.after_native(b,s,None,row(1,side,hit),'TEST')
 return p,s,events

class Tests(unittest.TestCase):
 def test_long_target_frozen(self):
  p,s,e=arm();r=row(2);r['hi20']=200.;p.after_native(asdict(s),s,None,r,'TEST');self.assertEqual(p.target,110.)
 def test_short_target_frozen(self):
  p,s,e=arm(-1);r=row(2,-1);r['lo20']=1.;p.after_native(asdict(s),s,None,r,'TEST');self.assertEqual(p.target,90.)
 def test_no_veto_no_new_filter(self):
  p,s,e=arm();self.assertFalse(p.after_native(asdict(s),s,None,row(2,hit=True),'TEST'));self.assertEqual(s.stage,1)
 def test_known_veto_without_hit_retains(self):
  p,s,e=arm();self.assertFalse(p.rejected(s,row(1),'TEST',1,'TREND_COHERENT'));self.assertEqual(s.stage,1)
 def test_unknown_does_not_expire(self):
  p,s,e=arm(hit=True);self.assertFalse(p.rejected(s,row(1,hit=True),'TEST',1,'UNBOUND'));self.assertEqual(s.stage,1)
 def test_target_already_hit_first_known_veto(self):
  p,s,e=arm(hit=True);self.assertTrue(p.rejected(s,row(1,hit=True),'TEST',1,'COMPRESSION'));self.assertEqual(s.stage,0)
 def test_later_long_hit_expires(self):
  p,s,e=arm();p.rejected(s,row(1),'TEST',1,'TREND_COHERENT');self.assertTrue(p.after_native(asdict(s),s,None,row(2,hit=True),'TEST'));self.assertEqual(e[0]['expired_ts_ms'],2)
 def test_later_short_hit_expires(self):
  p,s,e=arm(-1);p.rejected(s,row(1,-1),'TEST',1,'TREND_COHERENT');self.assertTrue(p.after_native(asdict(s),s,None,row(2,-1,True),'TEST'))
 def test_same_bar_generated_event_not_consumed(self):
  p,s,e=arm();p.rejected(s,row(1),'TEST',1,'TREND_COHERENT');b=asdict(s);s.episode_traded=True
  self.assertTrue(p.after_native(b,s,(1,95.),row(2,hit=True),'TEST'));self.assertFalse(s.episode_traded)
 def test_accepted_trade_not_exited(self):
  p,s,e=arm();p.rejected(s,row(1),'TEST',1,'TREND_COHERENT');s.episode_traded=True
  self.assertFalse(p.after_native(asdict(s),s,None,row(2,hit=True),'TEST'));self.assertEqual(s.stage,1);self.assertEqual(e,[])
 def test_natural_reset_clears_ancestry(self):
  p,s,e=arm();p.rejected(s,row(1),'TEST',1,'TREND_COHERENT');b=asdict(s);s.reset();p.after_native(b,s,None,row(2),'TEST');self.assertIsNone(p.first_veto_ts)
 def test_weak_state_preserved_below_objective(self):
  p,s,e=arm();p.rejected(s,row(1),'TEST',1,'TREND_COHERENT');p.after_native(asdict(s),s,None,row(2),'TEST');self.assertEqual(s.stage,1)
 def test_new_touch_resets_objective(self):
  p,s,e=arm();p.rejected(s,row(1),'TEST',1,'TREND_COHERENT');s.event_reset();b=asdict(s);s.stage=1;r=row(2);r['hi20']=120.
  p.after_native(b,s,None,r,'TEST');self.assertEqual(p.target,120.);self.assertIsNone(p.first_veto_ts)
 def test_target_on_touch_known_only_at_close(self):
  p,s,e=arm(hit=True);self.assertEqual(p.first_hit_ts,1)
 def test_no_same_bar_touch_and_turn(self):
  p=ObjectiveLifetime([]);s=State(side=1);b=asdict(s);s.stage=1
  with self.assertRaises(ValueError):p.after_native(b,s,(1,95.),row(1),'TEST')
 def test_no_future_regime_decision(self):
  p,s,e=arm()
  with self.assertRaises(ValueError):p.rejected(s,row(1),'TEST',2,'TREND_COHERENT')
 def test_nonfinite_reference_rejected(self):
  p=ObjectiveLifetime([]);s=State(side=1);b=asdict(s);s.stage=1;r=row(1);r['hi20']=float('nan')
  with self.assertRaises(ValueError):p.after_native(b,s,None,r,'TEST')
 def test_rollback_clock_rejected(self):
  p,s,e=arm()
  with self.assertRaises(ValueError):p.after_native(asdict(s),s,None,row(0),'TEST')
 def test_disabled_identical_callable(self):
  c=structure.ExitComparison(True).build();self.assertIs(build(c,source_text=inspect.getsource(structure.h.k._fresh_touch_successor),enabled=False),c)
 def test_isolated_build_preserves_incumbent_scope(self):
  c=structure.ExitComparison(True).build();old=dict(c.__globals__);f=build(c,source_text=inspect.getsource(structure.h.k._fresh_touch_successor),enabled=True)
  self.assertEqual(f.candidate_identity,IDENTITY);self.assertEqual(c.__globals__,old)
 def test_source_drift_rejected(self):
  c=structure.ExitComparison(True).build()
  with self.assertRaises(ValueError):build(c,source_text=inspect.getsource(structure.h.k._fresh_touch_successor)+'\n',enabled=True)
 def test_no_outcomes_in_policy_inputs(self):
  self.assertEqual(list(inspect.signature(ObjectiveLifetime.after_native).parameters),['self','before','state','event','row','symbol'])

if __name__=='__main__':unittest.main(verbosity=2)
