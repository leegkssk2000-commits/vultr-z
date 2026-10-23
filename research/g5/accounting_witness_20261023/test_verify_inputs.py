import hashlib
import tempfile
import unittest
from pathlib import Path
from verify_inputs import verify, strict_json, external_output


class InputGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = b'{"formal_credit":0}\n'
        (self.root / "state.json").write_bytes(self.raw)
        self.manifest = {"formal_pass_authority": False, "g5a_rows_reusable_for_g5b": False,
                         "files": [{"path": "state.json", "bytes": len(self.raw),
                                    "sha256": hashlib.sha256(self.raw).hexdigest()}]}

    def test_original_then_tamper(self):
        self.assertEqual(len(verify(self.root, self.manifest)), 1)
        (self.root / "state.json").write_bytes(self.raw.replace(b":0", b":1"))
        with self.assertRaisesRegex(ValueError, "INPUT_BYTES_MISMATCH"):
            verify(self.root, self.manifest)

    def test_traversal_rejected(self):
        self.manifest["files"][0]["path"] = "../state.json"
        with self.assertRaisesRegex(ValueError, "UNSAFE_INPUT_PATH"):
            verify(self.root, self.manifest)

    def test_duplicate_rejected(self):
        self.manifest["files"] *= 2
        with self.assertRaisesRegex(ValueError, "DUPLICATE_INPUT_PATH"):
            verify(self.root, self.manifest)

    def test_unknown_is_not_false_authority(self):
        self.manifest["formal_pass_authority"] = None
        with self.assertRaisesRegex(ValueError, "FORMAL_AUTHORITY"):
            verify(self.root, self.manifest)

    def test_g5b_credit_forbidden(self):
        self.manifest["g5a_rows_reusable_for_g5b"] = True
        with self.assertRaisesRegex(ValueError, "G5B_REUSE"):
            verify(self.root, self.manifest)

    def test_nonfinite_rejected(self):
        for val in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaisesRegex(ValueError, "NONFINITE_JSON"):
                strict_json('{"x":' + val + '}')

    def test_output_cannot_mutate_source(self):
        with self.assertRaisesRegex(ValueError, "OUTPUT_MUST_BE_OUTSIDE"):
            external_output(self.root, self.root / "backend/new")


if __name__ == "__main__":
    unittest.main()
