"""No replay, prefix causality and exact risk-accounting identities."""
import copy
import unittest
from unittest.mock import patch
from backend.research.rebuild import keltner_exit_risk_v1 as k
from backend.research.rebuild.test_top5_development_repair_v1 import fixture


def trade(symbol,signal,exit_ts,net):
    return {'lane_id':k.LANE,'symbol':symbol,'signal_ts':signal,'entry_ts':signal+1,
            'exit_ts':exit_ts,'side':'long','net_bps':float(net),
            'identity':f'{symbol}:{signal}:{exit_ts}'}


class Accounting(unittest.TestCase):
    def test_identical_window_amount_timing_new_excluded_add_exactly(self):
        p=[trade('A',1,10,10),trade('B',2,12,-20),trade('C',3,13,5)]
        c=[trade('A',1,8,-2),trade('B',2,12,-10),trade('D',4,12,-7)]
        a=k.streak_audit.bridge(p,c,9,13)
        self.assertEqual(a['common_exit_amount_change_at_child_close_bps'],10)
        self.assertEqual(a['common_parent_net_timing_shift_bps'],-10)
        self.assertEqual(a['new_trade_net_bps'],-7)
        self.assertEqual(a['excluded_parent_net_effect_bps'],-5)
        self.assertEqual(a['net_delta_bps'],-12)
        self.assertAlmostEqual(a['parity_residual_bps'],0.)

    def test_simultaneous_loss_removes_positive_reset_without_extra_time_label(self):
        p=[trade('A',1,10,-5),trade('B',2,20,2),trade('C',3,30,-5)]
        c=p+[trade('D',4,20,-3)]
        original=k.streak_audit.population(p);child=k.streak_audit.population(c)
        self.assertEqual(original['worst_amount_run']['loss_trade_sum_bps'],5)
        self.assertEqual(child['worst_amount_run']['loss_trade_sum_bps'],11)
        self.assertEqual(child['worst_amount_run']['length_groups'],3)
        self.assertEqual(sum(t['net_bps'] for t in c)-sum(t['net_bps'] for t in p),-3)
        value=k.streak_audit.build(p,p,c)
        self.assertTrue(value['maxima_difference_is_not_additive_causal_attribution'])
        resets=value['union_windows'][0]['nonnegative_reset_observations']['full_minus_parent']
        self.assertEqual(resets[0]['child_same_timestamp_group']['net_trade_sum_bps'],-1)

    def test_duplicates_and_nonfinite_values_block(self):
        t=trade('A',1,10,-5)
        with self.assertRaisesRegex(RuntimeError,'DUPLICATE'):k.streak_audit.population([t,t])
        with self.assertRaisesRegex(RuntimeError,'INVALID'):k.streak_audit.population([dict(t,net_bps=float('nan'))])

    def test_negative_tail_and_zero_reset_match_original_owner(self):
        ts=[trade('A',1,10,-4),trade('B',2,20,0),trade('C',3,30,-2),trade('D',4,40,-3)]
        v=k.streak_audit.population(ts)
        self.assertEqual([r['length_groups'] for r in v['negative_runs']],[1,2])
        self.assertEqual(v['worst_amount_run']['loss_trade_sum_bps'],5)

    def test_zero_net_group_is_a_real_streak_reset(self):
        p=[trade('A',1,10,-4),trade('B',2,20,2),trade('C',3,30,-4)]
        c=p+[trade('D',4,20,-2)]
        v=k.streak_audit.build(p,p,c)
        self.assertEqual(v['populations']['full']['worst_amount_run']['loss_trade_sum_bps'],4)
        self.assertEqual(k.streak_audit._resets(p,c,10,30),[])
        z=[trade('A',1,10,-4),trade('B',2,20,0),trade('C',3,30,-4)]
        removed=[z[0],z[2]]
        self.assertEqual(k.streak_audit._resets(z,removed,10,30)[0]['reference_reset_kind'],'ZERO_NET_RESET')


