"""Synthetic authority, goal and full-pipeline checks; no historical prices."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import break_channel_q1_v1 as x
from backend.research.rebuild.test_break_channel_structure_v1 import bars


def contract():
    return x.old.seal({'authorization': 'EXPLICIT_USER_ONE_Q1_AFTER_PR1190',
        'budget': deepcopy(x.BUDGET), 'rule': deepcopy(x.RULE), 'goal': deepcopy(x.GOAL),
        'outcomes_seen_at_freeze': False, 'code_files_sha256': {}, 'preserved_files_sha256': {},
        'Q0_receipt_sha256': 'prior', 'batch_id': 'SYNTHETIC_Q1',
        'symbols': ['TEST'], 'evaluation_interval_ms': [2*x.prior.DAY, 20*x.prior.DAY],
        'Q0_drawdown_window_ms': [5*x.prior.DAY, 10*x.prior.DAY],
        'data_sha256': 'synthetic-data', 'cost_sha256': 'synthetic-cost', 'data_reuse_history': [],
        'validation_access': False, 'OOS_access': False, 'G5B_changed': False,
        'G6_authorized': False, 'operating_changed': False, **x.old.probe.DEV_AUTH})


def prior_receipt(count=24):
    return x.old.seal({'budget': {'cumulative_after': count},
                      'comparisons': {'P_to_Q': {'decision': {'decision': 'DEV_INCONCLUSIVE'}}}})


def reseal(c):
    return x.old.seal({k:v for k,v in c.items() if k != 'receipt_sha256'})


class AuthorityTests(unittest.TestCase):
    def test_resealed_mutations_fail_before_data_loader(self):
        cases = [('count', lambda c:c['budget'].update(cumulative_after=26)),
            ('Q2',lambda c:c['budget'].update(Q2_authorized=True)),
            ('exit',lambda c:c['rule'].update(update='different strategy')),
            ('goal',lambda c:c['goal'].update(large_winner_capped_retention_min=.1)),
            ('authorization',lambda c:c.update(authorization='other')),
            ('seen',lambda c:c.update(outcomes_seen_at_freeze=True)),
            ('OOS',lambda c:c.update(OOS_access=True)),
            ('validation',lambda c:c.update(validation_access=True)),
            ('G5B',lambda c:c.update(G5B_changed=True)),
            ('G6',lambda c:c.update(G6_authorized=True)),
            ('operating',lambda c:c.update(operating_changed=True)),
            ('orders',lambda c:c.update(order_authority='OPEN'))]
        for name, mutation in cases:
            c=contract();mutation(c);c=reseal(c)
            with self.subTest(name=name), patch.object(x,'read_local',return_value=c), patch.object(x.prior.inputs,'load_inputs') as loader:
                with self.assertRaises(RuntimeError):x.run(Path('NEVER_LOAD'))
                loader.assert_not_called()

    def test_previous_count_status_and_bytes_preserved(self):
        c=contract();p=prior_receipt();c['Q0_receipt_sha256']=p['receipt_sha256'];c=reseal(c)
        def reads(path):return c if path==x.CONTRACT else p
        with patch.object(x,'read_local',side_effect=reads):self.assertEqual(x.authorize(),c)
        p=prior_receipt(23)
        with patch.object(x,'read_local',side_effect=reads):
            with self.assertRaisesRegex(RuntimeError,'PRIOR_ALLOCATION'):x.authorize()
        p=prior_receipt();p['comparisons']['P_to_Q']['decision']['decision']='DEV_PROMISING';p=reseal(p)
        c['Q0_receipt_sha256']=p['receipt_sha256'];c=reseal(c)
        with patch.object(x,'read_local',side_effect=reads):
            with self.assertRaisesRegex(RuntimeError,'Q0_STATUS'):x.authorize()
        p=prior_receipt();c['Q0_receipt_sha256']=p['receipt_sha256']
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'prior').write_text('unchanged')
            c['preserved_files_sha256']={'prior':x.old.file_sha(root/'prior')};c=reseal(c)
            with patch.object(x,'ROOT',root),patch.object(x,'read_local',side_effect=reads):
                self.assertEqual(x.authorize(),c)
                (root/'prior').write_text('altered')
                with self.assertRaisesRegex(RuntimeError,'FROZEN_IDENTITY'):x.authorize()

    def test_consumed_allocation_blocks_before_loader(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/x.OUTPUT;out.mkdir(parents=True);(out/'receipt.json').write_text('{}')
            with patch.object(x,'ROOT',root),patch.object(x,'authorize',return_value=contract()),patch.object(x.prior.inputs,'load_inputs') as loader:
                with self.assertRaisesRegex(RuntimeError,'ALLOCATION_CONSUMED'):x.run(root)
                loader.assert_not_called()


def goal_inputs():
    baseline={'base_cost':{'completed_T':10,'net_bps':100.,'expectancy_bps_per_trade':10.,'PF':2.,'realized_payoff':2.},
              'cost2x':{'net_bps':50.},'open_observations':{'T':0},
              'total_exposure_symbol_days':10.,'closed_plus_hypothetical_terminal_mark_bps':100.}
    metrics={s:deepcopy(baseline) for s in ('Q0','Q1_fixed','Q1')}
    for s in ('Q1_fixed','Q1'):metrics[s]['total_exposure_symbol_days']=9.
    di={s:{'lane_simultaneous_close_group_streaks':{'max_loss_trade_sum_bps':20.}} for s in metrics}
    marked={s:{'marked_DD_trade_sum_bps':30.} for s in metrics}
    large={s:{'lower':.9} for s in ('Q1_fixed','Q1')}
    u={'Q0_to_Q1':{'child_minus_parent_95pct_interval_bps_per_day':[-1,2]}}
    return metrics,di,marked,large,u


class GoalTests(unittest.TestCase):
    def test_observational_reference_is_separate_from_strong_and_formal_claim(self):
        result=x.study_decision(*goal_inputs())
        self.assertTrue(result['study_goal_met']);self.assertEqual(result['research_reference'],'Q1')
        self.assertEqual(result['decision'],'DEV_INCONCLUSIVE')
        self.assertFalse(result['formal_pass']);self.assertFalse(result['operating_adoption']);self.assertFalse(result['Q2_authorized'])

    def test_smaller_risk_cannot_hide_lost_aggregate_or_large_winners(self):
        for target in ('aggregate','large','exposure','risk','cost2','open'):
            args=goal_inputs();m,di,md,large,u=args
            if target=='aggregate':m['Q1_fixed']['closed_plus_hypothetical_terminal_mark_bps']=99.
            elif target=='large':large['Q1']['lower']=.899
            elif target=='exposure':m['Q1']['total_exposure_symbol_days']=10.
            elif target=='risk':md['Q1']['marked_DD_trade_sum_bps']=31.
            elif target=='cost2':m['Q1']['cost2x']['net_bps']=0.
            else:m['Q1']['open_observations']['T']=1
            with self.subTest(target=target):
                r=x.study_decision(*args);self.assertFalse(r['study_goal_met']);self.assertEqual(r['research_reference'],'Q0')

    def test_undefined_metrics_and_unfinished_evidence_are_separate(self):
        args=goal_inputs();args[0]['Q1']['base_cost']['PF']=None
        self.assertEqual(x.study_decision(*args)['decision'],'INSUFFICIENT')
        args=goal_inputs();args[0]['Q1']['open_observations']['T']=1
        r=x.study_decision(*args)
        self.assertEqual(r['decision'],'DEV_INCONCLUSIVE');self.assertEqual(r['study_screen_decision'],'DEV_REJECT')
        self.assertEqual(r['closed_absolute_screen_decision'],'POSITIVE_CLOSED_ECONOMICS')
        self.assertEqual(r['overall_blocker'],'UNRESOLVED_TERMINAL_POSITIONS');self.assertEqual(r['research_reference'],'Q0')


class PipelineTests(unittest.TestCase):
    def test_synthetic_full_pipeline_and_immutable_reproduction(self):
        rows=bars(120)
        prices=[100,100.1,101,102,103,103.1,105,106,107,103,103.1,104,105,104,103,103.1,104,105,106,107]
        for i,row in enumerate(rows):
            px=prices[i//6];row.update(open=px,high=px+.1,low=px-.1,close=px)
        snapshot=deepcopy(rows);c=contract();start,end=c['evaluation_interval_ms']
        costs={'TEST':{'fee_bps':10,'spread_bps':2,'impact_bps':1,'funding_p95_per_settlement_bps':3}}
        p={'development_interval_ms':[0,end],'batch_id':'SYNTHETIC_Q0','receipt_sha256':'synthetic-policy',
           'combined_data_sha256':'synthetic-data','cost_binding_sha256':'synthetic-cost',
           'code_files_sha256':{},'symbols':['TEST'],'uncertainty':{'replications':1000,'seed':1178}}
        daily=x.prior.structure.aggregate_daily(rows,split_end_ms=end)['daily']
        bundle=x.prior.structure.generate_signals(daily,eval_start_ms=start,eval_end_ms=end)
        raw=x.prior.structure.replay(rows,bundle,eval_start_ms=start,eval_end_ms=end)
        baseline={'trades':[],'open_observations':[],'events':[]}
        for s in ('P','Q'):
            baseline['trades'].extend(x.prior.charge(t,'TEST',s,p,costs,rows) for t in raw['trades'])
            baseline['open_observations'].extend(x.prior.charge_open(t,'TEST',s,p,costs,rows) for t in raw['open_positions'])
            baseline['events'].extend(dict(e,symbol='TEST',comparison_stage=s,lane_id=x.prior.LANE,scenario=s) for e in raw['events'])
        q0=prior_receipt();q0['metrics']={};q0['diagnostics']={};q0['marked_diagnostics']={}
        baseline['daily_valuation']=[];pp={**p,'development_interval_ms':[start,end]}
        for s in ('P','Q'):
            ts=[t for t in baseline['trades'] if t['comparison_stage']==s]
            os=[t for t in baseline['open_observations'] if t['comparison_stage']==s]
            es=[t for t in baseline['events'] if t['comparison_stage']==s]
            q0['metrics'][s]=x.prior.accounting.summarize(ts,os,es,pp,['TEST'])
            q0['diagnostics'][s]=x.prior.accounting.diagnostics(ts,start,end)
            val=x.prior.daily_valuation(ts,os,{'TEST':rows},costs,start,end)
            q0['marked_diagnostics'][s]=x.prior.accounting.daily_mark_diagnostics(val)
            baseline['daily_valuation'].extend(dict(t,comparison_stage=s) for t in val)
        q0=reseal(q0);c['Q0_receipt_sha256']=q0['receipt_sha256'];c=reseal(c)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/x.OUTPUT;out.mkdir(parents=True);previous=root/x.prior.OUTPUT;previous.mkdir(parents=True)
            for path,payload in ((x.CONTRACT,c),(x.DIAGNOSIS,{}),(x.prior.CONTRACT,{'evaluation_interval_ms':[start,end]}),(x.prior.OUTPUT+'/receipt.json',q0)):
                (root/path).write_bytes(x.old.probe.canonical(payload))
            (root/x.SOURCE).write_text('SYNTHETIC ONLY; NO HISTORICAL PRICES')
            for name,items in baseline.items():
                (previous/(name+'.jsonl.gz')).write_bytes(gzip.compress(b''.join(x.old.probe.canonical(t) for t in items),mtime=0))
            before_prior={p.name:p.read_bytes() for p in previous.iterdir()}
            loaded=(p,{'cost_by_symbol':costs},{'TEST':rows},{},{'TEST':{'decoded_partition':'SYNTHETIC_ONLY','decoded_validation_rows':0,'decoded_OOS_rows':0}})
            with patch.object(x,'ROOT',root),patch.object(x.prior.inputs,'load_inputs',return_value=loaded):
                r=x.run(root/'NO_EXTERNAL_INPUTS');before={p.name:p.read_bytes() for p in out.iterdir()}
                rr=x.run(root/'NO_EXTERNAL_INPUTS',verify_only=True)
                self.assertEqual(r,rr);self.assertEqual(before,{p.name:p.read_bytes() for p in out.iterdir()})
                self.assertEqual(before_prior,{p.name:p.read_bytes() for p in previous.iterdir()})
                self.assertEqual(r['budget']['cumulative_after'],25);self.assertEqual(r['budget']['new_trials_consumed'],1)
                self.assertEqual(r['budget']['remaining_allocated_trials'],0);self.assertFalse(r['decision']['formal_pass'])
                self.assertEqual(r['metrics']['Q1_fixed']['raw_signals'],len(raw['trades'])+len(raw['open_positions']))
                for w in r['same_calendar_windows'].values():self.assertEqual(w['parity'],'PASS')
                for k,v in x.old.probe.DEV_AUTH.items():self.assertEqual(r[k],v)
                self.assertEqual(r['validation_rows_decoded'],0);self.assertEqual(r['OOS_rows_decoded'],0)
                self.assertEqual(r['paid_external_AI_calls'],0)
        self.assertEqual(rows,snapshot)


if __name__=='__main__':unittest.main()
