"""Generated inputs only; these tests never replay collected market prices."""
import copy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from ops import scalp7_clocked_execution_v1 as m


def sample():
    rows=[[t,100,100.1,99.9,100,1,t+60001,0,'test'] for t in range(0,150*m.MINUTE,m.MINUTE)]
    frame=pd.DataFrame([{'open_ts_ms':t,'close_ts_ms':t+m.TF,'available_ts_ms':t+m.TF+61000,
                        'open':100.,'high':100.1,'low':99.9,'close':100.,'volume':1.,'segment_id':0}
                       for t in range(0,150*m.MINUTE,m.TF)])
    ready={int(r.open_ts_ms):int(r.available_ts_ms) for r in frame.itertuples()}
    signal={'identity':m.PARENT,'lane':'squeeze_break','symbol':'BTC-USDT','side':1,
            'timeframe_min':30,'signal_open_ts_ms':0,'signal_ts_ms':m.TF,
            'stop_price':98.,'max_hold_bars':1,'take_profit_r':None,
            'meta':{'regime':'PANIC_DISPERSION','frozen_cost_bps':14.,'atr_price':2.,
                    'entry_cost_gate':{'atr_price':2.,'min_ratio':4.},'fallback_stop_atr_mult':2.,'be_arm_r':None}}
    return signal,frame,rows,ready


def admit(s,p):return {'stop_price':s['stop_price']}
def hold(p,b,h):return {'exit_next_open':False}


class ClockedTests(unittest.TestCase):
    def call(self,modify=None,callback=hold):
        s,f,rows,r=sample()
        if modify:modify(s,f,rows,r)
        return m.simulate(s,f,rows,r,14.,admit,callback)

    def test_strict_next_minute(self):
        self.assertEqual(m.next_minute(60000),120000)
        self.assertEqual(m.next_minute(61000),120000)
        with self.assertRaises(Exception):m.next_minute(True)

    def test_delayed_entry_and_full_postentry_bar(self):
        trade,_,_,why,events=self.call()
        self.assertIsNone(why)
        self.assertEqual(trade['entry_ts_ms'],32*m.MINUTE)
        self.assertEqual(trade['exit_ts_ms'],92*m.MINUTE)
        self.assertEqual(events[0]['bar_open_ms'],60*m.MINUTE)
        self.assertGreater(trade['entry_ts_ms'],trade['signal_available_ms'])

    def test_stale_signal(self):
        x=self.call(lambda s,f,rows,r:r.update({0:60*m.MINUTE}))
        self.assertEqual(x[3],'STALE_SIGNAL_ONE_DECISION_BAR')

    def test_no_entry_body(self):
        x=self.call(lambda s,f,rows,r:rows.__delitem__(slice(31,None)))
        self.assertEqual(x[3],'NO_POST_AVAILABILITY_MINUTE')

    def test_stop_before_first_callback(self):
        x=self.call(lambda s,f,rows,r:rows[40].__setitem__(3,97.))
        self.assertEqual(x[0]['exit_prices']['BTC-USDT'],98.)
        self.assertEqual(x[4],[])

    def test_gap_stop_uses_worse_open(self):
        def change(s,f,rows,r):rows[40][1:5]=[97.,97.5,96.5,97.]
        x=self.call(change)
        self.assertEqual(x[0]['exit_prices']['BTC-USDT'],97.)
        self.assertEqual(x[0]['exit_ts_ms'],40*m.MINUTE)

    def test_no_preentry_high_for_mfe(self):
        observed=[]
        def cb(p,b,h):observed.append(p['mfe_R']);return hold(p,b,h)
        self.call(lambda s,f,rows,r:rows[31].__setitem__(2,1000.),cb)
        self.assertAlmostEqual(observed[0],.05)

    def test_future_price_not_in_callback(self):
        observed=[]
        def cb(p,b,h):observed.append(p['mfe_R']);return hold(p,b,h)
        self.call(lambda s,f,rows,r:rows[91].__setitem__(2,1000.),cb)
        self.assertAlmostEqual(observed[0],.05)

    def test_stop_update_cannot_backdate(self):
        def cb(p,b,h):return {'next_stop':100.2,'exit_next_open':False}
        def change(s,f,rows,r):s['max_hold_bars']=20
        x=self.call(change,cb)
        self.assertEqual(x[0]['entry_ts_ms'],32*m.MINUTE)
        self.assertEqual(x[0]['exit_ts_ms'],92*m.MINUTE)
        self.assertEqual(x[0]['exit_prices']['BTC-USDT'],100.)

    def test_callback_requires_received_position_prefix(self):
        with self.assertRaisesRegex(Exception,'POSITION_PREFIX'):
            self.call(lambda s,f,rows,r:rows[70].__setitem__(6,200*m.MINUTE))

    def test_exit_uses_current_not_old_open(self):
        def change(s,f,rows,r):rows[92][1:5]=[102.,102.1,101.9,102.]
        x=self.call(change,lambda p,b,h:{'exit_next_open':True,'reason':'CAUSAL_EXIT'})
        self.assertEqual(x[0]['exit_prices']['BTC-USDT'],102.)
        self.assertAlmostEqual(x[0]['net_bps'],186.)

    def test_unresolved_never_force_closes(self):
        x=self.call(lambda s,f,rows,r:s.update(max_hold_bars=100))
        self.assertIsNone(x[0]);self.assertIsNotNone(x[1]);self.assertEqual(x[2],2**63-1)

    def test_partial_profile_rejects(self):
        with self.assertRaisesRegex(Exception,'UNSUPPORTED_ORDER'):
            self.call(lambda s,f,rows,r:s.update(partial_take_profit_r=2.))

    def test_partial_callback_rejects(self):
        with self.assertRaisesRegex(Exception,'UNSUPPORTED_PARTIAL'):
            self.call(callback=lambda p,b,h:{'partial_fraction':.1})

    def test_callback_cannot_mutate(self):
        def cb(p,b,h):p['initial_risk']=10;return {}
        with self.assertRaisesRegex(Exception,'CALLBACK_MUTATED'):
            self.call(callback=cb)

    def test_no_favorable_initial_stop(self):
        with self.assertRaisesRegex(Exception,'ADVERSE_INITIAL_STOP'):
            self.call(lambda s,f,rows,r:s.update(stop_price=101.))

    def test_other_symbol_and_earlier_input_clock(self):
        clocks={s:{0:4*m.TF,m.TF:2*m.TF+1} for s in m.SYMBOLS}
        clocks['ETH-USDT'][0]=5*m.TF
        out=m.prefix_clocks(clocks)
        self.assertEqual(out[m.TF],5*m.TF)
        del clocks['ETH-USDT'][0]
        with self.assertRaisesRegex(Exception,'CLOCK_GRID'):m.prefix_clocks(clocks)

    def test_invalid_minute_gaps_and_nan(self):
        for bad in ('gap','nan'):
            _,_,rows,_=sample()
            if bad=='gap':del rows[5]
            else:rows[5][2]=float('nan')
            with self.subTest(bad=bad),self.assertRaises(Exception):m.verify_minute_rows(rows)

    def test_native_squeeze_callback_connected(self):
        from backend.research.rebuild import scalp7_positive_lanes_v2 as native
        s,f,rows,r=sample()
        result=m.simulate(s,f,rows,r,14.,native.entry_update,native.exit_update)
        self.assertEqual(result[0]['reason'],'MAX_HOLD_CLOCKED_OPEN')
        self.assertEqual(s['signal_ts_ms'],m.TF)

    def test_native_cost_gate_still_applies(self):
        from backend.research.rebuild import scalp7_positive_lanes_v2 as native
        s,f,rows,r=sample();s['meta']['entry_cost_gate']['atr_price']=.01
        result=m.simulate(s,f,rows,r,14.,native.entry_update,native.exit_update)
        self.assertEqual(result[3],'ENTRY_ATR_COST_GATE')

