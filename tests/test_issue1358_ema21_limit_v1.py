"""Synthetic only: clocks, conservative paths, census and durable order state."""
import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import pandas as pd

from ops import issue1358_ema21_limit_v1 as m

M,T = m.MINUTE,m.TF


def minute(t,low=101,opening=102,high=103,received=None):
    return [t,opening,high,low,opening,0,t+M if received is None else received,0,0]


def signal(opened=0):
    return dict(identity=m.PARENT,lane='SQUEEZE',symbol='BTC-USDT',side=1,timeframe_min=30,
                signal_open_ts_ms=opened,signal_ts_ms=opened+T,stop_price=98,
                max_hold_bars=11,take_profit_r=None,meta=dict(atr_price=1,regime='PANIC_DISPERSION',be_arm_r=None))


def fixture(low_at=None):
    rows=[minute(i*M,low=99 if i==low_at else 101) for i in range(130)]
    frame=pd.DataFrame([dict(open_ts_ms=i*T,close_ts_ms=(i+1)*T,open=102,high=103,low=101,close=102,
                             available_ts_ms=(i+1)*T+50) for i in range(4)])
    ready={i*T:(i+1)*T+50 for i in range(4)}
    return rows,frame,ready


class OrderTests(unittest.TestCase):
    def new(self):
        return m.LimitOrder('episode',T+50,31*M,2*T,100)

    def test_before_create_and_effective_touch_never_fills(self):
        order=self.new()
        self.assertIsNone(order.tick(minute(29*M,low=99)))
        self.assertIsNone(order.tick(minute(30*M,low=99)))
        self.assertIsNotNone(order.tick(minute(31*M,low=99)))

    def test_expiry_before_touch(self):
        order=self.new()
        self.assertIsNone(order.tick(minute(60*M,low=90)))
        self.assertEqual(order.state['status'],'EXPIRED_UNFILLED')
        self.assertIsNone(order.tick(minute(61*M,low=90)))

    def test_cancel_and_resume_cannot_fill(self):
        order=self.new(); order.cancel(31*M)
        restored=m.LimitOrder.restore(order.snapshot())
        self.assertIsNone(restored.tick(minute(32*M,low=90)))
        self.assertEqual(restored.state['status'],'CANCELLED')

    def test_restart_pending_and_filled_dedup(self):
        order=self.new(); order.tick(minute(31*M))
        resumed=m.LimitOrder.restore(order.snapshot())
        self.assertIsNone(resumed.tick(minute(31*M,low=90)))
        self.assertIsNotNone(resumed.tick(minute(32*M,low=99)))
        filled=m.LimitOrder.restore(resumed.snapshot())
        self.assertIsNone(filled.tick(minute(32*M,low=99)))
        self.assertIsNone(filled.tick(minute(33*M,low=99)))
        self.assertEqual(filled.snapshot(),resumed.snapshot())

    def test_cancelled_full_minute_sequence_negative_control(self):
        order=self.new();order.tick(minute(30*M,low=99));order.cancel(30*M+100)
        order=m.LimitOrder.restore(order.snapshot())
        fills=[order.tick(minute(i*M,low=90)) for i in range(31,70)]
        self.assertEqual(sum(x is not None for x in fills),0)


