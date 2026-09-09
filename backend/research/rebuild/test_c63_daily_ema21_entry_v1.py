"""Artificial prices only; test the actual daily availability boundary."""
from copy import deepcopy
from dataclasses import replace
from math import fsum
import unittest
from unittest.mock import patch
from backend.research.rebuild import c63_daily_ema21_entry_v1 as c

class DailyTests(unittest.TestCase):
    def bars(self,n=23):
        return [c.f.Bar(i*c.BAR,100.,101.,99.,100.,0.) for i in range(n*6)]
    def test_20_days_unavailable(self):
        x=c.observation(self.bars(),119);self.assertIsNone(x['value']);self.assertEqual(x['reason'],c.MISSING)
    def test_first_seed_at_exact_midnight(self):
        b=self.bars();b[125]=replace(b[125],close=100.5)
        x=c.observation(b,125);self.assertEqual(x['completed_days'],21);self.assertEqual(x['last_daily_available_at'],126*c.BAR);self.assertAlmostEqual(x['value'],(2000+100.5)/21);self.assertTrue(x['eligible'])
    def test_partial_day_not_used(self):
        b=self.bars();b[126]=replace(b[126],high=10001.,close=10000.)
        x=c.observation(b,126);self.assertEqual(x['value'],100.);self.assertEqual(x['completed_days'],21)
    def test_next_daily_update(self):
        b=self.bars();b[131]=replace(b[131],high=112.,close=111.)
        self.assertEqual(c.observation(b,131)['value'],101.)
    def test_strict_equality(self):self.assertEqual(c.observation(self.bars(),125)['reason'],c.VETO)
    def test_below_veto(self):
        b=self.bars();b[126]=replace(b[126],low=89.,close=90.)
        self.assertFalse(c.observation(b,126)['eligible'])
    def test_future_prefix_invariance(self):
        b=self.bars();x=c.observation(b,126)
        for j in range(127,len(b)):b[j]=replace(b[j],high=1e8,close=1e7)
        self.assertEqual(x,c.observation(b,126));self.assertEqual(x,c.observation(b[:127],126))
    def test_leading_partial_day_discarded_only_for_daily(self):
        b=self.bars(24)[2:];x=c.observation(b,129)
        self.assertEqual(x['leading_partial_bars'],4);self.assertEqual(x['daily_closes'][0]['open_ts'],c.DAY);self.assertEqual(x['completed_days'],21)
    def test_missing_middle_bar_rejected(self):
        b=self.bars();del b[30]
        with self.assertRaises(ValueError):c.observation(b,125)
    def test_duplicate_rejected(self):
        b=self.bars();b[30]=b[29]
        with self.assertRaises(ValueError):c.observation(b,125)
    def test_invalid_asof(self):
        for i in (-1,True,999):
            with self.assertRaises(ValueError):c.observation(self.bars(),i)
    def test_bad_ohlc_rejected(self):
        b=self.bars();b[126]=replace(b[126],close=float('nan'))
        with self.assertRaises(ValueError):c.observation(b,126)
    def test_no_sources_after_signal(self):
        x=c.observation(self.bars(),130);self.assertTrue(all(d['available_at']<=x['available_at'] for d in x['daily_closes']))
    def test_nonconstant_seed_and_ema(self):
        b=self.bars()
        for day in range(23):
            for j in range(day*6,(day+1)*6):b[j]=replace(b[j],open=100+day,high=101+day,low=99+day,close=100+day)
        v=fsum(range(100,121))/21
        v=(2/22)*121+(20/22)*v
        self.assertAlmostEqual(c.observation(b,131)['value'],v)
    def test_volume_unused(self):
        b=self.bars();x=c.observation(b,130);self.assertEqual(x,c.observation([replace(r,volume=999.) for r in b],130))
    def test_parent_veto_never_rescued(self):
        x=c.combine({'eligible':False,'reason':'ORIGINAL'},{'eligible':True,'reason':None});self.assertFalse(x['eligible']);self.assertEqual(x['reason'],'ORIGINAL')
    def test_filter_not_new_entry(self):
        for par in (True,False):
            for htf in (True,False):
                x=c.combine({'eligible':par,'reason':None if par else 'P'},{'eligible':htf,'reason':None if htf else 'H'})
                self.assertEqual(x['eligible'],par and htf)
    def test_input_dict_immutable(self):
        x={'eligible':True,'reason':None};y={'eligible':False,'reason':c.VETO};original=deepcopy((x,y));c.combine(x,y);self.assertEqual(original,(x,y))
    def test_disabled_is_c63_not_M1(self):
        with patch.object(c.parent,'replay',return_value={'sentinel':'C63'}) as p:
            self.assertEqual(c.replay([],eval_start_ms=0,eval_end_ms=c.BAR,enabled=False),{'sentinel':'C63'});self.assertNotIn('enabled',p.call_args.kwargs)
    def test_hook_restored(self):
        before=c.parent.context
        with patch.object(c.parent,'replay',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):c.replay([],eval_start_ms=0,eval_end_ms=c.BAR)
        self.assertIs(c.parent.context,before)
    def test_bool_strict(self):
        with self.assertRaises(ValueError):c.replay([],eval_start_ms=0,eval_end_ms=c.BAR,enabled=1)
    def test_scale_invariance(self):
        b=self.bars();b[126]=replace(b[126],high=102.,close=101.)
        a=c.observation(b,126);scaled=[replace(z,open=z.open*10,high=z.high*10,low=z.low*10,close=z.close*10) for z in b]
        d=c.observation(scaled,126);self.assertEqual(a['eligible'],d['eligible']);self.assertAlmostEqual(d['value'],10*a['value'])
if __name__=='__main__':unittest.main()
