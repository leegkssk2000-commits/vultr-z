"""Historical freeze remains strict; separately named MR extension is preserved."""
from pathlib import Path
import hashlib
import unittest
from unittest.mock import patch
from backend.research.rebuild import scalp7_campaign_v2 as campaign
from backend.research.rebuild import scalp7_mr_formation_v2 as original
from backend.research.rebuild import issue1377_mr_formation_cost2_v1 as extension
ROOT=Path(__file__).resolve().parents[1]
class SourceIsolationTests(unittest.TestCase):
    def test_frozen_original_bytes(self):
        self.assertEqual(hashlib.sha256((ROOT/'backend/research/rebuild/scalp7_mr_formation_v2.py').read_bytes()).hexdigest(), EXPECTED_ORIGINAL)
    def test_preserved_extension_bytes(self):
        self.assertEqual(hashlib.sha256((ROOT/'backend/research/rebuild/issue1377_mr_formation_cost2_v1.py').read_bytes()).hexdigest(), EXPECTED_EXTENSION)
    def test_original_and_extension_are_distinct(self):
        self.assertFalse(hasattr(original,'COST_COVERED_IDENTITY'))
        self.assertIn(extension.COST_COVERED_IDENTITY,extension.SUPPORTED_IDENTITIES)
        self.assertEqual(original.PARENT_IDENTITY,extension.PARENT_IDENTITY)
    def test_unchanged_freeze_rejects_tampering(self):
        real_sha=campaign.sha
        def altered(path):
            return '0'*64 if str(path).endswith('/scalp7_mr_formation_v2.py') else real_sha(path)
        with patch.object(campaign,'sha',side_effect=altered):
            with self.assertRaisesRegex(ValueError,'FROZEN_SOURCE_CHANGED:backend/research/rebuild/scalp7_mr_formation_v2.py'):
                campaign.verify_freeze()

EXPECTED_ORIGINAL='1674f245d57ed8b6d2b7ddd1984c1dade37af49172ef8fdd4341b8bbb873e6e5'
EXPECTED_EXTENSION='b0ef459e4084fbd477c1597cf32454918321d0c07b0d869b3d289ff4ddad54f3'
