from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_WORKER_ETA_SIDECAR_V1"
DEFAULT_UNIT = "zel-data-b-1m-v2.service"
DEFAULT_ROOT = Path("/var/lib/zel-research/data-b-1m-v2")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(*args: str) -> str:
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    return proc.stdout.strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def proc_snapshot(pid: int) -> dict[str, Any] | None:
    base = Path(f"/proc/{pid}")
    if not base.is_dir():
        return None
    try:
        parts = (base / "stat").read_text(encoding="utf-8").split()
        io: dict[str, int] = {}
        for line in (base / "io").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            io[key.strip()] = int(value.strip())
        return {
            "pid": pid,
            "state": parts[2],
            "utime_ticks": int(parts[13]),
            "stime_ticks": int(parts[14]),
            "io": io,
            "wchan": (base / "wchan").read_text(encoding="utf-8").strip(),
        }
    except Exception:
        return None


def descendant_pids(parent: int) -> list[int]:
    seen: set[int] = set()
    frontier = [parent] if parent > 0 else []
    while frontier:
        current = frontier.pop()
        raw = run("pgrep", "-P", str(current))
        for token in raw.split():
            if not token.isdigit():
                continue
            pid = int(token)
            if pid not in seen:
                seen.add(pid)
                frontier.append(pid)
    return sorted(seen)


def capture(pids: Sequence[int]) -> dict[str, dict[str, Any] | None]:
    return {str(pid): proc_snapshot(pid) for pid in pids}


def delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    active: list[int] = []
    for key in sorted(set(before) | set(after), key=lambda value: int(value)):
        left = before.get(key)
        right = after.get(key)
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            rows[key] = {"present_both_samples": False, "active": False}
            continue
        cpu = int(right.get("utime_ticks", 0)) + int(right.get("stime_ticks", 0))
        cpu -= int(left.get("utime_ticks", 0)) + int(left.get("stime_ticks", 0))
        left_io = left.get("io") if isinstance(left.get("io"), Mapping) else {}
        right_io = right.get("io") if isinstance(right.get("io"), Mapping) else {}
        io_delta = {
            name: int(right_io.get(name, 0)) - int(left_io.get(name, 0))
            for name in sorted(set(left_io) | set(right_io))
        }
        moving = cpu > 0 or any(
            io_delta.get(name, 0) > 0
            for name in ("read_bytes", "write_bytes", "syscr", "syscw", "rchar", "wchar")
        )
        if moving:
            active.append(int(key))
        rows[key] = {
            "present_both_samples": True,
            "cpu_delta_ticks": cpu,
            "io_delta": io_delta,
            "active": moving,
            "state": right.get("state"),
            "wchan": right.get("wchan"),
        }
    return {"rows": rows, "active_pids": active, "active_count": len(active)}


def checkpoint_intervals(checkpoint_dir: Path, limit: int = 12) -> list[float]:
    if not checkpoint_dir.is_dir():
        return []
    mtimes = sorted(path.stat().st_mtime for path in checkpoint_dir.glob("*.json.gz"))
    values = [right - left for left, right in zip(mtimes, mtimes[1:]) if right > left]
    return values[-limit:]


