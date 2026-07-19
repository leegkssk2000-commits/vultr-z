from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a4c1_token_view_diagnose.py"
SPEC = importlib.util.spec_from_file_location("r7a1a4c1", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_fingerprint_is_stable_and_nonsecret():
    value = "123456789:abcdefghijklmnopqrstuvwxyzABCDE12345"
    first = MODULE.fingerprint(value)
    second = MODULE.fingerprint(value)
    assert first == second
    assert len(first) == 16
    assert value not in first


def test_token_records_select_exact_expected_username(monkeypatch):
    values = {"fp-a": "token-a", "fp-b": "token-b", "fp-c": "token-c"}
    paths = {
        "fp-a": {"/a"},
        "fp-b": {"/b", "/b2"},
        "fp-c": {"/c"},
    }

    def fake_get_me(token: str):
        mapping = {
            "token-a": {"ok": True, "username": "other_bot"},
            "token-b": {"ok": True, "username": "z_os_zel_bot"},
            "token-c": {"ok": False, "username": None},
        }
        return mapping[token]

    monkeypatch.setattr(MODULE, "telegram_get_me", fake_get_me)
    records, matches = MODULE.token_records(values, paths, "z_os_zel_bot")
    assert matches == ["fp-b"]
    assert len(records) == 3
    assert all("token" not in record for record in records)
    assert next(row for row in records if row["fingerprint"] == "fp-b")["source_path_count"] == 2


def test_token_records_hold_on_multiple_expected_matches(monkeypatch):
    values = {"fp-a": "token-a", "fp-b": "token-b"}
    paths = {"fp-a": {"/a"}, "fp-b": {"/b"}}
    monkeypatch.setattr(
        MODULE,
        "telegram_get_me",
        lambda token: {"ok": True, "username": "z_os_zel_bot"},
    )
    _, matches = MODULE.token_records(values, paths, "z_os_zel_bot")
    assert matches == ["fp-a", "fp-b"]
