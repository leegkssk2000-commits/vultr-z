"""Artificial prices only. No historical strategy replay, network or ledger slots."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import jc_lifecycle_v1 as e
from backend.research.rebuild import jc_lifecycle_account_v1 as a
from backend.research.rebuild import chart_mechanism_features_v1 as f
COST=dict(fee_bps=10.,spread_bps=2.,impact_bps=2.,funding_p95_per_settlement_bps=1.)

def setup(**kw):
 s=dict(setup_ts=e.DAY,setup_day_index=0,handle_ts=0,H=120.,L=80.,ema8=98.,ema21=94.,atr=5.,tick=.01,
        breakout=105.,targets=[119.99,130.88,144.72]);s.update(kw);return s

def pos():return e.new_campaign(setup(),5)
def bar(o=100,h=101,l=99,c=100,t=e.DAY):return f.Bar(t,o,h,l,c,1.)

class LifecycleTests(unittest.TestCase):
 def test_allocation(self):
  c=pos();e.add(c,.3,98.,e.DAY,6,'ema8');e.add(c,.4,94.,e.DAY,6,'ema21');e.open_point(c,106.,e.DAY+e.BAR,7)
  self.assertAlmostEqual(c['invested'],1.);self.assertFalse(c['adds']);self.assertEqual(c['first_fill_ts'],e.DAY)
 def test_invalid_stop_refuses(self):
  c=e.new_campaign(setup(atr=60.),5);e.add(c,.3,98.,e.DAY,6,'ema8');self.assertTrue(c['closed']);self.assertEqual(e.remaining(c),0)
 def test_stop_never_widens(self):
  c=pos();e.add(c,.3,100.,e.DAY,6,'ema8');old=c['stop'];e.add(c,.4,95.,e.DAY+e.BAR,7,'ema21');self.assertEqual(c['stop'],old)
 def test_gap_stop(self):
  c=pos();e.add(c,1.,100.,e.DAY,6,'x');c['adds']=False;e.open_point(c,80.,e.DAY+e.BAR,7)
  self.assertTrue(c['closed']);self.assertEqual(c['legs'][0]['exit_price'],80.)
 def test_no_chase(self):
  c=pos();e.open_point(c,125.,e.DAY,6);self.assertTrue(c['closed']);self.assertIsNone(c['first_fill_ts'])
 def test_gap_targets(self):
  c=pos();e.add(c,1.,100.,e.DAY,6,'x');c['adds']=False;e.open_point(c,140.,e.DAY+e.BAR,7)
  self.assertEqual(c['stage'],2);self.assertAlmostEqual(e.remaining(c),.01/3);self.assertEqual(c['stop'],90.);self.assertEqual(c['next_stop'],100.)
 def test_partial_quantity(self):
  c=pos();e.add(c,.3,100.,e.DAY,6,'x');e.target(c,119.99,e.DAY+e.BAR,7)
  self.assertAlmostEqual(c['snapshot_qty'],.003);self.assertFalse(c['adds']);self.assertAlmostEqual(sum(l['qty'] for l in c['legs'])+e.remaining(c),.003)
 def test_three_targets_one_campaign(self):
  c=pos();e.add(c,1.,100.,e.DAY,6,'x');c['adds']=False
  for px in c['setup']['targets']:e.target(c,px,e.DAY+e.BAR,7)
  self.assertTrue(c['closed']);self.assertEqual(len(c['legs']),3);self.assertAlmostEqual(sum(l['weight'] for l in c['legs']),1.)
 def test_conservative_feasible_path(self):
  c=pos();out=e.execute_bar(c,bar(o=100,h=125,l=85,c=110),6,COST)
  self.assertTrue(out['ambiguity']);self.assertLessEqual(out['ambiguity'][0]['conservative_mark_net'],out['ambiguity'][0]['alternative_mark_net']);self.assertTrue(out['closed'])
 def test_equal_limit_levels(self):
  c=e.new_campaign(setup(ema8=95.,ema21=95.),5);e.segment(c,100,94,e.DAY+e.BAR,6)
  self.assertAlmostEqual(c['invested'],.7)
 def test_checkpoint_72h_not18h(self):
  c=pos();e.add(c,.3,100.,e.DAY,6,'x');e.manage_close(c,bar(t=e.DAY+2*e.DAY-e.BAR),[],COST);self.assertFalse(c['checked72'])
  e.add(c,.4,100.,e.DAY+2*e.DAY,18,'y');e.manage_close(c,bar(t=e.DAY+3*e.DAY-e.BAR),[],COST)
  self.assertTrue(c['checked72']);self.assertTrue(c['pending_exit']);self.assertFalse(c['adds'])
 def test_checkpoint_equality(self):
  c=pos();e.add(c,1.,100.,e.DAY,6,'x')
  with patch.object(e,'liquidation_value',return_value=0.):e.manage_close(c,bar(t=4*e.DAY-e.BAR),[],COST)
  self.assertTrue(c['pending_exit'])
 def test_checkpoint_next_open_gap(self):
  c=pos();e.add(c,1.,100.,e.DAY,6,'x');c['adds']=False;c['pending_exit']=True;e.open_point(c,97.,4*e.DAY,24)
  self.assertEqual(c['legs'][0]['exit_price'],97.);self.assertEqual(c['fills'][-1]['kind'],'FAILED_PROGRESS_NEXT_OPEN')
 def test_trail_effective_next_bar(self):
  c=pos();e.add(c,1.,100.,e.DAY,6,'x');c['adds']=False;e.target(c,120.,2*e.DAY,12);e.target(c,131.,2*e.DAY,12)
  days=[f.Bar(i*e.DAY,110,120,105+i,115,1) for i in range(3)]
  e.manage_close(c,bar(t=3*e.DAY-e.BAR,o=115,h=116,l=114,c=115),days,COST)
  self.assertEqual(c['stop'],90.);self.assertAlmostEqual(c['next_stop'],104.99)
 def test_no_timeout_and_pending_boundary(self):
  c=pos();e.add(c,1.,100.,e.DAY,6,'x');c['adds']=False;c['checked72']=True
  for i in range(50):e.manage_close(c,bar(t=e.DAY+i*e.BAR,o=110,h=111,l=109,c=110),[],COST)
  self.assertFalse(c['closed']);self.assertFalse(c['pending_exit'])
 def test_daily_assembly_and_gap(self):
  bars=[bar(t=i*e.BAR) for i in range(7)];self.assertEqual(len(f.completed_utc_days(bars,7*e.BAR)),1)
  with self.assertRaises(ValueError):f.completed_utc_days(bars[:2]+bars[3:],7*e.BAR)
 def test_daily_squeeze_clock(self):
  days=[f.Bar(i*e.DAY,100,110,90,100,1) for i in range(30)]
  normalized,sq,*_=e.daily_features(days);self.assertTrue(sq[-1]['squeeze_on']);self.assertEqual(len(sq),30)
  self.assertIsNone(e.setup_at(days,29,e.daily_features(days),.01))
 def test_future_pivot_unavailable(self):
  bars=[f.Bar(i*e.BAR,100,120 if i==3 else 110,90,100,1) for i in range(7)]
  self.assertFalse(any(p['index']==3 for p in f.confirmed_pivots(bars,4)));self.assertTrue(any(p['index']==3 for p in f.confirmed_pivots(bars,5)))
 def test_warmup_invariant_and_new_order_activation(self):
  bars=[bar(t=i*e.BAR) for i in range(18)];rows=[dict(bar_open_ts=b.open_ts,bar_close_ts=b.open_ts+e.BAR,open=b.open,high=b.high,low=b.low,close=b.close,volume=b.volume) for b in bars];before=deepcopy(rows)
  s=setup(ema8=99.,ema21=98.)
  with patch.object(e,'prepare',return_value={e.DAY:s}):
   out=e.replay(rows,eval_start_ms=0,eval_end_ms=3*e.DAY,warmup_days=[],tick=.01,cost_model=COST)
  self.assertEqual(rows,before);self.assertTrue(out['campaigns']);self.assertGreaterEqual(out['campaigns'][0]['first_fill_ts'],e.DAY)
  with self.assertRaises(ValueError):e.replay(rows,eval_start_ms=0,eval_end_ms=3*e.DAY,warmup_days=[f.Bar(0,100,110,90,100,1)],tick=.01,cost_model=COST)
 def test_terminal_setup_is_pending(self):
  rows=[dict(bar_open_ts=i*e.BAR,bar_close_ts=(i+1)*e.BAR,open=100.,high=101.,low=99.,close=100.,volume=1.) for i in range(6)]
  with patch.object(e,'prepare',return_value={e.DAY:setup()}):out=e.replay(rows,eval_start_ms=0,eval_end_ms=e.DAY,warmup_days=[],tick=.01,cost_model=COST)
  self.assertEqual(out['campaigns'],[]);self.assertEqual(out['pending'][0]['status'],'SETUP_AT_END_NO_NEXT_OPEN')
 def test_occupancy_and_later_rearm(self):
  rows=[dict(bar_open_ts=i*e.BAR,bar_close_ts=(i+1)*e.BAR,open=100.,high=101.,low=99.,close=100.,volume=1.) for i in range(24)]
  with patch.object(e,'prepare',return_value={e.DAY:setup(ema8=99.),2*e.DAY:setup(setup_ts=2*e.DAY,handle_ts=e.DAY,ema8=99.)}):
   out=e.replay(rows,eval_start_ms=0,eval_end_ms=4*e.DAY,warmup_days=[],tick=.01,cost_model=COST)
  self.assertEqual(len(out['campaigns']),1);self.assertTrue(any(x['kind']=='OCCUPIED_SETUP' for x in out['events']))
 def test_money_and_count(self):
  c=pos();e.add(c,.3,100.,e.DAY,6,'x');e.add(c,.4,95.,e.DAY+e.BAR,7,'y');c['adds']=False
  for px in c['setup']['targets']:e.target(c,px,2*e.DAY,12)
  policy=dict(batch_id='SYNTHETIC',combined_data_sha256='SYNTHETIC',receipt_sha256='SYNTHETIC',code_files_sha256={},cost_binding_sha256='SYNTHETIC')
  packet=dict(policy=policy,costs={'TEST':COST},rows_by={'TEST':[]})
  status,row=a.campaign(c,'TEST',packet);self.assertEqual(status,'C');self.assertEqual(len(row['weighted_legs']),6)
  self.assertTrue(a.verify_money(dict(trades=[row],open_observations=[])))
  self.assertAlmostEqual(sum(l['numerator'] for l in row['weighted_legs']),.7)
  self.assertAlmostEqual(row['gross_bps']-row['cost_bps'],row['net_bps'])
 def test_open_cost_mark(self):
  c=pos();e.add(c,.3,100.,e.DAY,6,'x');e.target(c,119.99,2*e.DAY,12);c.update(mark_price=110.,mark_ts=3*e.DAY,mark_index=17)
  packet=dict(policy=dict(batch_id='SYNTHETIC',combined_data_sha256='SYNTHETIC',receipt_sha256='SYNTHETIC',code_files_sha256={},cost_binding_sha256='SYNTHETIC'),costs={'TEST':COST},rows_by={'TEST':[]})
  status,row=a.campaign(c,'TEST',packet);self.assertEqual(status,'O');self.assertTrue(a.verify_money(dict(trades=[],open_observations=[row])))

if __name__=='__main__':unittest.main()
