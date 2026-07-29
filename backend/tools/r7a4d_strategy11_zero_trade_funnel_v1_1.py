from __future__ import annotations

import json
from pathlib import Path

from backend.tools import r7a4d_strategy11_zero_trade_funnel_v1 as v1


def find_strategy_summary(root: Path, strategy_id: str) -> Path:
    matches: list[Path] = []
    for path in sorted(root.rglob(f"{strategy_id}/summary.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("strategy_id") == strategy_id and isinstance(payload.get("variants"), list):
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError(f"REPLAY_SUMMARY_MATCH:{strategy_id}:{len(matches)}")
    return matches[0]


v1.find_strategy_summary = find_strategy_summary


if __name__ == "__main__":
    raise SystemExit(v1.main())
