from __future__ import annotations

import importlib.util
import sys
from collections import namedtuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools/r7a4b_strategy25_deterministic_dry_run_matrix.py"
spec = importlib.util.spec_from_file_location("r7a4b_dry_run_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


@dataclass
class SampleDataclass:
    intent: str
    confidence: float


class SampleIntent(str, Enum):
    HOLD = "hold"
    ENTER_LONG = "enter_long"


class PlainObject:
    def __init__(self) -> None:
        self.intent = "hold"
        self.payload = {"b": 2, "a": 1}


class MissingAsdictObject:
    def __init__(self) -> None:
        self.intent = "hold"
        self.payload = {"b": 2, "a": 1}

    def __getattr__(self, name: str):
        return None


def complete_a4_status() -> dict:
    return {
        "official_stage": "R7.A4",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": 25,
        "canonical_input_count": 28,
        "canonical_git_parity_count": 28,
        "required_category_coverage_count": 4,
        "input_set_id": "abc123",
        "active_entry_count": 0,
        "simulation_replay_execution_count": 0,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "next_stage": "R7.A4B_SIMULATION_REPLAY_DRY_RUN_MATRIX",
    }


def test_prior_gate_is_exact() -> None:
    status = complete_a4_status()
    assert module.prior_gate(status, 25) is True
    status["simulation_replay_execution_count"] = 1
    assert module.prior_gate(status, 25) is False


def test_fixtures_are_deterministic_and_distinct() -> None:
    first = module.build_fixture("trend_up", 320)
    second = module.build_fixture("trend_up", 320)
    down = module.build_fixture("trend_down", 320)
    assert first == second
    assert first != down
    assert len(first) == 320
    assert {"open", "high", "low", "close", "volume", "timestamp"}.issubset(first[0])


def test_normalized_hash_is_stable_for_attrbox() -> None:
    value = module.AttrBox(intent="hold", confidence=0.5, payload={"b": 2, "a": 1})
    normalized_a, digest_a = module.normalized_hash(value)
    normalized_b, digest_b = module.normalized_hash(value)
    assert normalized_a == normalized_b
    assert digest_a == digest_b
    assert normalized_a["intent"] == "hold"


def test_string_enum_intent_normalizes_to_value() -> None:
    normalized, _ = module.normalized_hash({"intent": SampleIntent.HOLD})
    assert normalized == {"intent": "hold"}
    assert module.extract_intent(normalized) == "hold"


def test_normalize_handles_missing_asdict_without_calling_none() -> None:
    normalized, _ = module.normalized_hash(MissingAsdictObject())
    assert normalized == {"intent": "hold", "payload": {"a": 1, "b": 2}}


def test_normalize_handles_dataclass_namedtuple_and_plain_object() -> None:
    Pair = namedtuple("Pair", ["intent", "confidence"])
    assert module.normalize(SampleDataclass("hold", 0.5)) == {"confidence": 0.5, "intent": "hold"}
    assert module.normalize(Pair("hold", 0.5)) == {"confidence": 0.5, "intent": "hold"}
    assert module.normalize(PlainObject()) == {"intent": "hold", "payload": {"a": 1, "b": 2}}


def test_dangerous_true_detection_is_recursive() -> None:
    value = {"payload": {"execution_allowed": True}, "route_allowed": False}
    assert module.contains_dangerous_true(value, {"execution_allowed", "route_allowed"}) == [
        "payload.execution_allowed"
    ]


def test_side_effect_guard_blocks_writes(tmp_path: Path) -> None:
    attempts: list[str] = []
    target = tmp_path / "blocked.txt"
    try:
        with module.side_effect_guard(attempts):
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("x")
    except module.SideEffectBlocked:
        pass
    assert attempts
    assert not target.exists()
