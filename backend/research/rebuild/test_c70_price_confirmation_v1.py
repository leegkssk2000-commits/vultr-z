"""Synthetic source-clock, admission and native lifecycle regression only."""
import unittest
from dataclasses import replace
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import c70_price_confirmation_v1 as c
from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,rows_of
from backend.research.rebuild.chart_mechanism_features_v1 import Bar

class PriceTests(unittest.TestCase):
    def args(self):
        original=dict(eligible=True,reason=None,range_context=dict(strict_escape=True))
        obs=dict(value=110.,eligible=False,signal_close=105.,available_at=40*c.daily.DAY,
            daily_closes=[dict(close=v,available_at=(i+1)*c.daily.DAY) for i,v in enumerate([120.,104.,103.,102.,101.,100.])])
        session=dict(high=104.,available_at=39*c.daily.DAY)
        return original,obs,session
    def test_falling_sma_price_breakout_can_pass(self):
        x=c.combine(*self.args());self.assertTrue(x['eligible']);self.assertFalse(x['recovery_context']['nonfalling_sma'])
    def test_day_high_equality_does_not_pass(self):
        o,d,s=self.args();s['high']=105.;self.assertFalse(c.combine(o,d,s)['eligible'])
    def test_below_day_high_does_not_pass(self):
        o,d,s=self.args();s['high']=106.;self.assertFalse(c.combine(o,d,s)['eligible'])
    def test_slope_alone_is_not_confirmation(self):
        o,d,s=self.args();d['daily_closes'][0]['close']=90.;s['high']=106.;x=c.combine(o,d,s);self.assertTrue(x['recovery_context']['nonfalling_sma']);self.assertFalse(x['eligible'])
    def test_price_must_be_above_sma(self):
        o,d,s=self.args();d['signal_close']=102.;s['high']=101.;self.assertFalse(c.combine(o,d,s)['eligible'])
    def test_original_range_escape_required(self):
        o,d,s=self.args();o['range_context']['strict_escape']=False;self.assertFalse(c.combine(o,d,s)['eligible'])
    def test_c69_preserved_even_without_rescue(self):
        o,d,s=self.args();d['eligible']=True;s['high']=1000.;self.assertTrue(c.combine(o,d,s)['eligible'])
    def test_native_ineligible_never_bypassed(self):
        o,d,s=self.args();o.update(eligible=False,reason='ORIGINAL');d['eligible']=True;x=c.combine(o,d,s);self.assertFalse(x['eligible']);self.assertEqual(x['reason'],'ORIGINAL')
    def test_daily_warmup_never_bypassed(self):
        o,d,s=self.args();d['value']=None;x=c.combine(o,d,s);self.assertFalse(x['eligible']);self.assertEqual(x['reason'],c.MISSING)
    def test_missing_prior_day_disables_only_rescue(self):
        o,d,s=self.args();self.assertFalse(c.combine(o,d,None)['eligible']);d['eligible']=True;self.assertTrue(c.combine(o,d,None)['eligible'])
    def test_future_daily_witness_rejected(self):
        o,d,s=self.args();d['daily_closes'][-1]['available_at']=d['available_at']+1
        with self.assertRaisesRegex(ValueError,'FUTURE_SMA'):c.combine(o,d,s)
    def test_future_high_rejected(self):
        o,d,s=self.args();s['available_at']=d['available_at']+1
        with self.assertRaisesRegex(ValueError,'FUTURE_PRIOR_DAY'):c.combine(o,d,s)
    def bars(self):return [Bar(i*c.daily.BAR,100.,110.+i,90.,100.,1.) for i in range(24)]
    def test_intraday_uses_prior_session(self):
        x=c.prior_session(self.bars(),9);self.assertEqual(x['high'],115.);self.assertEqual(x['available_at'],c.daily.DAY)
    def test_midnight_close_never_uses_signal_session(self):
        b=self.bars();x=c.prior_session(b,11);b[11]=replace(b[11],high=9999.);self.assertEqual(x,c.prior_session(b,11));self.assertEqual(x['high'],115.)
    def test_first_bar_new_day_uses_just_ended_day(self):
        x=c.prior_session(self.bars(),12);self.assertEqual(x['high'],121.);self.assertEqual(x['available_at'],2*c.daily.DAY)
    def test_partial_leading_day_not_full_day(self):self.assertIsNone(c.prior_session(self.bars()[2:],6))
    def test_future_change_irrelevant(self):
        b=self.bars();x=c.prior_session(b,9);b[20]=replace(b[20],high=10000.);self.assertEqual(x,c.prior_session(b,9))
    def test_inputs_immutable(self):
        a=self.args();b=deepcopy(a);c.combine(*a);self.assertEqual(a,b)
    def run_bars(self,enabled=True):
        b=momentum_fixture(180);rows=rows_of(b)
        return c.replay(rows,eval_start_ms=0,eval_end_ms=len(b)*c.daily.BAR,enabled=enabled)
    def test_disabled_is_exact_daily_parent(self):
        b=momentum_fixture(180);self.assertEqual(self.run_bars(False),c.daily.replay(rows_of(b),eval_start_ms=0,eval_end_ms=len(b)*c.daily.BAR))
    def test_boolean_flag_only(self):
        with self.assertRaises(ValueError):self.run_bars(1)
    def test_context_restored_after_error(self):
        before=c.daily.parent.context
        with patch.object(c,'combine',side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):self.run_bars()
        self.assertIs(before,c.daily.parent.context)
    def test_native_gap_rejected(self):
        b=momentum_fixture(180);rows=rows_of(b);del rows[10]
        with self.assertRaises(ValueError):c.replay(rows,eval_start_ms=0,eval_end_ms=len(b)*c.daily.BAR)
    def test_no_orders_or_formal_credit(self):
        self.assertEqual(self.run_bars()['audit']['formal_credit'],0)

if __name__=='__main__':unittest.main()
