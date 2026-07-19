from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a5a_runtime_error_classification.py"
SPEC = importlib.util.spec_from_file_location("r7a1a5a", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_classifies_telegram_conflict_without_raw_error():
    klass, code, fingerprint = MODULE.classify_error("HTTP Error 409: Conflict: terminated by other getUpdates request")
    assert klass == "HTTP_409_CONFLICT"
    assert code == 409
    assert fingerprint is not None and len(fingerprint) == 16


def test_classifies_timeout():
    klass, code, fingerprint = MODULE.classify_error("The read operation timed out")
    assert klass == "NETWORK_TIMEOUT"
    assert code is None
    assert fingerprint is not None


def test_empty_error_is_none():
    assert MODULE.classify_error(None) == ("NONE", None, None)


def test_other_error_is_redacted_to_class_and_fingerprint():
    raw = "unexpected internal detail"
    klass, code, fingerprint = MODULE.classify_error(raw)
    assert klass == "OTHER_ERROR"
    assert code is None
    assert raw not in str((klass, code, fingerprint))
