from __future__ import annotations

from pathlib import Path

from backend.tools import strategy11_v3_survivor_w1_overlay_v1 as overlay

_original_locate_one = overlay.locate_one


def locate_strategy_file(root: Path, pattern: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if pattern == "summary.json":
        matches = [path for path in matches if path.parent.name == "trend_ma_macd"]
    if len(matches) != 1:
        raise RuntimeError(f"FILE_CARDINALITY:{pattern}:{len(matches)}:{matches}")
    return matches[0]


overlay.locate_one = locate_strategy_file

if __name__ == "__main__":
    raise SystemExit(overlay.main())
