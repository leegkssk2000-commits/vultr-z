"""Focused synthetic timing, causal state, ownership and accounting gates."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from backend.research.rebuild import keltner_kr3_v1 as k
from backend.research.rebuild import break_br2_v1 as b
from backend.research.rebuild import focused_repair_v1 as s
from backend.research.rebuild.test_parallel_exit_keltner_v1 import bundle
from backend.research.rebuild.test_top5_performance_sprint_v1 import trend
from backend.research.rebuild.test_break_channel_source_v1 import policy,COSTS


def run(mod,rows,indices=(0,),**kw):
    return mod.replay(rows,bundle(rows,list(indices)),eval_start_ms=0,eval_end_ms=len(rows)*k.BAR,**kw)


def suppressed(n=40):
    rows=trend(n);rows[0].update(low=102.,open=103.,close=103.,high=104.)
    rows[2].update(close=101.5)
    return rows


class KR3Tests(unittest.TestCase):
    def test_disabled_exact_KR1_and_input_immutable(self):
        rows=suppressed();saved=deepcopy(rows)
        self.assertEqual(run(k,rows,enabled=False),run(k.kr,rows))
        run(k,rows);self.assertEqual(saved,rows)

    def test_prior_suppression_only_vetoes_extension_and_preserves_native_exit(self):
        rows=suppressed();p=run(k.kr,rows);c=run(k,rows)
        self.assertEqual(p['trades'][0]['exit_index'],24)
        self.assertEqual(c['trades'][0]['exit_index'],12)
        self.assertEqual(c['trades'][0]['runner_extension']['m2_state_at_decision'],k.SUPPRESSED)
        self.assertEqual(p['reference_checkpoint'],c['reference_checkpoint'])
        self.assertEqual(c['trades'][0]['exit_price'],rows[12]['close'])

    def test_no_breach_preserves_path_and_later_breach_cannot_veto_earlier_decision(self):
        rows=trend();p=run(k.kr,rows)['trades'][0];c=run(k,rows)['trades'][0]
        for key in ('entry_ts','exit_ts','exit_price','gross_bps'):self.assertEqual(p[key],c[key])
        rows[0].update(low=102.,open=103.,close=103.,high=104.);rows[15].update(close=101.5)
        out=run(k,rows);decision=next(x for x in out['trace'] if x['kind']==k.DECISION)
        self.assertTrue(decision['allowed']);self.assertEqual(decision['m2_state_at_decision'],k.UNCHECKED)

    def test_prefix_same_decision_reference_restart_duplicate_input_rejected(self):
        rows=suppressed();whole=run(k,rows);prefix=run(k,rows[:12])
        dec=lambda o:[x for x in o['trace'] if x['kind']==k.DECISION]
        self.assertEqual(dec(whole),dec(prefix))
        bb=bundle(rows,[0,3,13,27]);clock=k.parent.causal_clock(rows,bb,eval_start_ms=0,eval_end_ms=len(rows)*k.BAR,stop_after_index=15)
        self.assertEqual(run(k,rows,(0,3,13,27)),run(k,rows,(0,3,13,27),reference_checkpoint=json.loads(json.dumps(clock))))
        with self.assertRaises(RuntimeError):run(k,rows,(0,0))

    def test_existing_M2_exit_priority_and_boundary_mark(self):
        rows=suppressed();rows[2].update(close=99.)
        p=run(k.kr,rows)['trades'][0];c=run(k,rows)['trades'][0]
        self.assertEqual((p['exit_ts'],p['exit_reason']),(c['exit_ts'],c['exit_reason']))
        out=run(k,suppressed(13));self.assertEqual(len(out['open_positions']),1)
        self.assertFalse(out['open_positions'][0]['terminal_liquidation'])


class BR2Tests(unittest.TestCase):
    def test_disabled_exact_and_fixed_identical(self):
        rows=trend();kw=dict(kind='BR1',eval_start_ms=0,eval_end_ms=len(rows)*k.BAR)
        self.assertEqual(run(b,rows,(0,12,13),enabled=False),b.br.replay(rows,bundle(rows,[0,12,13]),**kw))
        self.assertEqual(run(b,rows,(0,12,13),fixed_signal_indices=[0,12]),b.br.replay(rows,bundle(rows,[0,12,13]),fixed_signal_indices=[0,12],**kw))

    def test_cap_fill_precedes_new_next_open_old_path_not_reset(self):
        rows=trend();rows[13].update(open=105.,high=106.);out=run(b,rows,(0,6,11,12,13,25))
        self.assertEqual([t['signal_index'] for t in out['trades']],[0,12,25])
        first,second=out['trades'][:2]
        self.assertEqual(first['exit_index'],12);self.assertEqual(second['entry_index'],13)
        self.assertEqual(first['exit_ts'],second['entry_ts']);self.assertEqual(second['entry_price'],105.)
        self.assertEqual([e['status'] for e in out['events'][:4]],['COMPLETED','EXCLUDED','EXCLUDED','COMPLETED'])
        self.assertEqual(out['audit']['old_position_hold_cap_resets'],0)

    def test_nonextended_and_early_exit_bar_ownership_unchanged(self):
        rows=trend();rows[5]['close']=100.;o=run(b,rows,(0,6,7))
        self.assertEqual(o['events'][1]['status'],'EXCLUDED')
        rows=trend();rows[6]['close']=100.;o=run(b,rows,(0,7,8))
        self.assertEqual(o['trades'][0]['exit_index'],7);self.assertEqual(o['events'][1]['status'],'EXCLUDED')

    def test_strict_boundary_never_releases_censored_cap(self):
        rows=trend(13);o=run(b,rows,(0,11))
        self.assertEqual(len(o['open_positions']),1);self.assertEqual(o['audit']['completed_extension_cap_releases_T'],0)
        rows=trend(15);o=run(b,rows,(0,12));self.assertEqual(len(o['open_positions']),1)
        self.assertEqual(o['open_positions'][0]['entry_index'],13)

    def test_early_open_on_cap_index_is_not_cap_close(self):
        rows=trend();rows[11]['close']=100.;o=run(b,rows,(0,12,13))
        self.assertEqual(o['trades'][0]['exit_index'],12)
        self.assertEqual(o['trades'][0]['exit_reason'],b.br.EXIT)
        self.assertEqual(o['events'][1]['status'],'EXCLUDED')
        self.assertEqual(o['audit']['completed_extension_cap_releases_T'],0)

    def test_no_next_open_HLC_lookahead_and_idempotent_replay(self):
        rows=trend();o=run(b,rows,(0,12));first=o['trades'][0]
        rows[13].update(high=1000.,low=1.,close=100.)
        self.assertEqual(first,run(b,rows,(0,12))['trades'][0])
        self.assertEqual(run(b,rows,(0,12)),run(b,deepcopy(rows),(0,12)))
        with self.assertRaises(RuntimeError):run(b,rows,(0,0))

    def test_new_entry_full_cost_funding_and_open_accounting(self):
        rows=trend(20);pol=policy();pol['development_interval_ms']=[0,len(rows)*k.BAR]
        p=run(b,rows,(0,12),enabled=False);c=run(b,rows,(0,12))
        charge=lambda x:s.account.charge_result(x,'TEST','break_and_continue_main','X',pol,COSTS,rows)
        pv,cv=charge(p),charge(c)
        self.assertEqual(len(cv['open_observations']),1)
        for t in cv['trades']:self.assertAlmostEqual(t['cost2x_net_bps'],t['gross_bps']-2*t['cost_bps'])
        stage=s.metrics.exits.build_stage(cv['trades'],cv['open_observations'],cv['events'],{'TEST':rows},COSTS,pol,['TEST'],0,len(rows)*k.BAR)
        self.assertEqual(s.metrics.stage_values(stage)['open_T'],1)
        self.assertGreater(stage['metrics']['terminal_totals_bps']['cost_bps'],sum(t['cost_bps'] for t in pv['trades']))


if __name__=='__main__':unittest.main()
