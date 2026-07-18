from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tools/q4r3_exact25_r73b4_readonly_display_parity_smoke_v6.py"
SPEC = importlib.util.spec_from_file_location("r73b4_v6", TARGET)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_metric_score_requires_display_metrics() -> None:
    assert module.metric_score('{"closed_count":2,"winrate_pct":50,"total_r":1.2,"latest_trace_id":"p.2"}') == 4
    assert module.metric_score("<html>view shell only</html>") == 0


def test_telegram_composite_merges_referenced_artifacts(tmp_path: Path) -> None:
    pnl = tmp_path / "pnl.json"
    trace = tmp_path / "trace.json"
    ledger = tmp_path / "ledger.jsonl"
    pnl.write_text(json.dumps({"closed_count": 2, "winrate_pct": 50.0, "total_r": 1.25}), encoding="utf-8")
    trace.write_text(json.dumps({"latest_trace_id": "exact25.shadow.p2"}), encoding="utf-8")
    ledger.write_text("", encoding="utf-8")
    source = f'PNL = "{pnl}"\nTRACE = "{trace}"\n'
    module.base.CONTEXTS[module.base.TELEGRAM_UNIT] = {
        "info": {"working_directory": str(tmp_path)},
        "environment": {},
        "combined": source,
        "source": tmp_path / "adapter.py",
    }
    label, text, count = module.choose_composite_artifact(source, ledger)
    payload = json.loads(text)
    assert label.startswith("COMPOSITE:")
    assert count == 2
    assert payload == {
        "closed_count": 2,
        "winrate_pct": 50.0,
        "total_r": 1.25,
        "latest_trace_id": "exact25.shadow.p2",
    }


def test_telegram_never_falls_back_to_view(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    module.base.CONTEXTS[module.base.TELEGRAM_UNIT] = {
        "info": {"working_directory": str(tmp_path)},
        "environment": {},
        "combined": "/view https://alimi.vip/view",
        "source": tmp_path / "adapter.py",
    }
    label, text, count = module.choose_composite_artifact("/view https://alimi.vip/view", ledger)
    assert (label, text, count) == ("", "", 0)
    assert module.DIAGNOSTICS["telegram_view_fallback_forbidden"] is True
