from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from backend.tools.r7a4d_strategy11_structure_lock import (
    STRUCTURE_VERSION,
    protected_diff,
    protected_snapshot,
)


STRATEGIES = (
    "alpha_combo", "anchor_vwap_trend", "bb_revert", "break_and_continue", "ema_ribbon_scalp",
    "fvg_revert", "grid_rebalance", "keltner_trend", "liquidity_sweep", "mfi_rsi_div",
    "obv_trend", "pivot_reversal", "range_fade", "rbreaker_like", "rsi_swing_fail",
    "scalp_snap", "session_bias", "squeeze_break", "sr_levels", "supertrend_pullback",
    "trend_ma_macd", "trend_rider", "turtle_trend", "vol_spike_fade", "vwap_revert",
)
DEFAULT_CHILD_TIMEOUT_S = 1800


def _heartbeat(event: str, *, label: str, elapsed_s: int | None = None, rc: int | None = None) -> None:
    payload: dict[str, object] = {"EVENT": event, "LABEL": label}
    if elapsed_s is not None:
        payload["ELAPSED_S"] = elapsed_s
    if rc is not None:
        payload["RC"] = rc
    print(json.dumps(payload, sort_keys=True), flush=True)


def _run(
    command: list[str],
    log_path: Path,
    *,
    label: str,
    timeout_s: int = DEFAULT_CHILD_TIMEOUT_S,
) -> tuple[int, str, int]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    started = time.monotonic()
    _heartbeat("CHILD_START", label=label)
    rc = 1
    with log_path.open("w", encoding="utf-8") as handle:
        try:
            process = subprocess.run(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=env,
                check=False,
                timeout=max(1, timeout_s),
            )
            rc = process.returncode
        except subprocess.TimeoutExpired:
            rc = 124
            handle.write(f"\nCHILD_TIMEOUT label={label} timeout_s={timeout_s}\n")
            handle.flush()
    elapsed_s = int(round(time.monotonic() - started))
    _heartbeat("CHILD_END", label=label, elapsed_s=elapsed_s, rc=rc)
    return rc, str(log_path), elapsed_s


def _screen(root: Path, strategy_id: str, timeout_s: int) -> tuple[str, int, str, int]:
    command = [
        sys.executable, "backend/tools/r7a4d_strategy11_screen_v2.py",
        "--root", str(root), "--strategy-id", strategy_id,
    ]
    rc, log, elapsed_s = _run(
        command,
        root / "artifacts/strategy11_orchestrator_v1/logs" / f"screen-{strategy_id}.log",
        label=f"screen:{strategy_id}",
        timeout_s=timeout_s,
    )
    return strategy_id, rc, log, elapsed_s


def _exact(root: Path, strategy_id: str, timeout_s: int) -> tuple[str, int, str, int]:
    summary = root / "artifacts/strategy11_screen_v1" / strategy_id / "summary.json"
    command = [
        sys.executable, "backend/tools/r7a4d_strategy11_exact_v2.py",
        "--root", str(root), "--strategy-id", strategy_id, "--screen-summary", str(summary),
    ]
    rc, log, elapsed_s = _run(
        command,
        root / "artifacts/strategy11_orchestrator_v1/logs" / f"exact-{strategy_id}.log",
        label=f"exact:{strategy_id}",
        timeout_s=timeout_s,
    )
    return strategy_id, rc, log, elapsed_s


