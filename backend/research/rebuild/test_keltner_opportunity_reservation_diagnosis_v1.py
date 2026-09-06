import copy
import unittest
import keltner_opportunity_reservation_diagnosis_v1 as d


def t(origin,i,j,net,symbol='X'):
    x={'origin_key':origin,'symbol':symbol,'signal_index':i,'signal_ts':(i+1)*14400000,
       'entry_index':i+1,'entry_ts':(i+1)*14400000,'exit_index':j,'exit_ts':(j+1)*14400000,
       'entry_price':100.0,'exit_price':100.0+(net+20)/100,'gross_bps':net+20.0,
       'cost_bps':20.0,'fee_bps':10.0,'spread_bps':2.0,'impact_bps':2.0,'slippage_bps':0.0,
       'funding_bps':3.0,'frozen_floor_reserve_bps':3.0,'net_bps':float(net),'cost2x_net_bps':net-20.0}
    return x


def event(trade,reason=None,half=True):
    return {'symbol':trade['symbol'],'signal_index':trade['signal_index'],'signal_ts':trade['signal_ts'],
            'entry_observation':{'close_on_directional_half':half},'exclusion_reason':reason,
            'status':'COMPLETED' if reason is None else 'EXCLUDED'}


def view(trades,events=None,opens=None):
    return {'trades':trades,'events':events if events is not None else list(map(event,trades)),
            'open_observations':opens or [],'trace':[],'admission':{}}


def fixture():
    root,a,b=t('root',0,12,-100),t('a',14,26,-40),t('b',30,42,-50)
    one,two=t('one',3,15,30),t('two',20,32,-120)
    de=[event(x) for x in [root,a,b]]+[event(x,'SIGNAL_DURING_OPEN') for x in [one,two]]
    ne=[event(root,'SIGNAL_CLOSE_BELOW_DIRECTIONAL_HALF',False)]+[event(x,'SIGNAL_DURING_OPEN') for x in [a,b]]+list(map(event,[one,two]))
    D=view([root,a,b],de);N=view([one,two],ne);C=view([a,b])
    return {'record':{},'views':{'P':copy.deepcopy(D),'D':D,'N':N,'N_COMMON_D':C}}


class LineageTests(unittest.TestCase):
    def test_multigeneration_occupancy_chain_not_flat_veto_list(self):
        r=d.analyze_period(fixture())
        self.assertEqual(r['counts']['direct_D_half_veto'],1)
        self.assertEqual(r['counts']['additional_displaced_D'],2)
        self.assertEqual(r['counts']['N_new_not_D'],2)
        self.assertEqual(r['counts']['direct_root_linked_new'],1)
        self.assertEqual(r['counts']['displaced_linked_new'],1)
        self.assertEqual(set(r['D_direct_half_veto_roots'][0]['downstream_origins']),{'one','a','two','b'})
        self.assertEqual(r['bridge']['COMMON_D_minus_N_bps_known_diagnostic_only'],0)

    def test_ancestry_requires_existing_occupancy_evidence(self):
        x=fixture();x['views']['D']['trades'][0]['exit_index']=2
        with self.assertRaises(AssertionError): d.analyze_period(x)

    def test_prior_result_geometry_mismatch_fails(self):
        x=fixture();old={'record':{},'views':{'P':copy.deepcopy(x['views']['P']),'FULL':copy.deepcopy(x['views']['D']),'FIXED':copy.deepcopy(x['views']['D'])}}
        old['views']['FULL']['trades'][0]['net_bps']+=1
        with self.assertRaises(AssertionError): d.diagnose({'SYNTHETIC':x},{'SYNTHETIC':old})

    def test_diagnosis_preserves_inputs_and_never_counts_candidate(self):
        x=fixture();old={'record':{},'views':{'P':copy.deepcopy(x['views']['P']),'FULL':copy.deepcopy(x['views']['D']),'FIXED':copy.deepcopy(x['views']['D'])}}
        original=copy.deepcopy((x,old));r=d.diagnose({'SYNTHETIC':x},{'SYNTHETIC':old})
        self.assertEqual((x,old),original)
        self.assertEqual(r['new_candidate_evaluations'],0)
        self.assertFalse(r['strategy_replay_performed'])

    def test_after_M_audit_only_values_produced_M_and_exposes_mismatch(self):
        x=fixture();r=d.after_M_audit(x,copy.deepcopy(x['views']['N_COMMON_D']),'SYNTHETIC')
        self.assertEqual(r['N_new_blocked_T'],2)
        self.assertEqual(r['displaced_D_restored_T'],2)
        self.assertTrue(r['COMMON_D_regression_equal'])
        self.assertAlmostEqual(r['M_minus_N_closed_bridge']['M_minus_N_bps'],0)
        bad=copy.deepcopy(x['views']['N_COMMON_D']);bad['trades'][0]['net_bps']-=7
        r=d.after_M_audit(x,bad,'SYNTHETIC')
        self.assertFalse(r['COMMON_D_regression_equal'])
        self.assertEqual(r['COMMON_D_regression_mismatches']['common_changed_economics'],['a'])
        self.assertEqual(r['M_minus_N_closed_bridge']['M_minus_N_bps'],-7)

    def test_residue_is_exhaustive_gross_cost_open_accounting(self):
        # One unchanged winner, adverse loser, cost-only loser, early-helpful
        # and early-harmful common exit, plus new-to-P origin shared with D.
        p=[t('win',1,13,100),t('bad',20,32,-70),t('costonly',40,52,-5),
           t('help',60,72,-80),t('harm',80,92,30)]
        n=copy.deepcopy(p);n[3]=t('help',60,66,-30);n[4]=t('harm',80,85,-50)
        n.append(t('new',100,112,60))
        op={'origin_key':'tail','symbol':'X','signal_index':120,'entry_index':121,'entry_ts':121*14400000,
            'mark_index':123,'mark_ts':124*14400000,'gross_mark_bps':-7.0,
            'hypothetical_liquidation_cost_bps':20.0,'hypothetical_liquidation_net_mark_bps':-27.0,
            'hypothetical_liquidation_cost2x_net_mark_bps':-47.0,'modeled_funding_accrued_bps':2.0,
            'hypothetical_cost_components_bps':{'fee_bps':10.0,'funding_bps':2.0,'other':8.0},
            'status':'CENSORED','actual_exit':False,'terminal_liquidation':False}
        payload={'views':{'P':view(p),'N':view(n,opens=[op]),'D':view(copy.deepcopy(n),opens=[op])}}
        r=d.residue(payload)
        self.assertEqual(r['closed_total']['T'],6)
        self.assertEqual(r['closed_total']['net_bps'],5)
        self.assertEqual(r['closed_total']['gross_bps'],125)
        self.assertEqual(r['closed_total']['cost_bps'],120)
        self.assertEqual(r['terminal_net_bps_hypothetical'],-22)
        self.assertEqual(r['terminal_cost2x_bps_hypothetical'],-162)
        self.assertEqual(r['unchanged_loss_secondary_partition']['cost_only_T'],1)
        self.assertEqual(r['unchanged_loss_secondary_partition']['gross_adverse_T'],1)
        self.assertEqual(r['closed_groups']['changed_exit_harmful']['N_minus_P_same_origin_bps']['net_bps'],-80)


if __name__=='__main__': unittest.main()
