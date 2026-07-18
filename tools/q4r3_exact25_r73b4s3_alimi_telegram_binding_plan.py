#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(contract: dict[str, Any], snapshot: dict[str, Any], parent: dict[str, Any], caddy_text: str, telegram_text: str) -> dict[str, Any]:
    blockers: list[str] = []
    if snapshot.get("sample_count") != 0 or snapshot.get("closed_count") != 0:
        blockers.append("SNAPSHOT_NOT_ZERO_EPOCH")
    if snapshot.get("runtime_active") is not False or snapshot.get("formal_ledger_bound") is not False:
        blockers.append("SNAPSHOT_AUTHORITY_INVALID")
    selected = parent.get("selected_endpoint", {})
    metrics = selected.get("metrics", {})
    if selected.get("http_status") != 200 or parent.get("origin_mode") != "ENDPOINT_ONLY":
        blockers.append("R73B4S2_ENDPOINT_ORIGIN_INVALID")
    if metrics.get("closed_count") != 68 or metrics.get("pnl_r") != 53.613052:
        blockers.append("LEGACY_68C_ENDPOINT_NOT_CONFIRMED")
    alimi = contract["alimi_binding"]
    telegram = contract["telegram_binding"]
    anchor = alimi["insert_before"]
    anchor_count = caddy_text.count(anchor)
    if anchor_count != 1:
        blockers.append("CADDY_API_ANCHOR_COUNT_INVALID")
    if alimi["route_marker"] in caddy_text:
        blockers.append("CADDY_ROUTE_ALREADY_PRESENT")
    command_hits = {command: telegram_text.count(command) for command in telegram["required_commands"]}
    if any(count == 0 for count in command_hits.values()):
        blockers.append("TELEGRAM_COMMAND_ANCHOR_MISSING")
    forbidden_hits: dict[str, list[str]] = {}
    for source in contract["forbidden_sources"]:
        hits = []
        if source in caddy_text:
            hits.append("caddy")
        if source in telegram_text:
            hits.append("telegram")
        forbidden_hits[source] = hits
    plan = {
        "schema": "q4r3_exact25_r73b4s3_alimi_telegram_binding_plan_status_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "read_only": True,
        "mutation_count": 0,
        "source_snapshot_count": 1,
        "source_snapshot_sha256": snapshot.get("snapshot_sha256"),
        "legacy_endpoint": {
            "origin_mode": parent.get("origin_mode"),
            "http_status": selected.get("http_status"),
            "closed_count": metrics.get("closed_count"),
            "pnl_r": metrics.get("pnl_r"),
            "canonical_json_sha256": selected.get("canonical_json_sha256")
        },
        "display_adapter": contract["display_adapter"],
        "alimi_plan": {
            "caddy_path": alimi["caddy_path"],
            "caddy_sha256_before": sha256_text(caddy_text),
            "insert_before": anchor,
            "anchor_count": anchor_count,
            "route_lines": alimi["route_lines"],
            "public_endpoint": alimi["public_endpoint"],
            "planned_artifact": contract["display_adapter"]["alimi_output"],
            "rollback": "restore exact caddy_sha256_before and reload Caddy only after validation"
        },
        "telegram_plan": {
            "unit": telegram["unit"],
            "source_path": telegram["source_path"],
            "source_sha256_before": sha256_text(telegram_text),
            "command_hits": command_hits,
            "command_count": sum(1 for value in command_hits.values() if value > 0),
            "planned_source": telegram["planned_source"],
            "patch_mode": telegram["patch_mode"],
            "rollback": "restore exact source_sha256_before and restart only the Telegram adapter"
        },
        "forbidden_hits": forbidden_hits,
        "planned_adapter_count": 1,
        "planned_output_count": 2,
        "rollback_ready_count": 2,
        "runtime_enabled": False,
        "telegram_send_performed": False,
        "shadow_activation_performed": False,
        "formal_ledger_write_performed": False,
        "next_stage": contract["next_stage"]
    }
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--telegram", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    parent = json.loads(args.parent.read_text(encoding="utf-8"))
    caddy_text = args.caddy.read_text(encoding="utf-8")
    telegram_text = args.telegram.read_text(encoding="utf-8")
    payload = build(contract, snapshot, parent, caddy_text, telegram_text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("state", "blocker_count", "planned_adapter_count", "planned_output_count", "rollback_ready_count", "mutation_count")}, sort_keys=True))
    return 0 if payload["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
