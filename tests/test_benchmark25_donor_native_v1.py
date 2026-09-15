import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REBUILD = ROOT / "backend/research/rebuild"
if str(REBUILD) not in sys.path:
    sys.path.insert(0, str(REBUILD))
self_test = importlib.import_module("benchmark25_donor_native_policy_v1").self_test
SPEC = ROOT / "backend/research/rebuild/benchmark25_donor_native_spec_v1.json"


def test_donor_native_children_are_25_and_parent_independent():
    spec = json.loads(SPEC.read_text())
    assert spec["child_count"] == 25
    assert spec["parent_reuse"] == {
        "entry": False,
        "exit": False,
        "lifecycle": False,
        "parent_intent_gate": False,
    }
    assert all(
        x["entry_source"] == "DONOR_NATIVE_RECONSTRUCTION_NOT_PARENT_INTENT"
        for x in spec["children"].values()
    )
    assert all(
        x["exit_source"] == "DONOR_NATIVE_RECONSTRUCTION_NOT_PARENT_EXIT"
        for x in spec["children"].values()
    )
    assert all(
        x["lifecycle_source"] == "DONOR_NATIVE_RECONSTRUCTION_NOT_PARENT_LIFECYCLE"
        for x in spec["children"].values()
    )
    assert self_test() == 0
