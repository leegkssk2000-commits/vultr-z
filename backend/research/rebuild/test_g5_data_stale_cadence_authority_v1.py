from __future__ import annotations

import unittest

from backend.research.rebuild import g5_data_stale_cadence_authority_v1 as authority


class CadenceAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = {"source": {"interval_ms": 14_400_000}}
        self.shadow = {
            "state": "CLEAN_RUNNER_SHADOW_PASS",
            "shadow_3bar_pass": True,
            "complete_bar_count": 3,
            "consecutive_complete_bar_count": 3,
            "source_parity": True,
            "child_parity": True,
            "duplicate": 0,
            "lookahead": 0,
            "formal_credit": 0,
        }
        self.evidence = {
            "schema_version": "zel.g5.data_stale.evidence.v1",
            "state": "AUTHORITY_EVIDENCE_PARTIAL_SYNTHETIC_ONLY",
            "timestamp_integrity": "PASS",
            "normal_N": 63,
            "real_failure_N": 0,
            "synthetic_failure_N": 63,
            "fresh_credit": 0,
            "ssot_mutated": False,
            "authority_value": None,
            "authority_created": False,
            "data_stale_authority_allowed": False,
        }

    def test_healthy_three_bar_runner_gets_frozen_cadence_authority(self) -> None:
        result = authority.derive_authority(self.contract, self.shadow, self.evidence)
        self.assertEqual(result["state"], "DATA_STALE_AUTHORITY_PASS_CADENCE_LOCK")
        self.assertEqual(result["authority_value"], 14_400_000)
        self.assertEqual(result["authority_unit"], "ms")
        self.assertEqual(result["authority_source"], "CONTRACT_GENUINE_CADENCE_LOCK")
        self.assertTrue(result["authority_created"])
        self.assertTrue(result["data_stale_authority_allowed"])
        self.assertFalse(result["authority_empirical_fit"])
        self.assertFalse(result["threshold_surface_allowed"])
        self.assertEqual(result["fresh_credit"], 0)
        self.assertFalse(result["strategy_mutation"])
        self.assertFalse(result["economic_mutation"])
        self.assertFalse(result["contract_mutation"])

    def test_shadow_gate_remains_fail_closed(self) -> None:
        bad = dict(self.shadow)
        bad["shadow_3bar_pass"] = False
        with self.assertRaisesRegex(authority.CadenceAuthorityError, "CLEAN_RUNNER_3BAR_INTEGRITY_REQUIRED"):
            authority.derive_authority(self.contract, bad, self.evidence)

    def test_timestamp_integrity_remains_fail_closed(self) -> None:
        bad = dict(self.evidence)
        bad["timestamp_integrity"] = "FAIL"
        with self.assertRaisesRegex(authority.CadenceAuthorityError, "TIMESTAMP_INTEGRITY_REQUIRED"):
            authority.derive_authority(self.contract, self.shadow, bad)

    def test_no_normal_evidence_cannot_create_authority(self) -> None:
        bad = dict(self.evidence)
        bad["normal_N"] = 0
        with self.assertRaisesRegex(authority.CadenceAuthorityError, "NORMAL_EVIDENCE_REQUIRED"):
            authority.derive_authority(self.contract, self.shadow, bad)


if __name__ == "__main__":
    unittest.main()