def _experiment_id(root: Path) -> str:
    path = root / "artifacts/strategy11_structure_lock_v2/preflight.json"
    if not path.is_file():
        return f"{STRUCTURE_VERSION}:MISSING_PREFLIGHT"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("experiment_id") or f"{STRUCTURE_VERSION}:UNKNOWN")
    except Exception:
        return f"{STRUCTURE_VERSION}:INVALID_PREFLIGHT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--child-timeout-s", type=int, default=DEFAULT_CHILD_TIMEOUT_S)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    workers = min(len(STRATEGIES), max(1, args.workers))
    child_timeout_s = max(1, args.child_timeout_s)
    evidence: dict[str, object] = {"prepare": None, "screen": [], "exact": [], "aggregate": None}
    blockers: list[str] = []

    try:
        protected_before = protected_snapshot(root)
    except Exception as exc:
        protected_before = {}
        blockers.append(f"STRUCTURE_CAPTURE:{type(exc).__name__}:{exc}")

    preflight = root / "artifacts/strategy11_structure_lock_v2/preflight.json"
    if not preflight.is_file():
        blockers.append("STRUCTURE_PREFLIGHT_MISSING")
    else:
        try:
            preflight_payload = json.loads(preflight.read_text(encoding="utf-8"))
            if preflight_payload.get("state") != "PASS" or preflight_payload.get("blockers"):
                blockers.append("STRUCTURE_PREFLIGHT_NOT_PASS")
        except Exception as exc:
            blockers.append(f"STRUCTURE_PREFLIGHT_INVALID:{type(exc).__name__}:{exc}")

    prepare_log = root / "artifacts/strategy11_orchestrator_v1/logs/prepare-data.log"
    if not blockers:
        prepare_rc, prepare_path, prepare_elapsed_s = _run(
            [sys.executable, "backend/tools/r7a4d_strategy11_prepare_data_v2.py", "--root", str(root)],
            prepare_log,
            label="prepare-data",
            timeout_s=child_timeout_s,
        )
        evidence["prepare"] = {"rc": prepare_rc, "log": prepare_path, "elapsed_s": prepare_elapsed_s}
        if prepare_rc != 0:
            blockers.append(f"PREPARE_DATA:RC={prepare_rc}")

    if not blockers:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_screen, root, strategy_id, child_timeout_s) for strategy_id in STRATEGIES]
            for future in concurrent.futures.as_completed(futures):
                strategy_id, rc, log, elapsed_s = future.result()
                evidence["screen"].append({
                    "strategy_id": strategy_id,
                    "rc": rc,
                    "log": log,
                    "elapsed_s": elapsed_s,
                })
                if rc != 0:
                    blockers.append(f"SCREEN:{strategy_id}:RC={rc}")
        evidence["screen"] = sorted(evidence["screen"], key=lambda row: row["strategy_id"])

    if not blockers:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_exact, root, strategy_id, child_timeout_s) for strategy_id in STRATEGIES]
            for future in concurrent.futures.as_completed(futures):
                strategy_id, rc, log, elapsed_s = future.result()
                evidence["exact"].append({
                    "strategy_id": strategy_id,
                    "rc": rc,
                    "log": log,
                    "elapsed_s": elapsed_s,
                })
                if rc != 0:
                    blockers.append(f"EXACT:{strategy_id}:RC={rc}")
        evidence["exact"] = sorted(evidence["exact"], key=lambda row: row["strategy_id"])

    aggregate_log = root / "artifacts/strategy11_orchestrator_v1/logs/aggregate.log"
    if not blockers:
        rc, log, elapsed_s = _run(
            [
                sys.executable, "backend/tools/r7a4d_strategy11_aggregate.py",
                "--exact-root", str(root / "artifacts/strategy11_exact_v1"), "--target", "11",
            ],
            aggregate_log,
            label="aggregate",
            timeout_s=child_timeout_s,
        )
        evidence["aggregate"] = {"rc": rc, "log": log, "elapsed_s": elapsed_s}
        if rc != 0:
            blockers.append(f"AGGREGATE:RC={rc}")

    try:
        protected_after = protected_snapshot(root)
        protected_mutations = protected_diff(protected_before, protected_after)
    except Exception as exc:
        protected_after = {}
        protected_mutations = [f"SNAPSHOT_FAILED:{type(exc).__name__}:{exc}"]
    if protected_mutations:
        blockers.append("PROTECTED_MUTATION:" + ",".join(protected_mutations[:20]))

    canonical_mutated = any(path.startswith("backend/strategies/") for path in protected_mutations)
    registry_mutated = "backend/strategy25/canonical_strategy_registry_v1.json" in protected_mutations
    runtime_authority_mutated = any(
        path.startswith(("backend/engine/", "services/", "canonical/", "policy/"))
        for path in protected_mutations
    )

    output = root / "artifacts/strategy11_orchestrator_v1/summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema_version": "3.1",
        "structure_version": STRUCTURE_VERSION,
        "experiment_id": _experiment_id(root),
        "state": "PASS" if not blockers else "HOLD",
        "workers": workers,
        "child_timeout_s": child_timeout_s,
        "strategy_count": len(STRATEGIES),
        "evidence": evidence,
        "blockers": blockers,
        "protected_before_count": len(protected_before),
        "protected_after_count": len(protected_after),
        "protected_mutations": protected_mutations,
        "canonical_mutated": canonical_mutated,
        "registry_mutated": registry_mutated,
        "runtime_authority_mutated": runtime_authority_mutated,
        "route_allowed": False,
        "shadow_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_allowed": False,
    }, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "STATE": "PASS" if not blockers else "HOLD",
        "BLOCKERS": blockers,
        "PROTECTED_MUTATIONS": protected_mutations,
    }, sort_keys=True), flush=True)
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
