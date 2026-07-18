from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "tools/q4r3_exact25_r73b4u7_telegram_input_source_cutover_v2.py"
SPEC = importlib.util.spec_from_file_location("r73b4u7", MODULE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_zero_payload_blocks_falsey_or_fallbacks() -> None:
    payload = module.zero_payload()
    for key in ("closed_count", "recent_rows", "last12_r", "winrate_pct", "ev_r", "pnl_r"):
        assert payload[key]
        assert float(payload[key]) == 0.0
    assert payload["last_close"] == "none"


def test_command_count_requires_pos_pnl_view() -> None:
    source = 'COMMANDS = {"/pos": 1, "/pnl": 2, "/view": 3}'
    assert module.command_count(source, ["/pos", "/pnl", "/view"]) >= 3


def test_zero_detection_accepts_numeric_strings_only() -> None:
    assert module.as_zero("0")
    assert module.as_zero(0.0)
    assert not module.as_zero("7.25")
    assert not module.as_zero(None)


def test_first_uses_primary_key_order() -> None:
    payload = {"closed": "68", "closed_count": "0"}
    assert module.first(payload, "closed_count", "closed") == "0"
