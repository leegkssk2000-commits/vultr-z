from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/q4r3_exact25_r73b4u9_telegram_final_render_boundary.py"
SPEC = importlib.util.spec_from_file_location("r73b4u9", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def artifact(tmp_path: Path) -> Path:
    path = tmp_path / "telegram_status_latest.json"
    path.write_text(
        json.dumps({
            "closed_count": 0,
            "recent_rows": 0,
            "last12_r": 0.0,
            "winrate_pct": 0.0,
            "ev_r": 0.0,
            "pnl_r": 0.0,
            "last_close": "none",
        }),
        encoding="utf-8",
    )
    return path


def test_wraps_return_boundary_without_rewriting_whole_module(tmp_path: Path) -> None:
    source = '''from __future__ import annotations

def render_pos(data):
    text = "ZEL POS\\nrecent_rows=43 last12=7.25R wr=37.209% ev=0.459302R"
    return text

def untouched():
    return "OTHER"
'''
    patched, stats = module.patch_source(source, str(artifact(tmp_path)))
    assert stats["pos_function"] == "render_pos"
    assert stats["boundary_kind"] == "return_boundary"
    assert stats["boundary_wrap_count"] == 1
    assert "return _r73b4u9_visible_pos(text)" in patched
    assert 'return "OTHER"' in patched
    compile(patched, "<patched>", "exec")


def test_wraps_reply_text_argument_at_final_send_boundary(tmp_path: Path) -> None:
    source = '''async def pos(update):
    message = "ZEL POS\\nlast_close=old"
    await update.message.reply_text(message)
'''
    patched, stats = module.patch_source(source, str(artifact(tmp_path)))
    assert stats["boundary_kind"] == "outbound_call"
    assert stats["boundary_wrap_count"] == 1
    assert "reply_text(_r73b4u9_visible_pos(message))" in patched
    compile(patched, "<patched>", "exec")


def test_dryrun_removes_every_visible_legacy_token(tmp_path: Path) -> None:
    path = artifact(tmp_path)
    source = '''def render_pos():
    return "ZEL POS"
'''
    patched, _ = module.patch_source(source, str(path))
    rendered, residue = module.execute_helper_dryrun(patched, path)
    assert residue == 0
    assert "closed=0 pnl=0R" in rendered
    assert "last_close=none" in rendered
    assert "recent_rows=0 last12=0R wr=0% ev=0R" in rendered
    assert "src=telegram_status_latest.json" in rendered


def test_non_pos_message_passes_through(tmp_path: Path) -> None:
    path = artifact(tmp_path)
    helper = module.helper_source(str(path))
    namespace = {}
    exec(helper, namespace)
    assert namespace["_r73b4u9_visible_pos"]("OTHER MESSAGE") == "OTHER MESSAGE"


def test_command_counter_preserves_all_commands() -> None:
    source = "A='/pos'\nB='/pnl'\nC='/view'\n"
    assert module.command_count(source, ("/pos", "/pnl", "/view")) == 3
