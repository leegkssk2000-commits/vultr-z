import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import run_saved_evidence as runner


class OfflineHandoffTests(unittest.TestCase):
    def test_exact_offline_outputs_and_no_overwrite(self):
        root = Path(__file__).resolve().parent
        repo = root.parents[5]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "new"
            receipt = runner.run(repo, output)
            self.assertEqual(receipt["state"], "NO_CAUSAL_CHILD")
            self.assertEqual(receipt["new_full_runs"], 0)
            self.assertEqual(len(receipt["files"]), 7)
            for name, item in receipt["files"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), item["sha256"])
            saved = json.loads((output / "RUN_RECEIPT.json").read_text())
            self.assertEqual(saved, receipt)
            rows = json.loads((output / "ROWS_AUDIT.json").read_text())
            self.assertEqual([r["saved_row"] for r in rows], json.loads((root / "inputs/long_only_prospective.json").read_text())["trades"])
            with self.assertRaises(FileExistsError):
                runner.run(repo, output)


if __name__ == "__main__":
    unittest.main()
