from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b3_static_lock_quarantine_canary.py"
SPEC = importlib.util.spec_from_file_location("r73b3", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def row(tmp_path: Path, name: str, body: bytes) -> dict[str, object]:
    original = tmp_path / "etc" / name
    backup = tmp_path / "backup" / name
    isolated = tmp_path / "isolated" / name
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(body)
    return {
        "unit": name,
        "original_path": str(original),
        "planned_backup_path": str(backup),
        "planned_isolated_path": str(isolated),
        "sha256_before": module.sha256(original),
        "mode_octal": "0o644",
        "enabled_before": "disabled" if name.endswith(".timer") else "static",
        "apply_order": 1 if name.endswith(".timer") else 2,
        "rollback_order": 2 if name.endswith(".timer") else 1,
    }


def manifest(tmp_path: Path) -> dict[str, object]:
    return {
        "state": "PASS",
        "blocker_count": 0,
        "target_count": 2,
        "protected_unit_count": 5,
        "targets": [
            row(tmp_path, "zel-s4g8r7f8t-telegram-6c-lock-only.timer", b"timer"),
            row(tmp_path, "zel-s4g8r7f8t-telegram-6c-lock-only.service", b"service"),
        ],
        "protected_units": [
            {"unit": f"protected-{index}.service", "path": str(tmp_path / f"p{index}.service")}
            for index in range(5)
        ],
    }


def test_atomic_copy_preserves_content(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "nested" / "destination"
    source.write_bytes(b"payload")
    module.atomic_copy(source, destination, 0o640)
    assert destination.read_bytes() == b"payload"
    assert destination.stat().st_mode & 0o777 == 0o640


def test_preflight_accepts_exact_inactive_states(tmp_path: Path, monkeypatch) -> None:
    data = manifest(tmp_path)
    states = {
        "zel-s4g8r7f8t-telegram-6c-lock-only.timer": ("inactive", "disabled"),
        "zel-s4g8r7f8t-telegram-6c-lock-only.service": ("inactive", "static"),
    }

    def value(unit: str, action: str) -> str:
        return states[unit][0 if action == "is-active" else 1]

    monkeypatch.setattr(module, "systemctl_value", value)
    module.target_preflight(data)


def test_restore_uses_verified_backup(tmp_path: Path, monkeypatch) -> None:
    data = manifest(tmp_path)
    for item in data["targets"]:
        original = Path(item["original_path"])
        backup = Path(item["planned_backup_path"])
        module.atomic_copy(original, backup, 0o644)
        original.unlink()
    monkeypatch.setattr(module, "command", lambda *args, **kwargs: None)
    assert module.restore_targets(data) == 2
    for item in data["targets"]:
        original = Path(item["original_path"])
        assert original.is_file()
        assert module.sha256(original) == item["sha256_before"]


def test_load_inputs_rejects_foreign_target(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.json"
    manifest_path = tmp_path / "manifest.json"
    contract_path.write_text(json.dumps({"official_stage": "R7.3B3"}), encoding="utf-8")
    data = manifest(tmp_path)
    data["targets"][0]["unit"] = "foreign.timer"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    try:
        module.load_inputs(contract_path, manifest_path)
    except RuntimeError as exc:
        assert "TARGET_SET_INVALID" in str(exc)
    else:
        raise AssertionError("foreign target was accepted")


def test_approval_token_is_fixed() -> None:
    assert module.APPROVAL_TOKEN == "R7.3B3_APPLY_STATIC_LOCK_QUARANTINE"
