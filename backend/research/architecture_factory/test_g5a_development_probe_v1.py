import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend.research.architecture_factory import g5a_development_probe_v1 as probe
from backend.research.rebuild import g5b_operational_terminal_v1 as g5b


def fixture_bars(count=80):
    start = 1_700_006_400_000
    return [{"bar_open_ts": start+i*14_400_000, "bar_close_ts": start+(i+1)*14_400_000,
             "open": 100.0+i, "high": 101.5+i, "low": 99.5+i, "close": 101.0+i, "volume": 10.0+i}
            for i in range(count)]


class AdmissionTests(unittest.TestCase):
    def inputs(self):
        return probe.read(probe.POLICY), probe.read(probe.TERMINAL), probe.read(probe.STAGE)

    def test_unresolved_p0_explicit_development_is_authorized_only(self):
        p,t,s=self.inputs()
        self.assertEqual(t['gates']['P0'],'FAIL')
        probe.authorize(p,t,s)
        self.assertFalse(probe.alpha.evaluate_bundle(t['bundle'])['p0_p6_passed'])
        for state in probe.STATE_MAP:
            fake={'schema_version':'zel.g5a.development_evidence_probe.v1','state':state,**probe.DEV_AUTH}
            with self.assertRaises(RuntimeError):
                probe.alpha.assert_receipt(fake,t['candidate']['candidate_sha256'])
            with self.assertRaisesRegex(RuntimeError,'ALPHA_PROOF_REQUIRED'):
                g5b.freeze_boundary(fake,{}, {},now_ms=1)

    def test_resealed_policy_cannot_grant_authority(self):
        p,t,s=self.inputs()
        for key in probe.DEV_AUTH:
            bad=copy.deepcopy(p);bad[key]=True if p[key] is not True else False
            bad.pop('receipt_sha256');bad=probe.seal(bad)
            with self.assertRaisesRegex(RuntimeError,'BLOCKED_AUTHORITY'):
                probe.authorize(bad,t,s)

    def test_policy_identity_code_cost_data_and_parent_drift_block(self):
        p,t,s=self.inputs()
        for key in ('parent_candidate_sha256','dataset_sha256','parent_terminal_sha256'):
            bad=copy.deepcopy(p);bad[key]='0'*64;bad.pop('receipt_sha256');bad=probe.seal(bad)
            with self.assertRaises(RuntimeError):probe.authorize(bad,t,s)
        bad=copy.deepcopy(p);bad['code_files_sha256'][next(iter(bad['code_files_sha256']))]='0'*64
        bad.pop('receipt_sha256');bad=probe.seal(bad)
        with self.assertRaisesRegex(RuntimeError,'CODE_CONFIG_IDENTITY'):probe.authorize(bad,t,s)
        bad=copy.deepcopy(s);bad['development']['cost_by_symbol'][next(iter(bad['development']['cost_by_symbol']))]['fee_bps']=0
        with self.assertRaisesRegex(RuntimeError,'BINDING_HASH'):probe.authorize(p,t,bad)
        bad=copy.deepcopy(t);bad['decision']='G5A_ECONOMIC_PASS'
        with self.assertRaises(RuntimeError):probe.authorize(p,bad,s)

    def test_original_reject_script_is_not_called_or_modified(self):
        p,t,s=self.inputs()
        with patch.object(probe.parent,'freeze_candidate',side_effect=AssertionError('MUST_NOT_CALL')),patch.object(probe.parent,'require_before_cheap',side_effect=AssertionError('MUST_NOT_CALL')):
            probe.authorize(p,t,s)
        self.assertIn('UNEXPECTED_PRIMARY_EVIDENCE_CHANGE_REQUIRES_SEPARATE_REVIEWED_CANDIDATE',Path(probe.parent.__file__).read_text())
        for path,digest in p['immutable_files_sha256'].items():
            self.assertEqual(probe.file_sha(probe.ROOT/path),digest)


