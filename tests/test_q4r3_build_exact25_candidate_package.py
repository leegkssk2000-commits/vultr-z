from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_build_exact25_candidate_package.py"
    spec = importlib.util.spec_from_file_location("q4r3_exact25_candidate_package_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_expected_universe_is_exactly_25_and_unique() -> None:
    assert len(MODULE.EXPECTED_25) == 25
    assert len(set(MODULE.EXPECTED_25)) == 25
    assert "ema_ribbon_scalp" in MODULE.EXPECTED_25
    assert "vol_spike_fade" in MODULE.EXPECTED_25


def test_ema_patch_keeps_reduce_available_after_add_cap() -> None:
    source = '''    if in_long and can_add_more:\n        long_add = pullback_long_add and long_reclaim and not failed_long\n        long_reduce = failed_long\n\n    if in_short and can_add_more:\n        short_add = pullback_short_add and short_reclaim and not failed_short\n        short_reduce = failed_short\n'''
    patched, patches = MODULE.patch_ema_ribbon_scalp(source)
    assert "if in_long:\n        long_reduce = failed_long\n        if can_add_more:" in patched
    assert "if in_short:\n        short_reduce = failed_short\n        if can_add_more:" in patched
    assert patches == ["reduce_remains_available_after_max_add_count"]


def test_vol_patch_disables_water_add_by_default() -> None:
    source = '''    max_pyramiding: int = 2\n\n    water_add_extension_atr: float = 1.80\n        long_water_add = long_fade_setup and body_atr >= cfg.water_add_extension_atr\n        short_water_add = short_fade_setup and body_atr >= cfg.water_add_extension_atr\n'''
    patched, patches = MODULE.patch_vol_spike_fade(source)
    assert "enable_water_add: bool = False" in patched
    assert "long_water_add = cfg.enable_water_add and" in patched
    assert "short_water_add = cfg.enable_water_add and" in patched
    assert patches == ["water_add_default_disabled_until_high_risk_route_promotion"]


def test_dangerous_call_detection() -> None:
    import ast

    clean = ast.parse("def strategy(df):\n    return {'action':'hold'}\n")
    dirty = ast.parse("def strategy(df):\n    Path('x').write_text('bad')\n")
    assert MODULE.dangerous_calls(clean) == []
    assert "Path.write_text" in MODULE.dangerous_calls(dirty)


def test_manifest_is_exact25_no_fallback() -> None:
    checks = []
    for strategy_id in MODULE.EXPECTED_25:
        checks.append(
            MODULE.StrategyCheck(
                strategy_id=strategy_id,
                source_path=f"candidate/{strategy_id}.py",
                owner_module=f"backend.strategies.{strategy_id}",
                owner_sha256="a" * 64,
                ast_ok=True,
                import_ok=True,
                strategy_callable=True,
                signature_ok=True,
                invalid_input_contract_ok=True,
                hard_risk_gate_contract_ok=True,
                lbot_adapter_found=True,
                short_core_guard_found=True,
                dangerous_call_hits=[],
                issues=[],
            )
        )
    recovery = {
        "ema_ribbon_scalp": {"source": "ema_source.py"},
        "vol_spike_fade": {"source": "vol_source.py"},
    }
    manifest = MODULE.build_manifest(checks, recovery)
    assert manifest["strategy_count"] == 25
    assert manifest["dynamic_fallback_allowed"] is False
    assert manifest["runtime_binding_status"] == "NOT_BOUND_CANDIDATE_ONLY"
    assert len({entry["strategy_id"] for entry in manifest["strategies"]}) == 25
    assert all(entry["enabled_for_shadow"] is True for entry in manifest["strategies"])
    assert all(entry["enabled_for_paper"] is False for entry in manifest["strategies"])
    assert all(entry["enabled_for_live"] is False for entry in manifest["strategies"])


def test_atomic_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    MODULE.atomic_json(path, {"ok": True, "count": 25})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True, "count": 25}
