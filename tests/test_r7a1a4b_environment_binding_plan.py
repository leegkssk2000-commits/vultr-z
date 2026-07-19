from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a4b_environment_binding_plan.py"
SPEC = importlib.util.spec_from_file_location("r7a1a4b", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_classify_direct_and_alias_keys():
    source = b'''\nimport os\ndef helper():\n    x = os.environ.get("OLD_A") or os.environ.get("OLD_B")\n    return x\ndef main():\n    token = os.environ.get("NEW_A", "")\n    chat_id = os.environ.get("NEW_B", "")\n'''
    records = MODULE.environment_key_records(source)
    direct, aliases = MODULE.classify_keys(records)
    assert sorted({row["key"] for row in direct}) == ["NEW_A", "NEW_B"]
    assert sorted({row["key"] for row in aliases}) == ["OLD_A", "OLD_B"]


def test_deployed_assignment_detection_does_not_return_values():
    source = b'''\ntoken = "sensitive-value"\nchat_id = "sensitive-id"\nother = "safe"\n'''
    rows = MODULE.deployed_sensitive_assignments(source)
    assert len(rows) == 2
    assert all("value" not in row for row in rows)
    assert [row["target"] for row in rows] == ["token", "chat_id"]


def test_parse_environment_names_only():
    text = '''\nEnvironment="EXAMPLE_A=value"\nEXAMPLE_B=other\n# EXAMPLE_C=ignored\n'''
    assert MODULE.parse_environment_names(text) == {"EXAMPLE_A", "EXAMPLE_B"}
