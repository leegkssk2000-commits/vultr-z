import importlib.util
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "tools/r7a3d3c_strategy25_explicit_registry_binding_plan.py"
S = importlib.util.spec_from_file_location("m", P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)


def c(path, explicit=False, direct=False):
    return {"implementation_path": path, "callable": "evaluate", "binding_kind": "direct" if direct else "registry_or_shared", "git_path_exists": True, "git_blob_sha": "a" * 40, "candidate_source_blob_sha": "a" * 40, "explicit_binding": explicit, "direct_name_match": direct, "active_import_chain": ["runner.py", path], "active_exact_units": []}


def test_direct_unique_ready():
    row = {"strategy_id": "alpha_combo", "resolved": False, "candidate_proofs": [c("backend/strategies/alpha_combo.py", direct=True), c("backend/engine.py")]}
    assert M.plan_mapping(row, 30)["registry_patch_ready"] is True


def test_tie_requires_more_proof():
    row = {"strategy_id": "alpha_combo", "resolved": False, "candidate_proofs": [c("backend/a.py", explicit=True), c("backend/b.py", explicit=True)]}
    assert M.plan_mapping(row, 30)["resolution"] == "SOURCE_DIFF_REQUIRED"


def test_diagnostic_is_rejected():
    score, _ = M.score_candidate(c("tools/strategy_audit.py", explicit=True))
    assert score < 0


def test_prior_mapping_preserved():
    row = {"strategy_id": "s", "resolved": True, "canonical_mapping": {"implementation_path": "x.py"}}
    assert M.plan_mapping(row, 30)["resolution"] == "PRIOR_RESOLVED"
