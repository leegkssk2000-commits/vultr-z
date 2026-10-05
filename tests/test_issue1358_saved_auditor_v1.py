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
                                 {'BTC-USDT':14},lambda *args:{'stop_price':98},lambda *args:{})
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
