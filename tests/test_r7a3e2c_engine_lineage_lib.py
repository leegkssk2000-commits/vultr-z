from tools.r7a3e2c_engine_lineage_lib import classify_strategy, function_rows, path_kind


def test_path_kind_blocks_diagnostics():
    assert path_kind("tools/audit_strategy.py") == "DIAGNOSTIC"
    assert path_kind("tests/test_strategy.py") == "DIAGNOSTIC"
    assert path_kind("backend/engine/strategy.py") == "SOURCE"


def test_unique_source_match_is_resolvable():
    reference = function_rows("def evaluate(x):\n    return x + 1\n", "tools/reference.py")
    source = function_rows("def evaluate(x):\n    return x + 1\n", "backend/engine/live.py")
    result = classify_strategy("alpha", reference, reference + source)
    assert result["classification"] == "UNIQUE_PRODUCTION_ENGINE"
    assert result["resolvable"] is True


def test_diagnostic_only_fails_closed():
    reference = function_rows("def evaluate(x):\n    return x + 1\n", "tools/reference.py")
    result = classify_strategy("alpha", reference, reference)
    assert result["classification"] == "DIAGNOSTIC_ONLY_REFERENCE"
    assert result["resolvable"] is False


def test_multiple_source_matches_are_ambiguous():
    reference = function_rows("def evaluate(x):\n    return x + 1\n", "tools/reference.py")
    first = function_rows("def evaluate(x):\n    return x + 1\n", "backend/a.py")
    second = function_rows("def evaluate(x):\n    return x + 1\n", "services/b.py")
    result = classify_strategy("alpha", reference, reference + first + second)
    assert result["classification"] == "MULTIPLE_PRODUCTION_MATCHES"
    assert result["resolvable"] is False