class ReservationTests(unittest.TestCase):
    def setup_claim(self, root):
        return ({'batch_id':m.BATCH,'execution_owner_sha256':'owner'},
                {'batch_id':m.BATCH,'contract_sha256':'a'*64})

    def test_atomic_concurrent_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'shared'; c,a=self.setup_claim(root)
            with patch.object(m,'CLAIM_ROOT',root),patch.object(m,'owner_fingerprint',return_value='owner'):
                def attempt(i):
                    try:m.acquire_reservation(c,a,Path(tmp)/str(i));return 1
                    except FileExistsError:return 0
                with ThreadPoolExecutor(max_workers=8) as pool:
                    self.assertEqual(sum(pool.map(attempt,range(8))),1)
            self.assertTrue((root/(m.BATCH+'.json')).exists())

    def test_different_output_after_failure_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'shared'; c,a=self.setup_claim(root)
            with patch.object(m,'CLAIM_ROOT',root),patch.object(m,'owner_fingerprint',return_value='owner'):
                m.acquire_reservation(c,a,Path(tmp)/'failed-output')
                with self.assertRaises(FileExistsError):
                    m.acquire_reservation(c,a,Path(tmp)/'retry-other-output')

    def test_wrong_host_before_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'shared';c,a=self.setup_claim(root)
            with patch.object(m,'CLAIM_ROOT',root),patch.object(m,'owner_fingerprint',return_value='other'):
                with self.assertRaisesRegex(Exception,'WRONG_EXECUTION_OWNER'):
                    m.acquire_reservation(c,a,Path(tmp)/'output')
                self.assertFalse(root.exists())

    def test_new_contract_hash_does_not_replenish_same_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'shared';c,a=self.setup_claim(root)
            with patch.object(m,'CLAIM_ROOT',root),patch.object(m,'owner_fingerprint',return_value='owner'):
                m.acquire_reservation(c,a,Path(tmp)/'one')
                a['contract_sha256']='b'*64
                with self.assertRaises(FileExistsError):m.acquire_reservation(c,a,Path(tmp)/'two')

if __name__=='__main__':unittest.main()
