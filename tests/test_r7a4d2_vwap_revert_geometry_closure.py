from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / "tools/r7a4d2_vwap_revert_geometry_closure.py"
    spec = importlib.util.spec_from_file_location("r7a4d2_vwap_geometry", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transform_is_exact_and_idempotent() -> None:
    module = load_module()
    source = "def strategy_fixture():\n" + module.OLD_BLOCK + "    return None\n"

    transformed, changed = module.transform_source(source)
    assert changed is True
    assert module.OLD_BLOCK not in transformed
    assert module.NEW_BLOCK in transformed
    module.validate_source(transformed, "fixture.py")

    second, second_changed = module.transform_source(transformed)
    assert second_changed is False
    assert second == transformed


def test_long_scale_in_requires_price_before_reversion_target() -> None:
    module = load_module()
    source = module.NEW_BLOCK
    assert '0.0 < long_avg_entry < price < long_reversion_target' in source
    assert 'cfg.scale_in_to_vwap_progress <= progress < 1.0' in source


def test_short_scale_in_requires_price_before_reversion_target() -> None:
    module = load_module()
    source = module.NEW_BLOCK
    assert 'short_reversion_target < price < short_avg_entry' in source
    assert 'cfg.scale_in_to_vwap_progress <= progress < 1.0' in source


def test_registry_update_changes_only_vwap_engine_identity() -> None:
    module = load_module()
    registry = {
        "strategy_count": 2,
        "entries": [
            {
                "strategy_id": "alpha_combo",
                "canonical_engine": {
                    "source_sha256": "alpha-old",
                    "binding_source": "old",
                    "decision_reason": "old",
                },
            },
            {
                "strategy_id": "vwap_revert",
                "canonical_engine": {
                    "source_sha256": "vwap-old",
                    "binding_source": "old",
                    "decision_reason": "old",
                },
            },
        ],
    }

    updated, old_sha, changed = module.update_registry(registry, "vwap-new")

    assert old_sha == "vwap-old"
    assert changed is True
    assert registry["entries"][1]["canonical_engine"]["source_sha256"] == "vwap-old"
    assert updated["entries"][0] == registry["entries"][0]
    engine = updated["entries"][1]["canonical_engine"]
    assert engine["source_sha256"] == "vwap-new"
    assert engine["binding_source"] == "R7.A4D2_VWAP_GEOMETRY_CLOSURE"
    assert engine["decision_reason"] == "VWAP_SCALE_IN_REVERSION_TARGET_GEOMETRY_CLOSED"
