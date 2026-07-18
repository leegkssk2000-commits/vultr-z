from __future__ import annotations

import importlib.util
from pathlib import Path

TARGET = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4s3_alimi_telegram_binding_plan.py"
SPEC = importlib.util.spec_from_file_location("r73b4s3", TARGET)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

CONTRACT = {
    "display_adapter": {
        "planned_unit": "zel-q4r3-exact25-display-adapter.service",
        "planned_script": "/usr/local/bin/zel_q4r3_exact25_display_adapter.py",
        "runtime_enabled_now": False,
        "input_count": 1,
        "output_count": 2,
        "alimi_output": "/var/www/z-os-alimi/api/q4r3_exact25_shadow_view_contract_latest.json",
        "telegram_output": "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json",
    },
    "alimi_binding": {
        "caddy_path": "/etc/caddy/Caddyfile",
        "insert_before": "handle_path /api/* {",
        "public_endpoint": "/api/view_contract_latest.json",
        "route_marker": "Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_BEGIN",
        "route_lines": ["route"],
    },
    "telegram_binding": {
        "unit": "zel-q4r3-telegram-pos-adapter-v2.service",
        "source_path": "/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py",
        "required_commands": ["/pos", "/pnl", "/view"],
        "planned_source": "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json",
        "patch_mode": "prefer_exact25_snapshot_artifact_preserve_existing_command_handlers",
    },
    "forbidden_sources": ["forward_r_ledger.jsonl", "q4r3_shadow_closed_ledger_latest.json", "telegram_pos_status_latest.json"],
    "next_stage": "R7.3B4T_EXPLICIT_BINDING_CANARY",
}
SNAPSHOT = {"sample_count": 0, "closed_count": 0, "runtime_active": False, "formal_ledger_bound": False, "snapshot_sha256": "a" * 64}
PARENT = {"origin_mode": "ENDPOINT_ONLY", "selected_endpoint": {"http_status": 200, "canonical_json_sha256": "b" * 64, "metrics": {"closed_count": 68, "pnl_r": 53.613052}}}
CADDY = "alimi.z-os.vip {\n    handle_path /api/* {\n        root * /var/www/z-os-alimi/api\n    }\n}"
TELEGRAM = "def handler(cmd):\n    # /pos /pnl /view\n    return cmd\n"


def test_complete_plan_passes() -> None:
    payload = module.build(CONTRACT, SNAPSHOT, PARENT, CADDY, TELEGRAM)
    assert payload["state"] == "PASS"
    assert payload["planned_adapter_count"] == 1
    assert payload["planned_output_count"] == 2
    assert payload["rollback_ready_count"] == 2
    assert payload["mutation_count"] == 0


def test_missing_caddy_anchor_holds() -> None:
    payload = module.build(CONTRACT, SNAPSHOT, PARENT, "alimi.z-os.vip {}", TELEGRAM)
    assert payload["state"] == "HOLD"
    assert "CADDY_API_ANCHOR_COUNT_INVALID" in payload["blockers"]


def test_missing_telegram_command_holds() -> None:
    payload = module.build(CONTRACT, SNAPSHOT, PARENT, CADDY, "/pos /view")
    assert payload["state"] == "HOLD"
    assert "TELEGRAM_COMMAND_ANCHOR_MISSING" in payload["blockers"]


def test_nonzero_snapshot_holds() -> None:
    payload = module.build(CONTRACT, dict(SNAPSHOT, closed_count=1), PARENT, CADDY, TELEGRAM)
    assert payload["state"] == "HOLD"
    assert "SNAPSHOT_NOT_ZERO_EPOCH" in payload["blockers"]
