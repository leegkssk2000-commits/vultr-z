"""Synthetic tests for independent accounting, never a market replay."""
import unittest
import tempfile
from pathlib import Path
from ops import verify_squeeze_nonpositive_saved_v1 as a

class SavedArithmeticTests(unittest.TestCase):
    def rows(self):
        def r(t,g,s='BTC-USDT'):
            return {'symbol':s,'side':1,'identity':a.CHILD,'signal_ts_ms':a.START+t-1,
                    'exit_ts_ms':a.START+t,'outcome_available_ts_ms':a.START+t,'gross_bps':g,'cost_bps':14.}
        return [r(10,114),r(20,-36),r(20,34,'ETH-USDT'),r(30,-6)]
    def test_costs_expectancy_and_grouped_drawdown(self):
        m=a.metrics(self.rows(),1)
        self.assertEqual(m['T'],4);self.assertEqual(m['WR_pct'],50.)
        self.assertEqual(m['Net_bps'],50.);self.assertEqual(m['DD_bps'],50.)
        self.assertAlmostEqual(m['PF'],120/70)
    def test_stress_is_same_trades_and_cost_not_leverage(self):
        x=a.metrics(self.rows(),1);y=a.metrics(self.rows(),2)
        self.assertEqual(x['T'],y['T']);self.assertEqual(x['Gross_bps'],y['Gross_bps'])
        self.assertEqual(y['Net_bps'],x['Net_bps']-x['Cost_bps'])
    def test_exact_end_outcome_excluded(self):
        rs=self.rows();rs[0]['outcome_available_ts_ms']=a.END
        self.assertEqual(a.metrics(rs,1)['T'],3)
    def test_nonfinite_and_mismatch_rejected(self):
        for v in (float('nan'),float('inf'),1.):
            with self.assertRaises(AssertionError):a.close(v,0.)
    def test_bundle_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.xz';p.write_bytes(b'bad')
            with self.assertRaisesRegex(AssertionError,'BUNDLE_HASH'):a.unpack(p,'0'*64)


class ExitEvidenceTests(unittest.TestCase):
    def fixture(self):
        def row(symbol,signal,reason):
            return {'symbol':symbol,'side':1,'signal_ts_ms':signal,'entry_ts_ms':100,
                    'exit_ts_ms':300,'outcome_available_ts_ms':310,'entry_prices':{symbol:100.},
                    'exit_prices':{symbol:99.},'reason':reason,'gross_bps':-100.,'cost_bps':14.,
                    'net_bps':-114.,'signal_available_ms':90}
        r=row('DOGE-USDT',50,'SQUEEZE_OBSERVED_NONPOSITIVE_MOMENTUM_NEXT_OPEN')
        parent={'trades':[{**r,'reason':'MAX_HOLD_CLOCKED_OPEN','exit_ts_ms':900}]}
        event={'signal_key':f"{a.CHILD}|DOGE-USDT|50",'bar_open_ms':120,'input_ready_ms':290,
               'order_effective_ms':300,'update':{'reason':r['reason'],'exit_next_open':True,'observed_momentum':-.01}}
        child={'signals':[r.copy()],'trades':[r.copy()],'events':[event]}
        return parent,child
    def test_one_failure_event_links_exact_trade_exit(self):
        p,c=self.fixture();r=a.exit_evidence(p,c)
        self.assertEqual(len(r['failure_trade_event_links']),1)
        self.assertEqual(r['changed_trade_evidence_T'],1)
    def test_same_net_different_exit_is_not_unchanged(self):
        p,c=self.fixture();r=a.exit_evidence(p,c)
        self.assertEqual(r['equal_net_different_evidence_T'],1)
        self.assertEqual(r['identical_trade_evidence_T'],0)
    def test_event_exit_time_mismatch_rejected(self):
        p,c=self.fixture();c['events'][0]['order_effective_ms']=301
        with self.assertRaisesRegex(AssertionError,'EXIT_TIME'):a.exit_evidence(p,c)
    def test_event_reason_mismatch_rejected(self):
        p,c=self.fixture();c['trades'][0]['reason']='OTHER'
        with self.assertRaisesRegex(AssertionError,'TRADE_REASON'):a.exit_evidence(p,c)
    def test_unknown_event_signal_rejected(self):
        p,c=self.fixture();c['events'][0]['signal_key']='wrong'
        with self.assertRaisesRegex(AssertionError,'UNKNOWN_EVENT'):a.exit_evidence(p,c)
    def test_missing_or_duplicate_failure_event_rejected(self):
        for count in (0,2):
            p,c=self.fixture();c['events']=c['events']*count
            with self.subTest(count=count),self.assertRaisesRegex(AssertionError,'ONE_EVENT'):a.exit_evidence(p,c)
    def test_failure_event_requires_actual_completed_trade(self):
        p,c=self.fixture();c['trades']=[]
        with self.assertRaisesRegex(AssertionError,'WITHOUT_COMPLETED'):a.exit_evidence(p,c)

if __name__=='__main__':unittest.main()
