"""Artificial-price causal, cash-flow and occupancy acceptance tests."""
from copy import deepcopy
from dataclasses import replace
from math import fsum
from unittest.mock import patch
import unittest
from backend.research.rebuild import c63_c70_trader_management_v1 as e
from backend.research.rebuild import c63_c70_trader_account_v1 as a
from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture, rows_of

COST=dict(fee_bps=10.,spread_bps=1.,impact_bps=2.,funding_p95_per_settlement_bps=1.)
POLICY=dict(batch_id='SYNTHETIC',combined_data_sha256='SYNTHETIC',receipt_sha256='SYNTHETIC',
            code_files_sha256={},cost_binding_sha256='SYNTHETIC')


def fixture(n=150, ei=60):
    bars=[]
    for j in range(n):
        price=100. if j<ei else 100.+(j-ei+1)*.5
        op=100. if j<=ei else bars[-1].close
        bars.append(e.f.Bar(j*e.BAR,op,max(op,price)+1,min(op,price)-1,price,1.))
    signal=dict(signal_index=ei-1,signal_ts=ei*e.BAR,episode_start=ei-3,
                setup_id='SYNTHETIC:'+str(ei),floor=90.,target=None,expiry=None)
    return bars,signal,[dict(momentum=1.) for _ in bars]


def position(bars,s,features):
    return e.position(bars,s,'M1',features,len(bars)*e.BAR,COST)


