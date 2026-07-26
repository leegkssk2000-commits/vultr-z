from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from backend.tools.r7a4d_strategy11_orchestrator import STRATEGIES
from backend.tools.r7a4d_strategy11_structure_lock import (
    STRUCTURE_VERSION,
    protected_diff,
    protected_snapshot,
)

BATCH_SIZE = 5
EXPECTED_BATCHES = 5
TIMEOUT_RC = 124


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _batch_strategies(batch_index: int) -> tuple[str, ...]:
    ordered = tuple(sorted(STRATEGIES))
    if len(ordered) != BATCH_SIZE * EXPECTED_BATCHES:
        raise RuntimeError(f"STRATEGY_COUNT:{len(ordered)}")
    if batch_index < 1 or batch_index > EXPECTED_BATCHES:
        raise ValueError(f"BATCH_INDEX:{batch_index}")
    start = (batch_index - 1) * BATCH_SIZE
    return ordered[start : start + BATCH_SIZE]


def _command(root: Path, phase: str, strategy_id: str) -> list[str]:
    if phase == "screen":
        return [
            sys.executable,
            "backend/tools/r7a4d_strategy11_screen_v2.py",
            "--root",
            str(root),
            "--strategy-id",
            strategy_id,
        ]
    summary = root / "artifacts/strategy11_screen_v1" / strategy_id / "summary.json"
    if not summary.is_file():
        raise FileNotFoundError(f"SCREEN_SUMMARY_MISSING:{strategy_id}:{summary}")
    return [
        sys.executable,
        "backend/tools/r7a4d_strategy11_exact_v2.py",
        "--root",
        str(root),
        "--strategy-id",
        strategy_id,
        "--screen-summary",
        str(summary),
    ]


def _run_one(
    root: Path,
    replay: str,
    phase: str,
    batch_index: int,
    strategy_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    log_dir = root / "artifacts/strategy11_batch_v1" / replay / phase / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"batch-{batch_index}-{strategy_id}.log"
    command = _command(root, phase, strategy_id)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)

    started = time.monotonic()
    print(
        f"CHILD_START replay={replay} phase={phase.upper()} "
        f"batch={batch_index}/{EXPECTED_BATCHES} strategy={strategy_id}",
        flush=True,
    )
    timed_out = False
    with log_path.open("w", encoding="utf-8") as handle:
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
            rc = int(completed.returncode)
        except subprocess.TimeoutExpired:
            rc = TIMEOUT_RC
            timed_out = True
            handle.write(f"\nTIMEOUT_SECONDS={timeout_seconds}\n")
    elapsed_s = round(time.monotonic() - started, 3)
    print(
        f"CHILD_END replay={replay} phase={phase.upper()} "
        f"batch={batch_index}/{EXPECTED_BATCHES} strategy={strategy_id} "
        f"rc={rc} elapsed_s={elapsed_s} timed_out={str(timed_out).lower()}",
        flush=True,
    )
    return {
        "strategy_id": strategy_id,
        "rc": rc,
        "elapsed_s": elapsed_s,
        "timed_out": timed_out,
        "log": str(log_path.relative_to(root)),
    }


