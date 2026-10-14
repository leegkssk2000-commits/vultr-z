"""Historical freeze and exact authorized relocation remain separately enforced."""

import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.research.rebuild import scalp7_campaign_v2 as campaign
from backend.research.rebuild import scalp7_mr_formation_v2 as original
from backend.research.rebuild import issue1377_mr_formation_cost2_v1 as extension
from ops import scalp7_mr_isolation_publication_guard_v1 as migration

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ORIGINAL = "1674f245d57ed8b6d2b7ddd1984c1dade37af49172ef8fdd4341b8bbb873e6e5"
EXPECTED_EXTENSION = "b0ef459e4084fbd477c1597cf32454918321d0c07b0d869b3d289ff4ddad54f3"


class SourceIsolationTests(unittest.TestCase):
    def test_frozen_original_bytes(self):
        raw = (ROOT / migration.OLD).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), EXPECTED_ORIGINAL)

    def test_preserved_extension_bytes(self):
        raw = (ROOT / migration.NEW).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), EXPECTED_EXTENSION)

    def test_original_and_extension_are_distinct(self):
        self.assertFalse(hasattr(original, "COST_COVERED_IDENTITY"))
        self.assertIn(extension.COST_COVERED_IDENTITY, extension.SUPPORTED_IDENTITIES)
        self.assertEqual(original.PARENT_IDENTITY, extension.PARENT_IDENTITY)

    def test_unchanged_freeze_rejects_tampering(self):
        real_sha = campaign.sha

        def altered(path):
            if str(path).endswith("/scalp7_mr_formation_v2.py"):
                return "0" * 64
            return real_sha(path)

        with patch.object(campaign, "sha", side_effect=altered):
            with self.assertRaisesRegex(
                ValueError,
                "FROZEN_SOURCE_CHANGED:backend/research/rebuild/scalp7_mr_formation_v2.py",
            ):
                campaign.verify_freeze()

    def test_exact_first_migration(self):
        self.assertTrue(migration.relocation_plan(
            EXPECTED_EXTENSION, None, EXPECTED_ORIGINAL, EXPECTED_EXTENSION,
        ))

    def test_already_published_migration_is_not_reprojected(self):
        self.assertFalse(migration.relocation_plan(
            EXPECTED_ORIGINAL, EXPECTED_EXTENSION,
            EXPECTED_ORIGINAL, EXPECTED_EXTENSION,
        ))

    def test_changed_original_not_covered_by_migration(self):
        with self.assertRaisesRegex(ValueError, "RESTORED_ORIGINAL_BYTES_MISMATCH"):
            migration.relocation_plan(EXPECTED_EXTENSION, None, "0" * 64, EXPECTED_EXTENSION)

    def test_changed_extension_not_covered_by_migration(self):
        with self.assertRaisesRegex(ValueError, "PRESERVED_EXTENSION_BYTES_MISMATCH"):
            migration.relocation_plan(EXPECTED_EXTENSION, None, EXPECTED_ORIGINAL, "0" * 64)

    def test_unknown_base_is_not_authorized(self):
        with self.assertRaisesRegex(ValueError, "UNREVIEWED_MIGRATION_BASE"):
            migration.relocation_plan("0" * 64, None, EXPECTED_ORIGINAL, EXPECTED_EXTENSION)

    def test_unexpected_existing_extension_is_not_authorized(self):
        with self.assertRaisesRegex(ValueError, "UNREVIEWED_MIGRATION_BASE"):
            migration.relocation_plan(EXPECTED_EXTENSION, "0" * 64,
                                      EXPECTED_ORIGINAL, EXPECTED_EXTENSION)

    def test_workflow_tampering_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "HISTORIC_WORKFLOW_CHANGED"):
            migration.adapted_workflow(b"on: push\njobs: {}\n")

    def test_published_adapter_unchanged(self):
        self.assertEqual(migration.verify_adapter_identity(b"trusted", b"trusted", b"trusted"),
                         "PUBLISHED_BASE_BYTES")

    def test_replacement_adapter_rejected_by_base_copy(self):
        with self.assertRaisesRegex(ValueError, "PUBLISHED_ADAPTER_CHANGED"):
            migration.verify_adapter_identity(b"replacement", b"trusted", b"trusted")

    def test_replacement_adapter_cannot_validate_itself(self):
        with self.assertRaisesRegex(ValueError, "PUBLISHED_ADAPTER_CHANGED"):
            migration.verify_adapter_identity(b"replacement", b"replacement", b"trusted")

    def test_untrusted_executing_copy_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_ADAPTER_EXECUTION"):
            migration.verify_adapter_identity(b"trusted", b"replacement", b"trusted")

    def test_initial_reviewed_bootstrap(self):
        self.assertEqual(migration.verify_adapter_identity(b"reviewed", b"reviewed", None),
                         "INITIAL_REVIEWED_BOOTSTRAP")

    def test_bootstrap_copy_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "BOOTSTRAP_ADAPTER_COPY_MISMATCH"):
            migration.verify_adapter_identity(b"reviewed", b"replacement", None)
