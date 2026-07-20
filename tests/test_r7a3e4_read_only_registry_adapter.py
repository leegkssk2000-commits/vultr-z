from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ADAPTER_PATH = Path(__file__).parents[1] / "backend/strategy25/read_only_registry_adapter_v1.py"
spec = importlib.util.spec_from_file_location("r7a3e4_adapter_test", ADAPTER_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ReadOnlyStrategy25RegistryAdapter = module.ReadOnlyStrategy25RegistryAdapter
RegistryContractError = module.RegistryContractError


def write_fixture(root: Path, *, config_ref: str = "backend/strategy25/canonical_strategy25_config_v1.json#/strategies/demo") -> None:
    source_path = root / "backend/strategies/demo.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source = "class DemoStrategy:\n    def decide(self):\n        return {'action': 'hold'}\n"
    source_path.write_text(source, encoding="utf-8")
    source_sha = hashlib.sha256(source.encode()).hexdigest()

    config_path = root / "backend/strategy25/canonical_strategy25_config_v1.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({
        "schema": "canonical_strategy25_config_v1",
        "strategy_count": 1,
        "active_entry_count": 0,
        "fail_closed": True,
        "strategies": {"demo": {"period": 14}},
    }), encoding="utf-8")

    registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    registry_path.write_text(json.dumps({
        "schema": "canonical_strategy25_registry_v1",
        "active_entry_count": 0,
        "fail_closed": True,
        "entries": [{
            "strategy_id": "demo",
            "active_allowed": False,
            "fail_closed": True,
            "config_ref": config_ref,
            "canonical_engine": {
                "implementation_path": "backend/strategies/demo.py",
                "callable": "DemoStrategy.decide",
                "source_sha256": source_sha,
            },
        }],
    }), encoding="utf-8")


def test_adapter_resolves_metadata_without_execution(tmp_path: Path) -> None:
    write_fixture(tmp_path)
    adapter = ReadOnlyStrategy25RegistryAdapter(tmp_path, expected_count=1)
    assert adapter.strategy_ids() == ("demo",)
    view = adapter.resolve_for_router("demo")
    assert view["read_only"] is True
    assert view["route_allowed"] is False
    assert view["execution_allowed"] is False
    assert view["active_allowed"] is False
    assert view["fail_closed"] is True
    assert view["decision"] == "hold"
    assert view["config"]["period"] == 14
    with pytest.raises(TypeError):
        view["decision"] = "enter_long"


def test_unknown_strategy_fails_closed(tmp_path: Path) -> None:
    write_fixture(tmp_path)
    adapter = ReadOnlyStrategy25RegistryAdapter(tmp_path, expected_count=1)
    with pytest.raises(RegistryContractError, match="UNKNOWN_STRATEGY_ID"):
        adapter.resolve_for_router("missing")


def test_noncanonical_config_reference_is_rejected(tmp_path: Path) -> None:
    write_fixture(tmp_path, config_ref="runtime_results/candidate/config.json#/strategies/demo")
    with pytest.raises(RegistryContractError, match="CONFIG_PATH_NOT_CANONICAL"):
        ReadOnlyStrategy25RegistryAdapter(tmp_path, expected_count=1)


def test_source_sha_mismatch_is_rejected(tmp_path: Path) -> None:
    write_fixture(tmp_path)
    source_path = tmp_path / "backend/strategies/demo.py"
    source_path.write_text(source_path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    with pytest.raises(RegistryContractError, match="SOURCE_SHA_MISMATCH"):
        ReadOnlyStrategy25RegistryAdapter(tmp_path, expected_count=1)
