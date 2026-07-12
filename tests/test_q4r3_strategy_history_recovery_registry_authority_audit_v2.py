from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_strategy_history_recovery_registry_authority_audit_v2.py"
    spec = importlib.util.spec_from_file_location(
        "q4r3_strategy_history_recovery_registry_authority_v2_test_module",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()
BASE = MODULE.BASE


def specialized_source(strategy: str) -> str:
    class_name = "EmaRibbonScalpStrategy" if strategy == "ema_ribbon_scalp" else "VolSpikeFadeStrategy"
    terms = (
        ["ema_fast", "ema_slow", "alignment", "pullback", "slope"]
        if strategy == "ema_ribbon_scalp"
        else ["volume_z", "zscore", "fade", "mean_reversion", "rsi"]
    )
    lines = [f"class {class_name}:"]
    for term in terms:
        lines.append(f"    def {term}(self, values): return 1.0")
    lines.extend(
        [
            "    def atr(self, candles): return 1.0",
            "    def stop_loss(self, entry, atr): return entry - atr",
            "    def take_profit(self, entry, atr): return entry + atr * 2",
            "    def strategy(self, payload):",
            f"        return {{'strategy_id':'{strategy}','entry_price':1.0,'stop_loss':0.9,'take_profit':1.2}}",
        ]
    )
    lines.extend(f"RULE_{index} = {index}" for index in range(120))
    return "\n".join(lines) + "\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_importfrom_alias_resolves_exact_module(tmp_path: Path) -> None:
    registry = tmp_path / "backend" / "engine" / "canonical_registry.py"
    registry.parent.mkdir(parents=True)
    registry.write_text("STRATEGY_MAP = {}\n", encoding="utf-8")
    entry = tmp_path / "backend" / "run_server.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("from backend.engine import canonical_registry\n", encoding="utf-8")

    _modules, graph = MODULE.import_graph(tmp_path, [registry, entry])
    assert "backend/engine/canonical_registry.py" in graph["backend/run_server.py"]


def test_runtime_exact_25_loader_is_authority_candidate(tmp_path: Path) -> None:
    loader = tmp_path / "backend" / "engine" / "canonical_registry.py"
    loader.parent.mkdir(parents=True)
    loader.write_text(
        "\n".join(
            [
                "import importlib",
                "def load_strategy(module_path): return importlib.import_module(module_path)",
                "STRATEGY_MAP = {",
                *[f"    '{name}': 'backend.strategies.{name}'," for name in BASE.EXPECTED_25],
                "}",
            ]
        ),
        encoding="utf-8",
    )
    entry = tmp_path / "backend" / "run_server.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("from backend.engine import canonical_registry\n", encoding="utf-8")

    files = [loader, entry]
    _module_map, graph = MODULE.import_graph(tmp_path, files)
    reachable = BASE.reachable_paths(["backend/run_server.py"], graph)
    result = BASE.registry_candidates(tmp_path, files, reachable)

    assert result["authoritative_candidate"] is not None
    assert result["authoritative_candidate"]["path"] == "backend/engine/canonical_registry.py"
    assert result["authoritative_candidate"]["coverage_count"] == 25


def test_deleted_exact_file_recovers_from_git_history(tmp_path: Path) -> None:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    target = tmp_path / "backend" / "strategies" / "ema_ribbon_scalp.py"
    target.parent.mkdir(parents=True)
    target.write_text(specialized_source("ema_ribbon_scalp"), encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "add ema canonical")
    target.unlink()
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "remove ema canonical")

    found = BASE.scan_reachable_git_history(tmp_path)
    candidates = list(found["ema_ribbon_scalp"].values())
    assert candidates
    assert max(candidate.score_100 for candidate in candidates) >= 60


def test_generic_wrapper_is_not_recovery_candidate() -> None:
    wrapper = BASE.candidate_score(
        "vol_spike_fade",
        "legendary_reserve_path",
        "backend/legendary_rebuild/strategies/vol_spike_fade_legendary.py",
        "def strategy(payload):\n    return {'strategy_id':'vol_spike_fade'}\n",
    )
    decision = BASE.decide_recovery(
        {"ema_ribbon_scalp": [], "vol_spike_fade": [wrapper]},
        {"authoritative_candidate": None},
    )
    assert decision["recoverable_strategy_count"] == 0
    assert decision["strategies"]["vol_spike_fade"]["verdict"] == "NO_QUALIFIED_ORIGINAL_FOUND_REBUILD_REQUIRED"


def test_exact_25_history_surface_is_not_runtime_authority(tmp_path: Path) -> None:
    inventory = tmp_path / "data" / "strategy_registry_latest.json"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({"strategies": list(BASE.EXPECTED_25)}), encoding="utf-8")
    result = BASE.registry_candidates(tmp_path, [inventory], set())
    assert result["authoritative_candidate"] is None
    assert result["candidates"][0]["role"] == "EXACT_25_DISCOVERY_OR_HISTORY_SURFACE"
