from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools import strategy11_supertrend_parent_basis_v1 as parent
from backend.tools.strategy11_supertrend_fast_basis_v1 import authentic_supertrend_fast

parent.authentic_supertrend = authentic_supertrend_fast
_original_parent_result = parent.parent_result


def complete_window_decomposition(strategy_id: str, **kwargs: Any) -> dict[str, Any]:
    result = _original_parent_result(strategy_id, **kwargs)
    archive_root = Path(kwargs["archive_root"])
    manifest = parent.read_json(archive_root / "manifest.json")
    windows = sorted({str(row["window_id"]) for row in manifest["rows"]})
    if len(windows) != 12:
        raise RuntimeError(f"ARCHIVE_WINDOW_COUNT:{len(windows)}")
    current = dict(result["repaired"]["window_stats"])
    zero = parent.stats([])
    result["repaired"]["window_stats"] = {
        window_id: current.get(window_id, dict(zero)) for window_id in windows
    }
    result["repaired"]["window_count"] = len(windows)
    result.pop("result_sha256", None)
    result["result_sha256"] = parent.stable_sha(result)
    return result


parent.parent_result = complete_window_decomposition

if __name__ == "__main__":
    raise SystemExit(parent.main())
