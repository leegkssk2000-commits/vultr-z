"""Read-only preservation and retained-artifact metadata checks; no strategy imports."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCOPE = "CHART_TF_VOLUME_BINDING_AFTER_PR1229_V1"
PRIOR = "research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1"
PREFIX = "research/data/g5a_stage_v1/"
SLOTS = {f"{lane}/{period}" for lane in ("T1", "F1", "F0")
         for period in ("DEV2025", "SEEN2026")}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def check_hashes(base, hashes):
    require(isinstance(hashes, dict) and hashes, "EMPTY_HASH_MANIFEST")
    for name, expected in hashes.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts,
                "INVALID_MANIFEST_PATH:" + name)
        path = base / relative
        require(path.is_file() and not path.is_symlink(), "MISSING_FILE:" + name)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                "PRESERVED_HASH_CHANGED:" + name)


def check_allocation(value, budget):
    require(value["scope"] == SCOPE, "ALLOCATION_SCOPE")
    require(value["volume_basis_verified"] is False, "UNPROVEN_VOLUME_AUTHORIZED")
    require(value["reservations"] == [] and value["candidate_allocations"] == [],
            "UNAUTHORIZED_RESERVATION_OR_CANDIDATE")
    for key in ("actual_executions", "additional_parallel_allocation"):
        require(type(value[key]) is int and value[key] == 0, "NONZERO:" + key)
    require(value["automatic_retry"] is False, "AUTOMATIC_RETRY")
    require(value["max_conditional_candidates"] == 3 and
            value["max_conditional_full"] == value["remaining_same_slots"] == 6,
            "CONDITIONAL_CAP_CHANGED")
    slots = value["same_prior_unconsumed_slots"]
    require(len(slots) == 6 and set(slots) == SLOTS, "DUPLICATE_OR_CHANGED_SLOT")
    require(value["prior_budget_path"] == PRIOR + "/BUDGET.json", "BUDGET_PARENT")
    require(budget["cumulative_actual"] == 59 and
            budget["cumulative_actual_evaluations"] == 98, "PR1229_LEDGER_CHANGED")
    allocation = budget["chart_allocation"]
    require(allocation["remaining"] == 6 and allocation["reserved"] == 4 and
            allocation["started"] == allocation["completed"] == 4 and
            allocation["failed"] == 0, "PR1229_ALLOCATION_CHANGED")


def check_artifact(value, audit):
    require(value["status"] == "ORIGINAL_ARTIFACT_EQUALS_ORIGINAL_COMMITTED_OUTPUTS",
            "ARTIFACT_INSPECTION_NOT_COMPLETE")
    require(value["artifact_id"] == audit["artifact"]["id"] == 9970019637 and
            value["original_run_id"] == audit["original_run"]["run_id"] == 33967876652 and
            value["original_commit"] == audit["manifest_first_commit"],
            "ORIGINAL_ARTIFACT_IDENTITY_CHANGED")
    expected = {x["path"].removeprefix(PREFIX): (x["bytes"], x["git_blob"])
                for x in audit["original_committed_files"]}
    members = value["members"]
    actual = {x["path"]: (x["bytes"], x["git_blob"]) for x in members}
    require(len(members) == len(actual) == len(expected) ==
            value["observed_file_count"] == audit["original_committed_file_count"] ==
            audit["actions_upload_file_count"] == 28, "ARTIFACT_MEMBER_COUNT")
    require(actual == expected and value["extra_members"] == [], "ARTIFACT_MEMBER_MAP")
    for member in members:
        digest = member["sha256"]
        require(isinstance(digest, str) and len(digest) == 64 and
                all(c in "0123456789abcdef" for c in digest), "INVALID_MEMBER_DIGEST")
        require(member["contents_decoded"] is False, "UNAUTHORIZED_CONTENT_DECODE")
        if member["path"] == "development_manifest.json":
            require(digest == audit["manifest_sha256"], "CANONICAL_MANIFEST_CHANGED")
    for key in ("price_rows_decoded", "unused_oos_rows_decoded", "economic_executions",
                "market_requests"):
        require(type(value[key]) is int and value[key] == 0, "NONZERO:" + key)
    require(value["volume_basis_verified"] is False, "HASHES_ARE_NOT_VOLUME_AUTHORITY")


def verify(here=HERE, root=ROOT):
    preservation = read(here / "PRESERVATION.json")
    check_hashes(root, preservation)
    # Completeness matters: a verifier must not silently accept a pruned manifest.
    prior = root / PRIOR
    required = {PRIOR + "/" + p for p in read(prior / "FINAL_HASHES.json")}
    required |= set(read(prior / "SPEC.json")["source_files_sha256"])
    required |= {PRIOR + "/BUDGET.json", PRIOR + "/FINAL_HASHES.json"}
    require(required <= set(preservation), "PRESERVATION_COVERAGE_MISSING")
    allocation = read(here / "ALLOCATION.json")
    budget = read(prior / "BUDGET.json")
    check_allocation(allocation, budget)
    require(allocation["prior_budget_sha256"] == preservation[PRIOR + "/BUDGET.json"],
            "BUDGET_HASH_LINK")
    check_artifact(read(here / "ARTIFACT_CONTENTS.json"), read(here / "ARTIFACT_AUDIT.json"))
    lineage = read(here / "HISTORICAL_LINEAGE.json")
    require(lineage["volume_basis_verified"] is False and
            lineage["economic_executions"] == lineage["candidate_allocations"] == 0,
            "HISTORICAL_LINEAGE_AUTHORITY_CHANGED")
    decision = read(here / "DECISION.json")
    require(decision["scope"] == SCOPE and
            decision["decision"] == "NOT_RUN_VOLUME_BINDING_UNPROVEN" and
            decision["volume_basis_verified"] is False, "DECISION_CHANGED")
    require(decision["cumulative_candidates"] == 59 and
            decision["cumulative_evaluations"] == 98 and
            decision["prior_unused_slots"] == 6, "DECISION_LEDGER_CHANGED")
    for key in ("new_candidates", "new_evaluations", "new_reservations",
                "additional_parallel_allocation", "market_requests", "paid_ai", "orders"):
        require(type(decision[key]) is int and decision[key] == 0, "NONZERO:" + key)
    require(set(decision["lanes"]) == {"T1", "F1", "F0"}, "DECISION_LANES")
    for lane in decision["lanes"].values():
        require(lane["status"] == "NOT_RUN" and lane["actual_full"] == 0 and
                lane["new_candidates"] == 0, "UNAUTHORIZED_LANE_EXECUTION")
        require(all(lane[key] is None for key in
                    ("avoided_loss_bps", "drawdown_bps", "missed_winner_bps")),
                "UNEXECUTED_METRICS_INVENTED")
    require(not any(p.name in {"ATTEMPT.json", "EXECUTION_STARTED.json", "RESULT.json.gz",
                              "RAW.json.gz"} for p in here.rglob("*")),
            "UNAUTHORIZED_ECONOMIC_OUTPUT")
    final = here / "FINAL_HASHES.json"
    require(final.is_file(), "FINAL_MANIFEST_REQUIRED")
    hashes = read(final)
    check_hashes(here, hashes)
    files = {str(p.relative_to(here)) for p in here.rglob("*") if p.is_file()
             and "__pycache__" not in p.parts and p != final}
    require(files == set(hashes), "FINAL_MANIFEST_COVERAGE")
    return {"status": "PRESERVATION_AND_ARTIFACT_METADATA_VERIFIED", "scope": SCOPE,
            "preserved_files": len(preservation), "original_artifact_members": 28,
            "cumulative_candidates": 59, "cumulative_evaluations": 98,
            "remaining_same_slots": 6, "volume_basis_verified": False,
            "economic_executions": 0, "price_rows_decoded": 0}


class GuardTests(unittest.TestCase):
    def test_duplicate_slot_cannot_replace_a_missing_slot(self):
        allocation = read(HERE / "ALLOCATION.json")
        allocation["same_prior_unconsumed_slots"][-1] = allocation["same_prior_unconsumed_slots"][0]
        with self.assertRaisesRegex(ValueError, "DUPLICATE_OR_CHANGED_SLOT"):
            check_allocation(allocation, read(ROOT / PRIOR / "BUDGET.json"))

    def test_artifact_digest_cannot_grant_volume_authority(self):
        value = copy.deepcopy(read(HERE / "ARTIFACT_CONTENTS.json"))
        value["volume_basis_verified"] = True
        with self.assertRaisesRegex(ValueError, "HASHES_ARE_NOT_VOLUME_AUTHORITY"):
            check_artifact(value, read(HERE / "ARTIFACT_AUDIT.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    if args.manifest_sha256:
        require(hashlib.sha256((HERE / "FINAL_HASHES.json").read_bytes()).hexdigest()
                == args.manifest_sha256, "PINNED_FINAL_MANIFEST_CHANGED")
    if args.self_test:
        unittest.main(argv=[__file__])
    else:
        print(json.dumps(verify(), sort_keys=True))
