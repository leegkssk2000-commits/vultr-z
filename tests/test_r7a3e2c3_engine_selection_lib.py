from tools.r7a3e2c3_engine_selection_lib import (
    import_hits,
    module_variants,
    score_candidate,
    select_candidate,
)


def test_module_variants_and_import_hits():
    path = "backend/strategies/alpha_combo.py"
    assert "backend.strategies.alpha_combo" in module_variants(path)
    source = "from backend.strategies.alpha_combo import evaluate\n"
    assert import_hits(source, path) == 1


def test_selects_only_with_strong_authority_and_margin():
    first = score_candidate(
        {"path": "backend/strategies/alpha_combo.py", "callable": "evaluate"},
        {"production_import_hits": 1},
        "alpha_combo",
    )
    second = score_candidate(
        {"path": "services/strategies/common.py", "callable": "evaluate"},
        {},
        "alpha_combo",
    )
    selected, ranked, reason = select_candidate([first, second], 80)
    assert reason is None
    assert selected["path"] == "backend/strategies/alpha_combo.py"
    assert len(ranked) == 2


def test_tie_fails_closed():
    rows = [
        score_candidate({"path": "backend/a.py", "callable": "evaluate"}, {"runtime_hits": 1}, "x"),
        score_candidate({"path": "services/a.py", "callable": "evaluate"}, {"runtime_hits": 1}, "x"),
    ]
    selected, _, reason = select_candidate(rows, 80)
    assert selected is None
    assert reason.startswith("SELECTION_MARGIN_TOO_SMALL")


def test_weak_identity_only_fails_closed():
    rows = [
        score_candidate({"path": "backend/alpha_combo.py", "callable": "evaluate"}, {}, "alpha_combo"),
        score_candidate({"path": "services/common.py", "callable": "evaluate"}, {}, "alpha_combo"),
    ]
    selected, _, reason = select_candidate(rows, 80)
    assert selected is None
    assert reason == "TOP_CANDIDATE_HAS_NO_STRONG_AUTHORITY"
