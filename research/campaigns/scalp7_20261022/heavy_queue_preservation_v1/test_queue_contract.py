"""Offline queue configuration regressions. No strategy, market API or order calls."""

from pathlib import Path
import copy
import hashlib
import json
import subprocess
import unittest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
GROUP = "a1-global-heavy-economic-evaluator-v1"


def blocks(doc):
    c = doc.get("concurrency")
    if isinstance(c, dict):
        yield "workflow", c
    for name, job in doc.get("jobs", {}).items():
        if isinstance(job, dict) and isinstance(job.get("concurrency"), dict):
            yield "job:" + name, job["concurrency"]


def violations(doc):
    return [
        name
        for name, c in blocks(doc)
        if GROUP in str(c.get("group", "")).lower()
        and (
            c.get("queue") != "max"
            or str(c.get("cancel-in-progress")).lower() != "false"
        )
    ]


def load(raw):
    return yaml.load(raw, Loader=yaml.BaseLoader)


def strip_queue(doc):
    doc = copy.deepcopy(doc)
    for _, c in blocks(doc):
        if GROUP in str(c.get("group", "")).lower():
            c.pop("queue", None)
    return doc


def fixture(queue=None, cancel="false", where="workflow", group=GROUP):
    c = {"group": group, "cancel-in-progress": cancel}
    if queue is not None:
        c["queue"] = queue
    return (
        {"concurrency": c}
        if where == "workflow"
        else {"jobs": {"x": {"concurrency": c}}}
    )


class QueueContract(unittest.TestCase):
    def test_missing_queue_is_rejected(self):
        self.assertEqual(violations(fixture()), ["workflow"])

    def test_explicit_single_is_rejected(self):
        self.assertTrue(violations(fixture("single")))

    def test_max_false_is_preserved(self):
        self.assertFalse(violations(fixture("max")))

    def test_max_true_is_rejected(self):
        self.assertTrue(violations(fixture("max", "true")))

    def test_missing_cancellation_is_rejected(self):
        d = fixture("max")
        del d["concurrency"]["cancel-in-progress"]
        self.assertTrue(violations(d))

    def test_job_level_is_covered(self):
        self.assertEqual(violations(fixture(where="job")), ["job:x"])

    def test_expression_global_branch_is_covered(self):
        self.assertTrue(
            violations(
                fixture(
                    group="${{ github.event_name == 'pull_request' && 'ci' || '"
                    + GROUP
                    + "' }}"
                )
            )
        )

    def test_case_insensitive_group(self):
        self.assertTrue(violations(fixture(group=GROUP.upper())))

    def test_unrelated_ci_group_is_not_modified(self):
        self.assertFalse(violations(fixture("single", "true", group="other-ci")))

    def test_multiple_job_blocks_are_all_covered(self):
        d = {
            "jobs": {
                "a": {"concurrency": fixture("max")["concurrency"]},
                "b": {"concurrency": fixture()["concurrency"]},
            }
        }
        self.assertEqual(violations(d), ["job:b"])

    def test_all_repository_group_participants(self):
        found = 0
        for path in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
            d = load(path.read_text())
            n = sum(GROUP in str(c.get("group", "")).lower() for _, c in blocks(d))
            if n:
                found += 1
                with self.subTest(path=str(path)):
                    self.assertEqual(violations(d), [])
        self.assertGreaterEqual(found, 62)

    def test_patch_preserves_all_nonqueue_semantics_and_bytes(self):
        m = json.loads((HERE / "PATCH_MANIFEST.json").read_text())
        for row in m["workflows"]:
            with self.subTest(path=row["path"]):
                old = subprocess.check_output(
                    ["git", "-C", str(ROOT), "show", m["base"] + ":" + row["path"]]
                )
                new = (ROOT / row["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(old).hexdigest(), row["before_sha256"])
                self.assertEqual(hashlib.sha256(new).hexdigest(), row["after_sha256"])
                self.assertEqual(strip_queue(load(old)), strip_queue(load(new)))
                self.assertEqual(
                    len(new.splitlines()) - len(old.splitlines()), row["insertions"]
                )

    def test_manifest_is_exactly_52_one_line_changes(self):
        m = json.loads((HERE / "PATCH_MANIFEST.json").read_text())
        self.assertEqual(m["workflow_count"], 62)
        self.assertEqual(m["changed_workflows"], 52)
        self.assertEqual(m["total_insertions"], 52)
        for k in (
            "strategy_changes",
            "running_job_cancellations",
            "schedule_changes",
            "permissions_changes",
        ):
            self.assertEqual(m[k], 0)

    def test_existing_validation_default_is_preserved(self):
        d = load(
            (ROOT / ".github/workflows/kp-input-validation-20261004.yml").read_text()
        )
        self.assertEqual(
            d["on"]["workflow_dispatch"]["inputs"]["queue_contract_only"]["default"],
            "false",
        )
        self.assertIn("!inputs.queue_contract_only", d["jobs"]["verify-input"]["if"])
        self.assertIn(
            "github.event_name == 'workflow_dispatch' && inputs.queue_contract_only",
            d["jobs"]["queue-contract"]["if"],
        )

    def test_queue_ci_has_no_heavy_or_write_authority(self):
        d = load(
            (ROOT / ".github/workflows/kp-input-validation-20261004.yml").read_text()
        )
        j = d["jobs"]["queue-contract"]
        self.assertNotIn("concurrency", j)
        self.assertEqual(j["permissions"], {"contents": "read"})
        t = json.dumps(j)
        for bad in (
            "secrets.",
            "workflow_dispatch:",
            "/cancel",
            "run_compare.py",
            "queue_apply_existing.py",
            "owner_claim.py",
        ):
            self.assertNotIn(bad, t)
        self.assertIn("npm run --prefix frontend/z-os-app-source validate", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
