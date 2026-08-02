from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_DATA_B_1M_V2_RECOVERY_RECEIPT_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def latest_legacy_run(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get("name") == "ZEL Data B 1m Single Owner Repair V1"]
    candidates.sort(key=lambda row: str(row.get("startedAt") or row.get("createdAt") or ""), reverse=True)
    return candidates[0] if candidates else None


def classify(run: dict[str, Any] | None, remote: dict[str, Any]) -> tuple[str, list[str]]:
    evidence: list[str] = []
    if run:
        evidence.append(f"actions_conclusion={run.get('conclusion')}")
        evidence.append(f"actions_duration_sec={run.get('duration_sec')}")
    evidence.append(f"kernel_oom_detected={remote.get('kernel_oom_detected')}")
    evidence.append(f"host_reboot_detected={remote.get('host_reboot_detected')}")
    evidence.append(f"legacy_process_count={remote.get('legacy_process_count')}")
    evidence.append(f"terminal_artifact_count={remote.get('terminal_artifact_count')}")

    if remote.get("kernel_oom_detected") is True:
        return "KERNEL_OOM_KILLED_REPLAY", evidence
    if remote.get("host_reboot_detected") is True:
        return "HOST_REBOOT_INTERRUPTED_REPLAY", evidence
    conclusion = str((run or {}).get("conclusion") or "").lower()
    duration = int((run or {}).get("duration_sec") or 0)
    if conclusion in {"timed_out", "cancelled"} and duration >= 410 * 60:
        return "GITHUB_ACTIONS_420M_TIMEOUT_TERMINATED_ATTACHED_SSH_REPLAY", evidence
    if conclusion == "timed_out":
        return "GITHUB_ACTIONS_TIMEOUT_TERMINATED_ATTACHED_SSH_REPLAY", evidence
    if remote.get("legacy_process_count") == 0 and remote.get("terminal_artifact_count") == 0:
        return "UNPROVED_ABRUPT_PROCESS_EXIT_NO_TERMINAL", evidence
    return "UNPROVED", evidence


def build(actions_rows: list[dict[str, Any]], remote: dict[str, Any], recovery: dict[str, Any]) -> dict[str, Any]:
    run = latest_legacy_run(actions_rows)
    cause, evidence = classify(run, remote)
    recovered = recovery.get("v2_service_active") is True or recovery.get("terminal_complete") is True
    state = "PASS_V2_RECOVERY_STARTED" if recovered else "HOLD_V2_RECOVERY_NOT_ACTIVE"
    return {
        "schema_version": "zel.data_b.1m.v2_recovery.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "legacy_termination_cause": cause,
        "legacy_run": run,
        "cause_evidence": evidence,
        "remote_diagnostic": remote,
        "recovery": recovery,
        "active_data_b_1m_mutated": True,
        "canonical_strategy_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    rows = [{
        "name": "ZEL Data B 1m Single Owner Repair V1",
        "conclusion": "timed_out",
        "duration_sec": 420 * 60,
        "startedAt": "2026-08-01T20:00:00Z",
    }]
    remote = {
        "kernel_oom_detected": False,
        "host_reboot_detected": False,
        "legacy_process_count": 0,
        "terminal_artifact_count": 0,
    }
    recovery = {"v2_service_active": True, "terminal_complete": False}
    result = build(rows, remote, recovery)
    assert result["state"] == "PASS_V2_RECOVERY_STARTED", result
    assert result["legacy_termination_cause"] == "GITHUB_ACTIONS_420M_TIMEOUT_TERMINATED_ATTACHED_SSH_REPLAY", result
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "receipt.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        assert json.loads(path.read_text())["execution_authority"] == "NONE"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-runs", type=Path)
    parser.add_argument("--remote-diagnostic", type=Path)
    parser.add_argument("--recovery-status", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.actions_runs, args.remote_diagnostic, args.recovery_status, args.out)):
        parser.error("actions-runs, remote-diagnostic, recovery-status and out are required")
    actions_rows = json.loads(args.actions_runs.read_text())
    remote = json.loads(args.remote_diagnostic.read_text())
    recovery = json.loads(args.recovery_status.read_text())
    result = build(actions_rows, remote, recovery)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": result["state"], "cause": result["legacy_termination_cause"]}, sort_keys=True))
    return 0 if result["state"] == "PASS_V2_RECOVERY_STARTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
