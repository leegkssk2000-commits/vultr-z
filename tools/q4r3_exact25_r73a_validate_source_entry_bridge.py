#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.engine.exact25_r73a_source_entry_bridge import build_lane_events


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def contract_errors(contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    auth = contract.get("authority", {})
    deps = contract.get("dependencies", {})
    if contract.get("schema") != "zos_exact25_r73a_source_entry_bridge_v1":
        errors.append("CONTRACT_SCHEMA_INVALID")
    if contract.get("official_stage") != "R7.3A":
        errors.append("CONTRACT_STAGE_INVALID")
    if auth.get("observer_only") is not True:
        errors.append("OBSERVER_ONLY_REQUIRED")
    for key in (
        "runtime_binding_allowed", "source_event_subscription_allowed", "source_ack_allowed",
        "projection_state_write_allowed", "producer_mutation_allowed", "writer_mutation_allowed",
        "formal_ledger_mutation_allowed", "provider_invocation_enabled", "network_call_enabled",
        "paper_enabled", "live_enabled", "order_enabled", "automatic_promotion_enabled",
    ):
        if auth.get(key) is not False:
            errors.append("AUTHORITY_INVALID:" + key)
    if auth.get("order_authority") != "blocked" or auth.get("execution_authority") != "none":
        errors.append("AUTHORITY_BOUNDARY_INVALID")
    if (deps.get("strategy_count"), deps.get("exit_policy_count"), deps.get("lane_template_count")) != (25, 4, 100):
        errors.append("DEPENDENCY_COUNTS_INVALID")
    if deps.get("raw_skill_set_required") != []:
        errors.append("RAW_SKILL_SET_INVALID")
    return errors


def fixture(projection: Mapping[str, Any]) -> dict[str, Any]:
    first = projection.get("templates", [])[0]
    return {
        "source_event_id": "r73a.fixture.entry.001",
        "source_position_id": "r73a.fixture.position.001",
        "source_sequence": 1,
        "strategy_id": first["strategy_id"],
        "strategy_source_sha256": projection["exact25_manifest_sha256"],
        "method_id": "r73a.fixture.method",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_ts_ms": 1800000000000,
        "observed_at_ms": 1800000001000,
        "entry_price": 100000.0,
        "market_path_id": "r73a.fixture.market.001",
        "cost_model_ref": first["cost_model_ref"],
        "source_ref": "runtime:r73a.fixture",
    }


def fail_closed_count(source: dict[str, Any], projection: dict[str, Any]) -> int:
    cases: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    bad = copy.deepcopy(source); bad["source_event_id"] = ""; cases.append((bad, projection, "SOURCE_FIELD_MISSING:source_event_id"))
    bad = copy.deepcopy(source); bad["side"] = "flat"; cases.append((bad, projection, "SOURCE_SIDE_INVALID"))
    bad = copy.deepcopy(source); bad["entry_price"] = 0; cases.append((bad, projection, "ENTRY_PRICE_INVALID"))
    bad = copy.deepcopy(source); bad["source_sequence"] = -1; cases.append((bad, projection, "SOURCE_SEQUENCE_INVALID"))
    bad = copy.deepcopy(source); bad["strategy_source_sha256"] = ""; cases.append((bad, projection, "SOURCE_FIELD_MISSING:strategy_source_sha256"))
    bad = copy.deepcopy(source); bad["strategy_source_sha256"] = "sha256:bad"; cases.append((bad, projection, "STRATEGY_DIGEST_INVALID"))
    bad = copy.deepcopy(source); bad["observed_at_ms"] = bad["entry_ts_ms"] + 300001; cases.append((bad, projection, "SOURCE_ENTRY_STALE"))
    bad = copy.deepcopy(source); bad["source_ref"] = "unknown:fixture"; cases.append((bad, projection, "SOURCE_REF_INVALID"))
    bad = copy.deepcopy(source); bad["strategy_id"] = "unknown"; cases.append((bad, projection, "FOUR_EXIT_TEMPLATES_NOT_FOUND"))
    contaminated = copy.deepcopy(projection); contaminated["templates"][0]["skill_set"] = ["SK_EXIT_PARTIAL_30"]
    cases.append((source, contaminated, "RAW_SKILL_CONTAMINATION"))
    bad = copy.deepcopy(source); bad["cost_model_ref"] = "other"; cases.append((bad, projection, "COST_MODEL_MISMATCH"))
    return sum(expected in build_lane_events(src, proj)["reason_codes"] for src, proj, expected in cases)


def validate(contract_path: Path, r72_path: Path, projection_path: Path, bridge_output: Path) -> dict[str, Any]:
    contract = read_json(contract_path)
    r72 = read_json(r72_path)
    projection = read_json(projection_path)
    blockers = contract_errors(contract)
    if r72.get("state") != "PASS" or r72.get("blockers"):
        blockers.append("R72_PASS_NOT_PROVEN")
    report = r72.get("report", {})
    if report.get("lane_template_count") != 100 or report.get("projection_sha256") != projection.get("projection_sha256"):
        blockers.append("R72_PROJECTION_PARITY_INVALID")
    if projection.get("state") != "PROJECTION_READY" or projection.get("lane_template_count") != 100:
        blockers.append("R72_PROJECTION_NOT_READY")
    if projection.get("runtime_active") is not False or projection.get("source_event_subscription_allowed") is not False:
        blockers.append("R72_RUNTIME_BOUNDARY_OPEN")
    if projection.get("formal_ledger_write_allowed") is not False:
        blockers.append("R72_LEDGER_WRITE_OPEN")
    source = fixture(projection) if projection.get("templates") else {}
    result = build_lane_events(source, projection) if source else {"state": "HOLD", "lane_event_count": 0, "lane_events": []}
    if result.get("state") != "BRIDGE_READY" or result.get("lane_event_count") != 4:
        blockers.append("SOURCE_TO_FOUR_LANE_BRIDGE_NOT_READY")
    rows = result.get("lane_events", [])
    for key in ("lane_event_id", "lane_position_id", "state_namespace", "cooldown_namespace"):
        values = [row.get(key) for row in rows]
        if len(values) != len(set(values)):
            blockers.append("LANE_ISOLATION_INVALID:" + key)
    failed_closed = fail_closed_count(source, projection) if source else 0
    if failed_closed != 11:
        blockers.append("FAIL_CLOSED_SCENARIOS_INCOMPLETE")
    atomic_json(bridge_output, result)
    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": "q4r3_exact25_r73a_source_entry_bridge_prebind_v1",
        "official_stage": "R7.3A",
        "state": state,
        "verdict": "R73A_SOURCE_ENTRY_BRIDGE_PREBIND_PASS" if state == "PASS" else "R73A_SOURCE_ENTRY_BRIDGE_PREBIND_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "runtime_binding_allowed": False,
            "source_event_subscription_allowed": False,
            "source_ack_allowed": False,
            "projection_state_write_allowed": False,
            "producer_mutation_performed": False,
            "writer_mutation_performed": False,
            "formal_ledger_mutation_performed": False,
            "provider_invocation_enabled": False,
            "network_call_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none"
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "source_fixture_count": 1,
            "lane_event_count": result.get("lane_event_count", 0),
            "exit_policy_coverage_count": len({row.get("exit_policy_id") for row in rows}),
            "fail_closed_scenario_count": failed_closed,
            "bridge_sha256": result.get("bridge_sha256", ""),
            "runtime_active": False,
            "source_event_subscription_active": False,
            "next_route": "R7.3B_ZERO_TO_ONE_C_SIDECAR_SMOKE"
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--r72", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--bridge-output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.contract, args.r72, args.projection, args.bridge_output)
    atomic_json(args.status_output, payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "source_fixture_count": payload["report"]["source_fixture_count"],
        "lane_event_count": payload["report"]["lane_event_count"],
        "exit_policy_coverage_count": payload["report"]["exit_policy_coverage_count"],
        "fail_closed_scenario_count": payload["report"]["fail_closed_scenario_count"],
        "runtime_active": payload["report"]["runtime_active"]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
