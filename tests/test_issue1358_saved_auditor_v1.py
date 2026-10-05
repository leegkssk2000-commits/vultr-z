"""New audit-oracle integration uses synthetic input only."""
import copy
import unittest
from ops import issue1358_ema21_limit_v1 as model
from ops import verify_issue1358_ema21_saved_v1 as audit
from tests.test_issue1358_ema21_limit_v1 import fixture,signal,minute,M,T


class AuditTests(unittest.TestCase):
    def setUp(self):
        rows,frame,ready=fixture()
        rows[31]=minute(31*M,low=97)
        for row in rows:
            row[0]+=audit.START;row[6]+=audit.START
        for col in ('open_ts_ms','close_ts_ms','available_ts_ms'):
            frame[col]+=audit.START
        ready={k+audit.START:v+audit.START for k,v in ready.items()}
        self.data={'minutes':{s:copy.deepcopy(rows) for s in model.SYMBOLS}}
        # Raw receipt aggregation and fixture clock must agree; delay every
        # terminal minute by50ms to match ready clocks.
        for symbol in model.SYMBOLS:
            for i in (29,59,89,119):self.data['minutes'][symbol][i][6]+=50
        self.result=model.replay([signal(audit.START)],{'BTC-USDT':frame},self.data['minutes'],ready,
                                 {'BTC-USDT':14},lambda *args:{'stop_price':98},lambda *args:dict(exit_next_open=False,reason='POSITIVE_LIFECYCLE_HOLD'))
        self.parent={'signals':self.result['signals'],'trades':[]}
        self.summary={'identity':model.CHILD,'economic_lane_executions':1,'parent_replays':0,
                      'order_authority':'BLOCKED','live_orders':0,'unused_oos_certified':False,
                      'g5_promotion':False,'realtime_fill_certified':False,'account_nav':None,'paired':{}}
        self.result['paired']={}
        for mult in (1,2):
            label=str(mult)+'x'
            metrics=audit.metrics(self.result['trades'],mult)
            self.assertAlmostEqual(metrics['Gross_bps'],-200)
            self.assertAlmostEqual(metrics['Cost_bps'],14*mult)
            self.parent['reference'+label]=audit.metrics([],mult)
            self.result['reference'+label]=metrics
            self.summary['reference'+label]=metrics
            self.summary['baseline_reference'+label]=self.parent['reference'+label]
            pair=dict(common_T=0,child_only_T=1,parent_only_T=0,harmed_T=0,improved_T=0,
                      parent_winners_harmed_T=0,common_delta_bps=0,new_opportunities_net_bps=metrics['Net_bps'],
                      missing_opportunities_contribution_bps=0,total_net_delta_bps=metrics['Net_bps'])
            self.result['paired'][label]=pair;self.summary['paired'][label]=pair
        self.contract={'reference_costs_bps':{'BTC-USDT':14}}

    def run_audit(self):
        return audit.audit(self.result,self.summary,self.data,self.parent,self.contract)

    def test_independent_loss_cost_and_census_oracle(self):
        report=self.run_audit()
        self.assertEqual(report['disposition'],'REJECT_NOT_COST_PROFITABLE')
        self.assertEqual(report['fills'],1)
        self.assertAlmostEqual(report['metrics']['1x']['Net_bps'],-214)
        self.assertAlmostEqual(report['metrics']['2x']['DD_bps'],228)

    def rebuild(self,stop_index=None,gap=False,long=False):
        import pandas as pd
        from tests.test_issue1358_ema21_limit_v1 import minute
        count=400 if long else 130
        rows=[minute(audit.START+i*M,low=99 if i==31 else 101) for i in range(count)]
        if stop_index is not None:
            rows[stop_index]=minute(audit.START+stop_index*M,low=96 if gap else 97,opening=97 if gap else 102)
        for i in range(29,count,30):rows[i][6]+=50
        self.data={'minutes':{s:copy.deepcopy(rows) for s in model.SYMBOLS}}
        frame=pd.DataFrame([dict(open_ts_ms=audit.START+i*T,close_ts_ms=audit.START+(i+1)*T,
                    open=102,high=103,low=101,close=102,available_ts_ms=audit.START+(i+1)*T+50)
                    for i in range(count//30)])
        ready=audit.receipt_clock(self.data)
        self.result=model.replay([signal(audit.START)],{'BTC-USDT':frame},self.data['minutes'],ready,
                {'BTC-USDT':14},lambda *args:{'stop_price':98},
                lambda *args:dict(exit_next_open=False,reason='POSITIVE_LIFECYCLE_HOLD'))
        self.parent['signals']=self.result['signals']
        self.refresh_accounting()

    def refresh_accounting(self):
        self.result['paired']={}
        for mult in (1,2):
            label=str(mult)+'x';m=audit.metrics(self.result['trades'],mult)
            self.result['reference'+label]=m;self.summary['reference'+label]=m
            pair=dict(common_T=0,child_only_T=len(self.result['trades']),parent_only_T=0,harmed_T=0,improved_T=0,
                    parent_winners_harmed_T=0,common_delta_bps=0,new_opportunities_net_bps=m['Net_bps'],
                    missing_opportunities_contribution_bps=0,total_net_delta_bps=m['Net_bps'])
            self.result['paired'][label]=pair;self.summary['paired'][label]=pair

    def forge_price(self):
        r=self.result['trades'][0];r['exit_prices']['BTC-USDT']=103
        r['gross_bps']=300;r['net_bps']=286
        self.refresh_accounting()

    def test_later_stop_and_gap_verified(self):
        for gap in (False,True):
            self.rebuild(40,gap);self.run_audit()
            self.forge_price()
            with self.assertRaises(AssertionError):self.run_audit()

    def test_later_exit_clock_and_reason_tamper(self):
        for field,value in [('reason','MAX_HOLD_CLOCKED_OPEN'),('exit_ts_ms',audit.START+45*M),
                            ('outcome_available_ts_ms',audit.START+46*M)]:
            self.rebuild(40);self.result['trades'][0][field]=value;self.refresh_accounting()
            with self.assertRaises(AssertionError):self.run_audit()

    def test_management_max_hold_price_and_missing_decision(self):
        self.rebuild(long=True);self.run_audit()
        self.forge_price()
        with self.assertRaises(AssertionError):self.run_audit()
        self.rebuild(long=True)
        self.result['events']=[e for e in self.result['events'] if e['kind']!='MANAGEMENT']
        with self.assertRaises(AssertionError):self.run_audit()

    def test_unresolved_cannot_hide_later_stop(self):
        self.rebuild();self.run_audit()
        self.data['minutes']['BTC-USDT'][40][3]=97
        with self.assertRaises(AssertionError):self.run_audit()

    def test_forged_management_policy_is_rejected(self):
        self.rebuild(long=True)
        e=next(e for e in self.result['events'] if e['kind']=='MANAGEMENT')
        e['update']=dict(exit_next_open=True,reason='SQUEEZE_TWO_WEAK_MOMENTUM_NEXT_OPEN')
        with self.assertRaises(AssertionError):self.run_audit()

    def test_stdlib_momentum_matches_native_on_synthetic_bars(self):
        import pandas as pd
        from backend.research.rebuild.scalp7_positive_lanes_v2 import _last_momenta
        bars=[dict(open_ts_ms=i*T,high=101+i*.4,low=99+i*.4,close=100+i*.4-i*i*.002) for i in range(60)]
        native=_last_momenta(pd.DataFrame(bars))
        expected=bool(native[2]>0 and native[1]>0 and native[2]<native[1]<native[0])
        self.assertEqual(audit.expected_update(bars,0)['exit_next_open'],expected)


    def test_optimistic_price_tamper_is_rejected(self):
        self.result['trades'][0]['entry_prices']['BTC-USDT']=99
        with self.assertRaises(AssertionError):self.run_audit()

    def test_missing_census_opportunity_is_rejected(self):
        self.result['census']=[]
        with self.assertRaises(AssertionError):self.run_audit()

    def test_fabricated_earlier_fill_is_rejected(self):
        self.result['census'][0]['order']['fill']['minute_open_ms']-=M
        with self.assertRaises(AssertionError):self.run_audit()


if __name__=='__main__':
    unittest.main()
