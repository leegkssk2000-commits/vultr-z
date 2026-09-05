import copy,unittest
from backend.research.architecture_factory import a1_research_pipeline_hardening_v1 as h

class ManualBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow=h.A5_WF.read_text()
        cls.contract=h.read(h.ROOT/'backend/research/contracts/g5_entry_fusion_rescue_v1.json')
    def test_current_owner_without_obsolete_markers(self):
        self.assertNotIn('named_channel_mechanisms_must_enter_top5_economic_replay',self.workflow)
        r=h.manual_bridge_ci_binding(self.workflow,self.contract)
        self.assertTrue(r['passed']);self.assertFalse(r['formal_or_economic_credit_granted'])
    def test_removed_or_commented_authority_assertion_blocks(self):
        target="assert r['g5_formal_credit_before_fresh'] == 0, r"
        for replacement in ['', '# '+target]:
            r=h.manual_bridge_ci_binding(self.workflow.replace(target,replacement),self.contract)
            self.assertFalse(r['passed']);self.assertIn(target,r['missing_assertions'])
    def test_weakened_values_block(self):
        cases=[('trend_rider','historical_union_allowed',True),('trend_rider','historical_metrics_formal_credit',1),('trend_rider','new_fresh_boundary_required',False),('paid_ai_policy','default_paid_requests',1),('paid_ai_policy','max_paid_requests_per_manual_invocation',2),('authorities','selection_authority',True),('authorities','execution_authority','LIVE')]
        for group,key,value in cases:
            with self.subTest(field=key):
                c=copy.deepcopy(self.contract);c[group][key]=value
                self.assertFalse(h.manual_bridge_ci_binding(self.workflow,c)['passed'])
    def test_automatic_paid_trigger_and_missing_source_test_block(self):
        for workflow in [self.workflow+'\n  schedule:\n',self.workflow+'\n  push:\n',self.workflow.replace('a1_trend_rider_wr8125_dynamic_trendline_htf_attribution_v2.py --self-test','')]:
            self.assertFalse(h.manual_bridge_ci_binding(workflow,self.contract)['passed'])

if __name__=='__main__':unittest.main()
