"""Falsify bad A5 source rules BEFORE any market/noisy economics calls."""
from __future__ import annotations

import unittest
from backend.research.architecture_factory import a1_a5_static_admission_v1 as admission
from ops.issue1388_candidate_static_preflight_v1 import audit_saved


class FakeEcon:
    def __init__(self):
        self.calls = []
    def evaluate_queue(self, queue):
        self.calls.append([v["candidate_id"] for v in queue])
        return {
            "rows":[{"candidate_id":x["candidate_id"],"state":"FAIL_DEVELOPMENT_ECONOMICS","economic_pass":False} for x in queue],
            "economic_pass_count":0,"passes":[],"candidate_count":len(queue),
            "source_skip_count":0,"insufficient_event_count":0,
            "economic_fail_count":len(queue),"spec_reject_count":0,
        }


class A5StaticEconomicsAdmissionTests(unittest.TestCase):
    def test_saved_failed_five_never_start_an_economic_evaluator(self):
        saved=audit_saved()
        original=[{"candidate_id":x["candidate_id"],
                   "executable_spec":{"entry_rule":x["entry_rule"],"bar_interval":x["bar_interval"]}}
                  for x in saved["candidates"]]
        econ=FakeEcon()
        result=admission.evaluate_queue(econ,original)
        self.assertEqual(econ.calls,[])
        self.assertEqual(result["spec_reject_count"],5)
        self.assertEqual(result["economic_fail_count"],0)
        self.assertEqual(result["economic_pass_count"],0)
        self.assertTrue(all(r["state"]=="REJECT_UNEXECUTABLE_SPEC" for r in result["rows"]))
        self.assertTrue(all(r["source_economic_claim_consumed"] is False for r in result["rows"]))

    def test_valid_pass_through_unchanged_without_extra_fields(self):
        econ=FakeEcon()
        data=[{"candidate_id":"valid","executable_spec":{"entry_rule":"roc(3)>0","bar_interval":"30m"}}]
        direct=econ.evaluate_queue(data)
        self.assertEqual(admission.evaluate_queue(econ,data),direct)
        self.assertEqual(econ.calls,[["valid"],["valid"]])

    def test_partial_invalid_remains_in_same_candidate_order(self):
        econ=FakeEcon()
        data=[
            {"candidate_id":"invalid","executable_spec":{"entry_rule":"close>highest(close,20)","bar_interval":"30m"}},
            {"candidate_id":"valid","executable_spec":{"entry_rule":"roc(3)>0","bar_interval":"30m"}},
        ]
        result=admission.evaluate_queue(econ,data)
        self.assertEqual(econ.calls,[["valid"]])
        self.assertEqual([x["candidate_id"] for x in result["rows"]],["invalid","valid"])
        self.assertEqual(result["spec_reject_count"],1)
        self.assertEqual(result["economic_fail_count"],1)
        self.assertEqual(result["candidate_count"],2)
        self.assertEqual(result["static_admission"]["blocked_count"],1)

    def test_candidate_id_duplicates_fail_closed(self):
        econ=FakeEcon()
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            admission.evaluate_queue(econ,[{"candidate_id":"x","executable_spec":{"entry_rule":"close>open","bar_interval":"30m"}}]*2)
        self.assertEqual(econ.calls,[])


if __name__=="__main__":
    unittest.main()