class DataBoundaryTests(unittest.TestCase):
    def test_prefix_does_not_decode_following_holdout_object(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'source.json';rows=fixture_bars(2)
            # A deliberately invalid holdout tail cannot be decoded by the prefix reader.
            path.write_text(json.dumps(rows)[:-1]+',THIS_IS_NOT_A_VALID_HOLDOUT_OBJECT]')
            self.assertEqual(probe.prefix_rows(path,2),rows)
            with self.assertRaises(RuntimeError):probe.prefix_rows(path,3)

    def test_live_ledger_network_and_process_are_inaccessible(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);allowed=root/'dev.json';allowed.write_text('{}');out=root/'out';out.mkdir()
            forbidden=root/'production_ledger.jsonl';forbidden.write_text('protected')
            with probe.io_boundary([allowed],out):
                self.assertEqual(allowed.read_text(),'{}')
                for op in (lambda:forbidden.read_text(),lambda:forbidden.write_text('bad'),lambda:socket.socket(),lambda:subprocess.run(['true'])):
                    with self.assertRaises(RuntimeError):op()
                (out/'receipt.json').write_text('{}')
            self.assertEqual(forbidden.read_text(),'protected')

    def test_output_existing_receipt_is_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'receipt.json';probe.write_immutable(p,b'a');probe.write_immutable(p,b'a',verify_only=True)
            with self.assertRaisesRegex(RuntimeError,'REPRODUCTION_MISMATCH'):probe.write_immutable(p,b'b')
            with self.assertRaisesRegex(RuntimeError,'MISSING'):probe.write_immutable(Path(td)/'missing',b'a',verify_only=True)


class CostAndMetricTests(unittest.TestCase):
    def test_cost_uses_actual_crossed_settlements_without_double_slippage(self):
        b={'fee_bps':10.0,'spread_bps':1.0,'impact_bps':2.0,'funding_p95_per_settlement_bps':2.0}
        for entry,exit,count in ((0,86_400_000,3),(28_800_000,57_600_000,1),(1,28_799_999,0)):
            c=probe.cost_components(entry,exit,b)
            self.assertEqual(c['funding_settlements_crossed'],count)
            self.assertEqual(c['cost_bps'],13+2*count)
            self.assertEqual(c['slippage_bps'],0)
            self.assertTrue(c['slippage_included_in_impact'])
            self.assertEqual(probe.parent.development_cost(entry,exit,b,multiplier=2),2*c['cost_bps'])

    def trades(self):
        return [{'entry_ts':i*probe.DAY_MS,'exit_ts':(i+1)*probe.DAY_MS,'signal_ts':i*probe.DAY_MS,'symbol':'A',
                 'net_bps':x,'gross_bps':x+10,'cost2x_net_bps':x-10,'hold_ms':probe.DAY_MS} for i,x in enumerate([100,-50,0])]

    def test_hand_calculated_metrics_use_net_basis_and_no_fake_average_r(self):
        r=probe.summarize(self.trades(),start_ms=0,end_ms=10*probe.DAY_MS,symbol_count=1)
        self.assertEqual(r['net_bps'],50);self.assertAlmostEqual(r['expectancy_bps_per_trade'],50/3)
        self.assertEqual(r['PF'],2);self.assertEqual(r['win_rate'],1/3)
        self.assertEqual(r['average_win_bps'],100);self.assertEqual(r['average_loss_bps'],-50)
        self.assertEqual(r['realized_payoff'],2);self.assertEqual(r['DD_trade_sum_bps'],50)
        self.assertEqual(r['time_in_market_fraction'],0.3);self.assertIsNone(r['avgR'])
        self.assertEqual(probe.summarize(self.trades(),start_ms=0,end_ms=10*probe.DAY_MS,symbol_count=1,cost2x=True)['net_bps'],20)

    def test_empty_or_missing_loss_distribution_not_zero_or_pass(self):
        for rows in ([],self.trades()[:1]):
            r=probe.summarize(rows,start_ms=0,end_ms=10*probe.DAY_MS,symbol_count=1)
            self.assertIsNone(r['PF']);self.assertIsNone(r['realized_payoff'])
        r=probe.summarize([],start_ms=0,end_ms=probe.DAY_MS,symbol_count=1)
        self.assertIsNone(r['expectancy_bps_per_trade']);self.assertIsNone(r['win_rate'])

    def test_cluster_resampling_reuses_joint_weeks_and_is_reproducible(self):
        p={'development_interval_ms':[0,20*probe.DAY_MS],'uncertainty':{'seed':1,'replications':50,'method':'JOINT_WEEK'}}
        a=probe.cluster_uncertainty({'base':self.trades(),'copy':self.trades()},p)
        self.assertEqual(a,probe.cluster_uncertainty({'base':self.trades(),'copy':self.trades()},p))
        self.assertEqual(a['paired_base_minus_control_95pct_interval_bps']['copy'],[0,0])
        self.assertIsNone(a['N_effective'])


class ScenarioTests(unittest.TestCase):
    def test_synthetic_complete_probe_is_deterministic_with_exact_ledger_parity(self):
        policy=probe.read(probe.POLICY);rows=fixture_bars(100)
        policy['development_interval_ms']=[rows[0]['bar_open_ts'],rows[-1]['bar_close_ts']]
        policy['uncertainty']['replications']=30
        dev=copy.deepcopy(probe.read(probe.STAGE)['development'])
        dev['cost_by_symbol']={'A':dev['cost_by_symbol']['BTC-USDT']}
        spec=probe.read('backend/research/contracts/g5a_stage_source_cost_contract_v1.json')['candidate_spec']
        a=probe.compute({'A':rows},policy,dev,spec);b=probe.compute({'A':rows},policy,dev,spec)
        self.assertEqual(a,b)
        trades,events,_,metrics,*_=a
        self.assertGreater(len(trades['base']),0)
        self.assertEqual(sum(len(ts) for ts in trades.values()),sum(e['status']=='COMPLETED' for e in events))
        for name,ts in trades.items():
            self.assertEqual(metrics[name]['base_cost']['completed_T'],len(ts))
            for t in ts:
                self.assertEqual(t['hold_ms'],24*60*60*1000)
                self.assertAlmostEqual(t['cost2x_net_bps'],t['gross_bps']-2*t['cost_bps'])
                self.assertEqual(t['formal_credit'],0)

    def test_dst_weekday_and_bar_overlap_are_not_entry_overlap(self):
        spec=probe.read('backend/research/contracts/g5a_stage_source_cost_contract_v1.json')['candidate_spec']
        def bar(start,end):return {'bar_open_ts':int(datetime.fromisoformat(start).timestamp()*1000),'bar_close_ts':int(datetime.fromisoformat(end).timestamp()*1000)}
        for start,end,expected in [('2025-03-10T12:00:00+00:00','2025-03-10T16:00:00+00:00',True),
                                   ('2025-03-31T16:00:00+00:00','2025-03-31T20:00:00+00:00',False),
                                   ('2025-03-29T12:00:00+00:00','2025-03-29T16:00:00+00:00',False),
                                   ('2025-01-10T16:00:00+00:00','2025-01-10T20:00:00+00:00',True)]:
            self.assertEqual(probe.parent.session_overlap(bar(start,end),spec),expected)
        b=bar('2025-01-10T16:00:00+00:00','2025-01-10T20:00:00+00:00')
        self.assertTrue(probe.parent.session_overlap(b,spec))
        self.assertFalse(probe.parent.session_overlap({'bar_open_ts':b['bar_close_ts'],'bar_close_ts':b['bar_close_ts']+1},spec))

    def test_all_controls_and_feature_ablations_are_preregistered(self):
        p=probe.read(probe.POLICY);spec=probe.read('backend/research/contracts/g5a_stage_source_cost_contract_v1.json')['candidate_spec']
        rows=fixture_bars();features=[probe.parent.features(rows,i,spec) for i in range(len(rows))]
        result=probe.scenario_signals(rows,features,p,spec)
        self.assertEqual(set(result),set(p['scenarios'])-{'baseline_exposure_matched'})
        self.assertEqual(result['direction_flip'],result['base'])
        self.assertEqual(result['delayed_entry'],result['base'])
        self.assertTrue(set(result['base']).issubset(result['ablation_session']))
        self.assertTrue(set(result['base']).issubset(result['ablation_volume']))
        self.assertTrue(set(result['base']).issubset(result['ablation_breakout']))
        self.assertEqual(result,probe.scenario_signals(rows,features,p,spec))

    def test_zero_volume_keeps_unknown_feature_separate_from_no_signal(self):
        spec=probe.read('backend/research/contracts/g5a_stage_source_cost_contract_v1.json')['candidate_spec']
        rows=fixture_bars(21)
        for r in rows:r['volume']=0.0
        self.assertIsNone(probe.parent.features(rows,20,spec))

    def test_volume_ablation_and_baseline_do_not_inherit_denominator_guard(self):
        p=probe.read(probe.POLICY);spec=probe.read('backend/research/contracts/g5a_stage_source_cost_contract_v1.json')['candidate_spec']
        rows=fixture_bars()
        for r in rows:r['volume']=0.0
        values=probe.feature_rows(rows,spec)
        self.assertTrue(all(v is None or v['relative_total_volume_activity'] is None for v in values))
        signals=probe.scenario_signals(rows,values,p,spec)
        self.assertEqual(signals['base'],[])
        self.assertTrue(signals['baseline_breakout'])
        self.assertTrue(signals['ablation_volume'])

    def test_incomplete_exposure_match_cannot_alone_reject_or_promote(self):
        p=probe.read(probe.POLICY)
        m={'base':{'event_count':3,'base_cost':{'completed_T':3,'PF':2,'expectancy_bps_per_trade':10},'cost2x':{'net_bps':10}},
           'baseline_exposure_matched':{'comparison_valid':False,'base_cost':{'expectancy_bps_per_trade':100}}}
        self.assertEqual(probe.decide(m,{},p)[0],'DEV_INCONCLUSIVE')
        m['base']['base_cost']['expectancy_bps_per_trade']=-1
        self.assertEqual(probe.decide(m,{},p)[0],'DEV_SCREEN_REJECT')

    def test_measurement_state_never_maps_prior_p0_to_economic_reject(self):
        p=probe.read(probe.POLICY)
        self.assertEqual(len(set(probe.STATE_MAP.values())),len(probe.STATE_MAP))
        self.assertFalse(any('G5A_ECONOMIC_REJECT' in x for x in probe.STATE_MAP.values()))
        m={'base':{'event_count':0,'base_cost':{'completed_T':0},'cost2x':{}}}
        self.assertEqual(probe.decide(m,{},p),('DEV_INCONCLUSIVE',['MEASURED_NO_EVENTS']))
        m['base']['event_count']=1
        self.assertEqual(probe.decide(m,{},p),('DEV_INCONCLUSIVE',['MEASURED_NO_COMPLETED_TRADES']))


if __name__=='__main__':unittest.main()
