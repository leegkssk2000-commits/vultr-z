from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from backend.strategy25.fvg_trend_nonbeam_child_v1 import (
    CHILD_MANIFEST,
    POLICY_ID,
    load_fvg_trend_aligned_strategy,
)


ROOT = Path(__file__).resolve().parents[2]
PARENT_RUNNER_PATH = ROOT / "backend/tools/r7a4d_fvg_trend_alignment_real_oos.py"


def _load_parent_runner() -> Any:
    module_name = "r7a4d_fvg_trend_alignment_parent_for_nonbeam_v1"
    spec = importlib.util.spec_from_file_location(module_name, PARENT_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PARENT_RUNNER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parent = _load_parent_runner()
    parent.POLICY_ID = POLICY_ID
    parent.CHILD_MANIFEST = CHILD_MANIFEST
    parent.load_fvg_trend_aligned_strategy = load_fvg_trend_aligned_strategy
    parent.OUTPUT_DIR = "artifacts/r7a4d_fvg_trend_nonbeam_real_oos_v1"
    return int(parent.main())


if __name__ == "__main__":
    raise SystemExit(main())
