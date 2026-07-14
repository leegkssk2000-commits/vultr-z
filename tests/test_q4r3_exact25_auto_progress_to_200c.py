from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_exact25_auto_progress_to_200c.py"
spec = importlib.util.spec_from_file_location("auto200", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_targets() -> None:
    assert module.TARGET_100C == 100
    assert module.TARGET_200C == 200


def test_jsonl_count(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text("{}\n{}\n\n{}\n", encoding="utf-8")
    assert module.jsonl_count(path) == 3