class IntegratedTests(unittest.TestCase):
    def run_one(self,rows,frame,ready,s=None,callback=lambda *args:{}):
        return m.sim…364 tokens truncated…self.run_one(rows,frame,ready)
        self.assertIsNone(row);self.assertIsNone(position)
        self.assertEqual(census['status'],'REJECTED_STALE')

    def test_incomplete_signal_bar_rejected(self):
        rows,frame,ready=fixture(31);ready[0]=29*M
        with self.assertRaisesRegex(Exception,'INCOMPLETE_SIGNAL_BAR'):
            self.run_one(rows,frame,ready)

    def test_management_excludes_entry_bar_and_unreceived_information(self):
        rows,frame,ready=fixture(31)
        ready[2*T]=101*M-50
        ready[3*T]=121*M-50
        called=[]
        def cb(position,bar,history):
            called.append(int(bar['open_ts_ms']))
            self.assertGreaterEqual(int(bar['open_ts_ms']),position['entry_ts_ms']+M)
            self.assertEqual(history.iloc[-1]['open_ts_ms'],bar['open_ts_ms'])
            return {'exit_next_open':True,'reason':'FIXTURE_EXIT'}
        row,_,_,_,trace=self.run_one(rows,frame,ready,callback=cb)
        self.assertEqual(called,[2*T])
        self.assertEqual(row['exit_ts_ms'],101*M)
        management=[e for e in trace if e['kind']=='MANAGEMENT']
        self.assertGreater(management[0]['order_effective_ms'],management[0]['input_ready_ms'])

    def test_unreceived_post_entry_prefix_fails_closed(self):
        rows,frame,ready=fixture(31)
        rows[61][6]=200*M
        with self.assertRaisesRegex(Exception,'UNRECEIVED_POSITION_PREFIX'):
            self.run_one(rows,frame,ready)

    def test_census_includes_unresolved_and_occupied(self):
        rows,frame,ready=fixture(31)
        s=signal();s['max_hold_bars']=100
        other=signal(T)
        result=m.replay([s,other],{'BTC-USDT':frame},{'BTC-USDT':rows},ready,{'BTC-USDT':14},
                        lambda *args:{'stop_price':98},lambda *args:{})
        self.assertEqual(result['status_counts'],{'FILLED_UNRESOLVED':1,'REJECTED_OCCUPIED':1})
        self.assertEqual(len(result['census']),2)
        self.assertEqual(len({e['event_id'] for e in result['events']}),len(result['events']))

    def test_expiry_releases_pending_occupancy_and_gate_rejections_count(self):
        rows,frame,ready=fixture()
        result=m.replay([signal(),signal(T)],{'BTC-USDT':frame},{'BTC-USDT':rows},ready,{'BTC-USDT':14},
                        lambda s,p:{} if s['signal_open_ts_ms']==0 else {'reject':True,'reason':'FIXTURE_GATE'},lambda *args:{})
        self.assertEqual(result['status_counts'],{'EXPIRED_UNFILLED':1,'REJECTED_GATE':1})

    def test_pending_end_is_not_no_order_or_real_fill(self):
        rows,frame,ready=fixture();rows=rows[:40]
        row,position,release,census,_=self.run_one(rows,frame,ready)
        self.assertIsNone(row);self.assertIsNone(position)
        self.assertEqual(census['status'],'PENDING_END')
        self.assertEqual(release,2**63-1)

    def test_duplicate_episode_rejected(self):
        rows,frame,ready=fixture()
        with self.assertRaisesRegex(Exception,'DUPLICATE_EPISODE'):
            m.replay([signal(),signal()],{'BTC-USDT':frame},{'BTC-USDT':rows},ready,{'BTC-USDT':14},
                     lambda *args:{},lambda *args:{})

    def test_real_signal_generation_requires_reservation_before_frame_build(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                m.run_lanes({}, {}, Path(tmp))

    def test_all_six_and_late_past_prefix_are_binding(self):
        clocks={s:{0:T+50,T:2*T+50} for s in m.SYMBOLS}
        clocks[m.SYMBOLS[-1]][0]=3*T+50
        ready=m.clock.prefix_clocks(clocks)
        self.assertEqual(ready[0],3*T+50)
        self.assertEqual(ready[T],3*T+50)
        rows,frame,_=fixture(31)
        row,position,_,census,_=self.run_one(rows,frame,ready)
        self.assertIsNone(row);self.assertIsNone(position)
        self.assertEqual(census['status'],'REJECTED_STALE')


if __name__ == '__main__':
    unittest.main()
