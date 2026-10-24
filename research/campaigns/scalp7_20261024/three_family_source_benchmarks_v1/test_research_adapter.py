import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_adapter as a


class AdapterContract(unittest.TestCase):
    def setUp(self):
        self.folder = Path(__file__).resolve().parent

    def test_default_off(self):
        r = a.export(self.folder)
        self.assertEqual(r["state"], "DEFAULT_OFF")
        self.assertEqual(r["signal_T"], 0)
        self.assertEqual(r["order_authority"], "BLOCKED")

    def test_external_live_scope_blocked(self):
        with self.assertRaisesRegex(ValueError, "FORBIDDEN_FORMAL"):
            a.export(self.folder, enabled=True, scope="LIVE")

    def test_false_formal_promotion_blocked(self):
        with self.assertRaisesRegex(ValueError, "FORBIDDEN_FORMAL"):
            a.export(self.folder, enabled=True, scope="FORMAL_G5")

    def test_source_integrity_protected(self):
        self.assertEqual(a.export(self.folder)["formal_g5_credit"], 0)


if __name__ == "__main__":
    unittest.main()
