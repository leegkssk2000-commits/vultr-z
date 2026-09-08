"""Synthetic-only mechanism tests; never execute an actual DEV allocation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.research.rebuild import step7_kr3_mechanism_separation_v1 as m

FIELDS=('entry_index','entry_ts','entry_price','exit_index','exit_ts','exit_price',
        'gross_bps','hold_ms','mfe_bps','mae_bps')


def tiny(n=70):
    rows=[{'bar_open_ts':i*m.BAR,'bar_close_ts':(i+1)*m.BAR,
           'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.} for i in range(n)]
    bundle={'signals':[{'signal_index':i,'signal_ts':rows[i]['bar_close_ts']} for i in (2,6,15,18,29,44,65) if i<n-1],
            'ema20':[100.]*n,'ema50':[99.]*n,'audit':{}}
    return rows,bundle


def core(out):
    return [{k:t.get(k) for k in FIELDS} for t in out['trades']]


class MechanismTests(unittest.TestCase):
    def test_four_fixed_diagnostics_not_candidate_search(self):
        self.assertEqual(len(m.MODES),4)
        self.assertEqual({x.delay for x in m.MODES},{6})
        self.assertTrue(all(x.require_origin_half for x in m.MODES))

    def test_synthetic_zero_delay_preserves_original_full_economics(self):
        rows,b=tiny()
        control=m.kr3.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*m.BAR)
        out=m.replay_symbol(rows,b,m.Mode('SYNTHETIC_ZERO',0,False,'ORIGIN','ORIGIN'),start=0,end=len(rows)*m.BAR)
        self.assertEqual(core(out),core(control))
        self.assertEqual(len(out['open_positions']),len(control['open_positions']))
        self.assertEqual([e['admission'] for e in out['events']],[e['status']!='EXCLUDED' for e in control['events']])

    def test_synthetic_legacy_endpoint_matches_native_shifted_full(self):
        rows,b=tiny()
        rows[2].update(high=104.,low=99.,close=100.) # original half rejects
        shifted=deepcopy(b)
        shifted['signals']=[{'signal_index':s['signal_index']+6,'signal_ts':rows[s['signal_index']+6]['bar_close_ts']}
                            for s in b['signals'] if s['signal_index']+6<len(rows)-1]
        legacy=m.kr3.replay(rows,shifted,eval_start_ms=0,eval_end_ms=len(rows)*m.BAR)
        mode=m.Mode('SYNTHETIC_LEGACY',6,True,'SHIFTED','SHIFTED',False)
        got=m.replay_symbol(rows,b,mode,start=0,end=len(rows)*m.BAR)
        self.assertEqual(core(got),core(legacy))
        self.assertEqual(len(got['open_positions']),len(legacy['open_positions']))

    def test_no_entry_before_delayed_observation(self):
        rows,b=tiny()
        out=m.replay_symbol(rows,b,m.MODES[0],start=0,end=len(rows)*m.BAR)
        self.assertTrue(out['trades'])
        for t in out['trades']+out['open_positions']:
            self.assertEqual(t['entry_index'],t['original_signal_index']+7)
            self.assertEqual(t['entry_ts'],t['decision_ts'])
            self.assertEqual(t['waiting_observed_bars'],6)

    def test_recheck_never_retroactively_cancels_an_earlier_fill(self):
        rows,b=tiny();rows[8].update(high=104.,close=100.)
        a=m.replay_symbol(rows,b,m.MODES[0],start=0,end=len(rows)*m.BAR)
        c=m.replay_symbol(rows,b,m.MODES[1],start=0,end=len(rows)*m.BAR)
        ea=next(e for e in a['events'] if e['signal_index']==2)
        ec=next(e for e in c['events'] if e['signal_index']==2)
        self.assertTrue(ea['admission']);self.assertFalse(ec['admission'])
        self.assertEqual(ec['exclusion_reason'],'DELAYED_HALF_RECHECK_FAILED')
        self.assertEqual(ec['exclusion_known_at'],rows[8]['bar_close_ts'])
        self.assertFalse(any(t['original_signal_index']==2 for t in c['trades']))

    def test_recheck_does_not_release_original_ghost_reservation(self):
        rows,b=tiny();rows[8].update(high=104.)
        a=m.replay_symbol(rows,b,m.MODES[0],start=0,end=len(rows)*m.BAR)
        c=m.replay_symbol(rows,b,m.MODES[1],start=0,end=len(rows)*m.BAR)
        self.assertEqual(a['reference_opportunities'],c['reference_opportunities'])
        self.assertEqual(a['reference_events'],c['reference_events'])

    def test_expired_reference_is_cancelled_only_when_known(self):
        rows,b=tiny();b['ema20'][4:]=[98.]*(len(rows)-4)
        out=m.replay_symbol(rows,b,m.MODES[0],start=0,end=len(rows)*m.BAR)
        e=out['events'][0]
        self.assertEqual(e['exclusion_reason'],'WAIT_REFERENCE_EXPIRED')
        self.assertEqual(e['exclusion_known_at'],rows[8]['bar_close_ts'])

    def test_no_ema_exit_pending_reference_entry(self):
        rows,b=tiny();b['ema20'][8]=98.
        out=m.replay_symbol(rows,b,m.MODES[0],start=0,end=len(rows)*m.BAR)
        self.assertEqual(out['events'][0]['exclusion_reason'],'WAIT_REFERENCE_EXIT_ALREADY_OBSERVED')

    def test_shift_reference_releases_no_earlier_than_observed(self):
        rows,b=tiny()
        out=m.replay_symbol(rows,b,m.MODES[2],start=0,end=len(rows)*m.BAR)
        self.assertEqual(out['reference_opportunities'][0]['reference_signal_index'],8)
        self.assertEqual(out['reference_opportunities'][0]['reservation_ts'],rows[8]['bar_close_ts'])

    def test_shift_reference_keeps_failed_origin_as_ghost_not_trade(self):
        rows,b=tiny();rows[2].update(high=104.)
        out=m.replay_symbol(rows,b,m.MODES[3],start=0,end=len(rows)*m.BAR)
        self.assertFalse(out['reference_opportunities'][0]['model_selected'])
        self.assertFalse(any(t['original_signal_index']==2 for t in out['trades']))

    def test_full_actual_positions_never_overlap(self):
        rows,b=tiny()
        for mode in m.MODES:
            out=m.replay_symbol(rows,b,mode,start=0,end=len(rows)*m.BAR)
            last=-1
            for t in out['trades']+out['open_positions']:
                self.assertGreater(t['decision_ts'],last)
                last=t.get('exit_ts',t.get('mark_ts'))

    def test_all_raw_origins_including_end_wait_are_accounted(self):
        rows,b=tiny()
        for mode in m.MODES:
            out=m.replay_symbol(rows,b,mode,start=0,end=len(rows)*m.BAR)
            self.assertEqual(len(out['events']),len(b['signals']))
            self.assertEqual(out['audit']['completed']+out['audit']['open']+out['audit']['excluded'],len(b['signals']))
            self.assertFalse(out['events'][-1]['admission'])

    def test_original_and_shifted_exit_anchors_are_separate_factor(self):
        rows,b=tiny()
        a=m.replay_symbol(rows,b,m.MODES[2],start=0,end=len(rows)*m.BAR)
        c=m.replay_symbol(rows,b,m.MODES[3],start=0,end=len(rows)*m.BAR)
        self.assertEqual(a['reference_opportunities'],c['reference_opportunities'])
        ta=next(t for t in a['trades'] if t['original_signal_index']==2)
        tc=next(t for t in c['trades'] if t['original_signal_index']==2)
        self.assertEqual(ta['entry_ts'],tc['entry_ts'])
        self.assertEqual(tc['exit_index']-ta['exit_index'],6)
        self.assertEqual(ta['exit_anchor_index'],2);self.assertEqual(tc['exit_anchor_index'],8)

    def test_preentry_extreme_not_in_held_excursion(self):
        rows,b=tiny();rows[5].update(high=1000.,low=1.)
        out=m.replay_symbol(rows,b,m.MODES[0],start=0,end=len(rows)*m.BAR)
        t=next(t for t in out['trades'] if t['original_signal_index']==2)
        self.assertLess(t['mfe_bps'],101.);self.assertGreater(t['mae_bps'],-101.)

    def test_future_suffix_does_not_change_earlier_decisions(self):
        rows,b=tiny(); altered=deepcopy(rows)
        for row in altered[35:]:row.update(open=80.,close=80.,high=81.,low=79.)
        for mode in m.MODES:
            a=m.replay_symbol(rows,b,mode,start=0,end=len(rows)*m.BAR)
            c=m.replay_symbol(altered,b,mode,start=0,end=len(rows)*m.BAR)
            fields=('signal_index','admission','decision_ts','exclusion_reason','exclusion_known_at')
            view=lambda x:[{k:e.get(k) for k in fields} for e in x['events'] if e.get('decision_ts') is not None and e['decision_ts']<35*m.BAR]
            self.assertEqual(view(a),view(c))

    def test_invalid_ohlcv_is_not_silently_skipped(self):
        rows,b=tiny();rows[3]['close']=float('nan')
        with self.assertRaises((RuntimeError,ValueError)):
            m.replay_symbol(rows,b,m.MODES[0],start=0,end=len(rows)*m.BAR)

    def test_exact_boundary_keeps_open_mark_not_fake_fill(self):
        rows,b=tiny(21);b['signals']=[{'signal_index':8,'signal_ts':rows[8]['bar_close_ts']}]
        out=m.replay_symbol(rows,b,m.MODES[0],start=0,end=len(rows)*m.BAR)
        self.assertEqual(len(out['open_positions']),1)
        self.assertFalse(out['open_positions'][0]['terminal_liquidation'])

    def test_scope_and_attempt_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'ATTEMPT.json';m.write_new(p,b'first')
            with self.assertRaises(FileExistsError):m.write_new(p,b'second')
            self.assertEqual(p.read_bytes(),b'first')

if __name__=='__main__':unittest.main()
