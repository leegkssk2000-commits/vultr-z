"""Causal exit timing, unchanged risk, cost binding and shared ownership parity."""
import copy
import json
import socket
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import top5_no_credit_exit_v1 as x
from backend.research.rebuild import g5_g14_governance_validator_v1 as gov
from backend.research.rebuild.test_top5_development_repair_v1 import fixture


def policy():
    p=x.old.read(x.old.POLICY)
    return {**p,'development_interval_ms':[0,400*x.HOUR]}


def costs():
    return {'TEST':{'fee_bps':6.,'spread_bps':2.,'impact_bps':2.,'funding_p95_per_settlement_bps':3.}}


def example(side='long', terminal=6):
    rows=fixture(12); closes=[100,101,100,99,101,103,104,104,104,104,104,104]
    for i,r in enumerate(rows):
        r.update(open=100. if i==0 else closes[i-1],close=closes[i],high=max(100,closes[i])+1,low=min(100,closes[i])-1)
    raw={'signal_index':0,'entry_index':1,'exit_index':terminal,'signal_ts':x.HOUR,'entry_ts':x.HOUR,
         'exit_ts':(terminal+1)*x.HOUR,'entry_price':100.,'exit_price':rows[terminal]['close'],'side':side,
         'gross_bps':(1 if side=='long' else -1)*(rows[terminal]['close']-100)*100,
         'exit_reason':'TIMEOUT','native_exit_bar_open_ts':terminal*x.HOUR,'hold_ms':terminal*x.HOUR,
         'mfe_bps':600.,'mae_bps':-200.}
    t=x.old.charge(raw,'TEST',x.old.LANES[0],'base',policy(),costs(),rows,x.HOUR)
    event={'sl':95. if side=='long' else 105.,'tp':None,'risk_size':{'fraction':.01},'exposure':{'x':1}}
    return rows,t,event


class ExitTiming(unittest.TestCase):
    def test_later_close_then_next_open_not_trigger_close(self):
        rows,t,e=example();rows[3]['open']=98.5
        out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertEqual(out['exit_index'],3);self.assertEqual(out['exit_ts'],3*x.HOUR)
        self.assertEqual(out['exit_price'],98.5);self.assertEqual(out['exit_overlay']['trigger_at_ms'],3*x.HOUR)
        self.assertEqual(out['exit_overlay']['armed_at_ms'],2*x.HOUR)
        self.assertEqual(out['entry_price'],t['entry_price']);self.assertEqual(out['original_protective_sl'],95.)

    def test_no_arm_from_intrabar_high_or_final_winner_label(self):
        rows,t,e=example()
        for r in rows:r.update(close=100.,high=9999)
        out=x.overlay(dict(t,net_bps=999999,mfe_bps=999999),e,rows,policy(),costs(),'child')
        self.assertFalse(out['exit_overlay']['exit_changed'])
        self.assertEqual(out['exit_ts'],t['exit_ts'])

    def test_same_rule_for_winners_losers_and_future_label_poison(self):
        rows,t,e=example();one=x.overlay(t,e,rows,policy(),costs(),'child')
        altered=copy.deepcopy(rows)
        for r in altered[3:]:r.update(high=9000,low=.001,close=8000)
        two=x.overlay(dict(t,net_bps=-999999,mfe_bps=999999,exit_price=1),e,altered,policy(),costs(),'child')
        for key in ['entry_ts','exit_ts','exit_price','gross_bps','net_bps','exit_overlay','mfe_bps','mae_bps']:
            self.assertEqual(one[key],two[key])

    def test_stop_on_trigger_bar_wins_before_closed_mark(self):
        rows,t,e=example(terminal=2);t.update(exit_reason='SL',exit_price=95.,gross_bps=-500.)
        out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertEqual(out['exit_reason'],'SL');self.assertEqual(out['exit_price'],95.)
        self.assertFalse(out['exit_overlay']['exit_changed'])

    def test_pending_open_before_later_intrabar_stop_and_gap_fill(self):
        rows,t,e=example(terminal=3);t.update(exit_reason='SL',exit_price=95.,gross_bps=-500.)
        rows[3].update(open=99.,low=90.)
        out=x.overlay(t,e,rows,policy(),costs(),'child');self.assertEqual(out['exit_price'],99.)
        rows[3]['open']=90.
        out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertEqual(out['exit_price'],90.);self.assertEqual(out['exit_reason'],'PENDING_EXIT_GAP_THROUGH_STOP')

    def test_short_uses_directional_observable_mark(self):
        rows,t,e=example('short');rows[1]['close']=99.;rows[2]['close']=100.;rows[3]['open']=101.
        out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertEqual(out['exit_index'],3);self.assertEqual(out['gross_bps'],-100.)

    def test_disabling_overlay_is_exact_parent_ablation(self):
        rows,t,e=example();out=x.overlay(t,e,rows,policy(),costs(),'base',False)
        x.assert_parent_parity([out],[t]);self.assertFalse(out['exit_overlay']['exit_changed'])

    def test_funding_recomputed_and_floor_not_lowered(self):
        rows,t,e=example(terminal=9);out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertEqual(t['funding_settlements_crossed'],1)
        self.assertEqual(out['funding_settlements_crossed'],0);self.assertEqual(out['funding_bps'],0)
        self.assertEqual(out['cost_bps'],20.);self.assertEqual(out['cost2x_net_bps'],out['gross_bps']-40.)
        bound=costs()['TEST']
        self.assertEqual(x.old.probe.cost_components(1,8*x.HOUR,bound)['funding_settlements_crossed'],1)
        self.assertEqual(x.old.probe.cost_components(1,8*x.HOUR-1,bound)['funding_settlements_crossed'],0)

    def test_current_mark_does_not_use_future_holding_cost(self):
        b=costs()['TEST'];b['funding_p95_per_settlement_bps']=100.
        self.assertGreater(x.mark_net(100,'long',x.HOUR,100.5,2*x.HOUR,b),0)
        self.assertLess(x.mark_net(100,'long',x.HOUR,100.5,9*x.HOUR,b),0)