class Observations(unittest.TestCase):
    def inputs(self):
        rows=fixture(300,4*k.prior.HOUR)
        spec=next(s for s in k.old.read(k.old.FREEZE)['children'] if s['lane_id']==k.LANE)['executable_spec']
        args={'entry_ts':rows[260]['bar_open_ts'],'entry_price':max(r['high'] for r in rows)*2,
              'trigger_ts':rows[265]['bar_close_ts'],'armed_ts':rows[261]['bar_close_ts'],
              'binding':{'fee_bps':6.,'spread_bps':2.,'impact_bps':2.,'funding_p95_per_settlement_bps':3.},'spec':spec}
        return rows,args

    def test_prefix_exact_and_future_prices_cannot_affect_observation(self):
        rows,a=self.inputs();v=k.trigger_observation(rows,**a)
        self.assertEqual(v,k.trigger_observation(rows[:266],**a))
        future=copy.deepcopy(rows)
        for r in future[266:]:r.update(close=999999,high=999999,low=.0001,open=999999)
        self.assertEqual(v,k.trigger_observation(future,**a))
        self.assertEqual(v['last_consumed_bar_close_ts'],a['trigger_ts'])

    def test_labels_are_not_accepted_as_feature_arguments(self):
        rows,a=self.inputs()
        with self.assertRaises(TypeError):k.trigger_observation(rows,**a,final_profit=999,mfe=999)
        poisoned=[dict(r,final_profit=999,mfe=999,loss_streak=99) for r in rows]
        self.assertEqual(k.trigger_observation(rows,**a),k.trigger_observation(poisoned,**a))

    def test_nonclosed_future_arm_and_positive_mark_block(self):
        rows,a=self.inputs()
        for update in [{'trigger_ts':a['trigger_ts']+1},{'armed_ts':a['trigger_ts']},{'entry_price':.01}]:
            with self.assertRaises(RuntimeError):k.trigger_observation(rows,**{**a,**update})

    def test_outcome_accounting_separates_profit_cut_from_new_loss(self):
        p=trade('A',1,10,100);p.update(gross_bps=120,cost2x_net_bps=80,funding_bps=3)
        c=dict(p,net_bps=-20,gross_bps=0,cost2x_net_bps=-40,funding_bps=1)
        answer=k.outcome_label(p,c,{k.prior.entry_key(p)})
        self.assertEqual(answer['cut_winner_profit_bps'],100)
        self.assertEqual(answer['extra_loss_on_parent_winner_bps'],20)
        self.assertEqual(answer['net_delta_bps'],-120)
        self.assertTrue(answer['cut_large_parent_winner'])
        p['net_bps']=-100;c['net_bps']=10
        answer=k.outcome_label(p,c,set())
        self.assertEqual(answer['saved_loss_bps'],100)
        self.assertFalse(answer['cut_parent_winner'])


class Screen(unittest.TestCase):
    def sample(self):
        week=k.old.probe.WEEK_MS;start=k.old.probe.MONDAY_MS
        policy={'development_interval_ms':[start,start+12*week],'symbols':['A','B'],
                'uncertainty':{'seed':1178,'replications':100}}
        rows=[]
        for w in range(12):
            for symbol in ['A','B']:
                for label in ['saved_parent_loss','cut_parent_winner']:
                    answer={'saved_parent_loss':label=='saved_parent_loss','cut_parent_winner':label=='cut_parent_winner',
                            'cut_large_parent_winner':False,'saved_loss_bps':10.,'cut_winner_profit_bps':10.,'net_delta_bps':0.,'cost2_net_delta_bps':0.}
                    obs={key:0. for key in ['close_to_ema50_bps','ema20_to_ema50_bps','held_closed_bars','closed_bars_since_arm','current_net_mark_bps']}
                    obs['original_trend_intact']=label=='cut_parent_winner'
                    rows.append({'symbol':symbol,'trigger_ts':start+w*week+1,'observation':obs,'answer':answer})
        return rows,policy

    def test_consistent_observable_separation_supports_separate_preregistration_only(self):
        rows,p=self.sample();v=k.evidence_screen(rows,p)
        self.assertTrue(v['passed']);self.assertEqual(v['separation_95pct_interval'],[1.,1.])
        self.assertFalse(v['formal_statistical_pass'])

    def test_identical_observables_do_not_support_arbitrary_new_child(self):
        rows,p=self.sample()
        for r in rows:r['observation']['original_trend_intact']=True
        v=k.evidence_screen(rows,p)
        self.assertFalse(v['passed']);self.assertEqual(v['point_separation'],0)

    def test_direction_reversing_in_reused_dev_half_does_not_pass(self):
        rows,p=self.sample();mid=sum(p['development_interval_ms'])//2
        for r in rows:
            if r['trigger_ts']>=mid:r['observation']['original_trend_intact']=not r['observation']['original_trend_intact']
        v=k.evidence_screen(rows,p)
        self.assertFalse(v['checks']['both_reused_DEV_halves_positive']);self.assertFalse(v['passed'])

    def test_missing_outcome_class_is_undefined_not_economic_reject(self):
        rows,p=self.sample();rows=[r for r in rows if r['answer']['cut_parent_winner']]
        v=k.evidence_screen(rows,p)
        self.assertIsNone(v['point_separation']);self.assertFalse(v['passed'])


if __name__=='__main__':unittest.main()
