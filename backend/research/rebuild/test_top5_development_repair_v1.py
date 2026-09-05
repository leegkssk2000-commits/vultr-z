import copy
import gzip
import hashlib
from dataclasses import asdict
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import top5_development_native_v1 as native
from backend.research.rebuild import top5_development_repair_v1 as repair
from backend.research.rebuild import trend_policy_batch_v1 as policy
from backend.research.rebuild import g5_clean_runner_binding_fix_v1 as binding
from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as owner
from backend.research.architecture_factory import g5a_development_probe_v1 as probe


def fixture(n=280,interval=3600000):
    rng=random.Random(1179);px=100.;rows=[]
    for i in range(n):
        c=px*math.exp(rng.uniform(-.035,.04))
        rows.append({'ts':i*interval,'ts_ms':i*interval,'bar_open_ts':i*interval,'bar_close_ts':(i+1)*interval,
                     'open':px,'close':c,'high':max(px,c)*1.003,'low':min(px,c)*.997,'volume':100+(i%11)*30})
        px=c
    return rows


class NativeParity(unittest.TestCase):
    def test_exact_feature_cache_prefixes(self):
        rows=fixture(180);cache=native.NativeFeatureCache(rows,policy.TrendPolicyConfig())
        for i in [63,64,65,100,139,179]:
            self.assertEqual(cache.feature(rows[:i+1],symbol='TEST',now_ts_ms=rows[i]['ts']),
                             policy.compute_trend_rider_feature(rows[:i+1],symbol='TEST',now_ts_ms=rows[i]['ts']))

    def test_cache_no_future_dependency(self):
        rows=fixture(150);future=copy.deepcopy(rows)
        for r in future[120:]:
            for k in ['open','high','low','close']:r[k]*=2
        a=native.NativeFeatureCache(rows,policy.TrendPolicyConfig());b=native.NativeFeatureCache(future,policy.TrendPolicyConfig())
        self.assertEqual(a.feature(rows[:120],symbol='TEST',now_ts_ms=rows[119]['ts']),b.feature(future[:120],symbol='TEST',now_ts_ms=rows[119]['ts']))

    def test_exact_native_trade_owner_parity(self):
        rows=fixture(140)
        with patch.object(owner,'paged_bars',lambda *a:rows),patch.object(owner.ev,'git_blob_sha',lambda p:'0'*64):
            reference,_=owner.primary_trades(0,len(rows)*native.HOUR,['TEST'])
        actual,events=native.native_replay(rows,'TEST','primary',0,len(rows)*native.HOUR,policy_sha='0'*64)
        self.assertEqual(actual,reference);self.assertTrue(events)

    def test_child_false_veto_and_ablation(self):
        rows=fixture(160);args=(rows,'TEST','broad',0,len(rows)*native.HOUR)
        baseline,_=native.native_replay(*args,policy_sha='0'*64)
        ablation,_=native.native_replay(*args,lambda *a:True,policy_sha='0'*64)
        veto,events=native.native_replay(*args,lambda *a:False,policy_sha='0'*64)
        self.assertEqual(baseline,ablation);self.assertEqual(veto,[]);self.assertTrue(events)

    def test_native_interval_gap_duplicate(self):
        rows=fixture(100)
        native.validate_native(rows,0,100*native.HOUR)
        for bad in [rows[:-1],rows[:20]+rows[21:],rows[:20]+[rows[19]]+rows[20:]]:
            with self.assertRaises((RuntimeError,ValueError)):native.validate_native(bad,0,100*native.HOUR)


