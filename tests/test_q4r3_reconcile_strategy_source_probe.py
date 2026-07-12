from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_reconcile_strategy_source_probe.py"
    spec = importlib.util.spec_from_file_location("q4r3_reconcile_strategy_source_probe_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def make_probe() -> dict:
    return {
        "contract_surface": {
            "strategies": [
                {
                    "strategy": f"strategy_{index:02d}",
                    "modules": [
                        {
                            "path": f"backend/legendary_rebuild/strategies/strategy_{index:02d}_legendary.py"
                        }
                    ],
                }
                for index in range(25)
            ]
        }
    }


def build_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    canonical = root / "backend" / "strategies"
    legendary = root / "backend" / "legendary_rebuild" / "strategies"
    canonical.mkdir(parents=True)
    legendary.mkdir(parents=True)
    candidates = []
    for index in range(25):
        name = f"strategy_{index:02d}"
        canonical_path = canonical / f"{name}.py"
        legendary_path = legendary / f"{name}_legendary.py"
        canonical_path.write_text("def strategy(): return {}\n", encoding="utf-8")
        legendary_path.write_text("def strategy(): return {}\n", encoding="utf-8")
        candidates.append({"path": f"backend/strategies/{name}.py"})
    inventory = root / "data" / "strategy_registry_latest.json"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({"candidates_top": candidates}), encoding="utf-8")
    return root


def test_reconciliation_recovers_omitted_canonical_files(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    result = MODULE.reconcile(root, make_probe())
    summary = result["source_reconciliation"]
    assert summary["expected_strategy_count"] == 25
    assert summary["original_module_count"] == 25
    assert summary["reconciled_module_count"] == 50
    assert summary["probe_omission_count"] == 25
    assert summary["all_25_have_canonical_source"] is True
    first = result["contract_surface"]["strategies"][0]
    paths = [item["path"] for item in first["modules"]]
    assert "backend/strategies/strategy_00.py" in paths
    assert "backend/legendary_rebuild/strategies/strategy_00_legendary.py" in paths


def test_strategy_from_path_removes_variant_suffixes() -> None:
    assert MODULE.strategy_from_path("backend/strategies/ema_ribbon_scalp.py") == "ema_ribbon_scalp"
    assert MODULE.strategy_from_path("backend/legendary_rebuild/strategies/ema_ribbon_scalp_legendary.py") == "ema_ribbon_scalp"
    assert MODULE.strategy_from_path("backend/strategies_v4/ema_ribbon_scalp_v4.py") == "ema_ribbon_scalp"


def test_exact_25_is_required(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    probe = make_probe()
    probe["contract_surface"]["strategies"].pop()
    try:
        MODULE.reconcile(root, probe)
    except RuntimeError as exc:
        assert "EXPECTED_EXACT_25_STRATEGIES" in str(exc)
    else:
        raise AssertionError("expected exact-25 guard")
