from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Iterable


BASE_PATH = Path(__file__).with_name("q4r3_patch_debris_retention_cleanup_v8.py")
SPEC = importlib.util.spec_from_file_location("q4r3_patch_debris_cleanup_v8_base", BASE_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("PATCH_DEBRIS_V8_BASE_IMPORT_FAILED")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)


def candidate_contains_active_reference(path: Path, references: Iterable[Path]) -> bool:
    """Protect only exact references or references located inside a candidate.

    Broad process roots/cwds such as / or /home/z/z must not protect every
    descendant backup generation.
    """
    try:
        resolved = path.resolve(strict=False)
    except BASE.PATH_ERRORS:
        return True
    for ref in references:
        try:
            if resolved == ref or resolved in ref.parents:
                return True
        except BASE.PATH_ERRORS:
            continue
    return False


BASE.touches_reference = candidate_contains_active_reference


if __name__ == "__main__":
    raise SystemExit(BASE.main())