class ManagementTests(unittest.TestCase):
    def test_third_UTC_day_and_next_open_partial(self):
        b,s,f=fixture();b[78]=replace(b[78],open=130.,high=131.)
        _,opened,trace=position(b,s,f)
        leg=opened['tm_legs'][0]
        self.assertEqual(leg['index'],78);self.assertEqual(leg['price'],130.)
        self.assertAlmostEqual(leg['qty'],1/3);self.assertAlmostEqual(opened['remaining_qty'],2/3)
        first=[x for x in trace if x.get('first_management')]
        self.assertEqual([x['index'] for x in first],[77])
        self.assertEqual(first[0]['daily_count'],3)
    def test_partial_entry_day_counts_only_at_complete_close(self):
        b,s,f=fixture(ei=62);_,o,t=position(b,s,f)
        self.assertEqual(o['tm_legs'][0]['index'],78)
        self.assertEqual([x['index'] for x in t if x.get('first_management')],[77])
    def test_no_profit_no_partial_and_no_late_retry(self):
        b,s,f=fixture()
        for j in range(60,78):b[j]=replace(b[j],open=100.,high=101.,low=99.,close=100.)
        _,o,t=position(b,s,f)
        self.assertEqual(o['partial_count'],0);self.assertFalse(o['runner_activated'])
        self.assertEqual(sum(x.get('first_management',False) for x in t),1)
    def test_cost_equality_is_not_profit(self):
        b,s,f=fixture();stamp=b[77].open_ts+e.BAR
        px=b[60].open*(1+e.cost_at(COST,b[60].open_ts,stamp)/10000)
        b[77]=replace(b[77],close=px,low=99.)
        with patch.object(e,'cost_at',return_value=(px/b[60].open-1)*10000):
            _,o,_=position(b,s,f)
        self.assertEqual(o['partial_count'],0)
    def test_floor_priority_at_partial_decision(self):
        b,s,f=fixture();s['floor']=b[77].close
        # Direct position isolates exit priority from the entry gap gate.
        c,o,t=position(b,s,f);self.assertEqual(c['partial_count'],0)
        self.assertEqual(c['exit_reason'],'FIXED_FLOOR_CLOSE_NEXT_OPEN')
    def test_native_momentum_before_partial(self):
        b,s,f=fixture();f[70]['momentum']=0.
        c,_,_=position(b,s,f);self.assertEqual(c['exit_index'],71)
        self.assertEqual(c['exit_reason'],'MOMENTUM_NONPOSITIVE_CLOSE_NEXT_OPEN')
    def test_source_runner_replaces_time_and_post_partial_momentum(self):
        b,s,f=fixture()
        for j in range(79,len(b)):f[j]['momentum']=-1.
        c,o,_=position(b,s,f)
        self.assertIsNone(c);self.assertTrue(o['runner_activated']);self.assertGreater(o['mark_index']-o['entry_index'],20)
    def test_native_floor_after_partial_precedes_runner(self):
        b,s,f=fixture();b[95]=replace(b[95],close=80.,low=79.)
        c,_,_=position(b,s,f)
        self.assertEqual(c['exit_reason'],'FIXED_FLOOR_CLOSE_NEXT_OPEN')
        self.assertEqual(c['exit_index'],96)
    def test_breakeven_close_uses_real_gap_open(self):
        b,s,f=fixture();b[95]=replace(b[95],close=99.,low=98.)
        b[96]=replace(b[96],open=85.,low=84.)
        c,_,_=position(b,s,f)
        self.assertEqual(c['exit_reason'],'RUNNER_BREAKEVEN_CLOSE_NEXT_OPEN')
        self.assertEqual(c['exit_price'],85.);self.assertEqual(c['tm_legs'][-1]['price'],85.)
    def test_dma_waits_completed_day_then_gap_open(self):
        b,s,f=fixture();b[130]=replace(b[130],close=110.,low=109.)
        b[131]=replace(b[131],close=110.,low=109.);b[132]=replace(b[132],open=107.,low=106.)
        c,_,t=position(b,s,f)
        self.assertEqual(c['exit_index'],132);self.assertEqual(c['exit_price'],107.)
        self.assertEqual(c['exit_reason'],'RUNNER_SMA10_CLOSE_NEXT_OPEN')
    def test_last_day_partial_pending_is_open_full_qty(self):
        b,s,f=fixture(n=78);c,o,t=position(b,s,f)
        self.assertIsNone(c);self.assertEqual(o['partial_count'],0);self.assertEqual(o['remaining_qty'],1.)
        self.assertEqual(o['pending_exit_trigger']['action'],'PARTIAL')
        self.assertFalse(o['terminal_liquidation'])
    def test_positive_D3_below_dma_still_records_partial_then_remainder(self):
        b,s,f=fixture()
        for j in range(60):b[j]=replace(b[j],open=150.,high=151.,low=149.,close=150.)
        c,_,_=position(b,s,f)
        self.assertEqual(c['exit_index'],78);self.assertEqual(c['partial_count'],1)
        self.assertEqual(c['exit_reason'],'D3_SMA10_SAFETY_CLOSE_NEXT_OPEN')
        self.assertAlmostEqual(fsum(l['qty'] for l in c['tm_legs']),1.)
    def test_future_mutation_prefix_and_daily_invariance(self):
        b,s,f=fixture();_,_,original=position(b,s,f);changed=deepcopy(b)
        for j in range(90,len(b)):changed[j]=replace(changed[j],open=50.,high=500.,low=1.,close=50.)
        _,_,mutated=position(changed,s,f)
        prefix=lambda t:[x for x in t if x['ts']<90*e.BAR]
        self.assertEqual(prefix(original),prefix(mutated))
        self.assertEqual(e.daily_observation(b,89),e.daily_observation(changed,89))
        _,_,truncated=position(b[:90],s,f[:90])
        self.assertEqual(prefix(original),prefix(truncated))
    def test_daily_missing_bar_rejected(self):
        b,_,_=fixture();del b[30]
        with self.assertRaises(ValueError):e.daily_observation(b,60)
    def test_OFF_exact_parent_synthetic(self):
        b=momentum_fixture();rows=rows_of(b)
        for parent in ('C63','C70_LOCAL'):
            kw=dict(parent=parent,eval_start_ms=0,eval_end_ms=len(b)*e.BAR)
            self.assertEqual(e.replay(rows,cost=COST,enabled=False,**kw),e.parent_replay(rows,**kw))
    def test_partial_does_not_release_slot(self):
        b,s,f=fixture();second=dict(s,signal_index=89,signal_ts=90*e.BAR,setup_id='SECOND')
        kw=dict(parent='C63',eval_start_ms=0,eval_end_ms=len(b)*e.BAR,cost=COST)
        with patch.object(e.native,'m1_setups',return_value=([s,second],[],f)),patch.object(e.c63,'context',return_value=dict(eligible=True,reason=None,range_context=dict(rescued=False))):
            out=e.replay(rows_of(b),**kw)
        self.assertEqual(out['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')
        self.assertEqual(len(out['open_positions']),1)
        self.assertTrue(any(x['kind']=='PARTIAL_FILL' and not x['slot_released'] for x in out['trace']))


class AccountingTests(unittest.TestCase):
    def test_partial_terminal_cash_funding_and_campaign_denominator(self):
        b,s,f=fixture(n=100);_,raw,_=position(b,s,f)
        packet=dict(policy=POLICY,costs={'TEST':COST},rows_by={'TEST':rows_of(b)})
        status,row=a.campaign(raw,'TEST','C63_TM',packet)
        self.assertEqual(status,'O');self.assertEqual(len(row['weighted_legs']),2)
        value=a.bridge._values((status,row))
        expected=fsum(l['qty']*((l['price']/100-1)*10000-e.cost_at(COST,60*e.BAR,l['ts'])) for l in raw['tm_legs'])
        self.assertAlmostEqual(value['net_bps'],expected)
        self.assertAlmostEqual(value['fee_bps'],10.)
        expected_funding=fsum(l['qty']*(l['ts']//(2*e.BAR)-30) for l in raw['tm_legs'])
        self.assertAlmostEqual(value['funding_bps'],expected_funding)
        self.assertAlmostEqual(value['gross_bps']-value['cost_bps'],value['net_bps'])
        self.assertAlmostEqual(value['gross_bps']-2*value['cost_bps'],value['cost2x_net_bps'])
    def test_campaign_metrics_and_marked_qty(self):
        b,s,f=fixture(n=100);_,raw,t=position(b,s,f)
        packet=dict(policy=POLICY,costs={'TEST':COST},rows_by={'TEST':rows_of(b)})
        result=a.charge({'TEST':dict(trades=[],open_positions=[raw],events=[],trace=t,audit={})},'C63_TM',packet,dict(start_ms=0,runoff_end_ms=len(b)*e.BAR))
        self.assertEqual(len(result['trades']),0);self.assertEqual(len(result['open_observations']),1)
        self.assertIsNone(result['metrics']['base_cost']['win_rate'])
        self.assertAlmostEqual(result['metrics']['daily'][-1]['cumulative_net_mark_bps'],result['metrics']['terminal_net_bps'])
    def test_full_close_two_legs_one_win(self):
        b,s,f=fixture();b[95]=replace(b[95],close=99.,low=98.)
        raw,_,t=position(b,s,f)
        packet=dict(policy=POLICY,costs={'TEST':COST},rows_by={'TEST':rows_of(b)})
        result=a.charge({'TEST':dict(trades=[raw],open_positions=[],events=[],trace=t,audit={})},'C63_TM',packet,dict(start_ms=0,runoff_end_ms=len(b)*e.BAR))
        self.assertEqual(len(result['trades']),1);self.assertEqual(len(result['trades'][0]['weighted_legs']),2)
        self.assertEqual(result['metrics']['base_cost']['win_rate'],1.)


if __name__=='__main__':unittest.main()
