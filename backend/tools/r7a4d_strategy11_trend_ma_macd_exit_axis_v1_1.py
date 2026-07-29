from __future__ import annotations

import json
from pathlib import Path

from backend.tools import r7a4d_strategy11_trend_ma_macd_exit_axis_v1 as v1


def find_source_variant(root: Path) -> Path:
    matches: list[Path] = []
    for path in sorted(root.rglob(f"{v1.STRATEGY_ID}/{v1.SOURCE_VARIANT_ID}/summary.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        config = payload.get("candidate_config") or {}
        if config.get("strategy_id") == v1.STRATEGY_ID and config.get("candidate_id") == v1.SOURCE_VARIANT_ID:
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError(f"SOURCE_VARIANT_MATCH:{len(matches)}")
    return matches[0]


v1.find_source_variant = find_source_variant


if __name__ == "__main__":
    raise SystemExit(v1.main())