class FourHourParity(unittest.TestCase):
    def test_fixed_hold_trade_geometry_matches_original_owner(self):
        rows=fixture(410,14400000);start=239*14400000;end=410*14400000
        for child in repair.read(repair.FREEZE)['children']:
            with patch.object(owner,'paged_bars',lambda *a:rows):
                reference,_=owner.v2_trades(child,start,end,['TEST'])
            reference=[t for t in reference if t['exit_ts']+14400000<end]
            _,engine=repair.dsl._features(rows,child['executable_spec'])
            signals=[i for i in range(239,len(rows)) if bool(engine.eval(child['executable_spec']['entry_rule'],i))]
            actual=repair.common.evaluate_development_events(rows,signals,split_start_ms=0,split_end_ms=end,interval_ms=14400000,hold_bars=child['executable_spec']['max_hold_bars'])['trades']
            self.assertEqual(len(actual),len(reference))
            for a,b in zip(actual,reference):
                self.assertEqual(a['signal_ts'],b['signal_ts']+14400000)
                self.assertEqual(a['entry_ts'],b['entry_ts']);self.assertEqual(a['exit_ts'],b['exit_ts']+14400000)
                self.assertEqual(a['entry_price'],b['entry_px']);self.assertEqual(a['exit_price'],b['exit_px'])
                self.assertAlmostEqual(a['gross_bps'],b['gross_bps'])

    def test_all_three_current_native_signal_parity(self):
        rows=fixture(350,14400000)
        c=repair.read('backend/research/rebuild/g5_clean_runner_contract_effective_v1.json')
        f=repair.read('backend/research/rebuild/g5_clean_runner_strategy_freeze_effective_v1.json')
        adapter=binding.CurrentTop5FrozenStrategyAdapter(c,f)
        for child in repair.read(repair.FREEZE)['children']:
            _,expr=repair.dsl._features(rows,child['executable_spec'])
            for i in range(239,len(rows)):
                self.assertEqual(bool(expr.eval(child['executable_spec']['entry_rule'],i)),adapter.evaluate(child['parent_strategy_id'],rows[:i+1])['signal'])

    def test_hold_6_12_and_cost_floor(self):
        rows=fixture(350,14400000);p={'development_interval_ms':[0,350*14400000],'batch_id':'TEST','combined_data_sha256':'a','receipt_sha256':'b','code_files_sha256':{},'cost_binding_sha256':'c'}
        costs={'TEST':{'fee_bps':10,'spread_bps':1,'impact_bps':2,'funding_p95_per_settlement_bps':1}}
        for child in repair.read(repair.FREEZE)['children']:
            trades,events=repair.four_hour(rows,'TEST',child,p,costs,'base')
            for t in trades:
                self.assertEqual(t['hold_ms'],child['executable_spec']['max_hold_bars']*14400000)
                self.assertGreaterEqual(t['cost_bps'],20)
                self.assertAlmostEqual(sum(t[k] for k in ['fee_bps','spread_bps','impact_bps','funding_bps','slippage_bps','frozen_floor_reserve_bps']),t['cost_bps'])
                self.assertAlmostEqual(t['cost2x_net_bps'],t['gross_bps']-2*t['cost_bps'])
                self.assertLess(t['exit_ts'],p['development_interval_ms'][1])
                self.assertEqual(t['formal_credit'],0);self.assertEqual(t['order_authority'],'BLOCKED')
            self.assertEqual(sum(e['status']=='COMPLETED' for e in events),len(trades))
            self.assertEqual(len({t['identity'] for t in trades}),len(trades))

    def test_geometry_no_future_or_total_volume_flow(self):
        rows=fixture(300,14400000);a=repair.geometry(rows,260)
        rows[261]['close']*=10;rows[260]['volume']*=10
        self.assertEqual(a,repair.geometry(rows,260))
        self.assertNotIn('orderflow',a)

    def test_holdout_decode_and_network_guards_reused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'prefix.json';p.write_text('[{"x":1}, INVALID_HOLDOUT]')
            self.assertEqual(probe.prefix_rows(p,1),[{'x':1}])
            with probe.io_boundary([p],root/'own'):
                with self.assertRaises(RuntimeError):(root/'production-ledger.json').read_text()


