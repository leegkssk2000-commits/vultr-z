from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PATTERN = "zel_historical_oos_exact25_replay_v1.py"
INTERVAL = "--interval 1m"
OUTPUT_DIR = Path("/tmp/zel_historical_oos_exact25_replay_v1_1m")
TERMINAL_FILES = ("report.json", "summary.json", "scoreboard.csv", "trades.jsonl.gz")
CLK_TCK = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


def cmd(args: list[str], timeout: int = 20) -> str:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    return p.stdout[-30000:]


def processes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            pid = int(proc.name)
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore").strip()
            if PATTERN not in command or INTERVAL not in command:
                continue
            stat = (proc / "stat").read_text().split()
            status = (proc / "status").read_text(errors="ignore")
            rss_match = re.search(r"^VmRSS:\s+(\d+)\s+kB", status, re.M)
            elapsed = cmd(["ps", "-o", "etimes=", "-p", str(pid)]).strip()
            rows.append({
                "pid": pid,
                "ppid": int(stat[3]),
                "cpu_sec": round((int(stat[13]) + int(stat[14])) / CLK_TCK, 3),
                "rss_mb": round((int(rss_match.group(1)) if rss_match else 0) / 1024, 3),
                "elapsed_sec": int(elapsed) if elapsed.isdigit() else None,
                "cmdline": command[:1200],
            })
        except (OSError, ValueError, IndexError):
            continue
    return sorted(rows, key=lambda row: row["pid"])


def ancestry_root(pid: int) -> int:
    current = pid
    seen: set[int] = set()
    candidate = pid
    for _ in range(15):
        if current <= 1 or current in seen:
            break
        seen.add(current)
        base = Path("/proc") / str(current)
        try:
            command = (base / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            stat = (base / "stat").read_text().split()
            ppid = int(stat[3])
        except (OSError, ValueError, IndexError):
            break
        if "sshd:" in command or "bash -se" in command or "bash -c" in command or "flock" in command:
            candidate = current
        current = ppid
    return candidate


def inventory() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total = 0
    latest_mtime = 0.0
    if OUTPUT_DIR.exists():
        for path in sorted(OUTPUT_DIR.rglob("*")):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            total += stat.st_size
            latest_mtime = max(latest_mtime, stat.st_mtime)
            rows.append({
                "path": str(path.relative_to(OUTPUT_DIR)),
                "bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
    return {
        "exists": OUTPUT_DIR.exists(),
        "file_count": len(rows),
        "total_bytes": total,
        "latest_mtime": datetime.fromtimestamp(latest_mtime, timezone.utc).isoformat() if latest_mtime else None,
        "latest_mtime_age_sec": round(time.time() - latest_mtime, 3) if latest_mtime else None,
        "terminal": {name: (OUTPUT_DIR / name).is_file() and (OUTPUT_DIR / name).stat().st_size > 0 for name in TERMINAL_FILES},
        "files": rows[:200],
    }


def snapshot() -> dict[str, Any]:
    proc = processes()
    roots: dict[str, list[int]] = {}
    for row in proc:
        roots.setdefault(str(ancestry_root(row["pid"])), []).append(row["pid"])
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "processes": proc,
        "process_count": len(proc),
        "root_groups": roots,
        "root_group_count": len(roots),
        "cpu_total_sec": round(sum(row["cpu_sec"] for row in proc), 3),
        "rss_total_mb": round(sum(row["rss_mb"] for row in proc), 3),
        "elapsed_min_sec": min((row["elapsed_sec"] for row in proc if row["elapsed_sec"] is not None), default=None),
        "elapsed_max_sec": max((row["elapsed_sec"] for row in proc if row["elapsed_sec"] is not None), default=None),
        "output": inventory(),
        "locks": cmd(["bash", "-lc", "lslocks 2>/dev/null | grep -E 'zel-data-b-1m|zel_historical_oos_exact25' || true"]).splitlines(),
    }


def main() -> int:
    first = snapshot()
    time.sleep(10)
    second = snapshot()
    cpu_delta = round(second["cpu_total_sec"] - first["cpu_total_sec"], 3)
    output_delta = second["output"]["total_bytes"] - first["output"]["total_bytes"]
    terminal_complete = all(second["output"]["terminal"].values())
    if terminal_complete:
        state = "PASS_DATA_B_1M_TERMINAL_FILES_PRESENT"
    elif second["root_group_count"] > 1:
        state = "HOLD_DUPLICATE_DATA_B_1M_OWNERS"
    elif second["process_count"] == 0:
        state = "HOLD_NO_DATA_B_1M_PROCESS"
    elif cpu_delta > 0.25 or output_delta != 0:
        state = "IN_PROGRESS_DATA_B_1M_ACTIVE"
    else:
        state = "IN_PROGRESS_DATA_B_1M_LOW_OBSERVABILITY"

    result = {
        "schema_version": "zel.data_b.1m.progress_probe.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "sample_window_sec": 10,
        "cpu_delta_sec": cpu_delta,
        "output_bytes_delta": output_delta,
        "first": first,
        "latest": second,
        "progress_pct": None,
        "eta_min": None,
        "eta_reason": "ENGINE_DOES_NOT_EMIT_UNIT_PROGRESS",
        "terminal_publication_allowed": terminal_complete and second["root_group_count"] <= 1,
        "integrity": {
            "single_owner": second["root_group_count"] == 1,
            "terminal_complete": terminal_complete,
            "activity_observed": cpu_delta > 0.25 or output_delta != 0,
        },
        "safety": {
            "read_only": True,
            "process_mutated": False,
            "output_mutated": False,
            "runtime_mutated": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        },
    }
    Path("/tmp/zel_data_b_1m_progress_probe_v2.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "state": state,
        "process_count": second["process_count"],
        "root_group_count": second["root_group_count"],
        "cpu_delta_sec": cpu_delta,
        "output_bytes_delta": output_delta,
        "terminal": second["output"]["terminal"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
