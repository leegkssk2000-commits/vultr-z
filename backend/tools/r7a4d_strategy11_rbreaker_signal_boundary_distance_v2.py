from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_rbreaker_signal_boundary_distance_v1 as v1

VERSION = "R7A4D_STRATEGY11_RBREAKER_SIGNAL_BOUNDARY_DISTANCE_V2"


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_patched_strategy(root: Path, expected_source_sha: str) -> tuple[Any, dict[str, Any]]:
    path = (root / v1.SOURCE_PATH).resolve()
    source = path.read_text(encoding="utf-8")
    source_sha = sha_text(source)
    if source_sha != expected_source_sha:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source_sha}:{expected_source_sha}")
    old_distance = '    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)'
    new_distance = '''    if long_break:\n        active_boundary = breakout_buy + atr_now * cfg.breakout_buffer_atr\n        dist_beyond_signal_atr = max(price - active_boundary, 0.0) / max(atr_now, 1e-9)\n    elif short_break:\n        active_boundary = breakout_sell - atr_now * cfg.breakout_buffer_atr\n        dist_beyond_signal_atr = max(active_boundary - price, 0.0) / max(atr_now, 1e-9)\n    elif long_reversal:\n        active_boundary = mid + atr_now * cfg.reversal_reclaim_atr\n        dist_beyond_signal_atr = max(price - active_boundary, 0.0) / max(atr_now, 1e-9)\n    elif short_reversal:\n        active_boundary = mid - atr_now * cfg.reversal_reclaim_atr\n        dist_beyond_signal_atr = max(active_boundary - price, 0.0) / max(atr_now, 1e-9)\n    else:\n        active_boundary = price\n        dist_beyond_signal_atr = 0.0'''
    replacements = (
        (old_distance, new_distance),
        ('    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr', '    late_chase_block = dist_beyond_signal_atr > cfg.max_chase_dist_atr'),
        ('        "dist_from_fast_atr": round(dist_from_fast_atr, 6),', '        "active_signal_boundary": round(active_boundary, 6),\n        "dist_beyond_signal_atr": round(dist_beyond_signal_atr, 6),'),
    )
    patched = source
    manifest_rows = []
    for old, new in replacements:
        count = patched.count(old)
        if count != 1:
            raise RuntimeError(f"SOURCE_REPLACEMENT_COUNT:{sha_text(old)}:{count}")
        patched = patched.replace(old, new, 1)
        manifest_rows.append({"old_sha": sha_text(old), "new_sha": sha_text(new), "count": 1})
    module_name = "backend.strategies.rbreaker_like_research_signal_boundary_v2"
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = "backend.strategies"
    sys.modules[module_name] = module
    try:
        exec(compile(patched, str(path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    strategy = module.__dict__.get("strategy")
    if not callable(strategy):
        raise RuntimeError("PATCHED_STRATEGY_NOT_CALLABLE")
    return strategy, {
        "canonical_source_sha": source_sha,
        "patched_source_sha": sha_text(patched),
        "semantic_change_count": 1,
        "text_replacement_count": len(replacements),
        "semantic_change": "EMA_DISTANCE_TO_BUFFERED_ACTIVE_SIGNAL_THRESHOLD_OVERSHOOT",
        "threshold_changed": False,
        "max_chase_dist_atr_unchanged": True,
        "breakout_buffer_included": True,
        "reversal_thresholds_unchanged": True,
        "replacements": manifest_rows,
    }


if __name__ == "__main__":
    v1.VERSION = VERSION
    v1.load_patched_strategy = load_patched_strategy
    raise SystemExit(v1.main())
