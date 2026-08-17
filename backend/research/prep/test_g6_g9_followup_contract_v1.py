import json
import unittest
from pathlib import Path

P = Path(__file__).with_name('g6_g9_followup_contract_v1.json')


class G6G9FollowupContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = json.loads(P.read_text())

    def test_research_only_authority(self):
        a = self.c['authority']
        self.assertFalse(a['selection_authority'])
        self.assertFalse(a['promotion_authority'])
        self.assertEqual(a['execution_authority'], 'NONE')
        self.assertEqual(a['order_authority'], 'BLOCKED')
        self.assertEqual(a['live_trade_authority'], 'BLOCKED')
        self.assertEqual(a['protected_mutations'], 0)

    def test_g6_has_no_method_control_and_conflict_hold(self):
        g = self.c['G6_PREP']
        self.assertTrue(g['survivor_input_required'])
        self.assertTrue(g['immutable_control_required'])
        self.assertTrue(g['no_method_control_required'])
        self.assertEqual(g['ownership_conflict_policy'], 'HOLD')
        self.assertIn('entry', g['decision_intent_transform_boundary']['method_must_not_invent'])
        self.assertIn('source_lineage', g['decision_intent_transform_boundary']['method_must_not_invent'])

    def test_g7_skill_set_and_dca_fail_closed(self):
        g = self.c['G7_PREP']
        expected = {'partial30','trailing','mfe_runner','runner_hold','scale_in','pyramiding','long_beam','short_beam','dca_observer'}
        self.assertEqual(set(g['skills']), expected)
        self.assertEqual(g['standalone_control'], 'NO_SKILL')
        self.assertEqual(g['dca']['mode'], 'OBSERVER_DESIGN_ONLY')
        self.assertEqual(g['dca']['missing_field_action'], 'HOLD')
        for field in ['exposure','drawdown','liq_buffer','max_add_count','add_spacing','stop_owner','rollback_contract']:
            self.assertIn(field, g['dca']['required_fields'])

    def test_g8_preserves_team_advisor_boundary(self):
        g = self.c['G8_PREP']
        self.assertEqual(g['team_bots'], ['LBot','MBot','OBot','SBot'])
        self.assertIn('ZBot', g['separate_advisors'])
        self.assertFalse(g['zbot_team_bot'])
        self.assertFalse(g['decision_authority'])
        self.assertTrue(g['immutable_lineage_required'])

    def test_g9_blocks_prepass_and_freezes_components(self):
        g = self.c['G9_PREP']
        self.assertEqual(g['input_gate'], 'STANDALONE_PASS_ONLY')
        self.assertTrue(g['component_sha_freeze'])
        self.assertEqual(g['redundancy_cosine_threshold'], 0.85)
        self.assertEqual(g['pre_standalone_pass_action'], 'BLOCK')
        self.assertEqual(len(g['outputs']), 3)

    def test_completion_markers_are_complete(self):
        c = self.c['completion']
        self.assertEqual(c['required_markers'], ['G6_PREP_READY','G7_PREP_READY','G8_PREP_READY','G9_PREP_READY'])
        self.assertEqual(c['final_marker'], 'FOLLOWUP_PREP_LANE_B_READY')


if __name__ == '__main__':
    unittest.main()
