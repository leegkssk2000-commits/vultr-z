from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
PATH = ROOT / "tools/q4r3_exact25_r73b4u8_visible_patch.py"
SPEC = importlib.util.spec_from_file_location("b4u8", PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_only_five_visible_assignments_and_path_are_rewritten() -> None:
    source = '''from __future__ import annotations
STATUS = "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json"

def render_pos():
    last_close = legacy.get("last_close") or "BTCUSDT old"
    recent_rows = legacy.get("recent_rows") or 43
    last12 = legacy.get("last12") or 7.25
    wr = legacy.get("wr") or 37.209
    ev = legacy.get("ev") or 0.459302
    return f"ZEL POS\\nlast_close={last_close}\\nrecent_rows={recent_rows} last12={last12} wr={wr} ev={ev}\\n{STATUS}"
'''
    patched, stats = module.patch_source(source, "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json")
    compile(patched, "<patched>", "exec")
    assert stats["assignment_patch_count"] == 5
    assert stats["fallback_count"] == 0
    assert stats["path_patch_count"] == 1
    for name in ("last_close", "recent_rows", "last12", "wr", "ev"):
        line = next(row for row in patched.splitlines() if row.strip().startswith(name + " ="))
        assert "_r73b4u8_metric(" in line
    assert "src=telegram_status_latest.json" in patched


def test_ambiguous_target_refuses_to_mutate() -> None:
    source = '''
def render_pos():
    last_close = 1
    last_close = 2
    recent_rows = 43
    last12 = 7.25
    wr = 37.209
    ev = 0.459302
    return f"ZEL POS {last_close} {recent_rows} {last12} {wr} {ev} {status_path}"
'''
    try:
        module.patch_source(source, "/canonical.json")
    except RuntimeError as exc:
        assert "TARGET_LINE_COUNTS" in str(exc)
    else:
        raise AssertionError("ambiguous source must fail closed")