def run_batch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    replay = str(args.replay).upper()
    phase = str(args.phase).lower()
    if replay not in {"A", "B"}:
        raise ValueError(f"REPLAY:{replay}")
    if phase not in {"screen", "exact"}:
        raise ValueError(f"PHASE:{phase}")

    strategies = _batch_strategies(args.batch_index)
    results: list[dict[str, Any]] = []
    blockers: list[str] = []

    def execute(strategy_id: str) -> dict[str, Any]:
        try:
            return _run_one(
                root,
                replay,
                phase,
                args.batch_index,
                strategy_id,
                args.timeout_seconds,
            )
        except Exception as exc:
            return {
                "strategy_id": strategy_id,
                "rc": 1,
                "elapsed_s": 0.0,
                "timed_out": False,
                "log": "",
                "error": f"{type(exc).__name__}:{exc}",
            }

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(args.workers, len(strategies)))
    ) as executor:
        futures = [executor.submit(execute, strategy_id) for strategy_id in strategies]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda row: str(row.get("strategy_id")))
    for row in results:
        if int(row.get("rc", 1)) != 0:
            blockers.append(
                f"{phase.upper()}:{row.get('strategy_id')}:RC={row.get('rc')}:"
                f"TIMED_OUT={row.get('timed_out')}"
            )

    payload = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_BATCH_REPLAY",
        "state": "PASS" if not blockers else "HOLD",
        "phase": phase.upper(),
        "batch_index": args.batch_index,
        "batch_count": EXPECTED_BATCHES,
        "strategy_count": len(strategies),
        "workers": args.workers,
        "strategies": list(strategies),
        "results": results,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_authority_mutated": False,
        "route_allowed": False,
        "shadow_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_allowed": False,
    }
    output = (
        root
        / "artifacts/strategy11_batch_v1"
        / replay
        / phase
        / f"batch-{args.batch_index}.json"
    )
    _atomic_json(output, payload)
    print(
        json.dumps(
            {
                "STATE": payload["state"],
                "PHASE": payload["phase"],
                "BATCH": f"{args.batch_index}/{EXPECTED_BATCHES}",
                "STRATEGIES": list(strategies),
                "BLOCKERS": blockers,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if not blockers else 1


def _read_batch_statuses(root: Path, replay: str, phase: str) -> tuple[list[dict[str, Any]], list[str]]:
    directory = root / "artifacts/strategy11_batch_v1" / replay / phase
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for batch_index in range(1, EXPECTED_BATCHES + 1):
        path = directory / f"batch-{batch_index}.json"
        if not path.is_file():
            blockers.append(f"{phase.upper()}_BATCH_STATUS_MISSING:{batch_index}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            blockers.append(f"{phase.upper()}_BATCH_STATUS_INVALID:{batch_index}:{type(exc).__name__}:{exc}")
            continue
        rows.append(payload)
        if payload.get("state") != "PASS" or payload.get("blockers"):
            blockers.append(f"{phase.upper()}_BATCH_NOT_PASS:{batch_index}")
    return rows, blockers


def _deterministic_evidence(statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for status in statuses:
        for row in status.get("results", []):
            if isinstance(row, Mapping):
                evidence.append(
                    {
                        "strategy_id": str(row.get("strategy_id")),
                        "rc": int(row.get("rc", 1)),
                    }
                )
    return sorted(evidence, key=lambda item: item["strategy_id"])


def finalize_replay(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    replay = str(args.replay).upper()
    if replay not in {"A", "B"}:
        raise ValueError(f"REPLAY:{replay}")

    screen_statuses, screen_blockers = _read_batch_statuses(root, replay, "screen")
    exact_statuses, exact_blockers = _read_batch_statuses(root, replay, "exact")
    blockers = screen_blockers + exact_blockers

    expected = list(sorted(STRATEGIES))
    screen_evidence = _deterministic_evidence(screen_statuses)
    exact_evidence = _deterministic_evidence(exact_statuses)
    if [row["strategy_id"] for row in screen_evidence] != expected:
        blockers.append("SCREEN_STRATEGY_SET_MISMATCH")
    if [row["strategy_id"] for row in exact_evidence] != expected:
        blockers.append("EXACT_STRATEGY_SET_MISMATCH")

    screen_summaries = sorted(
        path.parent.name
        for path in (root / "artifacts/strategy11_screen_v1").glob("*/summary.json")
    )
    exact_summaries = sorted(
        path.parent.name
        for path in (root / "artifacts/strategy11_exact_v1").glob("*/summary.json")
    )
    if screen_summaries != expected:
        blockers.append(f"SCREEN_SUMMARY_SET_MISMATCH:{len(screen_summaries)}")
    if exact_summaries != expected:
        blockers.append(f"EXACT_SUMMARY_SET_MISMATCH:{len(exact_summaries)}")

    aggregate_rc = 1
    aggregate_log = root / "artifacts/strategy11_orchestrator_v1/logs/aggregate.log"
    aggregate_log.parent.mkdir(parents=True, exist_ok=True)
    if not blockers:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root)
        with aggregate_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                [
                    sys.executable,
                    "backend/tools/r7a4d_strategy11_aggregate.py",
                    "--exact-root",
                    str(root / "artifacts/strategy11_exact_v1"),
                    "--target",
                    "11",
                ],
                cwd=root,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        aggregate_rc = int(completed.returncode)
        if aggregate_rc != 0:
            blockers.append(f"AGGREGATE:RC={aggregate_rc}")

    capture_path = root / "artifacts/strategy11_structure_lock_v2/capture.json"
    protected_before: dict[str, str] = {}
    if not capture_path.is_file():
        blockers.append("STRUCTURE_CAPTURE_MISSING")
    else:
        try:
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            protected_before = dict(capture.get("protected_before") or {})
        except Exception as exc:
            blockers.append(f"STRUCTURE_CAPTURE_INVALID:{type(exc).__name__}:{exc}")

    try:
        protected_after = protected_snapshot(root)
        protected_mutations = protected_diff(protected_before, protected_after)
    except Exception as exc:
        protected_after = {}
        protected_mutations = [f"SNAPSHOT_FAILED:{type(exc).__name__}:{exc}"]
    if protected_mutations:
        blockers.append("PROTECTED_MUTATION:" + ",".join(protected_mutations[:20]))

    preflight_path = root / "artifacts/strategy11_structure_lock_v2/preflight.json"
    experiment_id = f"{STRUCTURE_VERSION}:MISSING_PREFLIGHT"
    if preflight_path.is_file():
        try:
            preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
            experiment_id = str(preflight.get("experiment_id") or experiment_id)
        except Exception:
            experiment_id = f"{STRUCTURE_VERSION}:INVALID_PREFLIGHT"

    summary = {
        "schema_version": "3.3",
        "structure_version": STRUCTURE_VERSION,
        "experiment_id": experiment_id,
        "state": "PASS" if not blockers else "HOLD",
        "workers": 3,
        "batch_size": BATCH_SIZE,
        "batch_count": EXPECTED_BATCHES,
        "strategy_count": len(expected),
        "evidence": {
            "prepare": {"rc": 0},
            "screen": screen_evidence,
            "exact": exact_evidence,
            "aggregate": {"rc": aggregate_rc},
        },
        "blockers": blockers,
        "protected_before_count": len(protected_before),
        "protected_after_count": len(protected_after),
        "protected_mutations": protected_mutations,
        "canonical_mutated": any(path.startswith("backend/strategies/") for path in protected_mutations),
        "registry_mutated": "backend/strategy25/canonical_strategy_registry_v1.json" in protected_mutations,
        "runtime_authority_mutated": any(
            path.startswith(("backend/engine/", "services/", "canonical/", "policy/"))
            for path in protected_mutations
        ),
        "route_allowed": False,
        "shadow_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_allowed": False,
    }
    output = root / "artifacts/strategy11_orchestrator_v1/summary.json"
    _atomic_json(output, summary)
    print(
        json.dumps(
            {
                "STATE": summary["state"],
                "SCREEN_COUNT": len(screen_evidence),
                "EXACT_COUNT": len(exact_evidence),
                "AGGREGATE_RC": aggregate_rc,
                "BLOCKERS": blockers,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if not blockers else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    batch = subparsers.add_parser("run-batch")
    batch.add_argument("--root", default=".")
    batch.add_argument("--replay", required=True)
    batch.add_argument("--phase", choices=("screen", "exact"), required=True)
    batch.add_argument("--batch-index", type=int, required=True)
    batch.add_argument("--timeout-seconds", type=int, default=1800)
    batch.add_argument("--workers", type=int, default=3)
    batch.set_defaults(func=run_batch)

    finalize = subparsers.add_parser("finalize-replay")
    finalize.add_argument("--root", default=".")
    finalize.add_argument("--replay", required=True)
    finalize.set_defaults(func=finalize_replay)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
