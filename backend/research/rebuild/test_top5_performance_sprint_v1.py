"""Synthetic only: timing, occupancy, unchanged parents and accounting bridges."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.research.rebuild import keltner_kr1_v1 as kr
from backend.research.rebuild import q0_qf1_v1 as qf
from backend.research.rebuild import top5_sprint_metrics_v1 as metrics
from backend.research.rebuild import parallel_exit_dev_v1 as account
from backend.research.rebuild.test_parallel_exit_keltner_v1 import bars, bundle
from backend.research.rebuild.test_break_channel_source_v1 import policy, COSTS


def krun(rows, b=None, **kw):
    return kr.replay(rows,b or bundle(rows,[0]),eval_start_ms=0,
        eval_end_ms=rows[-1]['bar_close_ts'],**kw)


def trend(n=40):
    rows=bars(n)
    for row in rows[1:]: row.update(close=103., high=104.)
    return rows


def qrows(closes):
    rows=bars(6*len(closes))
    for i,v in enumerate(closes):
        for row in rows[i*6:(i+1)*6]: row.update(open=v,close=v,high=v+.1,low=v-.1)
    return rows


def qrun(rows, **kw):
    end=rows[-1]['bar_close_ts']; daily,b=qf.build_bundle(rows,0,end)
    return qf.replay(rows,daily,b,eval_start_ms=0,eval_end_ms=end,**kw)


class KR1Tests(unittest.TestCase):
    def test_disabled_exact_M2_and_inputs_immutable(self):
        rows=trend(); b=bundle(rows,[0,3,13,27]); before=deepcopy((rows,b))
        self.assertEqual(krun(rows,b,enabled=False),kr.m2.replay(rows,b,eval_start_ms=0,eval_end_ms=40*kr.BAR))
        krun(rows,b); self.assertEqual(before,(rows,b)); self.assertIs(kr.d._path,kr.m2.ORIGINAL_PATH)

    def test_t_minus_one_prefix_and_no_t_close_lookahead(self):
        rows=trend(); a=krun(rows); prefix=krun(rows[:12])
        decision=lambda r:[t for t in r['trace'] if t['kind']==kr.DECISION]
        self.assertEqual(decision(a),decision(prefix))
        self.assertEqual(decision(a)[0]['index'],11)
        rows[12].update(close=1.,low=1.)
        self.assertEqual(decision(a),decision(krun(rows)))
        rows[11].update(close=100.,low=98.); rows[12].update(close=1000.,high=1001.)
        t=krun(rows)['trades'][0]; self.assertEqual(t['exit_index'],12)
        self.assertFalse(t['runner_extension']['allowed'])

    def test_exact_once_24_bound_and_strict_end(self):
        t=krun(trend())['trades'][0]
        self.assertEqual(t['exit_index'],24)
        self.assertEqual(len([x for x in krun(trend())['trace'] if x['kind']==kr.DECISION]),1)
        o=krun(trend(25))['open_positions'][0]
        self.assertEqual(o['runner_planned_exit_index'],24); self.assertFalse(o['terminal_liquidation'])
        self.assertIsNone(o['pending_exit_signal_ts'])

    def test_prior_M2_and_D_orders_win_at_t_minus_one(self):
        for d in (False,True):
            rows=trend(); rows[11].update(close=97.,low=96.); b=bundle(rows,[0])
            if d:b['ema20'][11]=99.
            t=krun(rows,b)['trades'][0]
            self.assertEqual(t['exit_ts'],12*kr.BAR)
            self.assertFalse(t['runner_extension']['decided'])
            self.assertEqual(t['exit_reason'],'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN' if d else kr.m2.EXIT)

    def test_runner_next_open_no_future_HLC_and_priority(self):
        for mode in ('RUNNER','M2','D'):
            rows=trend(); rows[12].update(close=101. if mode=='RUNNER' else 97.,low=96.)
            b=bundle(rows,[0]);
            if mode=='D': b['ema20'][12]=99.
            rows[13].update(open=95.,low=94.)
            a=krun(rows,b)['trades'][0]
            self.assertEqual(a['exit_reason'],{'RUNNER':kr.EXIT,'M2':kr.m2.EXIT,'D':'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN'}[mode])
            self.assertEqual((a['exit_index'],a['exit_price']),(13,95.))
            rows[13].update(close=500.,high=1000.,low=1.)
            self.assertEqual(a,krun(rows,b)['trades'][0])

    def test_suppressed_never_rearms_in_runner(self):
        rows=trend(); b=bundle(rows,[0]); rows[2].update(close=97.,low=96.); b['ema50'][2]=96.
        rows[12].update(close=97.,low=96.); b['ema20'][12]=96.; b['ema50'][12]=95.
        t=krun(rows,b)['trades'][0]
        self.assertEqual(t['exit_index'],24); self.assertEqual(t['low_exit_state']['status'],kr.SUPPRESSED)

    def test_pending_boundary_not_forced_or_dropped(self):
        rows=trend(15); rows[-1].update(close=101.)
        o=krun(rows)['open_positions'][0]
        self.assertEqual(o['pending_exit_signal_ts'],15*kr.BAR)
        self.assertEqual(o['mark_price'],101.)

    def test_reference_restart_and_blocked_reservation_preserved(self):
        rows=trend(); b=bundle(rows,[0,3,13,27]); child=krun(rows,b); parent=krun(rows,b,enabled=False)
        for key in ('reference_events','reference_opportunities','reference_checkpoint'):
            self.assertEqual(parent[key],child[key])
        self.assertEqual(next(e for e in child['events'] if e['signal_index']==13)['exclusion_reason'],'RUNNER_OCCUPIED')
        self.assertEqual([t['signal_index'] for t in child['trades']+child['open_positions']],[0,27])
        ck=kr.parent.causal_clock(rows,b,eval_start_ms=0,eval_end_ms=40*kr.BAR,stop_after_index=15)
        self.assertEqual(child,krun(rows,b,reference_checkpoint=json.loads(json.dumps(ck))))
        fixed=krun(rows,b,fixed_signal_indices=[0,13,27])
        self.assertEqual(len(fixed['trades']+fixed['open_positions']),3)
        self.assertGreater(fixed['trades'][0]['exit_ts'],fixed['trades'][1]['entry_ts'])
        # Prefix can censor the runner but cannot change previous admissions.
        prefix=krun(rows[:16],bundle(rows[:16],[0,3,13]))
        admissions=lambda r:[(e['signal_index'],e['admission'],e['exclusion_reason']) for e in r['events'] if e['signal_index']<=13]
        self.assertEqual(admissions(child),admissions(prefix))

    def test_actual_exit_open_same_bar_later_close_is_free(self):
        rows=trend(); rows[12]['close']=101.; b=bundle(rows,[0,13,27])
        child=krun(rows,b)
        self.assertIn(13,[t['signal_index'] for t in child['trades']+child['open_positions']])
        # At an exit timestamp itself the signal still observes the old slot.
        rows=trend(); rows[13]['close']=101.; child=krun(rows,b)
        self.assertEqual(next(e for e in child['events'] if e['signal_index']==13)['exclusion_reason'],'RUNNER_OCCUPIED')

    def test_funding_actual_extension_and_closed_open_origin_bridge(self):
        rows=trend(30); b=bundle(rows,[0,13,27]); pol=policy(); pol['development_interval_ms']=[0,30*kr.BAR]
        charge=lambda raw:account.charge_result(raw,'TEST','keltner_trend_main','SYNTHETIC',pol,COSTS,rows)
        parent=charge(krun(rows,b,enabled=False)); fixed=charge(krun(rows,b,fixed_signal_indices=[0,13,27])); full=charge(krun(rows,b))
        self.assertGreater(fixed['trades'][0]['funding_bps'],parent['trades'][0]['funding_bps'])
        for t in full['trades']:
            self.assertAlmostEqual(t['cost2x_net_bps'],t['gross_bps']-2*t['cost_bps'])
        bridge=metrics.fixed_full_bridge(parent,fixed,full)
        self.assertEqual(bridge['parity'],'PASS')
        self.assertIn('C_O',metrics.effects(parent,fixed)['transition_groups'])
        self.assertIn('C_ABSENT',metrics.effects(parent,full)['transition_groups'])
        # Reverse direction proves new-origin and O->C accounting, not just removals.
        rev=metrics.effects(full,parent)
        self.assertIn('ABSENT_C',rev['transition_groups'])


class QF1Tests(unittest.TestCase):
    def test_strict_progress_equal_lower_rejected_anchor_and_prefix(self):
        for confirm,allowed in ((102.,True),(101.,False),(100.8,False)):
            rows=qrows([100.,100.2,101.,confirm,103.,103.])
            out=qrun(rows); e=out['events'][0]
            self.assertEqual(e['qf1_observation']['first_breakout_close'],101.)
            self.assertEqual(e['qf1_observation']['allowed'],allowed)
            self.assertEqual(e['exclusion_reason'],'COMMON_END_POSITION_OPEN' if allowed else qf.VETO)
            self.assertEqual(qrun(rows[:30])['events'][0]['qf1_observation'],e['qf1_observation'])
            rows[24].update(open=1000.,high=1001.,low=999.,close=1000.)
            self.assertEqual(qrun(rows)['events'][0]['qf1_observation'],e['qf1_observation'])

    def test_disabled_exact_generator_unchanged_and_full_new_opportunity(self):
        rows=qrows([100.,100.2,101.,101.,101.,102.,103.,103.,103.])
        ds,b=qf.build_bundle(rows,0,len(rows)*kr.BAR); saved=deepcopy((rows,ds,b))
        parent=qrun(rows,enabled=False)
        self.assertEqual(parent,qf.q0.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*kr.BAR))
        child=qrun(rows)
        self.assertEqual(saved,(rows,ds,b))
        self.assertNotEqual([t['signal_index'] for t in parent['open_positions']],[t['signal_index'] for t in child['open_positions']])
        fixed=qrun(rows,fixed_signal_indices=[t['signal_index'] for t in parent['trades']+parent['open_positions']])
        self.assertEqual(fixed['trades']+fixed['open_positions'],[])
        self.assertTrue(child['open_positions'])

    def test_original_down_gap_and_protective_stop_exact(self):
        for gap in (False,True):
            rows=qrows([100.,100.2,101.,102.,102.,102.,99.,98.,98.,98.])
            if gap: rows[24].update(open=95.,low=94.,close=95.)
            a=qrun(rows,enabled=False); b=qrun(rows)
            for key in ('trades','open_positions','trace'):
                self.assertEqual(a[key],b[key])

    def test_corrupt_anchor_fails_and_no_source_suffix(self):
        rows=qrows([100.,100.2,101.,102.,103.,103.]); end=len(rows)*kr.BAR
        ds,b=qf.build_bundle(rows,0,end); b['signals'][0]['anchor_daily_index']=0
        with self.assertRaisesRegex(RuntimeError,'LINEAGE'):
            qf.replay(rows,ds,b,eval_start_ms=0,eval_end_ms=end)
        with self.assertRaises(RuntimeError):
            kr.replay(trend(),bundle(trend(),[0]),eval_start_ms=0,eval_end_ms=20*kr.BAR)


class SprintIntegrationTests(unittest.TestCase):
    def test_serial_synthetic_artifacts_exact_reproduction_and_budget_no_retry(self):
        from backend.research.rebuild import top5_performance_sprint_v1 as s
        periods=('DEV2025','SEEN2026')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); output='SYNTHETIC_ONLY'
            for kind in ('KR1','QF1'):
                rows=trend(45) if kind=='KR1' else qrows([100.,100.2,101.,101.,101.,102.,103.,103.,103.])
                end=len(rows)*kr.BAR; pol=policy(); pol['development_interval_ms']=[0,end]
                if kind=='KR1':
                    raw=krun(rows,bundle(rows,[0,13,27]),enabled=False)
                else: raw=qrun(rows,enabled=False)
                view=account.charge_result(raw,'TEST','keltner_trend_main' if kind=='KR1' else account.source.LANE,'P',pol,COSTS,rows)
                view['reference_states']={'TEST':raw['reference_checkpoint']} if kind=='KR1' else {}
                stage=metrics.exits.build_stage(view['trades'],view['open_observations'],view['events'],{'TEST':rows},COSTS,pol,['TEST'],0,end)
                parent_views={n:deepcopy(view) for n in (('M','M2') if kind=='KR1' else ('Q0',))}
                parent_stages={n:deepcopy(stage) for n in parent_views} if kind=='KR1' else {}
                spec={'receipt_sha256':'SYNTHETIC_FREEZE','symbols':['TEST'],'code_files_sha256':{},
                    'period_data_sha256':dict.fromkeys(periods,'synthetic-data'),'parent_receipts':{},
                    'calendars':{k:dict.fromkeys(periods,[0,end]) for k in ('KELTNER','Q0')}}
                loader=(pol,COSTS,dict.fromkeys(periods,{'TEST':rows}),{'synthetic_only':True})
                original_build=kr.parent.build_bundle
                # Preserve the production signature while using explicit synthetic signals.
                def synthetic_build(rr,parent_spec,*,eval_start_ms,eval_end_ms):
                    self.assertEqual(parent_spec,kr.d.PARENT_SPEC)
                    return bundle(rr,[0,13,27])
                with patch.object(s,'ROOT',root),patch.object(s,'OUTPUT',output),patch.object(s,'authorize',return_value=spec), \
                     patch.object(s.account,'load_inputs',return_value=loader),patch.object(s,'parents',return_value=(parent_views,parent_stages)), \
                     patch.object(s.old,'read',side_effect=lambda p:json.loads((root/p).read_text())),patch.object(s,'log'), \
                     patch.object(kr.parent,'build_bundle',synthetic_build if kind=='KR1' else original_build):
                    a=s.run(kind,'synthetic-no-source')
                    self.assertEqual(a['candidate_ordinal'],33 if kind=='KR1' else 34)
                    b=s.run(kind,'synthetic-no-source',verify=True)
                    self.assertEqual(a,b)
                    with self.assertRaisesRegex(RuntimeError,'ALREADY_ATTEMPTED'):
                        s.run(kind,'synthetic-no-source')


if __name__=='__main__': unittest.main()
