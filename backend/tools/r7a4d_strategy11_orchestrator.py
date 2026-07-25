from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path


STRATEGIES = (
    "alpha_combo", "anchor_vwap_trend", "bb_revert", "break_and_continue", "ema_ribbon_scalp",
    "fvg_revert", "grid_rebalance", "keltner_trend", "liquidity_sweep", "mfi_rsi_div",
    "obv_trend", "pivot_reversal", "range_fade", "rbreaker_like", "rsi_swing_fail",
    "scalp_snap", "session_bias", "squeeze_break", "sr_levels", "supertrend_pullback",
    "trend_ma_macd", "trend_rider", "turtle_trend", "vol_spike_fade", "vwap_revert",
)


def _run(command: list[str], log_path: Path) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    with log_path.open("w", encoding="utf-8") as handle:
        process = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, env=env, check=False)
    return process.returncode, str(log_path)


def _screen(root: Path, strategy_id: str) -> tuple[str, int, str]:
    command = [
        sys.executable, "backend/tools/r7a4d_strategy11_screen.py",
        "--root", str(root), "--strategy-id", strategy_id,
    ]
    rc, log = _run(command, root / "artifacts/strategy11_orchestrator_v1/logs" / f"screen-{strategy_id}.log")
    return strategy_id, rc, log


def _exact(root: Path, strategy_id: str) -> tuple[str, int, str]:
    summary = root / "artifacts/strategy11_screen_v1" / strategy_id / "summary.json"
    command = [
        sys.executable, "backend/tools/r7a4d_strategy11_exact.py",
        "--root", str(root), "--strategy-id", strategy_id, "--screen-summary", str(summary),
    ]
    rc, log = _run(command, root / "artifacts/strategy11_orchestrator_v1/logs" / f"exact-{strategy_id}.log")
    return strategy_id, rc, log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    evidence: dict[str, object] = {"screen": [], "exact": [], "aggregate": None}
    blockers: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(_screen, root, strategy_id) for strategy_id in STRATEGIES]
        for future in concurrent.futures.as_completed(futures):
            strategy_id, rc, log = future.result()
            evidence["screen"].append({"strategy_id": strategy_id, "rc": rc, "log": log})
            if rc != 0:
                blockers.append(f"SCREEN:{strategy_id}:RC={rc}")

    if not blockers:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = [executor.submit(_exact, root, strategy_id) for strategy_id in STRATEGIES]
            for future in concurrent.futures.as_completed(futures):
                strategy_id, rc, log = future.result()
                evidence["exact"].append({"strategy_id": strategy_id, "rc": rc, "log": log})
                if rc != 0:
                    blockers.append(f"EXACT:{strategy_id}:RC={rc}")

    aggregate_log = root / "artifacts/strategy11_orchestrator_v1/logs/aggregate.log"
    if not blockers:
        rc, log = _run(
            [
                sys.executable, "backend/tools/r7a4d_strategy11_aggregate.py",
                "--exact-root", str(root / "artifacts/strategy11_exact_v1"), "--target", "11",
            ],
            aggregate_log,
        )
        evidence["aggregate"] = {"rc": rc, "log": log}
        if rc != 0:
            blockers.append(f"AGGREGATE:RC={rc}")

    output = root / "artifacts/strategy11_orchestrator_v1/summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema_version": "1.0",
        "state": "PASS" if not blockers else "HOLD",
        "workers": args.workers,
        "strategy_count": len(STRATEGIES),
        "evidence": evidence,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "shadow_allowed": False,
        "execution_allowed": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"STATE": "PASS" if not blockers else "HOLD", "BLOCKERS": blockers}, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
