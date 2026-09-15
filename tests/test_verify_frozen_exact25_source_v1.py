"""Adversarial checks for the exact-byte preservation gate."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.verify_frozen_exact25_source_v1 import (
    ARCHIVE,
    ROOT,
    SOURCE,
    FreezeError,
    verify,
)


class FrozenExact25Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for relative in (SOURCE, ARCHIVE, str(Path(SOURCE).with_suffix(".pyi"))):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def test_exact_original_and_complete_stub_pass(self) -> None:
        self.assertEqual(
            verify(self.root)["state"], "PASS_FROZEN_EXACT25_SOURCE_AND_STUB"
        )

    def test_even_formatting_only_source_change_fails(self) -> None:
        with (self.root / SOURCE).open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(FreezeError, "SOURCE_SHA_MISMATCH"):
            verify(self.root)

    def test_archive_tampering_fails(self) -> None:
        (self.root / ARCHIVE).write_bytes(b"forged original")
        with self.assertRaisesRegex(FreezeError, "ARCHIVE_SHA_MISMATCH"):
            verify(self.root)

    def test_missing_source_fails(self) -> None:
        (self.root / SOURCE).unlink()
        with self.assertRaisesRegex(FreezeError, "REQUIRED_FILE_MISSING"):
            verify(self.root)

    def test_stub_return_type_widening_fails(self) -> None:
        stub = (self.root / SOURCE).with_suffix(".pyi")
        stub.write_text(
            stub.read_text().replace(
                "def stable_sha(value: Any) -> str:",
                "def stable_sha(value: Any) -> Any:",
            )
        )
        with self.assertRaisesRegex(FreezeError, "STUB_SIGNATURE_MISMATCH"):
            verify(self.root)

    def test_omitted_function_fails(self) -> None:
        stub = (self.root / SOURCE).with_suffix(".pyi")
        stub.write_text(stub.read_text().replace("def main() -> None: ...", ""))
        with self.assertRaisesRegex(FreezeError, "STUB_SIGNATURE_MISMATCH"):
            verify(self.root)

    def test_constant_type_widening_fails(self) -> None:
        stub = (self.root / SOURCE).with_suffix(".pyi")
        stub.write_text(stub.read_text().replace("ROOT: Path", "ROOT: Any"))
        with self.assertRaisesRegex(FreezeError, "STUB_CONSTANT_MISMATCH"):
            verify(self.root)

    def test_missing_export_fails(self) -> None:
        stub = (self.root / SOURCE).with_suffix(".pyi")
        stub.write_text(stub.read_text().replace("import argparse as argparse", ""))
        with self.assertRaisesRegex(FreezeError, "STUB_IMPORT_EXPORT_MISMATCH"):
            verify(self.root)

    def test_import_type_authority_retargeting_fails(self) -> None:
        stub = (self.root / SOURCE).with_suffix(".pyi")
        stub.write_text(
            stub.read_text().replace(
                "from pathlib import Path as Path", "from typing import Any as Path"
            )
        )
        with self.assertRaisesRegex(FreezeError, "STUB_IMPORT_EXPORT_MISMATCH"):
            verify(self.root)

    def test_constant_value_insertion_fails(self) -> None:
        stub = (self.root / SOURCE).with_suffix(".pyi")
        stub.write_text(
            stub.read_text().replace("ROOT: Path", 'ROOT: Path = Path("/")')
        )
        with self.assertRaisesRegex(FreezeError, "STUB_CONSTANT_VALUE"):
            verify(self.root)

    def test_duplicate_function_fails(self) -> None:
        stub = (self.root / SOURCE).with_suffix(".pyi")
        with stub.open("a") as stream:
            stream.write("\ndef main() -> None: ...\n")
        with self.assertRaisesRegex(FreezeError, "STUB_DUPLICATE_FUNCTION"):
            verify(self.root)


if __name__ == "__main__":
    unittest.main()
