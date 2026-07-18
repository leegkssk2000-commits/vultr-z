from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/q4r3_exact25_r73b4u5_telegram_pos_recovery.py"
SPEC = importlib.util.spec_from_file_location("r73b4u5", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_command_count_preserves_pos_pnl_view_handlers() -> None:
    source = '''
if text == "/pos": pass
if text == '/pnl': pass
if text == "/view": pass
'''
    assert module.command_count(source) == 3


def test_exact_view_patch_removes_residue_and_trailing_placeholders() -> None:
    source = '''
<div>A/B/G/D team lane</div>
<div>src=q4r3_shadow_closed_ledger_latest.json</div>
<div>configured=7 · active=0 · VV/TR/LS/MO/VB/MS/SR— — —</div>
'''
    patched, count = module.exact_view_patch(source, "shadow_aggregate_snapshot/latest.json")
    assert count == 1
    assert "A/B/G/D team lane" not in patched
    assert "q4r3_shadow_closed_ledger_latest.json" not in patched
    assert "— — —" not in patched
    assert module.WRITER_TEXT in patched


def test_exact_view_patch_handles_original_writer_template() -> None:
    source = '<span>writer_count=${activeWriterCount} · ${symbol} ${side} ${strategy}</span>'
    patched, count = module.exact_view_patch(source, "shadow_aggregate_snapshot/latest.json")
    assert count == 1
    assert module.WRITER_TEXT in patched


def test_metric_alias_resolution() -> None:
    payload = {"closed": 0, "rows": 0, "net_r": 0.0}
    assert module.metric(payload, "closed_count", "closed", default=-1) == 0
    assert module.metric(payload, "recent_rows", "rows", default=-1) == 0
    assert module.metric(payload, "pnl_r", "net_r", default=-1.0) == 0.0
