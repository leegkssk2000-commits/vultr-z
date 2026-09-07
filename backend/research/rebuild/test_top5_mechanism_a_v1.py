"""Synthetic fixtures only; no market-data replay."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.research.rebuild import keltner_kr2_v1 as k
from backend.research.rebuild import top5_finite_runner_4h_v1 as f
from backend.research.rebuild import top5_mechanism_a_v1 as s
from backend.research.rebuild.test_parallel_exit_keltner_v1 import bars,bundle
from backend.research.rebuild.test_top5_performance_sprint_v1 import trend
from backend.research.rebuild.test_break_channel_source_v1 import policy,COSTS


def kr(rows,b=None,**kw):
    return k.replay(rows,b or bundle(rows,[0]),eval_start_ms=0,eval_end_ms=len(rows)*k.BAR,**kw)


def host(rows,kind='SR1',b=None,**kw):
    return f.replay(rows,b or bundle(rows,[0]),kind=kind,eval_start_ms=0,eval_end_ms=len(rows)*k.BAR,**kw)


class KR2Tests(unittest.TestCase):
    def test_disabled_exact_and_inputs_unchanged(self):
        rows=trend();b=bundle(rows,[0,3,13,27]);saved=deepcopy((rows,b))
        self.assertEqual(kr(rows,b,enabled=False),k.kr.replay(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*k.BAR))
        kr(rows,b); self.assertEqual((rows,b),saved)

    def fixture(self,n=40):
        rows=trend(n);rows[11].update(low=102.,open=103.)
        return rows

    def test_anchor_next_open_and_not_low_fill(self):
        rows=self.fixture();rows[12].update(close=101.5);rows[13].update(open=100.)
        t=kr(rows)['trades'][0]
        self.assertEqual((t['exit_reason'],t['exit_index'],t['exit_price']),(k.EXIT,13,100.))
        self.assertEqual(t['runner_extension']['runner_anchor_low'],102.)
        rows[13].update(close=1000.,high=1001.,low=1.)
        self.assertEqual(t,kr(rows)['trades'][0])

    def test_anchor_immutable_prefix_and_future_low_irrelevant(self):
        rows=self.fixture();rows[12].update(low=102.5,open=103.)
        rows[13].update(close=102.2,low=102.,open=103.)
        out=kr(rows);self.assertEqual(out['trades'][0]['exit_index'],24)
        dec=lambda r:[x for x in r['trace'] if x['kind']==k.DECISION]
        self.assertEqual(dec(out),dec(kr(rows[:12])))
        self.assertEqual(out['trades'][0]['runner_extension']['runner_anchor_low'],102.)

    def test_before_extension_no_anchor_and_strict_less(self):
        rows=self.fixture();rows[8].update(close=101.5);rows[12].update(close=102.)
        self.assertEqual(kr(rows)['trades'][0]['exit_index'],24)
        rows[11].update(close=100.,low=98.)
        t=kr(rows)['trades'][0];self.assertEqual(t['exit_index'],12)
        self.assertNotIn('runner_anchor_low',t['runner_extension'])

    def test_original_priority_cap_once_and_censor(self):
        rows=self.fixture();rows[12].update(close=101.)
        self.assertEqual(kr(rows)['trades'][0]['exit_reason'],k.kr.EXIT)
        rows=self.fixture();rows[24].update(close=95.,low=94.)
        out=kr(rows);self.assertEqual(out['trades'][0]['exit_index'],24)
        self.assertEqual(out['trace'][-1]['kind'],'RUNNER_FINAL_TIME_STOP_CLOSE')
        self.assertEqual(sum(t['kind']==k.DECISION for t in out['trace']),1)
        o=kr(self.fixture(25))['open_positions'][0];self.assertFalse(o['terminal_liquidation'])
        rows=self.fixture(14);rows[-1].update(close=101.5)
        self.assertEqual(kr(rows)['open_positions'][0]['pending_exit_signal_ts'],14*k.BAR)

    def test_reference_restart_actual_slot_restore_and_no_future_admission(self):
        rows=self.fixture();rows[12].update(close=101.5);b=bundle(rows,[0,3,13,27])
        a=kr(rows,b);p=kr(rows,b,enabled=False)
        for key in ('reference_events','reference_opportunities','reference_checkpoint'):
            self.assertEqual(a[key],p[key])
        self.assertIn(13,[t['signal_index'] for t in a['trades']+a['open_positions']])
        self.assertNotIn(13,[t['signal_index'] for t in p['trades']+p['open_positions']])
        ck=k.parent.causal_clock(rows,b,eval_start_ms=0,eval_end_ms=len(rows)*k.BAR,stop_after_index=15)
        self.assertEqual(a,kr(rows,b,reference_checkpoint=json.loads(json.dumps(ck))))


class FourHourTests(unittest.TestCase):
    def test_disabled_exact_shared_parent_both_native_holds(self):
        for kind,h in [('SR1',12),('BR1',6)]:
            rows=trend(45);b=bundle(rows,[0,3,13,27]);before=deepcopy((rows,b))
            out=host(rows,kind,b,enabled=False)
            raw=f.base.old.common.evaluate_development_events(rows,[0,3,13,27],split_start_ms=0,
                  split_end_ms=len(rows)*k.BAR,interval_ms=k.BAR,hold_bars=h)
            self.assertEqual(out['trades'],raw['trades']);self.assertEqual((rows,b),before)

    def test_t_minus_one_once_finite_cap_strict_end_both(self):
        for kind,h in [('SR1',12),('BR1',6)]:
            rows=trend();out=host(rows,kind)
            self.assertEqual(out['trades'][0]['exit_index'],2*h)
            ds=[x for x in out['trace'] if x['kind']==f.DECISION]
            self.assertEqual(len(ds),1);self.assertEqual(ds[0]['index'],h-1)
            prefix=host(rows[:h],kind)
            self.assertEqual(ds,[x for x in prefix['trace'] if x['kind']==f.DECISION])
            self.assertEqual(host(rows[:2*h+1],kind)['trades'],[])

    def test_pre_extension_trend_loss_never_exits_and_nonprofit_denies(self):
        for kind,h in [('SR1',12),('BR1',6)]:
            rows=trend();rows[2].update(close=95.,low=94.)
            self.assertEqual(host(rows,kind)['trades'][0]['exit_index'],2*h)
            rows[h-1].update(close=100.,low=99.)
            self.assertEqual(host(rows,kind)['trades'][0]['exit_index'],h)

    def test_runner_next_open_not_future_hlc_cap_and_pending(self):
        for kind,h in [('SR1',12),('BR1',6)]:
            rows=trend();rows[h].update(close=101.);rows[h+1].update(open=95.,low=94.)
            t=host(rows,kind)['trades'][0]
            self.assertEqual((t['exit_index'],t['exit_price'],t['exit_reason']),(h+1,95.,f.EXIT))
            rows[h+1].update(close=500.,high=1000.,low=1.)
            self.assertEqual(t,host(rows,kind)['trades'][0])
            rows=trend(h+2);rows[-1].update(close=101.)
            self.assertIsNotNone(host(rows,kind)['open_positions'][0]['pending_exit_signal_ts'])

    def test_native_exit_bar_ownership_and_fixed_overlap(self):
        rows=trend();b=bundle(rows,[0,13,27]);a=host(rows,b=b)
        self.assertEqual([t['signal_index'] for t in a['trades']+a['open_positions']],[0,27])
        fixed=host(rows,b=b,fixed_signal_indices=[0,13,27])
        self.assertEqual(len(fixed['trades']+fixed['open_positions']),3)
        rows[12].update(close=101.)
        self.assertEqual(host(rows,b=b)['events'][1]['exclusion_reason'],'SIGNAL_DURING_OPEN')

    def test_funding_cost2_censor_bridge_and_disabled_no_stop_claim(self):
        rows=trend(30);b=bundle(rows,[0,13,27]);pol=policy();pol['development_interval_ms']=[0,len(rows)*k.BAR]
        charge=lambda a:s.account.charge_result(a,'TEST','supertrend_pullback_main','X',pol,COSTS,rows)
        p=charge(host(rows,b=b,enabled=False));fixed=charge(host(rows,b=b,fixed_signal_indices=[0,13,27]));full=charge(host(rows,b=b))
        self.assertGreater(fixed['trades'][0]['funding_bps'],p['trades'][0]['funding_bps'])
        self.assertEqual(s.metrics.fixed_full_bridge(p,fixed,full)['parity'],'PASS')
        self.assertIn('C_O',s.metrics.effects(p,fixed)['transition_groups'])
        for t in full['trades']:self.assertAlmostEqual(t['cost2x_net_bps'],t['gross_bps']-2*t['cost_bps'])
        self.assertIsNone(host(rows)['audit']['native_SL'])


class IntegrationTests(unittest.TestCase):
    def test_serial_three_synthetic_receipts_reproduce_and_duplicate_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rows=trend(45); b=bundle(rows,[0,13,27]);end=len(rows)*k.BAR
            pol=policy();pol['development_interval_ms']=[0,end]
            raw=kr(rows,b,enabled=False);v=s.account.charge_result(raw,'TEST','keltner_trend_main','P',pol,COSTS,rows)
            v['reference_states']={'TEST':raw['reference_checkpoint']}
            views={n:deepcopy(v) for n in ('M','M2','KR1_FULL')}
            st=s.metrics.exits.build_stage(v['trades'],v['open_observations'],v['events'],{'TEST':rows},COSTS,pol,['TEST'],0,end)
            stages={n:deepcopy(st) for n in views}
            spec={'receipt_sha256':'SYNTHETIC','code_files_sha256':{},'symbols':['TEST'],
                  'period_data_sha256':dict.fromkeys(('DEV2025','SEEN2026'),'synthetic'),
                  'calendars':dict.fromkeys(('DEV2025','SEEN2026'),[0,end])}
            loader=(pol,COSTS,dict.fromkeys(('DEV2025','SEEN2026'),{'TEST':rows}),{'synthetic':True})
            with patch.object(s,'ROOT',root),patch.object(s,'OUTPUT','SYNTHETIC'),patch.object(s,'authorize',return_value=spec), \
                 patch.object(s.account,'load_inputs',return_value=loader),patch.object(s,'parents',return_value=(views,stages)), \
                 patch.object(s.old,'read',side_effect=lambda p:json.loads((root/p).read_text())), \
                 patch.object(k.parent,'build_bundle',return_value=b),patch.object(f,'build_bundle',return_value=b), \
                 patch.object(f,'specification',return_value={'lane_id':'supertrend_pullback_main','executable_spec':{}}), \
                 patch.object(s,'log'),patch.object(s,'parity',return_value='SYNTHETIC_ADAPTER_TESTED_SEPARATELY'):
                for i,kind in enumerate(s.ORDER):
                    a=s.run(kind,'synthetic');self.assertEqual(a['candidate_ordinal'],35+i)
                    self.assertEqual(a,s.run(kind,'synthetic',verify=True))
                    with patch.object(s.account,'load_inputs',side_effect=AssertionError('duplicate loaded data')):
                        self.assertIsNone(s.run(kind,'synthetic'))


if __name__=='__main__':unittest.main()
