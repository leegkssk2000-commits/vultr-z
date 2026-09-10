import unittest
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import c63_transplant_v1 as t

class GateTests(unittest.TestCase):
    def base(self, escape=True, eligible=True):
        return dict(eligible=eligible, reason=None if eligible else 'ER_HISTORY_UNAVAILABLE',
                    range_context=dict(strict_escape=escape))
    def obs(self, eligible=False, value=10.):
        return dict(eligible=eligible, value=value, available_at=100)
    def test_strict_escape_preserved_below_daily(self):
        self.assertTrue(t.gate(self.base(), self.obs())['eligible'])
    def test_non_escape_veto(self):
        self.assertEqual(t.gate(self.base(False), self.obs())['reason'], t.VETO)
    def test_non_escape_above_daily(self):
        self.assertTrue(t.gate(self.base(False), self.obs(True))['eligible'])
    def test_original_safety_not_rescued(self):
        out = t.gate(self.base(True, False), self.obs(True))
        self.assertFalse(out['eligible']); self.assertEqual(out['reason'], 'ER_HISTORY_UNAVAILABLE')
    def test_missing_new_daily_not_native_safety(self):
        self.assertTrue(t.gate(self.base(), self.obs(value=None))['eligible'])
        self.assertEqual(t.gate(self.base(False), self.obs(value=None))['reason'], t.daily.MISSING)
    def test_inputs_immutable(self):
        x, y = self.base(), self.obs(); original = deepcopy((x,y)); t.gate(x,y)
        self.assertEqual((x,y), original)

class RunnerTests(unittest.TestCase):
    def step(self, state, held, **kwargs):
        args = dict(close=120., floor=90., momentum=1., held=held,
                    ema20=110., ema50=100., available_at=held*t.engine.BAR)
        args.update(kwargs); return state.step(**args)
    def prepared(self):
        s=t.RunnerState(100.)
        for i in range(1,20): self.assertIsNone(self.step(s,i))
        self.assertTrue(s.extended); return s
    def test_no_decision_before19(self):
        s=t.RunnerState(100.)
        for i in range(1,19):self.step(s,i)
        self.assertFalse(s.decided)
    def test_extension_once_and_hard_cap40(self):
        s=self.prepared()
        for i in range(20,40):self.assertIsNone(self.step(s,i))
        self.assertEqual(self.step(s,40),'RUNNER_MAX_TIME_CLOSE')
    def test_no_late_rearming(self):
        s=t.RunnerState(100.)
        for i in range(1,20):self.step(s,i,close=99.)
        self.assertFalse(s.extended)
        self.assertEqual(self.step(s,20),'FIXED_TIME_CLOSE')
    def test_entry_profit_equality_no_extension(self):
        s=t.RunnerState(100.)
        for i in range(1,20):self.step(s,i,close=100.,ema20=99.,ema50=98.)
        self.assertFalse(s.extended)
    def test_ema_equality_no_extension(self):
        s=t.RunnerState(100.)
        for i in range(1,20):self.step(s,i,ema20=100.,ema50=100.)
        self.assertFalse(s.extended)
    def test_missing_ema_no_extension(self):
        s=t.RunnerState(100.)
        for i in range(1,20):self.step(s,i,ema50=None)
        self.assertEqual(self.step(s,20),'FIXED_TIME_CLOSE')
    def test_floor_priority(self):
        s=self.prepared();self.assertEqual(self.step(s,20,close=90.,momentum=-1.),'FIXED_FLOOR_CLOSE')
    def test_momentum_priority(self):
        s=self.prepared();self.assertEqual(self.step(s,20,momentum=0.),'MOMENTUM_NONPOSITIVE_CLOSE')
    def test_trend_loss_equality(self):
        s=self.prepared();self.assertEqual(self.step(s,20,close=110.),'RUNNER_EMA20_LOSS_CLOSE')
    def test_clock_gaps_rejected(self):
        with self.assertRaises(ValueError):self.step(t.RunnerState(100.),2)
    def test_invalid_entry(self):
        with self.assertRaises(ValueError):t.RunnerState(float('nan'))

class NativeIntegrationTests(unittest.TestCase):
    def fixture(self):
        e=t.engine
        bars=[e.f.Bar(i*e.BAR,100.+i,101.+i,99.+i,100.5+i,1.) for i in range(106)]
        sig=dict(signal_index=60,signal_ts=61*e.BAR,episode_start=58,
            setup_id='synthetic',floor=80.,target=None,expiry=None,max_hold_bars=20)
        features=[dict(momentum=1.) for _ in bars]
        return bars,sig,features
    def runpath(self,bars,sig,features,end=None):
        return t.runner_position(bars,sig,'M1',features,end or len(bars)*t.engine.BAR,t.engine._position)
    def test_native_next_open_and40_cap(self):
        b,s,f=self.fixture();trade,opened,trace=self.runpath(b,s,f)
        self.assertIsNone(opened);self.assertEqual(trade['exit_index'],101)
        self.assertEqual(trade['exit_price'],b[101].open)
        self.assertEqual(trade['exit_trigger']['signal_ts'],101*t.engine.BAR)
        self.assertEqual(trade['exit_reason'],'RUNNER_MAX_TIME_CLOSE_NEXT_OPEN')
        self.assertTrue(trade['runner_context']['extended'])
    def test_native_early_momentum(self):
        b,s,f=self.fixture();f[64]['momentum']=0.
        trade,_,_=self.runpath(b,s,f);self.assertEqual(trade['exit_index'],65)
    def test_future_mutation_invariance(self):
        b,s,f=self.fixture();before=self.runpath(b,s,f)
        b[104]=t.engine.f.Bar(104*t.engine.BAR,999.,1000.,1.,999.,1.)
        self.assertEqual(before,self.runpath(b,s,f))
    def test_end_window_open_not_forced_closed(self):
        b,s,f=self.fixture();b=b[:90];f=f[:90]
        trade,opened,_=self.runpath(b,s,f)
        self.assertIsNone(trade);self.assertEqual(opened['mark_ts'],90*t.engine.BAR)
        self.assertFalse(opened['terminal_liquidation'])
    def test_pending_exit_censored_at_boundary(self):
        b,s,f=self.fixture();b=b[:101];f=f[:101]
        trade,opened,_=self.runpath(b,s,f)
        self.assertIsNone(trade);self.assertEqual(opened['censor_reason'],'PENDING_EXIT_OUTSIDE_WINDOW')
    def test_disabled_dispatches_exact_c63(self):
        marker=object()
        with patch.object(t.c63,'replay',return_value=marker) as fn:
            self.assertIs(t.replay([],eval_start_ms=0,eval_end_ms=1,variant='GR',enabled=False),marker)
            fn.assert_called_once_with([],eval_start_ms=0,eval_end_ms=1)
    def test_actual_runner_occupancy_blocks_later_signal(self):
        b,s,f=self.fixture();s2=dict(s,signal_index=85,signal_ts=86*t.engine.BAR,episode_start=83,setup_id='synthetic2')
        rows=[dict(bar_open_ts=x.open_ts,bar_close_ts=x.open_ts+t.engine.BAR,
            open=x.open,high=x.high,low=x.low,close=x.close,volume=x.volume) for x in b]
        with patch.object(t.engine,'m1_setups',return_value=([s,s2],[],f)):
            result=t.replay(rows,eval_start_ms=0,eval_end_ms=len(b)*t.engine.BAR,variant='R')
        self.assertTrue(result['events'][0]['admission'])
        self.assertEqual(result['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')

if __name__=='__main__':unittest.main()
