from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_exact25_100c_checkpoint_observer.py"
spec = importlib.util.spec_from_file_location("checkpoint", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_jsonl_count(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text("{}\n\n{}\n", encoding="utf-8")
    assert module.jsonl_count(path) == 2


def test_target_is_100() -> None:
    assert module.TARGET_CLOSED_COUNT == 100


def test_atomic_json(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    module.atomic_json(path, {"state": "PASS", "target_closed_count": 100})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["state"] == "PASS"
    assert payload["target_closed_count"] == 100
