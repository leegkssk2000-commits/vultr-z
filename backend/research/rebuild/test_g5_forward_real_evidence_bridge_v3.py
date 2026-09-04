from __future__ import annotations

import unittest

from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as base
from backend.research.rebuild import g5_forward_real_evidence_bridge_v3 as v3
from backend.research.rebuild.test_g5_forward_real_evidence_bridge_v1 import FakeProvider, cost, depth, effective, signal


class G5ForwardRealRetryTest(unittest.TestCase):
    def test_transient_entry_capture_failure_does_not_terminalize_signal(self):
        rows = []
        base.bridge_event(rows, kind="ACTIVATED", payload={"activation_ts_ms": 1000}, event_ts_ms=1000)
        sig = signal(1500, 1400)

        # First observation cannot capture depth. v1 appends OPEN_REJECTED, but v3 must treat
        # the entry-provenance failure as retryable rather than consuming the future signal.
        rows, evidence, canonical, status1 = v3.run_process(
            source_rows=[sig],
            bridge_rows=rows,
            bridge_evidence=[],
            canonical_evidence=[],
            effective=effective(),
            cutover={"production_ready": True, "clean_runner_authority": True},
            stale={"authority_created": True, "data_stale_authority_allowed": True},
            cost=cost(),
            provider=FakeProvider(),
            current_ms=2000,
            fee_authority_sha="fee-sha",
        )
        self.assertEqual(status1["new_opens"], 0)
        transient = [row for row in rows if row["kind"] == "OPEN_REJECTED"]
        self.assertEqual(len(transient), 1)
        self.assertTrue(transient[0]["payload"]["reason"].startswith("ENTRY_PROVENANCE_CAPTURE_FAILED:"))
        _, terminal = v3.retry_safe_open_index(rows)
        self.assertNotIn(base.trade_id_for_signal(sig), terminal)

        # Next observation succeeds against the same immutable signal identity.
        rows, evidence, canonical, status2 = v3.run_process(
            source_rows=[sig],
            bridge_rows=rows,
            bridge_evidence=evidence,
            canonical_evidence=canonical,
            effective=effective(),
            cutover={"production_ready": True, "clean_runner_authority": True},
            stale={"authority_created": True, "data_stale_authority_allowed": True},
            cost=cost(),
            provider=FakeProvider(depths=[depth(2200)]),
            current_ms=2200,
            fee_authority_sha="fee-sha",
        )
        self.assertEqual(status2["new_opens"], 1)
        self.assertEqual(sum(1 for row in rows if row["kind"] == "OPENED_PROVENANCE"), 1)

    def test_permanent_identity_rejection_stays_terminal(self):
        rows = [
            {"kind": "OPEN_REJECTED", "payload": {"trade_id": "x", "reason": "SIGNAL_CHILD_NOT_CURRENT_EFFECTIVE_OWNER"}}
        ]
        _, terminal = v3.retry_safe_open_index(rows)
        self.assertIn("x", terminal)


if __name__ == "__main__":
    unittest.main()
