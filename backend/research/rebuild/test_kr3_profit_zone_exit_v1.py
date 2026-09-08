"""Synthetic-only integration boundaries for the single profit-zone hypothesis.

No market input, economic allocation, provider API, or historical replay is used.
"""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from backend.research.rebuild import kr3_profit_zone_exit_v1 as c

COST = dict(fee_bps=10., spread_bps=2., impact_bps=3.,
            funding_p95_per_settlement_bps=4.)


class ProfitZoneTests(unittest.TestCase):
    def fixture(self, n=350, origin=242):
        rows = [dict(bar_open_ts=i*c.BAR, bar_close_ts=(i+1)*c.BAR,
                     open=100., high=101., low=99., close=100., volume=10.)
                for i in range(n)]
        bundle = dict(signals=[dict(signal_index=origin,
                                   signal_ts=rows[origin]['bar_close_ts'])],
                      ema20=[100.]*n, ema50=[99.]*n, audit={})
        rows[origin+1].update(open=100., high=104., low=100., close=103.)
        bundle['ema20'][origin+1] = 102.
        bundle['ema50'][origin+1] = 101.
        rows[origin+2].update(open=103., high=104., low=101., close=101.5)
        bundle['ema20'][origin+2] = 102.5
        bundle['ema50'][origin+2] = 101.
        if n > origin+3:
            rows[origin+3].update(open=95., high=999., low=1., close=102.)
        return rows, bundle, max(0, origin-2)*c.BAR, n*c.BAR, origin

    def run_child(self, rows, bundle, start, end, **kw):
        return c.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end,
                        cost_model=deepcopy(COST), **kw)

    def test_disabled_exact_KR3_with_midwindow_original_coordinates(self):
        rows,b,start,end,_ = self.fixture()
        self.assertEqual(self.run_child(rows,b,start,end,enabled=False),
                         c.parent.replay(rows,b,eval_start_ms=start,eval_end_ms=end))
        # Disabled remains usable without any child cost binding.
        self.assertEqual(c.replay(rows,b,eval_start_ms=start,eval_end_ms=end,enabled=False),
                         c.parent.replay(rows,b,eval_start_ms=start,eval_end_ms=end))

    def test_active_bar_is_retained_then_later_close_fills_gap_open(self):
        rows,b,start,end,i = self.fixture()
        out = self.run_child(rows,b,start,end); t = out['trades'][0]
        self.assertEqual((t['signal_index'],t['entry_index'],t['exit_index']),(i,i+1,i+3))
        self.assertEqual((t['entry_price'],t['exit_price']),(100.,95.))
        self.assertAlmostEqual(t['gross_bps'],-500.)
        self.assertEqual(t['exit_reason'],c.GUARD_EXIT)
        self.assertEqual(t['profit_zone_state']['armed_index'],i+1)
        self.assertEqual(t['exit_trigger']['signal_index'],i+2)
        self.assertEqual(t['exit_trigger']['prior_protected_line'],102.)
        arm = [x for x in out['trace'] if x['kind']==c.GUARD_ARM]
        trigger = [x for x in out['trace'] if x['kind']==c.GUARD_TRIGGER]
        self.assertEqual([x['index'] for x in arm],[i+1])
        self.assertEqual([x['index'] for x in trigger],[i+2])
        self.assertLess(arm[0]['ts'],trigger[0]['ts'])
        self.assertEqual(t['frozen_signal_low'],rows[i]['low'])

    def test_entry_plus_profit_alone_does_not_arm(self):
        rows,b,start,end,i = self.fixture()
        for j in range(i+1,len(rows)):
            rows[j].update(open=100.,low=99.,high=103.,close=101.)
            b['ema20'][j]=100.;b['ema50'][j]=99.
        got=self.run_child(rows,b,start,end)
        self.assertFalse(any(t['kind']==c.GUARD_ARM for t in got['trace']))
        p=c.parent.replay(rows,b,eval_start_ms=start,eval_end_ms=end)
        own=deepcopy(got['trades'])
        for t in own:t.pop('profit_zone_state')
        self.assertEqual(own,p['trades'])

    def test_current_line_increase_cannot_trigger_retroactively(self):
        rows,b,start,end,i=self.fixture()
        rows[i+2].update(close=103.,low=102.,high=105.)
        b['ema20'][i+2]=104.;b['ema50'][i+2]=101.
        rows[i+3].update(open=103.,close=104.,low=103.,high=105.)
        b['ema20'][i+3]=103.;b['ema50'][i+3]=101.
        rows[i+4].update(open=104.,close=103.9,low=103.,high=105.)
        b['ema20'][i+4]=103.;b['ema50'][i+4]=101.
        out=self.run_child(rows,b,start,end)
        trigger=next(t for t in out['trace'] if t['kind']==c.GUARD_TRIGGER)
        self.assertEqual(trigger['index'],i+4)
        self.assertEqual(trigger['prior_protected_line'],104.)
        self.assertEqual(out['trades'][0]['exit_index'],i+5)

    def test_both_arming_comparisons_are_strict(self):
        row=dict(close=101.,bar_close_ts=4*c.BAR)
        cost=c.decision_cost(3*c.BAR,4*c.BAR,COST)
        initial=dict(armed_index=None,armed_ts=None,protected_line=None,last_index=None,exit_requested=False)
        covered=100.*(1.+cost['cost_bps']/10000.)
        for close,e20,e50 in [(101.,101.,99.),(101.,100.5,100.5),(101.,covered,99.)]:
            st,hit=c.guard_observation(initial,row=dict(row,close=close),index=3,
                ema20=e20,ema50=e50,entry_price=100.,cost=cost)
            self.assertIsNone(st['armed_index']);self.assertFalse(hit)

    def test_line_does_not_decrease_or_exit_at_equality(self):
        cost=c.decision_cost(3*c.BAR,5*c.BAR,COST)
        initial=dict(armed_index=3,armed_ts=4*c.BAR,protected_line=103.,last_index=3,exit_requested=False)
        st,hit=c.guard_observation(initial,row=dict(close=103.,bar_close_ts=5*c.BAR),
            index=4,ema20=102.,ema50=101.,entry_price=100.,cost=cost)
        self.assertFalse(hit);self.assertEqual(st['protected_line'],103.)
        self.assertEqual(initial['last_index'],3)

    def test_pending_intent_is_not_emitted_twice_after_state_roundtrip(self):
        state=dict(armed_index=3,armed_ts=4*c.BAR,protected_line=102.,last_index=4,exit_requested=True)
        restored=json.loads(json.dumps(state))
        got,hit=c.guard_observation(restored,row=dict(close=100.,bar_close_ts=6*c.BAR),
            index=5,ema20=102.,ema50=101.,entry_price=100.,
            cost=c.decision_cost(3*c.BAR,6*c.BAR,COST))
        self.assertFalse(hit);self.assertTrue(got['exit_requested'])
        self.assertEqual(restored,state)

    def test_existing_ema_exit_has_priority(self):
        rows,b,start,end,i=self.fixture();b['ema20'][i+2]=100.
        out=self.run_child(rows,b,start,end)
        self.assertEqual(out['trades'][0]['exit_reason'],'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN')
        self.assertFalse(any(t['kind']==c.GUARD_TRIGGER for t in out['trace']))

    def test_existing_allowed_low_exit_has_priority(self):
        rows,b,start,end,i=self.fixture()
        rows[i+2].update(close=98.,low=97.)
        b['ema20'][i+2]=100.;b['ema50'][i+2]=99.
        out=self.run_child(rows,b,start,end)
        self.assertEqual(out['trades'][0]['exit_reason'],c.m2.EXIT)
        self.assertFalse(any(t['kind']==c.GUARD_TRIGGER for t in out['trace']))

    def running_fixture(self, extended):
        rows,b,start,end,i=self.fixture(n=70,origin=2)
        for j in range(i+1,len(rows)):
            rows[j].update(open=105.,close=105.,low=100.,high=106.)
            b['ema20'][j]=102.;b['ema50'][j]=101.
        rows[i+1]['open']=100.
        if not extended:
            j=i+c.HOLD-1;rows[j]['close']=104.;b['ema20'][j]=104.
        return rows,b,start,end,i

    def test_original_timeout_has_priority_over_same_bar_guard(self):
        rows,b,start,end,i=self.running_fixture(False)
        rows[i+c.HOLD]['close']=103.
        out=self.run_child(rows,b,start,end)
        self.assertEqual(out['trades'][0]['exit_index'],i+c.HOLD)
        self.assertTrue(any(t['kind']=='ORIGINAL_TIME_STOP_CLOSE' for t in out['trace']))
        self.assertFalse(any(t['kind']==c.GUARD_TRIGGER for t in out['trace']))

    def test_existing_runner_exit_has_priority(self):
        rows,b,start,end,i=self.running_fixture(True)
        rows[i+c.HOLD]['close']=101.5
        out=self.run_child(rows,b,start,end)
        self.assertEqual(out['trades'][0]['exit_reason'],c.EXIT)
        self.assertEqual(out['trades'][0]['exit_index'],i+c.HOLD+1)
        self.assertFalse(any(t['kind']==c.GUARD_TRIGGER for t in out['trace']))

    def test_existing_extension_cap_has_priority(self):
        rows,b,start,end,i=self.running_fixture(True)
        rows[i+2*c.HOLD]['close']=101.5
        out=self.run_child(rows,b,start,end)
        self.assertEqual(out['trades'][0]['exit_index'],i+2*c.HOLD)
        self.assertTrue(any(t['kind']=='RUNNER_FINAL_TIME_STOP_CLOSE' for t in out['trace']))

    def test_future_hlc_and_suffix_do_not_change_completed_trade(self):
        rows,b,start,end,i=self.fixture()
        first=self.run_child(rows,b,start,end)['trades']
        rows[i+3].update(high=1000000.,low=.001,close=101.)
        for j in range(i+4,len(rows)):
            rows[j].update(open=20.,close=20.,high=21.,low=19.)
            b['ema20'][j]=20.;b['ema50'][j]=19.
        self.assertEqual(first,self.run_child(rows,b,start,end)['trades'])
        self.assertLess(first[0]['mfe_bps'],500.)
        self.assertGreater(first[0]['mae_bps'],-501.)

    def test_pending_boundary_preserves_guard_state_and_original_coordinates(self):
        rows,b,start,_,i=self.fixture();end=(i+3)*c.BAR
        with self.assertRaises((ValueError,RuntimeError)):
            self.run_child(rows,b,start,end)
        rows=rows[:i+3]
        for key in ('ema20','ema50'):b[key]=b[key][:i+3]
        out=self.run_child(rows,b,start,end)
        self.assertEqual(out['trades'],[])
        t=out['open_positions'][0]
        self.assertEqual(t['signal_index'],i)
        self.assertEqual(t['mark_index'],i+2)
        self.assertEqual(t['mark_ts'],end)
        self.assertEqual(t['pending_exit_signal_ts'],end)
        self.assertTrue(t['pending_exit_trigger']['profit_zone_condition'])
        self.assertTrue(t['profit_zone_state']['exit_requested'])
        self.assertFalse(t['terminal_liquidation'])
        self.assertNotIn('exit_price',t)
        self.assertFalse(any(t['kind']==c.GUARD_EXIT for t in out['trace']))

    def test_armed_last_bar_is_open_without_fabricated_pending(self):
        rows,b,start,_,i=self.fixture();end=(i+2)*c.BAR;rows=rows[:i+2]
        for key in ('ema20','ema50'):b[key]=b[key][:i+2]
        out=self.run_child(rows,b,start,end);t=out['open_positions'][0]
        self.assertEqual(out['trades'],[])
        self.assertEqual(t['profit_zone_state']['armed_index'],i+1)
        self.assertIsNone(t['pending_exit_signal_ts'])

    def test_reference_reservation_is_not_released_by_child_exit(self):
        rows,b,start,end,i=self.fixture()
        for j in (i+4,i+6,i+18):
            b['signals'].append(dict(signal_index=j,signal_ts=rows[j]['bar_close_ts']))
        child=self.run_child(rows,b,start,end)
        parent=c.parent.replay(rows,b,eval_start_ms=start,eval_end_ms=end)
        for k in ('reference_events','reference_opportunities','reference_checkpoint'):
            self.assertEqual(child[k],parent[k],k)
        self.assertEqual(len(child['events']),len(b['signals']))

    def test_serialized_reference_checkpoint_restart_has_no_duplicates(self):
        rows,b,start,end,i=self.fixture()
        partial=c.parent.parent.causal_clock(rows,b,eval_start_ms=start,eval_end_ms=end,stop_after_index=i+1)
        restored=json.loads(json.dumps(partial));before=deepcopy(restored)
        fresh=self.run_child(rows,b,start,end)
        self.assertEqual(self.run_child(rows,b,start,end,reference_checkpoint=restored),fresh)
        self.assertEqual(restored,before)
        self.assertEqual(self.run_child(rows,b,start,end,reference_checkpoint=json.loads(json.dumps(fresh['reference_checkpoint']))),fresh)

    def test_serialized_guard_observation_matches_uninterrupted_state(self):
        rows,b,_,_,i=self.fixture()
        initial=dict(armed_index=None,armed_ts=None,protected_line=None,last_index=None,exit_requested=False)
        entry=rows[i+1]['bar_open_ts']
        def step(st,j):
            return c.guard_observation(st,row=rows[j],index=j,ema20=b['ema20'][j],
                ema50=b['ema50'][j],entry_price=100.,cost=c.decision_cost(entry,rows[j]['bar_close_ts'],COST))
        armed,_=step(initial,i+1)
        self.assertEqual(step(armed,i+2),step(json.loads(json.dumps(armed)),i+2))

    def test_input_immutability_and_success_hook_restoration(self):
        rows,b,start,end,_=self.fixture();before=deepcopy((rows,b,COST))
        hooks=(c.parent.kr.path,c.d._path)
        for enabled in (True,False):
            self.run_child(rows,b,start,end,enabled=enabled)
            self.assertEqual((rows,b,COST),before)
            self.assertEqual((c.parent.kr.path,c.d._path),hooks)

    def test_exception_restores_both_hooks(self):
        rows,b,start,end,_=self.fixture();before=deepcopy((rows,b,COST))
        hooks=(c.parent.kr.path,c.d._path)
        with patch.object(c,'guard_observation',side_effect=RuntimeError('SYNTHETIC_INTERRUPT')):
            with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_INTERRUPT'):
                self.run_child(rows,b,start,end)
        self.assertEqual((c.parent.kr.path,c.d._path),hooks)
        self.assertEqual((rows,b,COST),before)
        self.assertEqual(self.run_child(rows,b,start,end)['trades'][0]['exit_reason'],c.GUARD_EXIT)

    def test_cost_uses_only_elapsed_settlements_and_floor(self):
        # entry < settlement <= decision; no eventual exit is available.
        before=deepcopy(COST)
        early=c.decision_cost(3*c.BAR,4*c.BAR,COST)
        later=c.decision_cost(3*c.BAR,6*c.BAR,COST)
        self.assertEqual((early['funding_settlements_crossed'],early['funding_bps']),(1,4.))
        self.assertEqual(early['frozen_floor_reserve_bps'],1.)
        self.assertEqual(early['cost_bps'],20.)
        self.assertEqual((later['funding_settlements_crossed'],later['funding_bps']),(2,8.))
        self.assertEqual(later['cost_bps'],23.)
        self.assertFalse(early['actual_historical_execution_cost_evidence'])
        self.assertEqual(COST,before)
        self.assertEqual(c.decision_cost(4*c.BAR,4*c.BAR,COST)['funding_settlements_crossed'],0)

    def test_arming_trace_cost_uses_exact_observation_timestamp(self):
        rows,b,start,end,i=self.fixture()
        out=self.run_child(rows,b,start,end)
        arm=next(t for t in out['trace'] if t['kind']==c.GUARD_ARM)
        expected=c.decision_cost(rows[i+1]['bar_open_ts'],rows[i+1]['bar_close_ts'],COST)
        self.assertEqual(arm['decision_cost'],expected)
        self.assertEqual(arm['decision_cost']['model_accrual_cutoff_ts'],arm['ts'])
        self.assertNotEqual(arm['ts'],out['trades'][0]['exit_ts'])

    def test_missing_invalid_cost_and_bool_are_rejected(self):
        rows,b,start,end,_=self.fixture()
        for binding in (None,{},dict(COST,fee_bps=float('nan')),dict(COST,impact_bps=-1.)):
            with self.assertRaises(ValueError):
                c.replay(rows,b,eval_start_ms=start,eval_end_ms=end,cost_model=binding)
        with self.assertRaises(ValueError):self.run_child(rows,b,start,end,enabled=1)
        with self.assertRaises(ValueError):c.decision_cost(3*c.BAR,2*c.BAR,COST)

    def test_observation_rejects_future_cost_and_noncontiguous_state(self):
        state=dict(armed_index=3,armed_ts=4*c.BAR,protected_line=102.,last_index=3,exit_requested=False)
        kwargs=dict(row=dict(close=103.,bar_close_ts=5*c.BAR),index=4,ema20=102.,ema50=101.,entry_price=100.)
        with self.assertRaisesRegex(ValueError,'COST_CUTOFF'):
            c.guard_observation(state,**kwargs,cost=c.decision_cost(3*c.BAR,6*c.BAR,COST))
        kwargs['index']=5
        with self.assertRaisesRegex(ValueError,'NONCONTIGUOUS'):
            c.guard_observation(state,**kwargs,cost=c.decision_cost(3*c.BAR,5*c.BAR,COST))

    def test_reference_clock_does_not_evaluate_candidate_path(self):
        rows,b,start,end,_=self.fixture()
        with patch.object(c,'path',side_effect=AssertionError('CANDIDATE_PATH_FORBIDDEN')):
            clock=c.parent.parent.causal_clock(rows,b,eval_start_ms=start,eval_end_ms=end)
        self.assertTrue(clock['reference_events'])
        self.assertEqual((c.HOLD,c.BAR),(12,14400000))


if __name__=='__main__':
    unittest.main()
