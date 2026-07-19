from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a4b1_assignment_shape_correction.py"
SPEC = importlib.util.spec_from_file_location("r7a1a4b1", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_assignment_shape_records_accept_nonliteral_rhs_without_values():
    source = b'''\ntoken, src = find_token()\nchat_id = str(message.get("chat_id"))\n'''
    rows = MODULE.assignment_shape_records(source, {"token", "chat_id"})
    assert [row["target"] for row in rows] == ["chat_id", "token"]
    assert all("value" not in row for row in rows)
    assert {row["rhs_ast_type"] for row in rows} == {"Call"}


def test_canonical_environment_records():
    source = b'''\nimport os\ntoken = os.environ.get("KEY_A", "")\nchat_id = os.getenv("KEY_B", "")\n'''
    rows = MODULE.canonical_env_records(source, {"token", "chat_id"})
    assert [(row["target"], row["environment_key"]) for row in rows] == [
        ("chat_id", "KEY_B"),
        ("token", "KEY_A"),
    ]


def test_duplicate_target_is_visible():
    source = b'''\ntoken = first()\ntoken = second()\nchat_id = third()\n'''
    rows = MODULE.assignment_shape_records(source, {"token", "chat_id"})
    counts = {name: sum(1 for row in rows if row["target"] == name) for name in ["chat_id", "token"]}
    assert counts == {"chat_id": 1, "token": 2}
