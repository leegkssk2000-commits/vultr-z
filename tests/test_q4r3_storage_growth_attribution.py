from __future__ import annotations

from tools.q4r3_storage_growth_attribution import classify, delta_rows


def test_delta_rows_orders_positive_growth_first() -> None:
    rows = delta_rows({"/a": 10, "/b": 20}, {"/a": 30, "/b": 15})
    assert rows[0]["path"] == "/a"
    assert rows[0]["delta_bytes"] == 20
    assert rows[-1]["delta_bytes"] == -5


def test_classify_worktree_growth() -> None:
    rows = classify(
        [
            {
                "path": "/home/z/z/.worktrees/example/file.bin",
                "before_bytes": 0,
                "after_bytes": 10,
                "delta_bytes": 10,
            }
        ]
    )
    assert rows[0]["category"] == "worktree_or_job_workspace_growth"


def test_classify_ignores_non_growth() -> None:
    assert classify(
        [
            {
                "path": "/tmp/a",
                "before_bytes": 10,
                "after_bytes": 5,
                "delta_bytes": -5,
            }
        ]
    ) == []
