import importlib
import json
from pathlib import Path
from typing import Any

sm: Any = importlib.import_module(
    "backend.research.rebuild." + "benchmark25_donor_state_machine_v2"
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "backend/research/rebuild/benchmark25_donor_state_machine_v2.json"


def test_state_machine_contract_is_exact_25_and_parent_independent():
    spec = sm.load_spec()
    raw = json.loads(SPEC.read_text())
    assert raw["identity_count"] == 25
    assert len(spec["children"]) == 25
    assert sm.validate_coverage() == 0
    for sid, child in spec["children"].items():
        assert child["child_id"] == f"{sid}__donor_state_machine_v2"
        assert not any(child["parent_reuse"].values())
        assert len(child["event_sequence"]) >= 6
        assert (
            "ENTER" in child["event_sequence"]
            or "ENTER_FADE" in child["event_sequence"]
        )
        assert (
            child["threshold_authority"]
            == "IMPLEMENTATION_TRANSLATION_NOT_PUBLIC_DONOR_PARAMETER"
        )
