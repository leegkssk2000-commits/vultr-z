from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

UTC = timezone.utc
TARGET_100C = 100
TARGET_200C = 200


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def nonblank_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def prefix_sha256(lines: list[str], count: int) -> str:
    selected = lines[:count]
    payload = ("\n".join(selected) + ("\n" if selected else "")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def observer_ok(name: str, payload: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
    if payload.get("state") != "PASS":
        issues.append({"code": "UPSTREAM_NOT_PASS", "severity": "C", "source": name, "detail": str(payload.get("verdict"))})
    if payload.get("observer_only") is not True:
        issues.append({"code": "UPSTREAM_NOT_OBSERVER_ONLY", "severity": "C", "source": name, "detail": str(payload.get("observer_only"))})
    for key in (
        "strategy_modified",
        "trade_method_modified",
        "skill_registry_modified",
        "producer_modified",
        "writer_modified",
        "formal_ledger_modified",
    ):
        if key in payload and payload.get(key) is not False:
            issues.append({"code": "UPSTREAM_MUTATION_FLAG", "severity": "C", "source": name, "detail": f"{key}={payload.get(key)}"})


def snapshot_payload(
    *,
    checkpoint: int,
    ledger_lines: list[str],
    source_paths: Mapping[str, Path],
    status_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "q4r3_exact25_auto_progress_checkpoint_snapshot_v1",
        "checkpoint_closed_count": checkpoint,
        "captured_at": now_iso(),
        "ledger_prefix_rows": checkpoint,
        "ledger_prefix_sha256": prefix_sha256(ledger_lines, checkpoint),
        "source_hashes": {name: file_sha256(path) for name, path in source_paths.items()},
        "source_verdicts": {name: payload.get("verdict") for name, payload in status_payloads.items()},
        "observer_only": True,
        "historical_backfill_performed": False,
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
        "action": "hold",
    }


def ensure_snapshot(
    path: Path,
    *,
    checkpoint: int,
    ledger_lines: list[str],
    source_paths: Mapping[str, Path],
    status_payloads: Mapping[str, Mapping[str, Any]],
    issues: list[dict[str, Any]],
) -> bool:
    expected_hash = prefix_sha256(ledger_lines, checkpoint)
    existing = load_json(path, None)
    if isinstance(existing, dict):
        if existing.get("checkpoint_closed_count") != checkpoint or existing.get("ledger_prefix_sha256") != expected_hash:
            issues.append({
                "code": "CHECKPOINT_SNAPSHOT_PREFIX_MISMATCH",
                "severity": "C",
                "source": str(path),
                "detail": f"checkpoint={checkpoint}",
            })
            return False
        return True
    atomic_json(
        path,
        snapshot_payload(
            checkpoint=checkpoint,
            ledger_lines=ledger_lines,
            source_paths=source_paths,
            status_payloads=status_payloads,
        ),
    )
    return True


def evaluate(
    *,
    ledger_lines: list[str],
    storage: Mapping[str, Any],
    checkpoint_100: Mapping[str, Any],
    integrity: Mapping[str, Any],
    trigger: Mapping[str, Any],
    projection: Mapping[str, Any],
    pair: Mapping[str, Any],
    risk: Mapping[str, Any],
    scoreboard: Mapping[str, Any],
    snapshot_100_path: Path,
    snapshot_200_path: Path,
    source_paths: Mapping[str, Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    statuses = {
        "checkpoint_100c": checkpoint_100,
        "pre100_integrity": integrity,
        "skill_trigger_lineage": trigger,
        "six_profile_projection": projection,
        "future_pair_join": pair,
        "risk_scenario_grid": risk,
        "method_scoreboard": scoreboard,
    }

    if storage.get("state") != "PASS" or storage.get("verdict") != "STORAGE_REGROWTH_GUARD_HEALTHY":
        issues.append({"code": "STORAGE_GUARD_NOT_HEALTHY", "severity": "C", "source": "storage", "detail": str(storage.get("verdict"))})

    for name, payload in statuses.items():
        observer_ok(name, payload, issues)

    closed_count = len(ledger_lines)
    integrity_current = int(integrity.get("current_closed_count") or 0)
    checkpoint_current = int(checkpoint_100.get("current_closed_count") or 0)
    integrity_clean = (
        integrity.get("state") == "PASS"
        and int(integrity.get("critical_count") or 0) == 0
        and int(integrity.get("major_count") or 0) == 0
        and integrity.get("integrity_gate_locked") is False
        and float(integrity.get("lineage_coverage_pct") or 0.0) >= 100.0
    )

    snapshot_100_ready = snapshot_100_path.exists()
    snapshot_200_ready = snapshot_200_path.exists()
    stage = "ACCUMULATING_TO_100C"
    verdict = "AUTO_PROGRESS_TO_100C_ACCUMULATING"

    if closed_count >= TARGET_100C:
        if checkpoint_current < TARGET_100C or integrity_current < TARGET_100C:
            stage = "WAITING_100C_OBSERVER_REFRESH"
            verdict = "AUTO_PROGRESS_WAITING_100C_OBSERVER_REFRESH"
        elif not integrity_clean:
            stage = "LOCKED_AT_100C_INTEGRITY_GATE"
            verdict = "AUTO_PROGRESS_100C_INTEGRITY_GATE_LOCKED"
        elif not any(row["severity"] == "C" for row in issues):
            snapshot_100_ready = ensure_snapshot(
                snapshot_100_path,
                checkpoint=TARGET_100C,
                ledger_lines=ledger_lines,
                source_paths=source_paths,
                status_payloads=statuses,
                issues=issues,
            )
            if closed_count < TARGET_200C:
                stage = "ACCUMULATING_100C_TO_200C"
                verdict = "AUTO_PROGRESS_100C_GATE_PASS_ACCUMULATING_TO_200C"
            else:
                snapshot_200_ready = ensure_snapshot(
                    snapshot_200_path,
                    checkpoint=TARGET_200C,
                    ledger_lines=ledger_lines,
                    source_paths=source_paths,
                    status_payloads=statuses,
                    issues=issues,
                )
                stage = "REACHED_200C"
                verdict = "AUTO_PROGRESS_200C_REACHED_MIDPOINT_AUDIT_REQUIRED"

    critical_count = sum(row["severity"] == "C" for row in issues)
    state = "HOLD" if critical_count else "PASS"
    if critical_count:
        stage = "LOCKED_CRITICAL"
        verdict = "AUTO_PROGRESS_CRITICAL_GAP"

    status = {
        "schema": "q4r3_exact25_auto_progress_200c_status_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "stage": stage,
        "automatic_progress_enabled": True,
        "producer_stop_at_100c": False,
        "producer_stop_at_200c": False,
        "current_closed_count": closed_count,
        "target_100c": TARGET_100C,
        "target_200c": TARGET_200C,
        "remaining_to_100c": max(0, TARGET_100C - closed_count),
        "remaining_to_200c": max(0, TARGET_200C - closed_count),
        "checkpoint_100_status_count": checkpoint_current,
        "integrity_status_count": integrity_current,
        "integrity_clean": integrity_clean,
        "snapshot_100_ready": snapshot_100_ready,
        "snapshot_200_ready": snapshot_200_ready,
        "skill_triggered_count": int(trigger.get("skill_triggered_count") or 0),
        "skill_blocked_count": int(trigger.get("skill_blocked_count") or 0),
        "close_outcome_joined_count": int(trigger.get("close_outcome_joined_count") or 0),
        "exact_pair_count": int(pair.get("exact_pair_count") or 0),
        "violation_count": len(issues),
        "critical_count": critical_count,
        "observer_only": True,
        "automatic_patch_allowed": False,
        "ranking_enabled": False,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "historical_backfill_performed": False,
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
        "action": "hold",
    }
    violations = {
        "schema": "q4r3_exact25_auto_progress_200c_violations_v1",
        "generated_at": now_iso(),
        "state": "VIOLATION" if issues else "CLEAR",
        "count": len(issues),
        "severity": "C" if critical_count else None,
        "notify": bool(critical_count),
        "violations": issues,
        "action": "hold",
    }
    return status, violations


def run(args: argparse.Namespace) -> int:
    ledger_lines = nonblank_lines(args.formal_ledger)
    paths = {
        "storage": args.storage_status,
        "checkpoint_100c": args.checkpoint_100_status,
        "pre100_integrity": args.integrity_status,
        "skill_trigger_lineage": args.trigger_status,
        "six_profile_projection": args.projection_status,
        "future_pair_join": args.pair_status,
        "risk_scenario_grid": args.risk_status,
        "method_scoreboard": args.scoreboard_status,
    }
    payloads = {name: load_json(path, {}) for name, path in paths.items()}
    status, violations = evaluate(
        ledger_lines=ledger_lines,
        storage=payloads["storage"],
        checkpoint_100=payloads["checkpoint_100c"],
        integrity=payloads["pre100_integrity"],
        trigger=payloads["skill_trigger_lineage"],
        projection=payloads["six_profile_projection"],
        pair=payloads["future_pair_join"],
        risk=payloads["risk_scenario_grid"],
        scoreboard=payloads["method_scoreboard"],
        snapshot_100_path=args.snapshot_100,
        snapshot_200_path=args.snapshot_200,
        source_paths=paths,
    )
    atomic_json(args.status, status)
    atomic_json(args.violations, violations)
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0 if status["state"] == "PASS" else 2


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--formal-ledger", type=Path, required=True)
    p.add_argument("--storage-status", type=Path, required=True)
    p.add_argument("--checkpoint-100-status", type=Path, required=True)
    p.add_argument("--integrity-status", type=Path, required=True)
    p.add_argument("--trigger-status", type=Path, required=True)
    p.add_argument("--projection-status", type=Path, required=True)
    p.add_argument("--pair-status", type=Path, required=True)
    p.add_argument("--risk-status", type=Path, required=True)
    p.add_argument("--scoreboard-status", type=Path, required=True)
    p.add_argument("--snapshot-100", type=Path, required=True)
    p.add_argument("--snapshot-200", type=Path, required=True)
    p.add_argument("--status", type=Path, required=True)
    p.add_argument("--violations", type=Path, required=True)
    return p


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
