"""Artificial saved-only verification, serialization and mutation rejection."""
from copy import deepcopy
from dataclasses import replace
from math import fsum
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from backend.research.rebuild import c70_lotlock_v1 as e
from backend.research.rebuild import c70_lotlock_account_v1 as c
from backend.research.rebuild import c70_lotlock_verify_v1 as v
from backend.research.rebuild.test_c63_c70_trader_management_v1 import fixture,COST,POLICY,rows_of


def saved_fixture(n=150,entries=(60,79,93),floor=False,reversal=True):
    bars,signal,_=fixture(n=n)
    if reversal:
        for j in range(91,n):bars[j]=replace(bars[j],open=111.,high=112.,low=110.,close=111.)
    if floor:bars[91]=replace(bars[91],close=80.,low=79.)
    features=[dict(momentum=bars[j].close-bars[j-14].close if j>=14 else 0.) for j in range(n)]
    signals=[dict(signal,signal_index=j-1,signal_ts=j*e.tm.BAR,setup_id=str(j)) for j in entries if j<n]
    obs=dict(eligible=True,reason=None,range_context=dict(rescued=False))
    rows=rows_of(bars)
    with patch.object(e.tm.native,'m1_setups',return_value=(signals,[],features)),\
         patch.object(e.tm.c63,'context',return_value=obs),\
         patch.object(e.tm,'c70_context',side_effect=lambda original,daily:original):
        raw=e.replay(rows,eval_start_ms=0,eval_end_ms=n*e.tm.BAR,cost=COST)
    return json.loads(c.a.canon(raw)),rows


def verify_all(raw,rows):
    end=rows[-1]['bar_close_ts']
    result=v.verify_lots(raw,rows,COST,end)
    for lot in raw['trades']+raw['open_positions']:
        trace=[t for t in raw['trace'] if t['signal_index']==lot['signal_index']]
        v.verify_source_actual(lot,trace,raw['source_references'][str(lot['signal_index'])],rows,COST,end,raw['lot_trace'])
    return result


