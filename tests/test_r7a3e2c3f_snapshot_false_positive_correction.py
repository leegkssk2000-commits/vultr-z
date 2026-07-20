from tools.r7a3e2c3f_strategy25_snapshot_false_positive_correction import path_kind


def test_runtime_results_is_artifact():
    assert path_kind("runtime_results/q4r3/strategy_source_snapshot/source/backend/strategies/a.py") == "ARTIFACT"
    assert path_kind("runtime_results/q4r3/exact25_candidate_package/source/backend/strategies/a.py") == "ARTIFACT"


def test_real_backend_is_source():
    assert path_kind("backend/strategies/a.py") == "SOURCE"


def test_tools_and_runtime_are_not_source():
    assert path_kind("tools/audit.py") == "DIAGNOSTIC"
    assert path_kind("runtime/status.py") == "CONFIG"
