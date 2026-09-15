from backend.research.rebuild.a1_scalp7_mr_reexpansion_exit_v1 import (
    MIN_FAIL_BARS,
    should_fail_reexpand,
)


def test_reexpansion_cannot_fire_before_minimum_hold() -> None:
    assert MIN_FAIL_BARS == 4
    assert not should_fail_reexpand(0.04, 0.05, 3)


def test_reexpansion_fires_at_or_after_minimum_hold() -> None:
    assert should_fail_reexpand(0.04, 0.04, 4)
    assert should_fail_reexpand(0.04, 0.05, 5)
    assert not should_fail_reexpand(0.04, 0.039, 5)
