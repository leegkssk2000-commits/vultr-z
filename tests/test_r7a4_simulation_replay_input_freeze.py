from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools/r7a4_simulation_replay_input_freeze.py"
spec = importlib.util.spec_from_file_location("r7a4_input_freeze_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def complete_a3e5_status() -> dict:
    expected = 25
    return {
        "official_stage": "R7.A3E5",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": expected,
        "registry_entry_count": expected,
        "unique_strategy_id_count": expected,
        "source_sha_match_count": expected,
        "callable_resolved_count": expected,
        "config_resolved_count": expected,
        "adapter_resolved_count": expected,
        "adapter_read_only_count": expected,
        "route_blocked_count": expected,
        "execution_blocked_count": expected,
        "fail_closed_count": expected,
        "hold_decision_count": expected,
        "binding_artifact_reference_count": 0,
        "duplicate_binding_count": 0,
        "strategy_module_import_count": 0,
        "target_git_source_parity_count": expected,
        "target_git_registry_parity_count": 1,
        "target_git_config_parity_count": 1,
        "adapter_target_git_parity_count": 1,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "active_entry_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "next_stage": "R7.A4_SIMULATION_REPLAY_INPUT_FREEZE",
    }


def terms() -> dict[str, list[str]]:
    return {
        "replay_harness": ["replay", "simulation", "backtest"],
        "market_data": ["market_data", "ohlcv", "dataset"],
        "execution_cost": ["slippage", "fee", "latency"],
        "regime_context": ["regime", "market_quality"],
    }


def test_prior_gate_is_exact() -> None:
    status = complete_a3e5_status()
    assert module.prior_gate(status, 25) is True
    status["active_entry_count"] = 1
    assert module.prior_gate(status, 25) is False


def test_category_detection_uses_real_inputs(tmp_path: Path) -> None:
    replay = tmp_path / "engine/replay_runner.py"
    replay.parent.mkdir(parents=True)
    replay.write_text("def run_replay():\n    return None\n", encoding="utf-8")
    assert "replay_harness" in module.category_for(
        "engine/replay_runner.py", replay, terms(), {".csv", ".json", ".jsonl", ".parquet"}
    )

    dataset = tmp_path / "data/market_data/btc_ohlcv.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("ts,open,high,low,close\n", encoding="utf-8")
    assert module.category_for(
        "data/market_data/btc_ohlcv.csv", dataset, terms(), {".csv", ".json", ".jsonl", ".parquet"}
    ) == {"market_data"}


def test_diagnostic_files_do_not_count_as_harness(tmp_path: Path) -> None:
    path = tmp_path / "tools/bootstrap_replay_verify.py"
    path.parent.mkdir(parents=True)
    path.write_text("def run_replay():\n    return None\n", encoding="utf-8")
    assert module.category_for(
        "tools/bootstrap_replay_verify.py", path, terms(), {".csv", ".json"}
    ) == set()


def test_content_detects_execution_cost_and_regime(tmp_path: Path) -> None:
    path = tmp_path / "backend/policy/model.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "maker_fee = 0.0002\nslippage = 0.0004\nmarket_regime = 'trend'\n",
        encoding="utf-8",
    )
    detected = module.category_for(
        "backend/policy/model.py", path, terms(), {".csv", ".json"}
    )
    assert detected == {"execution_cost", "regime_context"}
