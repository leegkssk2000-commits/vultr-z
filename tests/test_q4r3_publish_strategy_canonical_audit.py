from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_publish_strategy_canonical_audit.py"
    spec = importlib.util.spec_from_file_location("q4r3_publish_strategy_canonical_audit_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_sections_are_split() -> None:
    sections = MODULE.split_sections(["[3] FILES", "a", "[4] DEFINITIONS", "b"])
    assert sections["3"] == ["a"]
    assert sections["4"] == ["b"]


def test_location_sections_drop_source_excerpt() -> None:
    line = "./backend/strategy.py:42:api logic and full source text"
    assert MODULE.sanitize_line("4", line) == "./backend/strategy.py:42"


def test_secret_line_is_removed() -> None:
    assert MODULE.sanitize_line("3", "API_KEY=abcdef") is None


def test_duplicate_locations_are_deduplicated() -> None:
    lines = ["./a.py:1:x", "./a.py:1:y", "./b.py:2:z"]
    assert MODULE.sanitize_section("4", lines) == ["./a.py:1", "./b.py:2"]


def test_publish_omits_raw_audit_and_hash_section(tmp_path: Path) -> None:
    source = tmp_path / "audit.txt"
    source.write_text(
        "[3] FILES\n./backend/a.py\n"
        "[4] DEFINITIONS\n./backend/a.py:1:strategy_id='x'\n"
        "[8] HASHES\ndeadbeef secret.txt\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    manifest = MODULE.publish(source, output)
    assert manifest["raw_audit_published"] is False
    assert manifest["source_code_excerpts_published"] is False
    assert not (output / "hashes.txt").exists()
    assert (output / "strategy_definition_locations.txt").read_text().strip() == "./backend/a.py:1"
