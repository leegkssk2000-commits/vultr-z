"""Contract-level future-fill, cost and crash/restart adversarial proofs."""

from __future__ import annotations

import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path

j = importlib.import_module("k117_shadow_noorder_journal_v1")
k = importlib.import_module("k117_adapter")
obs = importlib.import_module("k117_price_only_source_observer_v1")


def fixture_state() -> tuple[dict, dict]:
    a = k.Adapter(enabled=True, fixture=False, development=True)
    s = {
        "schema": obs.SCHEMA,
        "phase": "WAIT_FIRST_PROSPECTIVE_CLOSED_30M",
        "started_at_ms": 1_792_956_000_000,
        "next_expected_complete_close_ms": 1_792_957_200_000,
        "first_context_open_ms": 1_792_957_200_000 - obs.BARS * obs.HALF_HOUR,
        "contract_sha256": "a" * 64,
        "formal_shadow_active": False,
        "formal_fresh_credit": False,
        "full_funding_verified": False,
        "virtual_fills": 0,
        "order_calls": 0,
        "decisions": [],
        "signals": [],
        "next_open_entry_holds": [],
    }
    return s, a.state


class K117DevelopmentNoOrderJournal(unittest.TestCase):
    def test_timing_exact_open_not_assumed_when_late(self):
        self.assertEqual(
            j.next_open_eligibility(
                expected_open_ms=10_000,
                decision_ts_ms=10_001,
                price_received_at_ms=10_500,
            ),
            "HOLD_LATE_NEXT_OPEN_NO_RETRO_FILL",
        )

    def test_no_quote_no_fill(self):
        self.assertEqual(
            j.next_open_eligibility(
                expected_open_ms=10_000, decision_ts_ms=9_500, price_received_at_ms=None
            ),
            "HOLD_NO_ASOF_QUOTE",
        )

    def test_earlier_candle_is_not_true_next_open(self):
        self.assertEqual(
            j.next_open_eligibility(
                expected_open_ms=10_000,
                decision_ts_ms=9_500,
                price_received_at_ms=9_500,
            ),
            "HOLD_PREOPEN_PRICE_NOT_OPEN_FILL",
        )

    def test_exact_event_remains_only_provisional(self):
        self.assertEqual(
            j.next_open_eligibility(
                expected_open_ms=10_000,
                decision_ts_ms=10_000,
                price_received_at_ms=10_000,
            ),
            "TIMING_POTENTIALLY_ELIGIBLE_REQUIRES_QUOTE_AND_COST_PROOF",
        )

    def test_checkpoint_roundtrip_and_exact_adapter_restart(self):
        s, state = fixture_state()
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            h = j.commit_checkpoint(p, s, state, "a" * 64, "b" * 64)
            saved = j.read_checkpoint(p, "a" * 64, "b" * 64)
            self.assertEqual(saved["state_sha256"] if "state_sha256" in saved else h, h)
            self.assertEqual(saved["adapter"], state)
            resumed = k.Adapter(
                enabled=True,
                development=True,
                started_at_ms=s["started_at_ms"],
                state=saved["adapter"],
            )
            self.assertEqual(k.digest(resumed.state), k.digest(state))
            s["decisions"].append({"symbol": "BTC-USDT", "status": "NO_SIGNAL"})
            s["next_expected_complete_close_ms"] += obs.HALF_HOUR
            j.commit_checkpoint(p, s, resumed.state, "a" * 64, "b" * 64)
            self.assertEqual(
                len(j.read_checkpoint(p, "a" * 64, "b" * 64)["status"]["decisions"]), 1
            )

    def test_mutated_checkpoint_rejected(self):
        s, state = fixture_state()
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            j.commit_checkpoint(p, s, state, "a" * 64, "b" * 64)
            f = p / "STATE.json"
            body = json.loads(f.read_text())
            body["status"]["order_calls"] = 1
            f.write_text(json.dumps(body))
            with self.assertRaisesRegex(ValueError, "CHECKPOINT_SHA256_MISMATCH"):
                j.read_checkpoint(p, "a" * 64, "b" * 64)

    def test_wrong_code_identity_rejected(self):
        s, state = fixture_state()
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            j.commit_checkpoint(p, s, state, "a" * 64, "b" * 64)
            with self.assertRaisesRegex(
                ValueError, "SHADOW_NO_ORDER_OR_CODE_BINDING_MISMATCH"
            ):
                j.read_checkpoint(p, "a" * 64, "c" * 64)

    def test_journal_cannot_drop_event_or_decision(self):
        s, state = fixture_state()
        s["decisions"] = [{"symbol": "BTC-USDT", "status": "NO_SIGNAL"}]
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            j.commit_checkpoint(p, s, state, "a" * 64, "b" * 64)
            s["decisions"] = []
            with self.assertRaisesRegex(
                ValueError, "OBSERVATION_LEDGER_REWRITTEN_OR_CLOCK_BACKWARDS"
            ):
                j.commit_checkpoint(p, s, state, "a" * 64, "b" * 64)

    def test_future_clock_reset_rejected(self):
        s, state = fixture_state()
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            j.commit_checkpoint(p, s, state, "a" * 64, "b" * 64)
            s["next_expected_complete_close_ms"] -= obs.HALF_HOUR
            with self.assertRaisesRegex(
                ValueError, "OBSERVATION_LEDGER_REWRITTEN_OR_CLOCK_BACKWARDS"
            ):
                j.commit_checkpoint(p, s, state, "a" * 64, "b" * 64)

    def test_account_or_formal_promotion_cannot_sneak_into_checkpoint(self):
        s, state = fixture_state()
        for field, value in [
            ("order_calls", 1),
            ("formal_shadow_active", True),
            ("virtual_fills", 1),
        ]:
            changed = copy.deepcopy(s)
            changed[field] = value
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(
                    ValueError, "FORBIDDEN_FORMAL_OR_UNPROVEN_VIRTUAL_FILL"
                ):
                    j.commit_checkpoint(
                        Path(directory), changed, state, "a" * 64, "b" * 64
                    )

    def test_cost_model_broker_funding_not_invented(self):
        source = json.loads(
            (
                k.ROOT
                / "research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
            ).read_text()
        )
        self.assertIn("funding_p95_abs_bps", source["snapshots"]["BTC-USDT"])
        self.assertFalse(bool(source.get("live_authority") in ("ALLOW", "LIVE")))
        self.assertTrue(source["costs_bps"]["BTC-USDT"] > 0)


if __name__ == "__main__":
    unittest.main()
