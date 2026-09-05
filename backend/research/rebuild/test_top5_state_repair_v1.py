"""State resets, causal availability, immutable history and inactive-component gates."""
import copy
import json
import unittest
from unittest.mock import patch
from backend.research.rebuild import top5_state_repair_v1 as s
from backend.research.rebuild import g5_g14_governance_validator_v1 as gov
from backend.research.rebuild.test_top5_development_repair_v1 import fixture


class State(unittest.TestCase):
    def test_prefix_no_future_or_outcomes(self):
        rows=fixture(360); events=[{'signal_index':i,'side':'long'} for i in range(65,360,7)]
        for lane in s.old.LANES:
            full=s.states(rows,lane,events)
            for end in [100,201,359]:
                partial=s.states(rows[:end+1],lane,[e for e in events if e['signal_index']<=end])
                self.assertEqual(partial,{i:v for i,v in full.items() if i<=end})
            contaminated=copy.deepcopy(rows)
            for r in contaminated: r.update(net_bps=999,mfe_bps=999,loss_streak=12)
            self.assertEqual(full,s.states(contaminated,lane,events))
            self.assertTrue(all(v['available_ts']==rows[i]['bar_close_ts'] for i,v in full.items()))

    def test_repeat_signal_requires_actual_price_reset(self):
        rows=[{'close':c,'open':c,'high':c+1,'low':c-1,'bar_close_ts':i+1} for i,c in enumerate([100]*60+[110,111,112,90,110])]
        events=[{'signal_index':i,'side':'long'} for i in [60,61,62,64]]
        for lane in s.old.LANES[:2]+s.old.LANES[4:]:
            values=s.states(rows,lane,events)
            self.assertEqual([values[i]['state_entry_pass'] for i in [60,61,62,64]],[True,False,False,True])
            self.assertNotEqual(values[60]['setup_id'],values[64]['setup_id'])

    def test_break_freezes_level_and_rearms_only_after_failure(self):
        rows=[{'close':100,'open':99,'high':101,'low':98,'bar_close_ts':i+1} for i in range(60)]
        rows += [{'close':c,'open':c-1,'high':c+1,'low':c-2,'bar_close_ts':61+i} for i,c in enumerate([105,106,100,106])]
        values=s.states(rows,s.old.LANES[2],[{'signal_index':i} for i in [60,61,63]])
        self.assertEqual([values[i]['state_entry_pass'] for i in [60,61,63]],[True,False,True])
        self.assertEqual(values[61]['break_level_before_signal'],101)

    def test_keltner_requires_prior_pullback_not_same_bar_invention(self):
        rows=[{'close':100+i/10,'open':100+i/10,'high':101+i/10,'low':99+i/10,'bar_close_ts':i+1} for i in range(80)]
        rows += [{'close':c,'open':c,'high':c+1,'low':c-1,'bar_close_ts':81+i} for i,c in enumerate([106,109,110])]
        values=s.states(rows,s.old.LANES[3],[{'signal_index':i} for i in [79,81,82]])
        self.assertEqual([values[i]['state_entry_pass'] for i in [79,81,82]],[False,True,False])

    def test_originals_and_prior_receipts_unchanged(self):
        s.previous.verify_previous()
        from backend.research.rebuild.top5_external_seal_v1 import verify
        self.assertEqual(verify()['files_sha256'].__len__(),21)

    def test_setup_map_does_not_use_result_ledgers(self):
        with patch.object(s.old.probe,'read',side_effect=AssertionError('NO_OUTCOME_ACCESS')):
            s.states(fixture(80),s.old.LANES[0],[{'signal_index':70,'side':'long'}])


class Applicability(unittest.TestCase):
    def evidence(self):
        return dict(enabled=False,bindings=[],reviewed=True,code_sha256='a'*64,config_sha256='b'*64,
                    baseline_behaviour_sha256='c'*64,disabled_behaviour_sha256='c'*64,
                    safety_checks={k:True for k in ['risk','stop','cost','integrity','explicit_live_approval']})

    def test_unused_unbound_identical_default_is_not_required(self):
        for stage in (7,8,9):
            v=gov.optional_stage_applicability(stage,self.evidence())
            self.assertFalse(v['implementation_required'])
            self.assertFalse(v['formal_pass']);self.assertFalse(v['generation_advance_authorized'])

    def test_enabled_bound_drift_or_unknown_stays_required(self):
        for key,value in [('enabled',True),('enabled',0),('bindings',['advisor']),('bindings',None),('reviewed',False),
                          ('code_sha256',''),('disabled_behaviour_sha256','d'*64)]:
            e=self.evidence();e[key]=value
            self.assertTrue(gov.optional_stage_applicability(8,e)['implementation_required'])
        self.assertTrue(gov.optional_stage_applicability(8,None)['implementation_required'])

    def test_no_exemption_for_risk_stop_cost_integrity_approval(self):
        for key in self.evidence()['safety_checks']:
            e=self.evidence();e['safety_checks'][key]=False
            self.assertTrue(gov.optional_stage_applicability(7,e)['implementation_required'])
        for stage in (5,6,10,11,12,13,14):
            self.assertTrue(gov.optional_stage_applicability(stage,self.evidence())['implementation_required'])

    def test_current_routing_uses_top5_and_preserves_history(self):
        contract=gov.load_json(gov.ROOT/'backend/research/rebuild/g5_g14_governance_contract_v1.json')
        self.assertEqual(gov.validate_contract(contract),[])
        contract['effective_development_objective']['primary']='NEW_ARCHITECTURE_PRIMARY'
        self.assertIn('CURRENT_TOP5_OBJECTIVE',gov.validate_contract(contract))
        wf=(s.ROOT/'.github/workflows/g5a-alpha-factory-lane-local-v1.yml').read_text()
        self.assertNotIn('secrets.',wf);self.assertNotIn('a1_mechanism_first_research_v2',wf)
        self.assertIn('g5_g14_governance_contract_v1.json',wf)


if __name__=='__main__':unittest.main()
