from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGET_100C = 100
TARGET_200C = 200


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def run(args: argparse.Namespace) -> int:
    pre100 = load_json(args.pre100_status, {})
    checkpoint = load_json(args.checkpoint_status, {})
    storage = load_json(args.storage_status, {})
    closed_count = jsonl_count(args.formal_ledger)

    issues: list[dict[str, Any]] = []
    if pre100.get("state") != "PASS":
        issues.append({"code": "PRE100_INTEGRITY_NOT_PASS", "severity": "C", "detail": str(pre100.get("verdict"))})
    if pre100.get("integrity_gate_locked") is not False:
        issues.append({"code": "INTEGRITY_GATE_LOCKED", "severity": "C", "detail": str(pre100.get("critical_count"))})
    if int(pre100.get("violation_count") or 0) != 0:
        issues.append({"code": "PRE100_VIOLATIONS_PRESENT", "severity": "C", "detail": str(pre100.get("violation_count"))})
    if checkpoint.get("state") != "PASS":
        issues.append({"code": "100C_CHECKPOINT_NOT_PASS", "severity": "C", "detail": str(checkpoint.get("verdict"))})
    if storage.get("state") != "PASS" or storage.get("verdict") != "STORAGE_REGROWTH_GUARD_HEALTHY":
        issues.append({"code": "STORAGE_GUARD_NOT_HEALTHY", "severity": "C", "detail": str(storage.get("verdict"))})

    critical = any(item["severity"] == "C" for item in issues)
    if critical:
        state = "HOLD"
        phase = "AUTO_PROGRESS_BLOCKED"
        verdict = "EXACT25_AUTO_PROGRESS_TO_200C_BLOCKED"
    elif closed_count < TARGET_100C:
        state = "PASS"
        phase = "ACCUMULATING_TO_100C"
        verdict = "EXACT25_AUTO_PROGRESS_ARMED_TO_100C"
    elif closed_count < TARGET_200C:
        state = "PASS"
        phase = "AUTO_CONTINUE_100C_TO_200C"
        verdict = "EXACT25_AUTO_PROGRESS_CONTINUING_TO_200C"
    else:
        state = "PASS"
        phase = "200C_REACHED"
        verdict = "EXACT25_200C_REACHED_MIDPOINT_AUDIT_REQUIRED"

    payload = {
        "schema": "q4r3_exact25_auto_progress_to_200c_status_v1",
        "generated_at": now_iso(),
        "state": state,
        "phase": phase,
        "verdict": verdict,
        "current_closed_count": closed_count,
        "target_100c": TARGET_100C,
        "target_200c": TARGET_200C,
        "remaining_to_100c": max(0, TARGET_100C - closed_count),
        "remaining_to_200c": max(0, TARGET_200C - closed_count),
        "auto_continue_enabled": not critical,
        "producer_stop_requested": False,
        "writer_stop_requested": False,
        "deep_audit_auto_mutation_enabled": False,
        "ranking_enabled": False,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "observer_only": True,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "violation_count": len(issues),
        "violations": issues,
        "action": "hold",
    }
    atomic_json(args.status, payload)
    atomic_json(args.violations, {
        "schema": "q4r3_exact25_auto_progress_to_200c_violations_v1",
        "generated_at": now_iso(),
        "state": "VIOLATION" if issues else "CLEAR",
        "count": len(issues),
        "severity": "C" if critical else None,
        "notify": critical,
        "violations": issues,
        "action": "hold",
    })
    return 0 if state == "PASS" else 2


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--formal-ledger", type=Path, required=True)
    p.add_argument("--pre100-status", type=Path, required=True)
    p.add_argument("--checkpoint-status", type=Path, required=True)
    p.add_argument("--storage-status", type=Path, required=True)
    p.add_argument("--status", type=Path, required=True)
    p.add_argument("--violations", type=Path, required=True)
    return p


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
