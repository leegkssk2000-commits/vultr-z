from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_strategy_history_recovery_registry_authority_audit.py"
    spec = importlib.util.spec_from_file_location("q4r3_strategy_history_recovery_registry_authority_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def specialized_ema_source() -> str:
    body = [
        "from dataclasses import dataclass",
        "@dataclass",
        "class EmaRibbonConfig:",
        "    fast: int = 8",
        "    slow: int = 34",
        "class EmaRibbonScalpStrategy:",
        "    def ema_fast(self, values): return values",
        "    def ema_slow(self, values): return values",
        "    def alignment(self, fast, slow): return fast > slow",
        "    def slope(self, values): return 1.0",
        "    def pullback(self, price, ribbon): return price <= ribbon",
        "    def atr(self, candles): return 1.0",
        "    def stop_loss(self, entry, atr): return entry - atr",
        "    def take_profit(self, entry, atr): return entry + atr * 2",
        "    def strategy(self, payload):",
        "        return {'strategy_id':'ema_ribbon_scalp','entry_price':1.0,'stop_loss':0.9,'take_profit':1.2}",
    ]
    body.extend(f"EMA_RIBBON_RULE_{index} = {index}" for index in range(120))
    return "\n".join(body) + "\n"


def specialized_vol_source() -> str:
    body = [
        "class VolSpikeFadeStrategy:",
        "    def volume_z(self, values): return 3.0",
        "    def zscore(self, values): return 3.0",
        "    def mean_reversion(self, price, mean): return price > mean",
        "    def fade(self, price): return -1",
        "    def rsi(self, values): return 80.0",
        "    def atr(self, candles): return 1.0",
        "    def stop_loss(self, entry, atr): return entry + atr",
        "    def take_profit(self, entry, atr): return entry - atr * 2",
        "    def strategy(self, payload):",
        "        return {'strategy_id':'vol_spike_fade','entry_price':1.0,'stop_loss':1.1,'take_profit':0.8}",
    ]
    body.extend(f"VOL_SPIKE_FADE_RULE_{index} = {index}" for index in range(120))
    return "\n".join(body) + "\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_specialized_source_scores_above_generic_wrapper() -> None:
    specialized = MODULE.candidate_score(
        "ema_ribbon_scalp",
        "historical_reachable_blob_exact",
        "backend/strategies/ema_ribbon_scalp.py",
        specialized_ema_source(),
    )
    wrapper = MODULE.candidate_score(
        "ema_ribbon_scalp",
        "legendary_reserve_path",
        "backend/legendary_rebuild/strategies/ema_ribbon_scalp_legendary.py",
        "def strategy(payload):\n    return {'strategy_id':'ema_ribbon_scalp'}\n",
    )
    assert specialized.score_100 >= 60
    assert specialized.wrapper_like is False
    assert specialized.ast_valid is True
    assert specialized.score_100 > wrapper.score_100


def test_deleted_exact_file_is_recovered_from_reachable_git_history(tmp_path: Path) -> None:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    target = tmp_path / "backend" / "strategies" / "ema_ribbon_scalp.py"
    target.parent.mkdir(parents=True)
    target.write_text(specialized_ema_source(), encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "add ema canonical")
    target.unlink()
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "remove ema canonical")

    found = MODULE.scan_reachable_git_history(tmp_path)
    candidates = list(found["ema_ribbon_scalp"].values())
    assert candidates
    assert any(candidate.source_path == "backend/strategies/ema_ribbon_scalp.py" for candidate in candidates)
    assert max(candidate.score_100 for candidate in candidates) >= 60


def test_backup_working_file_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "_TRASH_ZEL" / "backend" / "strategies" / "vol_spike_fade.py"
    target.parent.mkdir(parents=True)
    target.write_text(specialized_vol_source(), encoding="utf-8")
    found = MODULE.scan_working_tree(tmp_path)
    candidates = list(found["vol_spike_fade"].values())
    assert candidates
    assert candidates[0].origin_kind == "backup_or_archive_path"


def test_archive_member_is_detected(tmp_path: Path) -> None:
    archive_path = tmp_path / "strategy_backup.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("backend/strategies/ema_ribbon_scalp.py", specialized_ema_source())
    found = MODULE.scan_archives(tmp_path)
    candidates = list(found["ema_ribbon_scalp"].values())
    assert candidates
    assert candidates[0].origin_kind == "archive_member"


def test_secret_candidate_is_never_qualified() -> None:
    source = specialized_ema_source() + "API_KEY='ABCDEFGHIJKLMNOP'\n"
    candidate = MODULE.candidate_score(
        "ema_ribbon_scalp",
        "historical_reachable_blob_exact",
        "backend/strategies/ema_ribbon_scalp.py",
        source,
    )
    assert candidate.secret_safe is False
    assert candidate.score_100 == 0


def test_runtime_exact_25_loader_is_authority_candidate(tmp_path: Path) -> None:
    loader = tmp_path / "backend" / "engine" / "canonical_registry.py"
    loader.parent.mkdir(parents=True)
    payload = "\n".join(
        [
            "import importlib",
            "def load_strategy(module_path): return importlib.import_module(module_path)",
            "STRATEGY_MAP = {",
            *[f"    '{name}': 'backend.strategies.{name}'," for name in MODULE.EXPECTED_25],
            "}",
        ]
    )
    loader.write_text(payload, encoding="utf-8")
    entry = tmp_path / "backend" / "run_server.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("from backend.engine import canonical_registry\n", encoding="utf-8")
    files = [loader, entry]
    _module_map, graph = MODULE.import_graph(tmp_path, files)
    reachable = MODULE.reachable_paths(["backend/run_server.py"], graph)
    result = MODULE.registry_candidates(tmp_path, files, reachable)
    assert result["authoritative_candidate"] is not None
    assert result["authoritative_candidate"]["coverage_count"] == 25


def test_exact_25_history_surface_is_not_runtime_authority(tmp_path: Path) -> None:
    inventory = tmp_path / "data" / "strategy_registry_latest.json"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({"strategies": list(MODULE.EXPECTED_25)}), encoding="utf-8")
    result = MODULE.registry_candidates(tmp_path, [inventory], set())
    assert result["authoritative_candidate"] is None
    assert result["candidates"][0]["role"] == "EXACT_25_DISCOVERY_OR_HISTORY_SURFACE"


def test_recovery_decision_requires_non_wrapper_qualified_candidates() -> None:
    ema = MODULE.candidate_score(
        "ema_ribbon_scalp",
        "historical_reachable_blob_exact",
        "backend/strategies/ema_ribbon_scalp.py",
        specialized_ema_source(),
    )
    vol_wrapper = MODULE.candidate_score(
        "vol_spike_fade",
        "legendary_reserve_path",
        "backend/legendary_rebuild/strategies/vol_spike_fade_legendary.py",
        "def strategy(payload):\n    return {'strategy_id':'vol_spike_fade'}\n",
    )
    decision = MODULE.decide_recovery(
        {"ema_ribbon_scalp": [ema], "vol_spike_fade": [vol_wrapper]},
        {"authoritative_candidate": None},
    )
    assert decision["recoverable_strategy_count"] == 1
    assert decision["strategies"]["vol_spike_fade"]["verdict"] == "NO_QUALIFIED_ORIGINAL_FOUND_REBUILD_REQUIRED"
