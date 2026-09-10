import unittest
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import c63_r_b20_v1 as c

p, e = c.parent, c.parent.engine


class StateTests(unittest.TestCase):
    def step(self, state, held, **kw):
        args = dict(close=120., floor=90., momentum=1., held=held,
                    ema20=110., ema50=100., available_at=held*e.BAR)
        args.update(kw)
        return state.step(**args)

    def prepared(self, n=20):
        s = c.RunnerState(100.)
        for held in range(1, n+1):
            self.assertIsNone(self.step(s, held))
        return s

    def test_T1_same_R_decisions_through20(self):
        for close in (120., 99.):
            a, b = p.RunnerState(100.), c.RunnerState(100.)
            for held in range(1, 21):
                self.assertEqual(self.step(a, held, close=close),
                                 self.step(b, held, close=close))
            self.assertEqual(a.extended, b.extended)

    def test_T2_anchor_only_after_surviving_extended20_and_fixed(self):
        s = self.prepared(19)
        self.assertIsNone(s.b20)
        self.assertIsNone(self.step(s, 20, close=119.))
        self.assertEqual((s.b20, s.b20_available_at), (119., 20*e.BAR))
        self.assertIsNone(self.step(s, 21, close=125.))
        self.assertEqual(s.b20, 119.)
        s = self.prepared(19)
        self.assertEqual(self.step(s, 20, close=110.), 'RUNNER_EMA20_LOSS_CLOSE')
        self.assertIsNone(s.b20)

    def test_T3_equality_does_not_trigger_strict_later_breach_does(self):
        s = self.prepared()
        self.assertIsNone(self.step(s, 21, close=120.))
        self.assertEqual(self.step(s, 22, close=119.), c.EXIT)
        self.assertTrue(s.witnesses[-1]['b20_triggered'])

    def test_T4_existing_exit_priority(self):
        for kw, expected in [({'close':90.},'FIXED_FLOOR_CLOSE'),
                             ({'close':119.,'momentum':0.},'MOMENTUM_NONPOSITIVE_CLOSE'),
                             ({'close':110.},'RUNNER_EMA20_LOSS_CLOSE')]:
            s = self.prepared()
            self.assertEqual(self.step(s,21,**kw),expected)
            self.assertFalse(s.witnesses[-1]['b20_triggered'])
        s = self.prepared(39)
        self.assertEqual(self.step(s,40,close=119.),'RUNNER_MAX_TIME_CLOSE')

    def test_no_extra_profit_or_rising20_condition(self):
        s = self.prepared(19)
        self.assertIsNone(self.step(s,20,close=99.,ema20=98.,ema50=97.))
        self.assertEqual(s.b20,99.)
        self.assertEqual(self.step(s,21,close=98.5,ema20=98.,ema50=97.),c.EXIT)

    def test_T7_bad_clock_and_sources_fail(self):
        for kw in ({'close':None},{'close':float('nan')},{'close':float('inf')},
                   {'momentum':None},{'available_at':None},{'available_at':-1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.step(c.RunnerState(100.),1,**kw)
        with self.assertRaises(ValueError): self.step(c.RunnerState(100.),2)
        s = self.prepared()
        with self.assertRaises(ValueError): self.step(s,21,available_at=20*e.BAR)


class NativeTests(unittest.TestCase):
    def fixture(self, breach=True):
        b = [e.f.Bar(i*e.BAR,100.+i,101.+i,99.+i,100.5+i,1.) for i in range(106)]
        if breach:
            b[81] = e.f.Bar(81*e.BAR,181.,182.,175.,176.,1.)
            b[82] = e.f.Bar(82*e.BAR,130.,183.,129.,182.5,1.)
        s = dict(signal_index=60,signal_ts=61*e.BAR,episode_start=58,
                 setup_id='synthetic',floor=80.,target=None,expiry=None,max_hold_bars=20)
        f = [dict(momentum=1.) for _ in b]
        return b,s,f

    def position(self,b,s,f,end=None,enabled=True):
        if not enabled:
            return p.runner_position(b,s,'M1',f,end or len(b)*e.BAR,e._position)
        with patch.object(p,'RunnerState',c.RunnerState):
            return p.runner_position(b,s,'M1',f,end or len(b)*e.BAR,e._position)

    def rows(self,b):
        return [dict(bar_open_ts=x.open_ts,bar_close_ts=x.open_ts+e.BAR,
            open=x.open,high=x.high,low=x.low,close=x.close,volume=x.volume) for x in b]

    def test_T5_next_open_gap_and_causal_witness(self):
        b,s,f=self.fixture();trade,opened,_=self.position(b,s,f)
        self.assertIsNone(opened)
        self.assertEqual(trade['exit_reason'],c.EXIT+'_NEXT_OPEN')
        self.assertEqual((trade['exit_index'],trade['exit_price']),(82,130.))
        self.assertEqual(trade['exit_trigger']['signal_ts'],82*e.BAR)
        obs=trade['runner_context']['observations']
        self.assertEqual(obs[-1]['held'],21)
        self.assertEqual(obs[-1]['b20'],b[80].close)
        self.assertLess(obs[-1]['b20_available_at'],obs[-1]['available_at'])

    def test_T6_no_next_open_remains_pending_and_unrealized(self):
        b,s,f=self.fixture();b,f=b[:82],f[:82]
        trade,opened,_=self.position(b,s,f)
        self.assertIsNone(trade)
        self.assertEqual(opened['censor_reason'],'PENDING_EXIT_OUTSIDE_WINDOW')
        self.assertEqual(opened['pending_exit_trigger']['reason'],c.EXIT)
        self.assertFalse(opened['terminal_liquidation'])
        self.assertNotIn('net_bps',opened)

    def test_future_hlc_and_input_immutability_hooks_restored(self):
        b,s,f=self.fixture();before=deepcopy((b,s,f));original=(p.RunnerState,e.exit_reason,e._position)
        out=self.position(b,s,f)
        self.assertEqual((b,s,f),before)
        b[82]=e.f.Bar(82*e.BAR,130.,9000.,1.,7000.,1.)
        self.assertEqual(out,self.position(b,s,f))
        self.assertEqual(original,(p.RunnerState,e.exit_reason,e._position))
        f[61]['momentum']=float('nan')
        with self.assertRaises(ValueError): self.position(b,s,f)
        self.assertEqual(original,(p.RunnerState,e.exit_reason,e._position))

    def test_T8_disabled_exact_R_and_runner_disabled_C63(self):
        b,s,f=self.fixture();rows=self.rows(b);kwargs=dict(eval_start_ms=0,eval_end_ms=len(b)*e.BAR)
        with patch.object(e,'m1_setups',return_value=([s],[],f)):
            self.assertEqual(c.replay(rows,enabled=False,**kwargs),p.replay(rows,variant='R',**kwargs))
            self.assertEqual(c.replay(rows,runner_enabled=False,**kwargs),p.c63.replay(rows,**kwargs))

    def test_T1_nonextended_exact_C63_position(self):
        b,s,f=self.fixture(False)
        for j in range(61,81):
            b[j]=e.f.Bar(j*e.BAR,100.,105.,95.,99.,1.)
        x=self.position(b,s,f);y=e._position(b,s,'M1',f,len(b)*e.BAR)
        x[0].pop('runner_context')
        self.assertEqual(x,y)

    def test_T9_changed_occupancy_preserves_all_signal_opportunities(self):
        b,s,f=self.fixture();signals=[s]+[dict(s,signal_index=i,signal_ts=(i+1)*e.BAR,
            episode_start=i-2,setup_id='s'+str(i)) for i in (81,82)]
        kwargs=dict(eval_start_ms=0,eval_end_ms=len(b)*e.BAR)
        with patch.object(e,'m1_setups',return_value=(signals,[],f)):
            new=c.replay(self.rows(b),**kwargs)
            old=p.replay(self.rows(b),variant='R',**kwargs)
        self.assertEqual([x['signal_index'] for x in new['events']],[60,81,82])
        self.assertEqual(new['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')
        self.assertTrue(new['events'][2]['admission'])
        self.assertFalse(old['events'][2]['admission'])

    def test_mid_window_uses_original_indices_and_preparation(self):
        b,s,f=self.fixture();rows=self.rows(b)
        with patch.object(e,'m1_setups',return_value=([s],[],f)):
            out=c.replay(rows,eval_start_ms=50*e.BAR,eval_end_ms=len(b)*e.BAR)
        self.assertEqual(out['trades'][0]['entry_index'],61)
        self.assertEqual(out['trades'][0]['exit_index'],82)


class ScopeTests(unittest.TestCase):
    def test_disjoint_aggregate_uses_counts_and_profit_sums(self):
        from backend.research.rebuild import c63_r_b20_study_v1 as study
        def result(values):
            return dict(trades=[dict(net_bps=v) for v in values],open_observations=[],
                metrics=dict(terminal_net_bps=sum(values),terminal_cost2x_net_bps=sum(values)-len(values)))
        out=study.aggregate([result([100.,-10.]),result([-10.]*8)])
        self.assertEqual(out['win_rate'],.1)
        self.assertAlmostEqual(out['PF'],100/90)
        self.assertEqual(out['terminal_net_bps'],10.)
        self.assertIsNone(out['marked_DD_trade_sum_bps'])

    def test_T10_new_successor_ready_old_closed_scope_blocked(self):
        from backend.research.rebuild import c63_r_b20_study_v1 as study
        study.ensure_execution_scope(study.SCOPE,'PREPARED')
        with self.assertRaises((RuntimeError,ValueError)):
            study.ensure_execution_scope(p.RULES['R'],'REPORT_ONLY')
        with self.assertRaises((RuntimeError,ValueError)):
            study.ensure_execution_scope(study.SCOPE,'REPORT_ONLY')


if __name__=='__main__': unittest.main()