def quantile(values: Sequence[float], q: float) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)) and value > 0)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = (len(clean) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return clean[low]
    return clean[low] * (high - position) + clean[high] * (position - low)


def estimate_eta(
    completed: int,
    total: int,
    active_workers: int,
    intervals_sec: Sequence[float],
) -> dict[str, Any]:
    remaining = max(0, total - completed)
    median_sec = statistics.median(intervals_sec) if intervals_sec else None
    p75_sec = quantile(intervals_sec, 0.75)
    enough_history = len(intervals_sec) >= 3
    parallelism = max(1, active_workers)
    if remaining == 0:
        return {
            "state": "PASS_TERMINAL_OR_ALL_UNITS_COMPLETE",
            "remaining_units": 0,
            "eta_low_min": 0.0,
            "eta_high_min": 0.0,
            "confidence": "HIGH",
            "basis": "completed_units_equals_total_units",
        }
    if not enough_history or active_workers <= 0 or median_sec is None or p75_sec is None:
        return {
            "state": "HOLD_ETA_INSUFFICIENT_ACTIVITY_OR_HISTORY",
            "remaining_units": remaining,
            "eta_low_min": None,
            "eta_high_min": None,
            "confidence": "NONE",
            "basis": "requires_active_worker_and_three_checkpoint_intervals",
        }
    waves = math.ceil(remaining / parallelism)
    return {
        "state": "PASS_BOUNDED_ETA_ESTIMATE",
        "remaining_units": remaining,
        "eta_low_min": round(waves * median_sec / 60.0, 3),
        "eta_high_min": round(waves * max(p75_sec, median_sec) * 1.5 / 60.0, 3),
        "confidence": "MEDIUM" if len(intervals_sec) >= 6 else "LOW",
        "basis": "recent_checkpoint_intervals_divided_by_observed_active_workers",
        "active_worker_count": active_workers,
        "checkpoint_interval_sample_count": len(intervals_sec),
        "checkpoint_interval_median_sec": round(median_sec, 3),
        "checkpoint_interval_p75_sec": round(p75_sec, 3),
    }


def build(unit: str, root: Path, sample_sec: float) -> dict[str, Any]:
    active = run("systemctl", "is-active", unit) == "active"
    enabled = run("systemctl", "is-enabled", unit) == "enabled"
    try:
        main_pid = int(run("systemctl", "show", "-p", "MainPID", "--value", unit) or 0)
    except ValueError:
        main_pid = 0
    children = descendant_pids(main_pid)
    pids = ([main_pid] if main_pid else []) + children
    before = capture(pids)
    time.sleep(max(0.1, sample_sec))
    after = capture(pids)
    activity = delta(before, after)

    progress = read_json(root / "progress.json")
    terminal = read_json(root / "terminal_receipt.json")
    completed = int(progress.get("completed_units") or 0)
    total = int(progress.get("total_units") or 0)
    intervals = checkpoint_intervals(root / "checkpoints")
    eta = estimate_eta(completed, total, int(activity["active_count"]), intervals)

    heartbeat = progress.get("heartbeat_at")
    heartbeat_age_sec = None
    if heartbeat:
        try:
            stamp = datetime.fromisoformat(str(heartbeat).replace("Z", "+00:00"))
            heartbeat_age_sec = (datetime.now(timezone.utc) - stamp).total_seconds()
        except Exception:
            heartbeat_age_sec = None

    terminal_complete = terminal.get("state") == "PASS" or (total > 0 and completed == total)
    if terminal_complete:
        state = "PASS_WORKER_SIDECAR_TERMINAL"
    elif not active or main_pid <= 0:
        state = "HOLD_SERVICE_NOT_ACTIVE"
    elif int(activity["active_count"]) <= 0:
        state = "HOLD_NO_CPU_OR_IO_ACTIVITY"
    else:
        state = "PASS_WORKER_ACTIVITY_OBSERVED"

    return {
        "schema_version": "zel.worker_eta_sidecar.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "unit": unit,
        "root": str(root),
        "service_active": active,
        "service_enabled": enabled,
        "main_pid": main_pid,
        "descendant_pids": children,
        "sample_sec": sample_sec,
        "activity": activity,
        "completed_units": completed,
        "total_units": total,
        "progress_pct": (completed / total * 100.0) if total else None,
        "heartbeat_at": heartbeat,
        "heartbeat_age_sec": heartbeat_age_sec,
        "checkpoint_count": len(list((root / "checkpoints").glob("*.json.gz"))) if (root / "checkpoints").is_dir() else 0,
        "eta": eta,
        "terminal_complete": terminal_complete,
        "read_only": True,
        "runtime_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    before = {
        "10": {"utime_ticks": 1, "stime_ticks": 1, "io": {"read_bytes": 0}, "state": "S", "wchan": "futex"},
        "11": {"utime_ticks": 2, "stime_ticks": 2, "io": {"read_bytes": 0}, "state": "R", "wchan": "0"},
    }
    after = {
        "10": {"utime_ticks": 1, "stime_ticks": 1, "io": {"read_bytes": 0}, "state": "S", "wchan": "futex"},
        "11": {"utime_ticks": 22, "stime_ticks": 4, "io": {"read_bytes": 10}, "state": "R", "wchan": "0"},
    }
    activity = delta(before, after)
    assert activity["active_pids"] == [11], activity
    eta = estimate_eta(23, 25, 2, [100, 120, 140, 160])
    assert eta["state"] == "PASS_BOUNDED_ETA_ESTIMATE", eta
    assert eta["remaining_units"] == 2, eta
    assert eta["eta_low_min"] > 0, eta
    hold = estimate_eta(23, 25, 0, [100, 120, 140])
    assert hold["state"] == "HOLD_ETA_INSUFFICIENT_ACTIVITY_OR_HISTORY", hold
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", default=DEFAULT_UNIT)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--sample-sec", type=float, default=10.0)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    row = build(args.unit, args.root.resolve(), args.sample_sec)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
