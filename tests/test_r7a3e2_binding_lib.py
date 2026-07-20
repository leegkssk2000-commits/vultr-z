from tools.r7a3e2_binding_lib import (
    find_pointers,
    select_unique_engine,
    select_unique_manifest,
)


def test_unique_engine_is_required():
    chosen, error = select_unique_engine([
        {"implementation_path": "backend/strategies/a.py", "callable": "run", "selection_score": 300},
        {"implementation_path": "backend/strategies/b.py", "callable": "run", "selection_score": 200},
    ])
    assert error is None
    assert chosen["implementation_path"].endswith("a.py")


def test_engine_tie_fails_closed():
    chosen, error = select_unique_engine([
        {"implementation_path": "backend/strategies/a.py", "callable": "run", "selection_score": 300},
        {"implementation_path": "backend/strategies/b.py", "callable": "run", "selection_score": 300},
    ])
    assert chosen is None
    assert error == "ENGINE_SELECTION_NOT_UNIQUE"


def test_manifest_pointer_must_be_unique():
    ids = ["alpha", "beta"]
    candidate = {
        "manifest_path": "config/exact25.json",
        "selection_score": 100,
        "strategy_pointers": {
            "alpha": ["/strategies/0/id"],
            "beta": ["/strategies/1/id"],
        },
    }
    chosen, error = select_unique_manifest([candidate], ids)
    assert error is None
    assert chosen["manifest_path"] == "config/exact25.json"


def test_json_pointer_discovery():
    value = {"strategies": [{"id": "alpha"}, {"id": "beta"}]}
    assert find_pointers(value, "beta") == ["/strategies/1/id"]
