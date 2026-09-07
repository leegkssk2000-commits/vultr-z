"""TPC1 synthetic-only state, exact-parent, restart and accounting contracts."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from backend.research.rebuild import trend_primary_combined_v1 as x
from backend.research.rebuild import trend_primary_protection_v1 as p
from backend.research.rebuild import top5_native_finite_runner_v1 as n
from backend.research.rebuild.test_top5_mechanism_b_v1 import fixture
from backend.research.rebuild.test_break_channel_source_v1 import policy

COST={'fee_bps':10.,'spread_bps':1.,'impact_bps':2.,'funding_p95_per_settlement_bps':3.}
ZERO_FUNDING={**COST,'funding_p95_per_settlement_bps':0.}
FILL_KINDS={'SL','TP','TIMEOUT','PROTECTION_TOUCH','PROTECTION_GAP_OPEN',
            'NATIVE_RUNNER_NEXT_OPEN','PENDING_EXIT_GAP_THROUGH_STOP'}


def protected_fixture(side='long',count=130):
    rows,c,e=fixture(side,count);sign=1 if side=='long' else -1
    for r in rows:
        r.update(open=100.+3*sign,close=100.+4*sign,
                 low=102. if sign>0 else 95.,high=105. if sign>0 else 98.)
    rows[1].update(open=100.,low=96. if sign>0 else 95.,high=105. if sign>0 else 104.)
    c.st[1]=(100.+sign,sign)
    return rows,c,e


def call(rows,c,e,**kw):
    return x.path(rows,e,c,cost_binding=kw.pop('cost_binding',COST),**kw)


def charge(raw,rows):
    pol=policy();pol['development_interval_ms']=[0,len(rows)*n.HOUR]
    return x.a.account.charge_result(raw,'TEST',n.LANES['TPR1'],'TPC1',pol,{'TEST':COST},rows)


class ExactParentTests(unittest.TestCase):
    def test_all_three_ablations_complete_raw_trace_checkpoint_byte_parity(self):
        for side in ('long','short'):
            for scenario in ('base','protection','stop','tp','trend_loss'):
                rows,c,e=protected_fixture(side) if scenario=='protection' else fixture(side)
                if scenario=='stop':rows[49]['low' if side=='long' else 'high']=e['sl']
                if scenario=='tp':e['tp']=103. if side=='long' else 97.
                if scenario=='trend_loss':c.st[55]=(100.,-1 if side=='long' else 1)
                for cut in (2,49,50,56,98,130):
                    rr=rows[:cut]
                    for extension,protection in ((True,False),(False,True),(False,False)):
                        with self.subTest(side=side,scenario=scenario,cut=cut,flags=(extension,protection)):
                            expected=p.path(rr,e,c,cost_binding=COST) if protection else n.path(rr,e,c,enabled=extension)
                            actual=call(rr,c,e,extension_enabled=extension,protection_enabled=protection)
                            self.assertEqual(actual,expected)
                            self.assertEqual(x.a.old.probe.canonical(actual),x.a.old.probe.canonical(expected))
                            restored=call(rr,c,e,extension_enabled=extension,protection_enabled=protection,
                                          checkpoint=json.loads(json.dumps(expected[3])))
                            parent_ck=json.loads(json.dumps(expected[3]))
                            parent_restored=p.path(rr,e,c,cost_binding=COST,checkpoint=parent_ck) if protection else n.path(rr,e,c,enabled=extension,checkpoint=parent_ck)
                            self.assertEqual(parent_restored,restored)
                            self.assertEqual(x.a.old.probe.canonical(expected),x.a.old.probe.canonical(restored))

    def test_all_three_ablations_complete_replay_and_fixed_parity(self):
        for side in ('long','short'):
            rows,c,e=protected_fixture(side)
            tape=[dict(e,signal_index=i,signal_ts=(i+1)*n.HOUR) for i in (0,1,2,3,55,105)]
            for fixed in (None,[0,2,55]):
                for extension,protection in ((True,False),(False,True),(False,False)):
                    expected=p.replay(rows,tape,c,COST,fixed_indices=fixed) if protection else n.replay(rows,tape,c,enabled=extension,fixed_indices=fixed)
                    actual=x.replay(rows,tape,c,COST,extension_enabled=extension,protection_enabled=protection,fixed_indices=fixed)
                    self.assertEqual(actual,expected)

    def test_flags_and_native_horizon_fail_closed(self):
        rows,c,e=fixture()
        for flags in ({'extension_enabled':1},{'protection_enabled':None}):
            with self.assertRaisesRegex(RuntimeError,'TPC1_ENABLED_BOOL'):call(rows,c,e,**flags)
            with self.assertRaisesRegex(RuntimeError,'TPC1_ENABLED_BOOL'):x.replay(rows,[e],c,COST,**flags)
        e['timeout']['bars']=47
        with self.assertRaisesRegex(RuntimeError,'NATIVE_H48_DRIFT'):call(rows,c,e)


class CombinedTimingTests(unittest.TestCase):
    def test_original49_extension97_and_exact_native_decision(self):
        for side in ('long','short'):
            rows,c,e=fixture(side)
            result=call(rows,c,e);native=n.path(rows,e,c)
            self.assertEqual(result[0]['exit_index'],97)
            self.assertEqual(result[0]['runner_extension'],native[0]['runner_extension'])
            self.assertEqual(result[2],native[2])
            self.assertEqual(sum(t['kind']=='NATIVE_RUNNER_DECISION' for t in result[2]),1)
            for mode in ('profit','direction','line','ema','slope'):
                rr,cc,ee=fixture(side)
                if mode=='profit':rr[48]['close']=100.
                if mode=='direction':cc.st[48]=(100.,-1 if side=='long' else 1)
                if mode=='line':cc.st[48]=(rr[48]['close'],1 if side=='long' else -1)
                if mode=='ema':cc.ema[48]=rr[48]['close']
                if mode=='slope':cc.ema[48]=cc.ema[47]
                self.assertEqual(call(rr,cc,ee)[0]['exit_index'],49)

    def test_unavailable_same_bar_line_cannot_fill_and_exit_stops_extension(self):
        for side in ('long','short'):
            rows,c,e=protected_fixture(side);sign=1 if side=='long' else -1
            rows[2]['low' if sign>0 else 'high']=100.
            t,_,trace,_=call(rows,c,e)
            self.assertEqual((t['exit_index'],t['exit_price'],t['exit_reason']),(2,100.+sign,'PROTECTION_TOUCH'))
            self.assertEqual(trace[0]['effective_from_index'],2)
            self.assertFalse(t['runner_extension']['decided'])
            self.assertEqual(sum(z['kind'] in FILL_KINDS for z in trace),1)

    def test_monotonic_levels_continue_through_extension(self):
        for side in ('long','short'):
            rows,c,e=protected_fixture(side);sign=1 if side=='long' else -1
            c.st[2]=(100.+.5*sign,sign)
            c.st[3]=(200. if sign>0 else 1.,-sign)
            c.st[48]=(100.+1.25*sign,sign)
            c.st[55]=(100.+1.5*sign,sign)
            t,_,trace,_=call(rows,c,e)
            levels=[z['level'] for z in trace if 'level' in z]
            self.assertEqual(levels,[100.+sign,100.+1.25*sign,100.+1.5*sign])
            self.assertEqual(t['exit_index'],97)
            self.assertTrue(t['runner_extension']['allowed'])
            self.assertEqual(t['protection_level'],levels[-1])

    def test_strict_hurdle_and_accrued_funding_use_original_entry(self):
        rows,c,e=fixture();c.st[1]=(100.2,1)
        self.assertFalse(any(z['kind']=='PROTECTION_ACTIVATE' for z in call(rows,c,e,cost_binding=ZERO_FUNDING)[2]))
        rows,c,e=protected_fixture();c.st[55]=(101.5,1)
        _,_,trace,_=call(rows,c,e)
        update=next(z for z in trace if z['kind']=='PROTECTION_UPDATE')
        cost=x.a.old.probe.cost_components(rows[1]['bar_open_ts'],rows[55]['bar_close_ts'],COST)
        self.assertEqual(update['cost_hurdle_bps'],max(20.,cost['cost_bps']))
        self.assertEqual(update['funding_boundaries_observed'],cost['funding_settlements_crossed'])
        self.assertGreater(update['funding_boundaries_observed'],0)
        self.assertEqual(update['cost_available_at'],rows[55]['bar_close_ts'])

    def test_every_priority_collision_has_one_fill(self):
        for side in ('long','short'):
            for reason in ('PROTECTION_GAP_OPEN','SL','TP','PROTECTION_TOUCH'):
                rows,c,e=protected_fixture(side);sign=1 if side=='long' else -1
                e['tp']=106. if sign>0 else 94.
                row=rows[2]
                row['low' if sign>0 else 'high']=100.
                if reason in ('PROTECTION_GAP_OPEN','SL'):
                    row['low' if sign>0 else 'high']=e['sl']
                if reason in ('PROTECTION_GAP_OPEN','SL','TP'):
                    row['high' if sign>0 else 'low']=e['tp']
                if reason=='PROTECTION_GAP_OPEN':row['open']=89. if sign>0 else 111.
                t,_,trace,_=call(rows,c,e)
                self.assertEqual(t['exit_reason'],reason)
                self.assertEqual(sum(z['kind'] in FILL_KINDS for z in trace),1)
                self.assertFalse(any(z.get('index')==2 and 'level' in z for z in trace))

    def test_pending_and_new_protection_update_same_close_gap_next_open(self):
        for side in ('long','short'):
            for stop_gap in (False,True):
                rows,c,e=protected_fixture(side);sign=1 if side=='long' else -1
                c.ema[49]=105. if sign>0 else 95.
                c.st[49]=(100.+1.5*sign,sign)
                rows[50]['open']=(89. if sign>0 else 111.) if stop_gap else 100.+.5*sign
                t,_,trace,_=call(rows,c,e)
                self.assertEqual(t['exit_reason'],'PENDING_EXIT_GAP_THROUGH_STOP' if stop_gap else 'NATIVE_RUNNER_NEXT_OPEN')
                self.assertEqual(t['exit_index'],50)
                self.assertTrue(any(z['kind']=='PROTECTION_UPDATE' and z['index']==49 for z in trace))
                self.assertTrue(any(z['kind']=='NATIVE_RUNNER_TREND_LOSS_CLOSE' and z['index']==49 for z in trace))
                self.assertEqual(sum(z['kind'] in FILL_KINDS for z in trace),1)
                rows[50].update(high=10000.,low=.01,close=9999.)
                self.assertEqual(t,call(rows,c,e)[0])
                raw=x.replay(rows,[e],c,COST);charged=charge(raw,rows)
                self.assertEqual(len(charged['trades']),1)
                trade=charged['trades'][0]
                parts=x.a.old.probe.cost_components(trade['entry_ts'],trade['exit_ts'],COST)
                self.assertEqual(trade['cost_bps'],max(20.,parts['cost_bps']))
                self.assertEqual(trade['funding_bps'],parts['funding_bps'])
                self.assertAlmostEqual(trade['net_bps'],trade['gross_bps']-trade['cost_bps'])

    def test_active_gap_exit_ignores_unavailable_hlc(self):
        rows,c,e=protected_fixture();rows[2]['open']=100.
        t=call(rows,c,e)[0];rows[2].update(high=9999.,low=.01,close=9998.)
        self.assertEqual(t,call(rows,c,e)[0])

    def test_cap_precedes_new_updates_and_protection_touch_precedes_cap(self):
        rows,c,e=protected_fixture();c.st[97]=(101.5,1)
        t,_,trace,_=call(rows,c,e)
        self.assertEqual(t['exit_reason'],'TIMEOUT')
        self.assertFalse(any(z.get('index')==97 and 'level' in z for z in trace))
        rows[97]['low']=100.5
        self.assertEqual(call(rows,c,e)[0]['exit_reason'],'PROTECTION_TOUCH')

    def test_stopped_bar_has_no_extension_or_protection_update(self):
        rows,c,e=fixture();c.st[48]=(101.,1);rows[48]['low']=89.
        t,_,trace,_=call(rows,c,e)
        self.assertEqual(t['exit_reason'],'SL')
        self.assertFalse(t['runner_extension']['decided'])
        self.assertFalse(any(z['kind'].startswith('PROTECTION_') for z in trace))


class RestartAccountingTests(unittest.TestCase):
    def test_restart_before_decision_after_update_pending_and_closed(self):
        for side in ('long','short'):
            rows,c,e=protected_fixture(side);sign=1 if side=='long' else -1
            c.st[55]=(100.+1.5*sign,sign);c.ema[55]=105. if sign>0 else 95.
            rows[56]['open']=100.
            full=call(rows,c,e)
            for cut in (2,45,49,50,55,56,57,70,130):
                ck=call(rows[:cut],c,e)[3]
                self.assertEqual(full,call(rows,c,e,checkpoint=json.loads(json.dumps(ck))))

    def test_checkpoint_rejects_origin_cost_and_consumed_feature_drift(self):
        rows,c,e=protected_fixture();ck=call(rows[:40],c,e)[3]
        for altered in ('origin','cost','rows','line','ema'):
            rr,cc,ee=deepcopy(rows),deepcopy(c),deepcopy(e);cost=deepcopy(COST)
            if altered=='origin':ee['symbol']='OTHER'
            if altered=='cost':cost['fee_bps']+=1
            if altered=='rows':rr[30]['close']+=1
            if altered=='line':cc.st[30]=(101.5,1)
            if altered=='ema':cc.ema[30]+=1
            with self.assertRaisesRegex(RuntimeError,'PREFIX'):call(rr,cc,ee,cost_binding=cost,checkpoint=ck)
        with self.assertRaisesRegex(RuntimeError,'PREFIX'):call(rows,c,e,protection_enabled=False,checkpoint=ck)
        with self.assertRaisesRegex(RuntimeError,'PREFIX'):call(rows,c,e,extension_enabled=False,checkpoint=ck)

    def test_future_data_cannot_change_completed_prefix_decision_hash(self):
        rows,c,e=protected_fixture();before=call(rows[:49],c,e)
        altered=deepcopy(c);altered.st[49:]=[(900.,-1)]*(len(rows)-49)
        altered.ema[49:]=[10000.]*(len(rows)-49)
        self.assertEqual(before,call(rows[:49],altered,e))
        # Final loss and huge post-exit excursion are diagnostics, never inputs.
        rows[49]['open']=100.;closed=call(rows,c,e)
        rows[70].update(open=9999.,close=.01,high=10000.,low=.01)
        self.assertEqual(closed,call(rows,c,e))

    def test_strict_end_cap_and_stop_restore_original_fill(self):
        for side in ('long','short'):
            rows,c,e=fixture(side)
            for stop in (False,True):
                rr=deepcopy(rows)
                if stop:rr[97]['low' if side=='long' else 'high']=e['sl']
                t,o,_,ck=call(rr[:98],c,e)
                self.assertIsNone(t);self.assertFalse(o['terminal_liquidation'])
                self.assertEqual(o['boundary_native_fill_reason'],'SL' if stop else None)
                self.assertEqual((t,o),call(rr[:98],c,e,checkpoint=json.loads(json.dumps(ck)))[:2])
                if stop:self.assertEqual(o['mark_price'],e['sl'])
                self.assertEqual(call(rr,c,e),call(rr,c,e,checkpoint=json.loads(json.dumps(ck))))

    def test_boundary_protection_fill_censored_and_last_open_fill_closed(self):
        rows,c,e=protected_fixture();rows[2]['low']=100.
        t,o,_,ck=call(rows[:3],c,e)
        self.assertIsNone(t);self.assertEqual(o['boundary_native_fill_reason'],'PROTECTION_TOUCH')
        self.assertEqual(o['mark_price'],101.)
        self.assertEqual(call(rows,c,e),call(rows,c,e,checkpoint=json.loads(json.dumps(ck))))
        rows[2]['open']=100.
        self.assertIsNotNone(call(rows[:3],c,e)[0])

    def test_extended_cost_recomputed_and_unfinished_funding_marked(self):
        rows,c,e=fixture()
        raw=x.replay(rows,[e],c,COST);native=n.replay(rows,[e],c,enabled=False)
        extended=charge(raw,rows)['trades'][0];parent=charge(native,rows)['trades'][0]
        self.assertGreater(extended['funding_bps'],parent['funding_bps'])
        self.assertGreater(extended['cost_bps'],parent['cost_bps'])
        parts=x.a.old.probe.cost_components(extended['entry_ts'],extended['exit_ts'],COST)
        self.assertEqual(extended['cost_bps'],parts['cost_bps'])
        short_rows=rows[:80];raw=x.replay(short_rows,[e],c,COST)
        open_position=charge(raw,short_rows)['open_observations'][0]
        self.assertEqual(open_position['mark_ts'],80*n.HOUR)
        self.assertGreater(open_position['modeled_funding_accrued_bps'],parent['funding_bps'])
        self.assertFalse(open_position['terminal_liquidation'])

    def test_actual_extended_ownership_exact_cooldown_and_tail(self):
        rows,c,e=fixture()
        tape=[dict(e,signal_index=i,signal_ts=(i+1)*n.HOUR) for i in (0,49,96,97,98,99,105)]
        out=x.replay(rows,tape,c,COST)
        self.assertEqual([z['status'] for z in out['events']],
                         ['COMPLETED','EXCLUDED','EXCLUDED','EXCLUDED','EXCLUDED','CENSORED','EXCLUDED'])
        self.assertEqual(len(out['trades']),1);self.assertEqual(len(out['open_positions']),1)
        fixed=x.replay(rows,tape,c,COST,fixed_indices=[0,49,99])
        self.assertEqual(len(fixed['trades'])+len(fixed['open_positions']),3)
        self.assertEqual(out['audit']['maximum_entry_bar_inclusive_count'],97)
        self.assertEqual(out['audit']['same_bar_high_low_order'],'UNKNOWN')

    def test_actual_protection_exit_releases_only_after_native_cooldown(self):
        rows,c,e=protected_fixture();rows[2]['open']=100.
        tape=[dict(e,signal_index=i,signal_ts=(i+1)*n.HOUR) for i in (0,1,2,3,4)]
        out=x.replay(rows,tape,c,COST)
        self.assertEqual([z['status'] for z in out['events'][:4]],['COMPLETED','EXCLUDED','EXCLUDED','EXCLUDED'])
        self.assertNotEqual(out['events'][4]['status'],'EXCLUDED')

    def test_native_binding_restored_after_success_or_error(self):
        rows,c,e=fixture();original=n.path
        x.replay(rows,[e],c,COST);self.assertIs(n.path,original)
        with patch.object(x,'path',side_effect=RuntimeError('synthetic')):
            with self.assertRaisesRegex(RuntimeError,'synthetic'):x.replay(rows,[e],c,COST)
        self.assertIs(n.path,original)


if __name__=='__main__':unittest.main()
