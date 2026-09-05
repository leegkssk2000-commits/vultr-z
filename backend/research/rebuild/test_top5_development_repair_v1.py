import copy
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


if __name__=='__main__':unittest.main()
