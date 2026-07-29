from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_self_healing_operations_contract_v1 import (
    SelfHealingContractError,
    evaluate_operations,
    stable_sha,
)

VERSION = "STRATEGY11_SELF_HEALING_FIXTURE_V1"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def base_snapshot(policy_sha: str) -> dict[str, Any]:
    source_sha = "a" * 64
    return {
        "now_ms": 200000,
        "source_binding": {
            "source_sha": source_sha,
            "data_sha": "b" * 64,
            "policy_sha": policy_sha,
            "run_id": "fixture-run-self-healing-001",
            "artifact_id": "fixture-artifact-self-healing-001",
        },
        "writers": [
            {"domain": "STATE", "writer_id": "state-writer-1", "active": True},
            {"domain": "LEDGER", "writer_id": "ledger-writer-1", "active": True},
            {"domain": "DISPLAY", "writer_id": "display-writer-1", "active": True},
        ],
        "components": [
            {
                "component_id": "collector",
                "heartbeat_ts_ms": 190000,
                "data_ts_ms": 180000,
                "service_state": "ACTIVE",
                "timer_active": True,
                "expected_source_sha": source_sha,
                "observed_source_sha": source_sha,
            },
            {
                "component_id": "ledger_projection",
                "heartbeat_ts_ms": 192000,
                "data_ts_ms": 185000,
                "service_state": "ACTIVE",
                "timer_active": True,
                "expected_source_sha": source_sha,
                "observed_source_sha": source_sha,
            },
            {
                "component_id": "display_projection",
                "heartbeat_ts_ms": 191000,
                "data_ts_ms": 184000,
                "service_state": "ACTIVE",
                "timer_active": True,
                "expected_source_sha": source_sha,
                "observed_source_sha": source_sha,
            },
        ],
        "parity_checks": [
            {"name": "STATE_LEDGER_POSITION", "expected_sha": "c" * 64, "observed_sha": "c" * 64},
            {"name": "LEDGER_PNL_CLOSED", "expected_sha": "d" * 64, "observed_sha": "d" * 64},
            {"name": "PNL_DISPLAY_SUMMARY", "expected_sha": "e" * 64, "observed_sha": "e" * 64},
        ],
        "last_good_snapshot": {
            "snapshot_sha": "f" * 64,
            "compile_ok": True,
            "verified": True,
        },
        "authority": {
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        },
        "incidents": [
            {"fingerprint": "fp:collector:stale:001", "severity": "m", "required_action": "hold"},
            {"fingerprint": "fp:collector:stale:001", "severity": "m", "required_action": "hold"},
        ],
    }


def expect_error(name: str, fn: Any, prefix: str) -> dict[str, Any]:
    try:
        fn()
    except SelfHealingContractError as exc:
        message = str(exc)
        if not message.startswith(prefix):
            raise AssertionError(f"{name}:{message}:{prefix}") from exc
        return {"name": name, "state": "PASS_EXPECTED_ERROR", "error": message}
    raise AssertionError(f"{name}:EXPECTED_ERROR_NOT_RAISED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    snapshot = base_snapshot(str(policy["policy_sha"]))

    healthy = evaluate_operations(snapshot, policy)
    assert healthy["state"] == "PASS_SELF_HEALING_OBSERVER"
    assert healthy["action"] == "hold"
    assert healthy["blockers"] == []
    assert healthy["metrics"]["incident_duplicate_count"] == 1

    duplicate_writer_input = deepcopy(snapshot)
    duplicate_writer_input["writers"].append({"domain": "LEDGER", "writer_id": "ledger-writer-2", "active": True})
    duplicate_writer = evaluate_operations(duplicate_writer_input, policy)
    assert duplicate_writer["state"] == "BLOCK_SELF_HEALING_AUTHORITY"
    assert duplicate_writer["action"] == "block"
    assert duplicate_writer["blockers"] == ["MULTIPLE_ACTIVE_WRITERS:LEDGER"]

    parity_input = deepcopy(snapshot)
    parity_input["parity_checks"][1]["observed_sha"] = "1" * 64
    parity = evaluate_operations(parity_input, policy)
    assert parity["state"] == "HOLD_SELF_HEALING_OPERATIONS"
    assert parity["blockers"] == ["PARITY_MISMATCH:LEDGER_PNL_CLOSED"]

    service_input = deepcopy(snapshot)
    service_input["components"][0]["service_state"] = "FAILED"
    service_input["components"][0]["timer_active"] = False
    service = evaluate_operations(service_input, policy)
    assert service["state"] == "ROLLBACK_REQUEST_SELF_HEALING"
    assert service["action"] == "rollback"
    assert service["recovery_requests"][0]["execute_allowed"] is False
    assert service["recovery_requests"][0]["failed_components"] == ["collector"]

    authority_input = deepcopy(snapshot)
    authority_input["authority"] = {
        "protected_mutations": 1,
        "execution_allowed": True,
        "order_authority": "OPEN",
    }
    authority = evaluate_operations(authority_input, policy)
    assert authority["state"] == "BLOCK_SELF_HEALING_AUTHORITY"
    assert authority["action"] == "block"
    assert set(authority["blockers"]) == {
        "EXECUTION_AUTHORITY_ANOMALY", "ORDER_AUTHORITY_ANOMALY", "PROTECTED_MUTATION_DETECTED"
    }

    tampered_policy = deepcopy(policy)
    tampered_policy["max_data_age_ms"] = 999999
    policy_error = expect_error(
        "POLICY_SHA_TAMPER",
        lambda: evaluate_operations(snapshot, tampered_policy),
        "POLICY_SHA_MISMATCH",
    )

    summary = {
        "schema_version": "strategy11.self_healing_fixture.v1",
        "version": VERSION,
        "state": "PASS_SELF_HEALING_OPERATIONS_FIXTURES",
        "case_count": 6,
        "policy_sha": policy["policy_sha"],
        "healthy": healthy,
        "duplicate_writer_block": duplicate_writer,
        "parity_hold": parity,
        "service_rollback_request": service,
        "authority_block": authority,
        "negative_cases": [policy_error],
        "runtime_activation_allowed": False,
        "automatic_recovery_execute_allowed": False,
        "service_mutation_allowed": False,
        "ledger_mutation_allowed": False,
        "writer_reassignment_allowed": False,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    summary["fixture_sha"] = stable_sha(summary)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "summary.json", summary)
    atomic_json(args.out / "healthy.json", healthy)
    atomic_json(args.out / "duplicate_writer_block.json", duplicate_writer)
    atomic_json(args.out / "service_rollback_request.json", service)
    print(summary["state"], summary["case_count"], healthy["metrics"]["incident_duplicate_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
