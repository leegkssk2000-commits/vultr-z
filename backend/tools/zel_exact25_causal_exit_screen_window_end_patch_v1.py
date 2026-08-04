from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

VERSION = "ZEL_EXACT25_CAUSAL_EXIT_WINDOW_END_PATCH_V1"
ORIGINAL_NAME = "zel_exact25_causal_exit_screen_v1.py"

_INSERT_ANCHOR = """    return {\n        \"strategy_id\": strategy_id,\n        \"owner_sha256\": str(getattr(owner, \"owner_sha256\", \"\")),\n        \"symbol\": symbol,\n"""
_INSERT_BLOCK = """    window_end_close_count = 0\n    if config is not None and isinstance(position, dict):\n        final_index = len(frame) - 1\n        final_last = frame.iloc[final_index]\n        final_current = frame.iloc[\n            max(0, final_index - int(engine.FRAME_LIMIT) + 1): final_index + 1\n        ].copy()\n        final_ts_iso = pd.Timestamp(final_last[\"timestamp\"]).isoformat()\n        final_features = producer.feature_snapshot(final_current)\n        closed.append(\n            close_row(\n                engine,\n                producer,\n                position,\n                float(final_last[\"close\"]),\n                final_ts_iso,\n                \"window_end_close\",\n                final_features,\n                funding_rows,\n                file_row,\n            )\n        )\n        position = None\n        window_end_close_count = 1\n\n"""
_CENSORED_ANCHOR = '        "censored_open_at_window_end": 1 if isinstance(position, dict) else 0,\n'
_EXTRA_ANCHOR = '            "censored_open_at_window_end",\n'
_VERSION_ANCHOR = 'VERSION = "ZEL_EXACT25_CAUSAL_EXIT_SCREEN_V1"'


def transform(source: str) -> str:
    checks = {
        "insert_anchor": source.count(_INSERT_ANCHOR),
        "censored_anchor": source.count(_CENSORED_ANCHOR),
        "extra_anchor": source.count(_EXTRA_ANCHOR),
        "version_anchor": source.count(_VERSION_ANCHOR),
    }
    if checks != {
        "insert_anchor": 1,
        "censored_anchor": 1,
        "extra_anchor": 1,
        "version_anchor": 1,
    }:
        raise RuntimeError(f"PATCH_ANCHOR_MISMATCH:{checks}")
    patched = source.replace(
        _VERSION_ANCHOR,
        'VERSION = "ZEL_EXACT25_CAUSAL_EXIT_SCREEN_V2_WINDOW_END_CLOSE"',
        1,
    )
    patched = patched.replace(_INSERT_ANCHOR, _INSERT_BLOCK + _INSERT_ANCHOR, 1)
    patched = patched.replace(
        _CENSORED_ANCHOR,
        _CENSORED_ANCHOR
        + '        "window_end_close_count": window_end_close_count,\n',
        1,
    )
    patched = patched.replace(
        _EXTRA_ANCHOR,
        _EXTRA_ANCHOR + '            "window_end_close_count",\n',
        1,
    )
    if patched.count('"window_end_close"') != 1:
        raise RuntimeError("WINDOW_END_CLOSE_INSERT_COUNT_INVALID")
    return patched


def load_patched() -> types.ModuleType:
    original = Path(__file__).with_name(ORIGINAL_NAME)
    if not original.is_file() or original.is_symlink():
        raise RuntimeError(f"ORIGINAL_SCREEN_MISSING_OR_INVALID:{original}")
    source = transform(original.read_text(encoding="utf-8"))
    module_name = f"zel_exact25_causal_exit_screen_window_end_runtime_{id(source)}"
    module = types.ModuleType(module_name)
    module.__file__ = str(original)
    module.__package__ = ""
    sys.modules[module_name] = module
    exec(compile(source, str(original), "exec"), module.__dict__)
    return module


def self_test() -> int:
    original = Path(__file__).with_name(ORIGINAL_NAME)
    transformed = transform(original.read_text(encoding="utf-8"))
    assert "ZEL_EXACT25_CAUSAL_EXIT_SCREEN_V2_WINDOW_END_CLOSE" in transformed
    assert transformed.count('"window_end_close"') == 1
    assert '"window_end_close_count": window_end_close_count' in transformed
    assert '"window_end_close_count",' in transformed
    print("PASS_WINDOW_END_PATCH_TRANSFORM")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

_PATCHED = load_patched()
for _name, _value in vars(_PATCHED).items():
    if _name not in {"__name__", "__file__", "__package__", "__loader__", "__spec__"}:
        globals()[_name] = _value
PATCH_VERSION = VERSION
