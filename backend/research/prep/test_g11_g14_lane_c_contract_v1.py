import json
import unittest
from pathlib import Path

P = Path(__file__).with_name('g11_g14_lane_c_contract_v1.json')


def load_contract():
    return json.loads(P.read_text())


class LaneCContractTests(unittest.TestCase):
    def test_authority_is_fail_closed(self):
        d = load_contract()
        a = d['authority']
        self.assertFalse(a['selection_authority'])
        self.assertFalse(a['promotion_authority'])
        self.assertEqual(a['execution_authority'], 'NONE')
        self.assertEqual(a['order_authority'], 'BLOCKED')
        self.assertEqual(a['live_trade_authority'], 'BLOCKED')
        self.assertFalse(a['exchange_order_submitted'])
        self.assertEqual(a['protected_mutations'], 0)

    def test_g11_no_allocation_decision(self):
        d = load_contract()
        self.assertEqual(d['g11']['marker'], 'G11_PREP_READY')
        self.assertFalse(d['g11']['actual_weight_selection_allowed'])
        self.assertTrue(d['g11']['rollback']['deterministic_rehearsal'])

    def test_g12_shadow_never_activates_and_writer_is_single(self):
        d = load_contract()
        self.assertEqual(d['g12']['marker'], 'G12_PREP_READY')
        self.assertFalse(d['g12']['runtime_activation_allowed'])
        self.assertTrue(d['g12']['guards']['single_writer'])
        self.assertEqual(d['g12']['guards']['duplicate_open'], 0)
        self.assertEqual(d['g12']['guards']['duplicate_close'], 0)
        self.assertTrue(d['g12']['guards']['stale_missing_fail_closed'])
        self.assertTrue(d['g12']['guards']['source_parity_required'])

    def test_g13_canary_is_manifest_only(self):
        d = load_contract()
        self.assertEqual(d['g13']['marker'], 'G13_PREP_READY')
        self.assertEqual(d['g13']['canary_days'], 30)
        self.assertTrue(d['g13']['immutable_manifest'])
        self.assertFalse(d['g13']['paper_activation_allowed'])
        self.assertEqual(d['g13']['mutation_policy'], 'RESTART_CLOCK_OR_SEPARATE_SEALED_CANARY')

    def test_g14_requires_explicit_user_approval(self):
        d = load_contract()
        self.assertEqual(d['g14']['marker'], 'G14_PREP_READY')
        self.assertTrue(d['g14']['receipt_only'])
        self.assertTrue(d['g14']['explicit_user_approval_required'])
        self.assertEqual(d['g14']['live_trade_authority'], 'BLOCKED')
        self.assertEqual(d['g14']['order_authority'], 'BLOCKED')
        self.assertEqual(d['final_marker'], 'FOLLOWUP_PREP_LANE_C_READY')


if __name__ == '__main__':
    unittest.main()