class SavedLotVerificationTests(unittest.TestCase):
    def test_JSON_roundtrip_open_cut_and_source_priority(self):
        for n,floor in ((78,False),(92,False),(150,False),(150,True)):
            with self.subTest(n=n,floor=floor):
                raw,rows=saved_fixture(n=n,floor=floor)
                observations,triggers=verify_all(raw,rows)
                self.assertEqual(observations,len(raw['lot_trace']))
                self.assertEqual(triggers,raw['audit']['lot_lock_triggers'])

    def test_checker_never_calls_strategy_or_wrapper(self):
        raw,rows=saved_fixture()
        with patch.object(e,'replay',side_effect=AssertionError('REPLAY_FORBIDDEN')),\
             patch.object(e,'manage',side_effect=AssertionError('WRAPPER_FORBIDDEN')),\
             patch.object(e,'lot_value',side_effect=AssertionError('ENGINE_CASH_FORBIDDEN')),\
             patch.object(e.tm,'position',side_effect=AssertionError('SOURCE_REPLAY_FORBIDDEN')),\
             patch.object(e.tm,'cost_at',side_effect=AssertionError('ENGINE_COST_FORBIDDEN')):
            verify_all(raw,rows)

    def test_missing_close_observation_rejected(self):
        raw,rows=saved_fixture();raw['lot_trace'].pop(4)
        with self.assertRaisesRegex(AssertionError,'MISSING_COMPLETED'):verify_all(raw,rows)

    def test_cross_lot_bank_or_peak_rejected(self):
        for field in ('lot_realized_bank_net','lot_peak_marked_net'):
            raw,rows=saved_fixture()
            obs=next(t for t in raw['lot_trace'] if t['first_partial_fill_ts'] is not None)
            obs[field]+=1.
            with self.assertRaises(AssertionError):verify_all(raw,rows)

    def test_partial_decision_cannot_become_actual_bank(self):
        raw,rows=saved_fixture()
        obs=next(t for t in raw['lot_trace'] if t['ts']==78*e.tm.BAR)
        self.assertIsNone(obs['first_partial_fill_ts'])
        obs['first_partial_fill_ts']=obs['ts']
        with self.assertRaisesRegex(AssertionError,'ACTUAL_PARTIAL_FIRST'):verify_all(raw,rows)

    def test_false_trigger_cannot_be_hidden_by_matching_audit(self):
        raw,rows=saved_fixture()
        obs=next(t for t in raw['lot_trace'] if t['trigger']);obs['trigger']=False
        raw['audit']['lot_lock_triggers']-=1
        with self.assertRaisesRegex(AssertionError,'OWN_LOT_FIRST_THRESHOLD'):verify_all(raw,rows)

    def test_other_lot_decision_cannot_close_this_lot(self):
        raw,rows=saved_fixture();lot=next(r for r in raw['trades'] if r['lot_lock_exit'])
        lot['exit_trigger']['lot_signal_index']+=1
        with self.assertRaises(AssertionError):verify_all(raw,rows)

    def test_extra_post_trigger_observation_rejected(self):
        raw,rows=saved_fixture();obs=deepcopy(next(t for t in raw['lot_trace'] if t['trigger']))
        obs['index']+=1;obs['ts']+=e.tm.BAR;raw['lot_trace'].append(obs)
        with self.assertRaisesRegex(AssertionError,'POST_TRIGGER'):verify_all(raw,rows)

    def test_normalized_fill_tamper_rejected(self):
        raw,rows=saved_fixture();event=next(t for t in raw['trace'] if 'normalized_fill_qty' in t)
        event['normalized_fill_qty']*=2
        with self.assertRaisesRegex(AssertionError,'NORMALIZED_FILL'):verify_all(raw,rows)

    def test_normalized_lot_bank_peak_and_quantity_tamper_rejected(self):
        for name in ('normalized_lot_realized_bank_net','normalized_lot_peak_marked_net','normalized_remaining_qty'):
            raw,rows=saved_fixture(reversal=False)
            event=next(t for t in raw['lot_trace'] if t['allocation_denominator']>1 and t['lot_peak_marked_net'] is not None)
            event[name]+=1
            with self.assertRaisesRegex(AssertionError,'NORMALIZED_OWN_LOT'):verify_all(raw,rows)

    def test_uncut_lot_path_is_immutable(self):
        raw,rows=saved_fixture();lot=next(r for r in raw['trades']+raw['open_positions'] if not r['lot_lock_exit'])
        lot['tm_legs'][-1]['price']+=1
        with self.assertRaisesRegex(AssertionError,'UNCUT_SOURCE_LIFECYCLE_CHANGED'):verify_all(raw,rows)

    def test_risk_fill_uses_observed_open(self):
        raw,rows=saved_fixture();lot=next(r for r in raw['trades'] if r['lot_lock_exit'])
        lot['exit_price']+=1
        with self.assertRaisesRegex(AssertionError,'OBSERVABLE_GAP_FILL'):verify_all(raw,rows)

    def test_campaign_cash_weights_all_legs_once(self):
        raw,rows=saved_fixture();packet=dict(policy=POLICY,costs={'TEST':COST},rows_by={'TEST':rows})
        result=c.charge({'TEST':raw},packet,dict(start_ms=0,runoff_end_ms=rows[-1]['bar_close_ts']))
        values={c.a.key(r):(status,r) for status,name in [('C','trades'),('O','open_observations')] for r in result[name]}
        for lot in raw['trades']+raw['open_positions']:
            status,row=values[('TEST',lot['signal_index'],lot['signal_ts'])]
            q=lot['allocation_numerator']/lot['allocation_denominator']
            net=q*fsum(l['qty']*((l['price']/lot['entry_price']-1)*10000-
                fsum(v.old.independent_cost(COST,lot['entry_ts'],l['ts']).values())) for l in lot['tm_legs'])
            self.assertAlmostEqual(c.a.bridge._values((status,row))['net_bps'],net)
        self.assertEqual(len(values),len(raw['trades'])+len(raw['open_positions']))

    def test_saved_period_integration_without_economic_replay(self):
        raw,rows=saved_fixture();packet=dict(policy=POLICY,costs={'TEST':COST},rows_by={'TEST':rows})
        cal=dict(start_ms=0,runoff_end_ms=rows[-1]['bar_close_ts'])
        result=json.loads(c.a.canon(c.charge({'TEST':raw},packet,cal)))
        # Artificial saved parents exercise adapters, never historical engines.
        parents={label:deepcopy(result) for label in ('C70_LOCAL','C70_TM','CAPREUSE','PROFITLOCK')}
        with TemporaryDirectory() as temp:
            root=Path(temp);out=root/'scope';inputs=root/'inputs';parent=root/'parent';per='SYNTHETIC'
            folder=out/per
            for path,value in ((inputs/(per+'.json.gz'),packet),(folder/'RAW.json.gz',{'TEST':raw}),
                (folder/'RESULT.json.gz',result),(parent/per/'RAW.json.gz',{'TEST':raw}),
                (folder/'PARENT_DD_ATTRIBUTION.json.gz',c.attribution(parents,packet,cal)),
                (folder/'DD_ATTRIBUTION.json.gz',c.attribution(dict(parents,LOTLOCK=result),packet,cal)),
                (folder/'SNAPSHOT.json',c.snapshot(result,parents['C70_LOCAL'])),
                (folder/'RISK_BRIDGE.json',c.risk_bridge(parents['CAPREUSE'],result))):c.a.put(path,value)
            for label,p,ch in [('A','C70_LOCAL','C70_TM'),('B','C70_TM','CAPREUSE'),('C','CAPREUSE','LOTLOCK'),('D','C70_LOCAL','LOTLOCK')]:
                c.a.put(folder/('DECOMPOSITION_'+label+'.json'),c.a.decomposition(parents[p],result if ch=='LOTLOCK' else parents[ch]))
            with patch.object(c,'OUT',out),patch.object(c.a,'INPUTS',inputs),patch.object(c.cap,'OUT',parent),\
                 patch.object(c,'parents',return_value=parents),patch.object(e,'replay',side_effect=AssertionError('NO_REPLAY')):
                checked=v.verify_period(per,dict(periods={per:cal}))
            self.assertEqual(checked['status'],'PASS');self.assertEqual(checked['economic_replays'],0)
            self.assertEqual(checked['other_lot_collateral_exit_qty'],0)

    def test_budget_and_exclusive_start_receipts(self):
        with TemporaryDirectory() as temp:
            out=Path(temp);periods=list(c.a.PERIODS)
            spec=dict(scope=e.SCOPE,candidate=e.RULE,candidate_ordinal=84,max_candidates=1,max_FULL=2,frozen_ns=100,
                      plan=[dict(period=per,candidate_ordinal=84,evaluation_ordinal=151+j) for j,per in enumerate(periods)])
            c.a.put(out/'SPEC.json',spec)
            prior=dict(candidate_trials=[{'saved':'old_candidate'}],trials=[{'saved':'old_trial'}],
                       cumulative_actual=83,cumulative_actual_evaluations=150)
            budget=deepcopy(prior)
            budget.update(cumulative_actual=84,cumulative_actual_evaluations=152,
                c70_lotlock_allocation=dict(scope=e.SCOPE,max_candidates=1,max_executions=2,retry=False,
                    started=2,completed=2,reserved=2,remaining=0,failed=0,candidate_ordinal=84,evaluation_ordinals=[151,152]))
            budget['candidate_trials'].append(dict(candidate=e.RULE,first_evaluation=151,ordinal=84,scope=e.SCOPE))
            for j,plan in enumerate(spec['plan']):
                trial=dict(plan,actual_experiment_ordinal=plan['evaluation_ordinal'],status='COMPLETED',
                    scope=e.SCOPE,variant=e.RULE,execution_mode='LOCAL_WORK_FIRST_FULL',spec_sha256=c.a.h(out/'SPEC.json'),
                    started_ns=101+2*j,finished_ns=102+2*j,frozen_commit='f'*40,owner='SYNTHETIC')
                budget['trials'].append(trial)
                c.a.put(out/plan['period']/'ATTEMPT.json',trial)
                c.a.put(out/plan['period']/'EXECUTION_STARTED.json',dict({k:v for k,v in trial.items() if k!='finished_ns'},status='STARTED'))
            with patch.object(c,'OUT',out):
                v.verify_history(spec,prior,budget)
                for change in ('OLD_HISTORY','EXTRA_CANDIDATE','EXTRA_TRIAL','FAKE_COMPLETION'):
                    mutated=deepcopy(budget)
                    if change=='OLD_HISTORY':mutated['trials'][0]['saved']='changed'
                    if change=='EXTRA_CANDIDATE':mutated['candidate_trials'].append(dict(mutated['candidate_trials'][-1]))
                    if change=='EXTRA_TRIAL':mutated['trials'].append(dict(mutated['trials'][-1]))
                    if change=='FAKE_COMPLETION':mutated['trials'][-1]['finished_ns']+=1
                    with self.subTest(change=change),self.assertRaises(AssertionError):v.verify_history(spec,prior,mutated)


if __name__=='__main__':unittest.main()