class OwnershipAndAttribution(unittest.TestCase):
    def test_native_and_v2_disabled_full_lifecycle_matches_shared_engine(self):
        p=policy();c=costs()
        for lane in x.old.LANES:
            native=lane in x.old.LANES[:2];interval=x.HOUR if native else 4*x.HOUR
            rows=fixture(400,interval);p['development_interval_ms']=[0,len(rows)*interval]
            if native:base,events=x.old.one_hour(rows,'TEST',lane,p,c,'base')
            else:
                spec=next(s for s in x.old.read(x.old.FREEZE)['children'] if s['lane_id']==lane)
                base,events=x.old.four_hour(rows,'TEST',spec,p,c,'base')
            pool,audit=x.candidate_pool(rows,'TEST',lane,p,c,events)
            actual,_=x.lifecycle(pool,rows,p,c,'disabled',False)
            eligible={e['signal_index'] for e in audit if e['full_lifecycle_eligible']}
            x.assert_parent_parity(actual,[t for t in base if t['signal_index'] in eligible])
            self.assertTrue(all(e['time_only_max_hold_end_index']<len(rows)-1 for _,e in pool))

    def test_entry_attribution_does_not_use_exit_identity(self):
        rows,t,e=example();out=x.overlay(t,e,rows,policy(),costs(),'child')
        a=x.attribute([t],[out]);self.assertEqual(a['common_T'],1);self.assertEqual(a['new_T'],0)
        self.assertEqual(a['net_delta_bps'],out['net_bps']-t['net_bps'])
        with self.assertRaisesRegex(RuntimeError,'DUPLICATE'):x.attribute([t,t],[out])

    def test_changed_exit_changes_occupancy_and_new_trade_cost(self):
        rows,t,e=example();e.update(ownership=[True,0],signal_index=0)
        second=dict(t,signal_index=3,signal_ts=4*x.HOUR,entry_index=4,entry_ts=4*x.HOUR)
        second['identity']=x.old.digest(second)
        pool=[(t,e),(second,dict(e,signal_index=3))]
        parent,_=x.lifecycle(pool,rows,policy(),costs(),'base',False)
        child,_=x.lifecycle(pool,rows,policy(),costs(),'child',True)
        self.assertEqual(len(parent),1);self.assertEqual(len(child),2)
        a=x.attribute(parent,child);self.assertEqual(a['new_T'],1)
        self.assertEqual(a['new_net_bps'],child[1]['net_bps']);self.assertGreater(child[1]['cost_bps'],0)

    def test_tail_policy_is_time_only_and_all_fixed_trades_still_compared(self):
        source=Path(x.__file__).read_text()
        self.assertIn('MAX_HOLD_CROSSES_COMMON_DEV_END_EMBARGO',source)
        self.assertIn('FIXED_ENTRY_SAMPLE_DRIFT',source)


class Boundaries(unittest.TestCase):
    def test_development_io_guard_blocks_network_and_holdout(self):
        with x.old.probe.io_boundary([],x.ROOT/x.OUTPUT):
            with self.assertRaisesRegex(RuntimeError,'NETWORK'):socket.socket()
            with self.assertRaisesRegex(RuntimeError,'READ_FORBIDDEN'):Path('/tmp/validation.json').read_text()

    def test_governance_never_opens_formal_or_operating_authority(self):
        c=gov.load_json(gov.CONTRACT_PATH);self.assertEqual(gov.validate_contract(c),[])
        for key in ['G6_authorized','operating_replacement','validation_access','OOS_access','formal_credit']:
            bad=copy.deepcopy(c);bad['effective_development_objective']['development_exit_experiment'][key]=True
            self.assertIn('DEV_EXIT_AUTHORITY:'+key,gov.validate_contract(bad))
        for key in ['protective_stop_fixed','initial_risk_fixed','entries_fixed','full_lifecycle_required']:
            bad=copy.deepcopy(c);bad['effective_development_objective']['development_exit_experiment'][key]=False
            self.assertIn('DEV_EXIT_SAFETY:'+key,gov.validate_contract(bad))

    def test_old_receipts_and_terminal_records_unchanged(self):
        x.previous.verify_previous()
        from backend.research.rebuild.top5_external_seal_v1 import verify
        verify()
        state=x.old.read('research/development_evidence/TOP5_STATE_20260906_V1/receipt.json')
        self.assertEqual([state['lanes'][l]['comparison']['decision'] for l in x.old.LANES],
                         ['DEV_REJECT','DEV_REJECT','NOT_RUN','NOT_RUN','DEV_REJECT'])

    def test_preregistration_budget_data_and_authorities(self):
        c=x.authorize();self.assertEqual(c['rule'],x.RULE)
        self.assertEqual(c['exit_hypotheses_per_lane'],1);self.assertEqual(c['paid_AI_calls'],0)


if __name__=='__main__':unittest.main()
