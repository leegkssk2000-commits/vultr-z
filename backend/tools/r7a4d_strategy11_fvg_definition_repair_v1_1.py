from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_fvg_definition_repair_v1 as core


def load_patched_strategy(root: Path, expected_source_sha: str) -> tuple[Any, dict[str, Any]]:
    path = (root / core.SOURCE_PATH).resolve()
    source = path.read_text(encoding="utf-8")
    source_sha = core.sha_text(source)
    if source_sha != expected_source_sha:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source_sha}:{expected_source_sha}")
    patched_source, manifest = core.patch_source(source)
    module_name = "backend.strategies.fvg_revert_research_three_candle_v1"
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = "backend.strategies"
    sys.modules[module_name] = module
    try:
        exec(compile(patched_source, str(path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    strategy = module.__dict__.get("strategy")
    if not callable(strategy):
        raise RuntimeError("PATCHED_STRATEGY_NOT_CALLABLE")
    return strategy, {
        "canonical_source_sha": source_sha,
        "patched_source_sha": core.sha_text(patched_source),
        "replacement_manifest": manifest,
        "semantic_change_count": 1,
        "semantic_change": "ADJACENT_GAP_TO_THREE_CANDLE_FVG",
        "loader_fix": "REGISTER_MODULE_BEFORE_DATACLASS_EXEC",
    }


core.load_patched_strategy = load_patched_strategy


if __name__ == "__main__":
    raise SystemExit(core.main())
