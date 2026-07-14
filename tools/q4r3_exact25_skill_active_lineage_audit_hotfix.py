from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from tools import q4r3_exact25_skill_active_lineage_audit as base


MODULE_NAME = "q4r3_skill_resolver_v2_candidate_runtime"


def import_candidate_resolver(path: Path) -> Any:
    """Load the candidate resolver with its module registered for dataclasses."""
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"RESOLVER_IMPORT_SPEC_FAILED:{path}")

    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(MODULE_NAME)
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous is None:
            sys.modules.pop(MODULE_NAME, None)
        else:
            sys.modules[MODULE_NAME] = previous
        raise
    return module


base.import_candidate_resolver = import_candidate_resolver


if __name__ == "__main__":
    raise SystemExit(base.main())
