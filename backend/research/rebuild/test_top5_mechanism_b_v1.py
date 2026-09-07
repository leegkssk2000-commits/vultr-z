"""Synthetic native1h long/short timing, cost, ownership and restart checks."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from backend.research.rebuild import top5_native_finite_runner_v1 as n
from backend.research.rebuild import top5_mechanism_b_v1 as b
from backend.research.rebuild.test_parallel_exit_keltner_v1 import bars
from backend.research.rebuild.test_break_channel_source_v1 import policy,COSTS


def fixture(side='long',count=130):
    rows=bars(count)
    for i,r in enumerate(rows):
        r.update(ts=i*n.HOUR,ts_ms=i*n.HOUR,bar_open_ts=i*n.HOUR,bar_close_ts=(i+1)*n.HOUR,
                 open=100.,close=103. if side=='long' else 97.,high=104.,low=96.)
    cache=SimpleNamespace(st=[(100.,1 if side=='long' else -1)]*count,
                          ema=[101.+i*.001 if side=='long' else 99.-i*.001 for i in range(count)])
    e={'symbol':'TEST','lane_id':'trend_rider_primary_wr8125','signal_index':0,'signal_ts':n.HOUR,
       'side':side,'sl':90. if side=='long' else 110.,'tp':None,'timeout':{'bars':48},
       'risk_size':{'risk_fraction_of_equity':.005},'exposure':{'cap':.15},'owns_position':True,'cooldown_bars':2}
    return rows,cache,e


class NativePathTests(unittest.TestCase):
    def test_disabled_native49_and_enabled97_both_sides(self):
        for side in ('long','short'):
            rows,c,e=fixture(side)
            self.assertEqual(n.path(rows,e,c,enabled=False)[0]['exit_index'],49)
            t,o,trace,_=n.path(rows,e,c)
            self.assertEqual(t['exit_index'],97);self.assertIsNone(o)
            ds=[x for x in trace if x['kind']=='NATIVE_RUNNER_DECISION']
            self.assertEqual(len(ds),1);self.assertEqual(ds[0]['index'],48)

    def test_profit_and_each_trend_condition_strict(self):
        for side in ('long','short'):
            for mode in ('profit','direction','line','ema','slope'):
                rows,c,e=fixture(side)
                if mode=='profit':rows[48]['close']=100.
                if mode=='direction':c.st[48]=(100.,-1 if side=='long' else 1)
                if mode=='line':c.st[48]=(rows[48]['close'],1 if side=='long' else -1)
                if mode=='ema':c.ema[48]=rows[48]['close']
                if mode=='slope':c.ema[48]=c.ema[47]
                self.assertEqual(n.path(rows,e,c)[0]['exit_index'],49)

    def test_native_stop_tp_priority_original_decision_cap_and_extension(self):
        for side in ('long','short'):
            for j in (2,48,49,65,97):
                rows,c,e=fixture(side)
                rows[j]['low' if side=='long' else 'high']=e['sl']
                t=n.path(rows,e,c)[0]
                self.assertEqual((t['exit_index'],t['exit_price'],t['exit_reason']),(j,e['sl'],'SL'))
            rows,c,e=fixture(side);e['tp']=103. if side=='long' else 97.
            self.assertEqual(n.path(rows,e,c)[0]['exit_reason'],'TP')
            rows[1]['low' if side=='long' else 'high']=e['sl']
            self.assertEqual(n.path(rows,e,c)[0]['exit_reason'],'SL')

    def test_next_open_and_gap_no_future_hlc(self):
        for side in ('long','short'):
            rows,c,e=fixture(side);c.st[49]=(100.,-1 if side=='long' else 1)
            rows[50]['open']=89. if side=='long' else 111.
            rows[50]['low']=min(88.,rows[50]['open']);rows[50]['high']=max(112.,rows[50]['open'])
            t=n.path(rows,e,c)[0]
            self.assertEqual((t['exit_index'],t['exit_price'],t['exit_reason']),
                             (50,rows[50]['open'],'PENDING_EXIT_GAP_THROUGH_STOP'))
            rows[50].update(close=500.,high=1000.,low=1.)
            self.assertEqual(t,n.path(rows,e,c)[0])

    def test_lastbar_timeout_is_unfilled_and_boundary_sl_not_erased(self):
        for side in ('long','short'):
            rows,c,e=fixture(side,50)
            t,o,_,ck=n.path(rows,e,c,enabled=False)
            self.assertIsNone(t);self.assertIsNone(o['boundary_native_fill_reason'])
            self.assertFalse(o['terminal_liquidation'])
            rows[-1]['low' if side=='long' else 'high']=e['sl']
            t,o,_,ck=n.path(rows,e,c,enabled=False)
            self.assertEqual(o['boundary_native_fill_reason'],'SL');self.assertEqual(o['mark_price'],e['sl'])
            self.assertLess(o['gross_mark_bps'],0)
            self.assertEqual((t,o),n.path(rows,e,c,enabled=False,checkpoint=json.loads(json.dumps(ck)))[:2])

    def test_restart_pending_decision_completed_and_prefix_binding(self):
        for side in ('long','short'):
            rows,c,e=fixture(side);c.st[55]=(100.,-1 if side=='long' else 1)
            full=n.path(rows,e,c)
            for cut in (45,49,56,70):
                ck=n.path(rows[:cut],e,c)[3]
                self.assertEqual(full,n.path(rows,e,c,checkpoint=json.loads(json.dumps(ck))))
            ck=full[3]
            self.assertEqual(full,n.path(rows,e,c,checkpoint=json.loads(json.dumps(ck))))
            altered=deepcopy(e);altered['symbol']='OTHER'
            with self.assertRaisesRegex(RuntimeError,'PREFIX'):n.path(rows,altered,c,checkpoint=ck)
            with self.assertRaisesRegex(RuntimeError,'PREFIX'):n.path(rows,e,c,enabled=False,checkpoint=ck)

    def test_restart_strict_boundary_timeout_promotes_only_original_price(self):
        rows,c,e=fixture();prefix=n.path(rows[:50],e,c,enabled=False)
        self.assertIsNone(prefix[1]['boundary_native_fill_reason'])
        self.assertEqual(n.path(rows,e,c,enabled=False),n.path(rows,e,c,enabled=False,checkpoint=json.loads(json.dumps(prefix[3]))))

    def test_cooldown_open_clock_actual_extension_and_tail_single_slot(self):
        rows,c,e=fixture();events=[dict(e,signal_index=i,signal_ts=(i+1)*n.HOUR) for i in (0,50,51,52,105)]
        p=n.replay(rows,events,c,enabled=False);full=n.replay(rows,events,c)
        self.assertEqual([t['signal_index'] for t in p['trades']],[0,51])
        self.assertEqual([t['signal_index'] for t in full['trades']],[0])
        self.assertEqual(len(full['open_positions']),1)
        fixed=n.replay(rows,events,c,fixed_indices=[0,51,105])
        self.assertEqual(len(fixed['trades'])+len(fixed['open_positions']),3)
        self.assertGreater(fixed['trades'][0]['exit_ts'],fixed['open_positions'][0]['entry_ts'])

    def test_long_short_terminal_cost2_daily_mark_and_boundary_loss(self):
        for side in ('long','short'):
            rows,c,e=fixture(side,80);pol=policy();pol['development_interval_ms']=[0,len(rows)*n.HOUR]
            events=[e];raw=n.replay(rows,events,c);v=b.charge(raw,'TEST','TPR1','X',pol,COSTS,rows)
            with n.reporting():
                st=b.metrics.exits.build_stage(v['trades'],v['open_observations'],v['events'],{'TEST':rows},COSTS,pol,['TEST'],0,len(rows)*n.HOUR)
            total=st['metrics']['terminal_totals_bps']
            self.assertAlmostEqual(total['cost2x_net_bps'],total['gross_bps']-2*total['cost_bps'])
            self.assertEqual(st['daily'][-1]['cumulative_net_mark_bps'],total['net_bps'])
            self.assertEqual(v['open_observations'][0]['native_interval_ms'],n.HOUR)


class IntegrationTests(unittest.TestCase):
    def test_serial_two_synthetic_whole_reports_and_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows,c,e=fixture(count=140);end=len(rows)*n.HOUR
            pol=policy();pol['development_interval_ms']=[0,end]
            spec={'receipt_sha256':'SYNTHETIC','calendar':[0,end],'code_files_sha256':{},'native_data_sha256':'synthetic',
                  'symbols':['TEST'],'native_policy_sha256':dict.fromkeys(b.ORDER,'synthetic'),'parents':dict.fromkeys(b.ORDER,'P')}
            with patch.object(b,'ROOT',root),patch.object(b,'OUTPUT','SYNTHETIC'),patch.object(b,'authorize',return_value=spec), \
                 patch.object(b,'load_inputs',return_value=(pol,COSTS,{'TEST':rows})), \
                 patch.object(n,'prepare',return_value=(c,[e],None)),patch.object(b,'verify_parent',return_value={'synthetic':True}), \
                 patch.object(b.old,'read',side_effect=lambda p:json.loads((root/p).read_text())),patch.object(b.a,'log'):
                for i,kind in enumerate(b.ORDER):
                    a=b.run(kind);self.assertEqual(a['candidate_ordinal'],38+i)
                    self.assertEqual(a,b.run(kind,verify=True))
                    with patch.object(b,'load_inputs',side_effect=AssertionError('duplicate source access')):
                        self.assertIsNone(b.run(kind))


if __name__=='__main__':unittest.main()
