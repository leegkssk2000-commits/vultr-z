from pathlib import Path
import importlib.util
import json
import sys


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a6c3b_false_positive_correction_and_exact_stability_verify.py"
SPEC = importlib.util.spec_from_file_location("r7a1a6c3b", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_nested_legacy_values_do_not_fail_without_file_change(tmp_path):
    target = tmp_path / "view.json"
    target.write_text(
        json.dumps({"official": {"closed": 0}, "legacy": {"closed": 68, "pnl_r": 53.613052}}),
        encoding="utf-8",
    )
    before = MODULE.snapshot((target,))
    after = MODULE.snapshot((target,))
    assert MODULE.diff_snapshots(before, after) == []


def test_byte_change_is_detected(tmp_path):
    target = tmp_path / "view.json"
    target.write_text('{"closed":0}\n', encoding="utf-8")
    before = MODULE.snapshot((target,))
    target.write_text('{"closed":1}\n', encoding="utf-8")
    after = MODULE.snapshot((target,))
    changes = MODULE.diff_snapshots(before, after)
    assert len(changes) == 1
    assert changes[0]["before"]["sha256"] != changes[0]["after"]["sha256"]


def test_atomic_replace_inode_change_is_detected(tmp_path):
    target = tmp_path / "view.json"
    replacement = tmp_path / "replacement.json"
    target.write_text('{"closed":0}\n', encoding="utf-8")
    before = MODULE.snapshot((target,))
    replacement.write_text('{"closed":0}\n', encoding="utf-8")
    replacement.replace(target)
    after = MODULE.snapshot((target,))
    changes = MODULE.diff_snapshots(before, after)
    assert len(changes) == 1
    assert changes[0]["before"]["inode"] != changes[0]["after"]["inode"]


def test_contract_allows_pass_with_zero_writer():
    contract = {
        "official_stage": "R7.A1A6C3B",
        "allow_no_overwriter_observed": True,
        "quarantine_on_unconfirmed_change": False,
        "required_exact_verify_count": 3,
    }
    assert MODULE.contract_valid(contract) is True


def test_old_c3_contract_is_rejected():
    contract = {
        "official_stage": "R7.A1A6C3",
        "allow_no_overwriter_observed": False,
        "quarantine_on_unconfirmed_change": True,
        "required_exact_verify_count": 1,
    }
    assert MODULE.contract_valid(contract) is False
