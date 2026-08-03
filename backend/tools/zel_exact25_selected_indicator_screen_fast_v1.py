from __future__ import annotations

import os
import sys
from pathlib import Path

import zel_exact25_selected_indicator_screen_v1 as screen

VERSION = "ZEL_EXACT25_SELECTED_INDICATOR_SCREEN_FAST_V1"


def link_source_read_only(source_root: Path, destination: Path) -> None:
    """Expose the immutable source tree without copying runtime/data/backups.

    The wrapped evaluator performs no source writes. Live source-owner SHA-256
    preflight and baseline economic-digest parity remain mandatory fail-closed
    gates before any candidate result is accepted.
    """
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"SOURCE_LINK_DESTINATION_ALREADY_EXISTS:{destination}")
    os.symlink(source_root.resolve(), destination, target_is_directory=True)


def self_test() -> int:
    assert screen.copy_source is not link_source_read_only
    original = screen.copy_source
    screen.copy_source = link_source_read_only
    assert screen.copy_source is link_source_read_only
    screen.copy_source = original
    print("PASS")
    return 0


def main() -> int:
    if "--self-test-fast-wrapper" in sys.argv:
        return self_test()
    screen.copy_source = link_source_read_only
    return screen.main()


if __name__ == "__main__":
    raise SystemExit(main())