@unittest.skipUnless((repair.ROOT/repair.OUTPUT/'comparison/receipt.json').exists(),'First comparison not yet committed')
class DurableEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=repair.ROOT/repair.OUTPUT
        cls.result=json.loads((cls.root/'comparison/receipt.json').read_text())
        cls.trades=[json.loads(x) for x in gzip.decompress((cls.root/'comparison/trades.jsonl.gz').read_bytes()).splitlines()]

    def test_parent_immutable_and_comparison_baseline_identical(self):
        p=repair.read(repair.POLICY);a=json.loads((self.root/'baseline/receipt.json').read_text())
        for path,sha in p['immutable_files_sha256'].items():self.assertEqual(repair.file_sha(repair.ROOT/path),sha)
        for lane in repair.LANES:self.assertEqual(a['lanes'][lane]['metrics']['base'],self.result['lanes'][lane]['metrics']['base'])

    def test_independent_arithmetic_cost_ledger_exactly_once(self):
        keys=set()
        for t in self.trades:
            key=(t['lane_id'],t['scenario'],t['identity']);self.assertNotIn(key,keys);keys.add(key)
            self.assertAlmostEqual(t['net_bps'],t['gross_bps']-t['cost_bps'])
            self.assertAlmostEqual(t['cost2x_net_bps'],t['gross_bps']-2*t['cost_bps'])
            self.assertGreaterEqual(t['cost_bps'],20)
            self.assertEqual(t['formal_credit'],0);self.assertEqual(t['execution_authority'],'NONE')
        for lane,v in self.result['lanes'].items():
            for scenario in ['base','child']:
                ts=[t for t in self.trades if t['lane_id']==lane and t['scenario']==scenario];xs=[t['net_bps'] for t in ts]
                m=v['metrics'][scenario]['base_cost'];self.assertEqual(len(xs),m['completed_T'])
                self.assertAlmostEqual(sum(xs),m['net_bps'],places=7)
                self.assertAlmostEqual(sum(x for x in xs if x>0)/-sum(x for x in xs if x<0),m['PF'])
                self.assertAlmostEqual(sum(x>0 for x in xs)/len(xs),m['win_rate'])

    def test_child_native_geometry_and_population_separation(self):
        events=[json.loads(x) for x in gzip.decompress((self.root/'comparison/events.jsonl.gz').read_bytes()).splitlines()]
        parents={(e['lane_id'],e['symbol'],e['signal_ts']):e for e in events if e['scenario']=='base'}
        for e in events:
            if e['scenario']!='child':continue
            p=parents[(e['lane_id'],e['symbol'],e['signal_ts'])]
            for k in ['sl','tp','timeout','risk_size','exposure']:
                self.assertEqual(e.get(k),p.get(k))
        self.assertFalse(self.result['new_g5b_boundary']);self.assertEqual(self.result['production_grade_credit'],0)
        self.assertEqual(self.result['validation_rows_decoded'],0);self.assertEqual(self.result['OOS_rows_decoded'],0)

    def test_durable_seals_and_hashes(self):
        probe.verify_seal(self.result,'RESULT')
        for a in self.result['artifacts'].values():self.assertEqual(repair.file_sha(repair.ROOT/a['path']),a['file_sha256'])
        child=repair.read(repair.CHILDREN);probe.verify_seal(child,'CHILDREN')
        self.assertFalse(child['child_outcomes_observed_at_freeze'])
        self.assertEqual(set(child['lanes']),set(repair.LANES))
        for lane,c in child['lanes'].items():
            self.assertEqual(c['parent_sha256'],repair.read(repair.POLICY)['parents'][lane]['sha256'])
            self.assertEqual(c['trial_budget_remaining_after_run'],0)

    def test_research_registry_never_changes_operational_authority(self):
        registry=json.loads((self.root/'research_registry.json').read_text());probe.verify_seal(registry,'REGISTRY')
        self.assertFalse(registry['operating_G5B_version_changed']);self.assertEqual(registry['formal_credit_transferred'],0)
        for lane,entry in registry['lanes'].items():
            result=self.result['lanes'][lane];promising=result['comparison']['decision']=='DEV_PROMISING'
            self.assertEqual(entry['research_version_increment'],int(promising))
            self.assertEqual(entry['current_research_version'],result['child_id'] if promising else result['parent_id'])
            self.assertFalse(entry['formal_PASS'])


if __name__=='__main__':unittest.main()
