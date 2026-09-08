"""Synthetic scope/budget tests; no market inputs or economic replay."""
from copy import deepcopy
from dataclasses import asdict, replace
import unittest
from unittest.mock import patch
from backend.research.rebuild import kr3_d_seen2026_v1 as m

class ExactDTests(unittest.TestCase):
    def test_exact_mode_is_d_not_c_or_b(self):
        self.assertEqual(asdict(m.mode()),m.CANONICAL_MODE)
        self.assertEqual(m.mode().reference_anchor,'SHIFTED')
        self.assertEqual(m.mode().exit_anchor,'SHIFTED')
        self.assertTrue(m.mode().require_origin_half)
        self.assertEqual(m.mode().delay,6)
    def test_mode_drift_rejected(self):
        modes=list(m.p.MODES);modes[3]=replace(modes[3],exit_anchor='ORIGIN')
        with patch.object(m.p,'MODES',tuple(modes)):
            with self.assertRaisesRegex(ValueError,'ORIGINAL_D_MODE_DRIFT'):m.mode()
    def base(self):
        return {'cumulative_actual':45,'cumulative_actual_evaluations':63,
                'trials':[{'actual_experiment_ordinal':63}],
                'protected':{'source_used':2,'oos':0,'candidate_history':['E_REJECT']}}
    def test_reservation_appends_only_one_existing_config_evaluation(self):
        original=self.base();before=deepcopy(original)
        out=m.claim_budget(original,{'receipt_sha256':'fixture'}, {'actual_experiment_ordinal':64})
        self.assertEqual(original,before)
        self.assertEqual(out['cumulative_actual'],45)
        self.assertEqual(out['cumulative_actual_evaluations'],64)
        self.assertEqual(out['trials'][:-1],original['trials'])
        self.assertEqual(out['protected'],original['protected'])
        self.assertEqual(out['kr3_d_seen2026_allocation']['used'],1)
        self.assertTrue(out['kr3_d_seen2026_allocation']['no_retry'])
    def test_double_reservation_rejected(self):
        out=m.claim_budget(self.base(),{'receipt_sha256':'fixture'}, {'actual_experiment_ordinal':64})
        with self.assertRaisesRegex(ValueError,'BUDGET_ALREADY_USED'):m.claim_budget(out,{}, {})
    def test_existing_scope_even_with_old_counters_cannot_retry(self):
        out=self.base();out['kr3_d_seen2026_allocation']={'used':1}
        with self.assertRaisesRegex(ValueError,'D_SCOPE_ALREADY_CLAIMED'):m.claim_budget(out,{}, {})
    def test_existing_ordinal_cannot_be_renamed(self):
        out=self.base();out['trials'].append({'actual_experiment_ordinal':64})
        with self.assertRaisesRegex(ValueError,'ORDINAL_USED'):m.claim_budget(out,{}, {})
    def test_missing_universe_rejected_before_any_replay(self):
        with self.assertRaisesRegex(ValueError,'SEVEN_ORIGINAL_SYMBOLS'):m.validate_packet({'rows_by':{}})
    def test_calendar_and_hash_requirements_are_exact(self):
        self.assertEqual(m.CALENDAR,[1778198400000,1788566400000])
        self.assertEqual(set(m.BINDINGS),{'rows_by','policy','costs'})
        self.assertTrue(all(len(x)==64 for x in m.BINDINGS.values()))

if __name__=='__main__':unittest.main()
