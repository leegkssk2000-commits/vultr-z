from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/q4r3_exact25_r73b4u3u4_rendered_residue_eradication.py"
SPEC = importlib.util.spec_from_file_location("r73b4u3u4", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def telegram_fixture() -> str:
    return '''#!/usr/bin/env python3
import json
from pathlib import Path
PRIMARY = Path("/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json")
OLD1 = Path("/home/z/z/q4r3_telegram_pos_adapter_v2_state.json")
OLD2 = Path("/usr/local/bin/q4r3_shadow_closed_ledger_latest.json")

def render():
    data = json.loads(PRIMARY.read_text())
    old = json.loads(OLD1.read_text()) if OLD1.exists() else {}
    last_close = data.get("last_close") or old.get("last_close")
    recent_rows = data.get("recent_rows") or old.get("recent_rows", 43)
    last12 = data.get("last12") or old.get("last12", 7.25)
    wr = data.get("wr") or old.get("wr", 37.209)
    ev = data.get("ev") or old.get("ev", 0.459302)
    return f"last_close={last_close} recent_rows={recent_rows} last12={last12} wr={wr} ev={ev} src={PRIMARY}"
'''


def test_telegram_patch_eliminates_secondary_paths_and_metric_fallbacks() -> None:
    secondary = {
        "/home/z/z/q4r3_telegram_pos_adapter_v2_state.json",
        "/usr/local/bin/q4r3_shadow_closed_ledger_latest.json",
    }
    patched, stats = module.patch_telegram(
        telegram_fixture(),
        "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json",
        secondary,
        "shadow_aggregate_snapshot/latest.json",
    )
    compile(patched, "<patched>", "exec")
    assert stats["metric_rewrite_count"] >= 5
    assert stats["path_rewrite_count"] >= 2
    assert module.direct_metric_access_count(patched) == 0
    assert not any(path in patched for path in secondary)
    assert "shadow_aggregate_snapshot/latest.json" in patched


def test_view_patch_removes_legacy_source_team_lane_and_corrects_writers_card() -> None:
    source = '''
<div>A/B/G/D team lane</div>
<div>Ledger-bound · src=q4r3_shadow_closed_ledger_latest.json</div>
<div id="writers">WRITERS 7</div>
<div>writer_count=${activeWriterCount} · ${symbol} ${side} ${strategy}</div>
'''
    patched, stats = module.patch_view(source, "shadow_aggregate_snapshot/latest.json")
    assert "q4r3_shadow_closed_ledger_latest.json" not in patched
    assert "A/B/G/D team lane" not in patched
    assert module.WRITER_LABEL in patched
    assert stats == {
        "legacy_source_replacement_count": 1,
        "team_lane_replacement_count": 1,
        "writer_card_replacement_count": 1,
    }


def test_last_close_assignment_is_forced_to_canonical_helper() -> None:
    patched, _ = module.patch_telegram(
        "last_close = legacy.get('last_close') or {'reason': 'SL_TOUCH_CLOSED'}\n",
        "/canonical.json",
        set(),
        "shadow_aggregate_snapshot/latest.json",
    )
    assert "last_close = _r73b4u3_value('last_close')" in patched
    assert module.direct_metric_access_count(patched) == 0


def test_view_fallback_relabels_flat_writer_count_when_template_shape_differs() -> None:
    source = '<p>WRITERS 7</p><span>writer_count=' + '${count}</span>'
    patched, stats = module.patch_view(source, "shadow_aggregate_snapshot/latest.json")
    assert stats["writer_card_replacement_count"] == 1
    assert "configured=7" in patched
