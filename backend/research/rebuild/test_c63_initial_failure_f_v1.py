import unittest
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import c63_initial_failure_f_v1 as c
from backend.research.rebuild import test_c63_r_b20_v1 as fixtures

e=c.engine

class StateTests(unittest.TestCase):
    def step(self,s,h,m=10.,**kw):
        d=dict(held=h,available_at=h*e.BAR,close=90.,momentum=m,ema20=100.,original=None)
        d.update(kw);return s.step(**d)

    def test_bounds_and_strictness(self):
        for end in (2,3,19,20):
            s=c.FailureState()
            for h in range(1,end+1):
                out=self.step(s,h,30.-h)
            self.assertEqual(out,c.EXIT if end in (3,19) else None)
        for ms in ((3.,2.,1.),(3.,3.,1.),(3.,2.,2.),(3.,2.,0.),(3.,2.,-1.)):
            s=c.FailureState()
            for h,m in enumerate(ms,1):out=self.step(s,h,m)
            self.assertEqual(out,c.EXIT if ms==(3.,2.,1.) else None)
        s=c.FailureState()
        for h in range(1,4):out=self.step(s,h,4.-h,close=100.)
        self.assertIsNone(out)

    def test_parent_priority(self):
        for reason in ('FIXED_FLOOR_CLOSE','MOMENTUM_NONPOSITIVE_CLOSE','FIXED_TIME_CLOSE',
                       'RUNNER_B20_LOSS_CLOSE','RUNNER_EMA20_LOSS_CLOSE','RUNNER_MAX_TIME_CLOSE'):
            s=c.FailureState()
            for h in range(1,4):out=self.step(s,h,4.-h,original=reason if h==3 else None)
            self.assertEqual(out,reason)

    def test_invalid_sources_and_clock(self):
        for kw in ({'momentum':None},{'momentum':float('nan')},{'close':float('inf')},
                   {'available_at':None},{'held':2}):
            d=dict(held=1,available_at=e.BAR,close=90.,momentum=3.,ema20=100.,original=None);d.update(kw)
            with self.assertRaises(ValueError):c.FailureState().step(**d)
        for bad in (None,float('nan'),float('inf')):
            s=c.FailureState();self.step(s,1);self.step(s,2)
            with self.assertRaises(ValueError):self.step(s,3,ema20=bad)
        s=c.FailureState();self.step(s,1)
        with self.assertRaises(ValueError):self.step(s,2,available_at=3*e.BAR)

class NativeTests(unittest.TestCase):
    def fixture(self,trigger=3):
        b,s,f=fixtures.NativeTests().fixture(False)
        j=60+trigger
        for k,m in zip(range(j-2,j+1),(3.,2.,1.)):f[k]['momentum']=m
        b[j]=e.f.Bar(j*e.BAR,120.,121.,109.,110.,1.)
        b[j+1]=e.f.Bar((j+1)*e.BAR,95.,190.,94.,180.,1.)
        return b,s,f

    def pos(self,b,s,f,variant='F_ONLY',end=None):
        original=e._position
        wrapped=lambda b,s,v,f,end:c.position(b,s,v,f,end,original)
        if variant=='B20_F':
            with patch.object(c.b20.parent,'RunnerState',c.b20.RunnerState):
                return c.b20.parent.runner_position(b,s,'M1',f,end or len(b)*e.BAR,wrapped)
        return wrapped(b,s,'M1',f,end or len(b)*e.BAR)

    def test_fill_gap_pending_and_future_mutation(self):
        for variant in c.VARIANTS:
            b,s,f=self.fixture();before=deepcopy((b,s,f));hooks=(e._position,e.exit_reason,c.b20.parent.RunnerState)
            out=self.pos(b,s,f,variant);t=out[0]
            self.assertEqual((t['exit_index'],t['exit_price'],t['exit_reason']),(64,95.,c.EXIT+'_NEXT_OPEN'))
            self.assertEqual((b,s,f),before)
            b[64]=e.f.Bar(64*e.BAR,95.,9000.,1.,8000.,1.)
            self.assertEqual(out,self.pos(b,s,f,variant))
            opened=self.pos(b[:64],s,f[:64],variant)[1]
            self.assertEqual(opened['censor_reason'],'PENDING_EXIT_OUTSIDE_WINDOW')
            self.assertFalse(opened['terminal_liquidation'])
            self.assertIsNone(self.pos(b,s,f,variant,end=64*e.BAR)[0])
            f[61]['momentum']=float('nan')
            with self.assertRaises(ValueError):self.pos(b,s,f,variant)
            self.assertEqual(hooks,(e._position,e.exit_reason,c.b20.parent.RunnerState))

    def test_gap_next_observed_open_and_time_mismatch(self):
        b,s,f=self.fixture();b[64]=e.f.Bar(66*e.BAR,95.,190.,94.,180.,1.)
        self.assertEqual(self.pos(b[:65],s,f[:65],end=67*e.BAR)[0]['exit_ts'],66*e.BAR)
        f[63]['available_at']=65*e.BAR
        with self.assertRaises(ValueError):self.pos(b,s,f)

    def test_held19_F_has_no_anchor_or_extension_exposure(self):
        b,s,f=self.fixture(19);t=self.pos(b,s,f,'B20_F')[0]
        self.assertEqual(t['exit_reason'],c.EXIT+'_NEXT_OPEN')
        self.assertEqual(t['f_context']['actual_extended_held_bars'],0)
        self.assertFalse(t['runner_context']['extended'])
        self.assertIsNone(t['runner_context']['observations'][-1]['b20'])

    def test_disabled_exact_parents_and_full_followups(self):
        b,s,f=self.fixture();rows=fixtures.NativeTests().rows(b);kw=dict(eval_start_ms=50*e.BAR,eval_end_ms=len(b)*e.BAR)
        signals=[s]+[dict(s,signal_index=i,signal_ts=(i+1)*e.BAR,setup_id='s'+str(i)) for i in (63,64)]
        for variant,parent in [('F_ONLY',c.b20.parent.c63),('B20_F',c.b20)]:
            with patch.object(e,'m1_setups',return_value=(signals,[],f)):
                self.assertEqual(c.replay(rows,variant=variant,enabled=False,**kw),parent.replay(rows,**kw))
                result=c.replay(rows,variant=variant,**kw)
            self.assertEqual(result['trades'][0]['entry_index'],61)
            self.assertEqual(result['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')
            self.assertTrue(result['events'][2]['admission'])

    def test_unchanged_surviving_B20_path_and_max40(self):
        b,s,f=fixtures.NativeTests().fixture();new=self.pos(b,s,f,'B20_F');old=fixtures.NativeTests().position(b,s,f)
        new[0].pop('f_context');self.assertEqual(new,old)
        b,s,f=fixtures.NativeTests().fixture(False);t=self.pos(b,s,f,'B20_F')[0]
        self.assertEqual(t['exit_reason'],'RUNNER_MAX_TIME_CLOSE_NEXT_OPEN')
        self.assertTrue(t['runner_context']['extended'])
        self.assertEqual(t['f_context']['actual_extended_held_bars'],20)

class ScopeTests(unittest.TestCase):
    def test_scope_guard(self):
        from backend.research.rebuild import c63_initial_failure_f_study_v1 as s
        s.ensure_execution_scope(s.SCOPE,'PREPARED')
        for scope in (s.SCOPE,c.b20.RULE_ID):
            with self.assertRaises((RuntimeError,ValueError)):s.ensure_execution_scope(scope,'REPORT_ONLY')

if __name__=='__main__':unittest.main()
