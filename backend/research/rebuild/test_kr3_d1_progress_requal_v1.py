"""Synthetic tests only; no economic dataset replay or provider requests."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from dataclasses import replace
from backend.research.rebuild import kr3_d1_progress_requal_v1 as m
from backend.research.rebuild.test_step7_kr3_mechanism_separation_v1 import tiny, core

class ProgressTests(unittest.TestCase):
    def run_case(self, rows,bundle):
        return m.replay_symbol(rows,bundle,start=0,end=len(rows)*m.p.BAR)
    def progress_case(self):
        rows,b=tiny();rows[8].update(open=104.,high=108.,low=103.,close=104.)
        b['ema20'][8]=102.;b['ema50'][8]=101.
        return rows,b
    def test_no_override_equals_exact_D_fills(self):
        rows,b=tiny();parent=m.p.replay_symbol(rows,b,m.p.MODES[3],start=0,end=len(rows)*m.p.BAR)
        child=self.run_case(rows,b)
        self.assertEqual(core(parent),core(child))
        self.assertEqual(parent['reference_opportunities'],child['reference_opportunities'])
    def test_progress_allows_low_half_at_sixth_close_not_first(self):
        rows,b=self.progress_case();parent=m.p.replay_symbol(rows,b,m.p.MODES[3],start=0,end=len(rows)*m.p.BAR)
        child=self.run_case(rows,b)
        self.assertFalse(parent['events'][0]['admission'])
        self.assertTrue(child['events'][0]['admission'])
        self.assertEqual(child['events'][0]['admission_path'],'D1_PROGRESS_CONFIRMED_AT_SIXTH_CLOSE')
        t=child['trades'][0];self.assertEqual(t['entry_index'],9)
        self.assertEqual(t['exit_anchor_index'],8)
    def test_original_half_failure_not_rescued(self):
        rows,b=self.progress_case();rows[2]['high']=104.
        c=self.run_case(rows,b);self.assertFalse(c['events'][0]['admission'])
        self.assertEqual(c['events'][0]['exclusion_reason'],'ORIGIN_HALF_FAILED')
    def test_strict_breakout_equality_rejected(self):
        o={'high':104.,'bar_close_ts':1};c={'close':104.,'bar_close_ts':7}
        self.assertFalse(m.progress_confirmed(o,c,102.,101.))
    def test_below_fast_ema_rejected(self):
        self.assertFalse(m.progress_confirmed({'high':101.,'bar_close_ts':1},{'close':104.,'bar_close_ts':7},105.,102.))
    def test_flat_or_inverted_trend_rejected(self):
        for slow in (102.,103.):
            self.assertFalse(m.progress_confirmed({'high':101.,'bar_close_ts':1},{'close':104.,'bar_close_ts':7},102.,slow))
    def test_bad_observation_fails_closed(self):
        for bad in (float('nan'),float('inf'),True,-1.):
            with self.assertRaises(ValueError):m.progress_confirmed({'high':bad,'bar_close_ts':1},{'close':104.,'bar_close_ts':7},102.,101.)
    def test_future_or_same_time_origin_rejected(self):
        with self.assertRaises(ValueError):m.progress_confirmed({'high':101.,'bar_close_ts':7},{'close':104.,'bar_close_ts':7},102.,101.)
    def test_recheck_reject_still_reserves_reference(self):
        rows,b=tiny();rows[8]['high']=104.
        c=self.run_case(rows,b);self.assertTrue(c['events'][0]['reference_created'])
        self.assertFalse(c['reference_opportunities'][0]['model_selected'])
    def test_all_signal_denominators_and_no_overlap(self):
        rows,b=self.progress_case();c=self.run_case(rows,b)
        self.assertEqual(len(c['events']),len(b['signals']))
        self.assertEqual(sum(c['audit'][x] for x in ('completed','open','excluded')),len(b['signals']))
        last=-1
        for t in c['trades']+c['open_positions']:
            self.assertGreater(t['decision_ts'],last)
            last=t.get('exit_ts',t.get('mark_ts'))
    def test_earlier_decisions_do_not_use_future_suffix(self):
        rows,b=self.progress_case();alt=deepcopy(rows)
        for r in alt[35:]:r.update(open=80.,high=81.,low=79.,close=80.)
        fields=('signal_index','decision_ts','admission','exclusion_reason','progress_confirmation')
        def view(x):return [{k:e.get(k) for k in fields} for e in x['events'] if e.get('decision_ts') is not None and e['decision_ts']<35*m.p.BAR]
        self.assertEqual(view(self.run_case(rows,b)),view(self.run_case(alt,b)))
    def test_no_future_price_or_outcome_predicate(self):
        o={'high':101.,'bar_close_ts':1,'future_net':-999};c={'close':104.,'bar_close_ts':7,'symbol':'WHATEVER'}
        self.assertTrue(m.progress_confirmed(o,c,102.,101.))
        o['future_net']=999;c['symbol']='ANOTHER'
        self.assertTrue(m.progress_confirmed(o,c,102.,101.))
    def test_frozen_parent_ref_and_exit_cannot_drift(self):
        modes=list(m.p.MODES);modes[3]=replace(modes[3],exit_anchor='ORIGIN')
        rows,b=tiny()
        with patch.object(m.p,'MODES',tuple(modes)):
            with self.assertRaises(ValueError):self.run_case(rows,b)
    def test_preentry_high_not_held_excursion(self):
        rows,b=self.progress_case();rows[5].update(high=1000.,low=1.)
        c=self.run_case(rows,b);t=c['trades'][0]
        self.assertLess(t['mfe_bps'],1000.)
    def test_original_good_half_not_tightened(self):
        rows,b=tiny();c=self.run_case(rows,b)
        self.assertTrue(c['events'][0]['admission']);self.assertFalse(c['events'][0]['progress_confirmation'])
    def test_reference_reservation_clock_not_released_by_actual_exit(self):
        rows,b=self.progress_case();c=self.run_case(rows,b)
        self.assertFalse(c['audit']['reference_released_by_actual_exit'])
        self.assertEqual(c['reference_opportunities'][0]['reference_signal_index'],8)

if __name__=='__main__':unittest.main()
