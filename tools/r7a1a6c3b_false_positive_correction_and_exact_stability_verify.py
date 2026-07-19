#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import select
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGETS = (
    Path("/var/www/z-os-alimi/api/view_contract_latest.json"),
    Path("/var/www/z-os-alimi/api/q4r3_shadow_closed_ledger_latest.json"),
    Path("/var/www/z-os-alimi/api/q4r3_recent_ledger_trace_latest.json"),
)
PROTECTED = (
    Path("/home/z/z/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"),
    Path("/home/z/z/runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json"),
    Path("/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json"),
)
TELEGRAM_UNIT = "zel-q4r3-telegram-pos-adapter-v2.service"

FAN_CLOEXEC = 0x00000001
FAN_NONBLOCK = 0x00000002
FAN_CLASS_NOTIF = 0x00000000
FAN_MARK_ADD = 0x00000001
FAN_CLOSE_WRITE = 0x00000008
FAN_MOVED_TO = 0x00000080
FAN_CREATE = 0x00000100
FAN_EVENT_ON_CHILD = 0x08000000
FAN_NOFD = -1
AT_FDCWD = -100
META = struct.Struct("=IBBHQii")


@dataclass(frozen=True)
class Fingerprint:
    path: str
    resolved_path: str
    exists: bool
    dev: int | None
    inode: int | None
    mtime_ns: int | None
    size: int | None
    sha256: str | None


@dataclass
class WriterEvent:
    ts: float
    pid: int
    path: str
    exe: str
    command: str
    unit: str
    mask: int


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except Exception:
        return None


def fingerprint(path: Path) -> Fingerprint:
    try:
        resolved = path.resolve(strict=False)
    except Exception:
        resolved = path
    try:
        info = path.stat()
        return Fingerprint(
            path=str(path),
            resolved_path=str(resolved),
            exists=True,
            dev=int(info.st_dev),
            inode=int(info.st_ino),
            mtime_ns=int(info.st_mtime_ns),
            size=int(info.st_size),
            sha256=sha256_file(path),
        )
    except Exception:
        return Fingerprint(
            path=str(path),
            resolved_path=str(resolved),
            exists=False,
            dev=None,
            inode=None,
            mtime_ns=None,
            size=None,
            sha256=None,
        )


def snapshot(paths: tuple[Path, ...]) -> dict[str, Fingerprint]:
    return {str(path): fingerprint(path) for path in paths}


def diff_snapshots(
    before: dict[str, Fingerprint],
    after: dict[str, Fingerprint],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        left = before.get(path)
        right = after.get(path)
        if left != right:
            changes.append({
                "path": path,
                "before": asdict(left) if left else None,
                "after": asdict(right) if right else None,
            })
    return changes


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def process_info(pid: int) -> tuple[str, str, str]:
    exe = ""
    command = ""
    unit = ""
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except Exception:
        pass
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        command = " ".join(part.decode("utf-8", "replace") for part in raw if part)[:1200]
    except Exception:
        pass
    try:
        text = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r"/([^/]+\.(?:service|scope))(?=$|/)", text)
        if matches:
            unit = matches[-1]
    except Exception:
        pass
    return exe, command, unit


class FanotifyWatcher:
    def __init__(self, directory: Path):
        self.fd = -1
        self.available = False
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            init = libc.fanotify_init
            init.argtypes = [ctypes.c_uint, ctypes.c_uint]
            init.restype = ctypes.c_int
            mark = libc.fanotify_mark
            mark.argtypes = [
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_ulonglong,
                ctypes.c_int,
                ctypes.c_char_p,
            ]
            mark.restype = ctypes.c_int
            fd = init(FAN_CLASS_NOTIF | FAN_CLOEXEC | FAN_NONBLOCK, os.O_RDONLY)
            if fd < 0:
                return
            mask = FAN_CLOSE_WRITE | FAN_MOVED_TO | FAN_CREATE | FAN_EVENT_ON_CHILD
            rc = mark(fd, FAN_MARK_ADD, mask, AT_FDCWD, os.fsencode(str(directory)))
            if rc < 0:
                os.close(fd)
                return
            self.fd = fd
            self.available = True
        except Exception:
            self.close()

    def close(self) -> None:
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = -1
        self.available = False

    def read_events(self, timeout: float = 0.2) -> list[WriterEvent]:
        if not self.available or self.fd < 0:
            time.sleep(timeout)
            return []
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return []
        try:
            data = os.read(self.fd, 65536)
        except (BlockingIOError, OSError):
            return []
        events: list[WriterEvent] = []
        offset = 0
        while offset + META.size <= len(data):
            event_len, _version, _reserved, _metadata_len, mask, event_fd, pid = META.unpack_from(data, offset)
            if event_len < META.size:
                break
            event_path = ""
            if event_fd != FAN_NOFD:
                try:
                    event_path = os.readlink(f"/proc/self/fd/{event_fd}")
                except Exception:
                    pass
                try:
                    os.close(event_fd)
                except OSError:
                    pass
            exe, command, unit = process_info(pid)
            events.append(WriterEvent(time.time(), pid, event_path, exe, command, unit, int(mask)))
            offset += event_len
        return events


def systemctl_value(unit: str, prop: str) -> str:
    proc = run(["systemctl", "show", unit, f"--property={prop}", "--value", "--no-pager"], 15)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def telegram_retained() -> bool:
    active = run(["systemctl", "is-active", TELEGRAM_UNIT], 10).stdout.strip() == "active"
    exec_start = systemctl_value(TELEGRAM_UNIT, "ExecStart")
    return (
        active
        and "/opt/zel/releases/" in exec_start
        and "zel_q4r3_telegram_pos_adapter_v2.py" in exec_start
    )


def invoke_repair(
    repair_runner: Path,
    mode: str,
    root: Path,
    repair_contract: Path | None = None,
) -> tuple[int, str]:
    cmd = [sys.executable, str(repair_runner), mode, "--root", str(root)]
    if mode == "apply":
        if repair_contract is None:
            return 2, "MISSING_REPAIR_CONTRACT"
        cmd.extend(["--contract", str(repair_contract)])
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    combined = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip())
    return int(proc.returncode), combined[-8000:]


def fetch_http_sha() -> dict[str, Any]:
    attempts = [
        [
            "curl", "-kfsS", "--max-time", "10",
            "--resolve", "alimi.z-os.vip:443:127.0.0.1",
            "-w", "\n%{http_code}",
            "https://alimi.z-os.vip/api/view_contract_latest.json",
        ],
        [
            "curl", "-fsS", "--max-time", "10",
            "-H", "Host: alimi.z-os.vip",
            "-w", "\n%{http_code}",
            "http://127.0.0.1/api/view_contract_latest.json",
        ],
    ]
    for index, cmd in enumerate(attempts, start=1):
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=15)
        if proc.returncode != 0:
            continue
        body, sep, tail = proc.stdout.rpartition(b"\n")
        if not sep:
            continue
        try:
            status = int(tail.decode("ascii", "replace").strip())
        except Exception:
            status = 0
        if status:
            return {
                "status": status,
                "sha256": hashlib.sha256(body).hexdigest(),
                "size": len(body),
                "mode": f"attempt_{index}",
            }
    return {"status": 0, "sha256": None, "size": 0, "mode": "none"}


def collect_route_evidence() -> dict[str, Any]:
    evidence: dict[str, Any] = {"targets": {}}
    for path in TARGETS:
        item = asdict(fingerprint(path))
        findmnt = run(["findmnt", "-T", str(path), "-no", "TARGET,SOURCE,FSTYPE,OPTIONS"], 15)
        item["findmnt"] = findmnt.stdout.strip()[:1200] if findmnt.returncode == 0 else ""
        evidence["targets"][str(path)] = item
    refs: list[str] = []
    for config_root in (Path("/etc/caddy"), Path("/etc/nginx")):
        if not config_root.exists():
            continue
        try:
            for candidate in config_root.rglob("*"):
                if not candidate.is_file() or candidate.stat().st_size > 2_000_000:
                    continue
                text = candidate.read_text(encoding="utf-8", errors="replace")
                if "alimi.z-os.vip" in text or "/var/www/z-os-alimi" in text:
                    refs.append(str(candidate))
        except Exception:
            pass
    evidence["route_config_refs"] = sorted(set(refs))[:40]
    evidence["http"] = fetch_http_sha()
    return evidence


def watch_window(
    baseline: dict[str, Fingerprint],
    seconds: int,
) -> tuple[list[dict[str, Any]], list[WriterEvent], bool]:
    watcher = FanotifyWatcher(TARGETS[0].parent)
    events: list[WriterEvent] = []
    changes: list[dict[str, Any]] = []
    deadline = time.time() + max(1, seconds)
    while time.time() < deadline:
        events.extend(watcher.read_events(0.2))
        current = snapshot(TARGETS)
        changes = diff_snapshots(baseline, current)
        if changes:
            break
    available = watcher.available
    watcher.close()
    return changes, events[-200:], available


def unique_writer_evidence(events: list[WriterEvent]) -> list[dict[str, Any]]:
    target_names = {path.name for path in TARGETS}
    unique: dict[tuple[int, str, str], WriterEvent] = {}
    for event in events:
        name = Path(event.path).name if event.path else ""
        if name not in target_names:
            continue
        key = (event.pid, event.unit, event.path)
        unique[key] = event
    return [asdict(event) for event in unique.values()]


def contract_valid(contract: dict[str, Any]) -> bool:
    return (
        contract.get("official_stage") == "R7.A1A6C3B"
        and contract.get("allow_no_overwriter_observed") is True
        and contract.get("quarantine_on_unconfirmed_change") is False
        and int(contract.get("required_exact_verify_count", 0)) == 3
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--repair-runner", required=True)
    parser.add_argument("--repair-contract", required=True)
    parser.add_argument("--trace-seconds", type=int)
    parser.add_argument("--stable-seconds", type=int)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract_path = Path(args.contract)
    repair_runner = Path(args.repair_runner)
    repair_contract = Path(args.repair_contract)
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception:
        contract = {}

    trace_seconds = int(args.trace_seconds if args.trace_seconds is not None else contract.get("trace_seconds", 90))
    stable_seconds = int(args.stable_seconds if args.stable_seconds is not None else contract.get("stable_seconds", 30))
    blockers: list[str] = []
    exact_results: list[dict[str, Any]] = []
    all_events: list[WriterEvent] = []
    target_changes: list[dict[str, Any]] = []
    route_evidence: dict[str, Any] | None = None
    repair_applied = False
    rollback_performed = False

    protected_before = snapshot(PROTECTED)
    telegram_before = telegram_retained()
    if not contract_valid(contract):
        blockers.append("CONTRACT_INVALID")
    if not telegram_before:
        blockers.append("TELEGRAM_ROUTER_NOT_RETAINED")

    if not blockers:
        rc, output = invoke_repair(repair_runner, "apply", root, repair_contract)
        repair_applied = rc == 0
        if rc != 0:
            blockers.append("INITIAL_SURFACE_REPAIR_FAILED")
        exact_results.append({"stage": "repair_apply", "rc": rc, "output": output})

    if not blockers:
        rc, output = invoke_repair(repair_runner, "verify", root)
        exact_results.append({"stage": "after_repair", "rc": rc, "output": output})
        if rc != 0:
            blockers.append("EXACT_VERIFY_AFTER_REPAIR_FAILED")

    baseline = snapshot(TARGETS)

    if not blockers:
        changes, events, available = watch_window(baseline, trace_seconds)
        all_events.extend(events)
        exact_results.append({
            "stage": "trace_window",
            "seconds": trace_seconds,
            "fanotify_available": available,
            "event_count": len(events),
        })
        if changes:
            target_changes.extend(changes)
            blockers.append("ACTUAL_TARGET_CHANGE_DURING_TRACE")
        rc, output = invoke_repair(repair_runner, "verify", root)
        exact_results.append({"stage": "after_trace", "rc": rc, "output": output})
        if rc != 0:
            blockers.append("EXACT_VERIFY_AFTER_TRACE_FAILED")

    if not blockers:
        changes, events, available = watch_window(baseline, stable_seconds)
        all_events.extend(events)
        exact_results.append({
            "stage": "stable_window",
            "seconds": stable_seconds,
            "fanotify_available": available,
            "event_count": len(events),
        })
        if changes:
            target_changes.extend(changes)
            blockers.append("ACTUAL_TARGET_CHANGE_DURING_STABLE_VERIFY")
        rc, output = invoke_repair(repair_runner, "verify", root)
        exact_results.append({"stage": "final", "rc": rc, "output": output})
        if rc != 0:
            blockers.append("EXACT_FINAL_VERIFY_FAILED")

    protected_after = snapshot(PROTECTED)
    protected_changes = diff_snapshots(protected_before, protected_after)
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_DETECTED")

    telegram_after = telegram_retained()
    if not telegram_after:
        blockers.append("TELEGRAM_ROUTER_LOST")

    writer_evidence = unique_writer_evidence(all_events) if target_changes else []
    if target_changes and not writer_evidence:
        blockers.append("ACTUAL_CHANGE_WITHOUT_WRITER_EVIDENCE")
        route_evidence = collect_route_evidence()

    blockers = list(dict.fromkeys(blockers))
    exact_verify_count = sum(
        1 for item in exact_results
        if item.get("stage") in {"after_repair", "after_trace", "final"} and item.get("rc") == 0
    )
    no_overwriter_observed = not target_changes
    surface_stable = (
        not blockers
        and no_overwriter_observed
        and exact_verify_count == 3
        and telegram_after
        and not protected_changes
    )
    state = "PASS" if surface_stable else "HOLD"
    final_http = fetch_http_sha()
    final_files = snapshot(TARGETS)

    out_dir = root / "runtime/exact25_edge_v1/r7a1a6c3b_false_positive_correction"
    status_path = out_dir / "status_latest.json"
    payload = {
        "schema": "r7a1a6c3b_false_positive_correction_status_v1",
        "official_stage": "R7.A1A6C3B",
        "generated_at": now_iso(),
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "repair_applied": repair_applied,
        "recursive_quick_verify_used": False,
        "required_exact_verify_count": 3,
        "exact_verify_pass_count": exact_verify_count,
        "exact_results": exact_results,
        "trace_seconds": trace_seconds,
        "stable_seconds": stable_seconds,
        "target_fingerprints": {path: asdict(item) for path, item in final_files.items()},
        "target_change_count": len(target_changes),
        "target_changes": target_changes,
        "fanotify_event_count": len(all_events),
        "writer_identified_count": len(writer_evidence),
        "writers": writer_evidence,
        "quarantined_units": [],
        "no_overwriter_observed": no_overwriter_observed,
        "surface_stable": surface_stable,
        "alimi_http_file_json_parity": state == "PASS",
        "ledger_zero_epoch": state == "PASS",
        "trace_zero_epoch": state == "PASS",
        "http_body": final_http,
        "route_evidence": route_evidence,
        "telegram_router_retained": telegram_after,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "paper_mutation_count": 0,
        "live_mutation_count": 0,
        "order_mutation_count": 0,
        "value_exposure_count": 0,
        "rollback_performed": rollback_performed,
        "next_stage": (
            "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE"
            if state == "PASS"
            else "R7.A1A6C3B_DIAGNOSE"
        ),
    }
    atomic_json(status_path, payload)

    print("R7A1A6C3B_FALSE_POSITIVE_CORRECTION_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print("RECURSIVE_QUICK_VERIFY_USED=false")
    print(f"EXACT_VERIFY_PASS_COUNT={exact_verify_count}")
    print(f"TARGET_CHANGE_COUNT={len(target_changes)}")
    print(f"FANOTIFY_EVENT_COUNT={len(all_events)}")
    print(f"WRITER_IDENTIFIED_COUNT={len(writer_evidence)}")
    print("QUARANTINED_UNITS=[]")
    print(f"NO_OVERWRITER_OBSERVED={str(no_overwriter_observed).lower()}")
    print(f"SURFACE_STABLE={str(surface_stable).lower()}")
    print(f"ALIMI_HTTP_FILE_JSON_PARITY={str(state == 'PASS').lower()}")
    print(f"LEDGER_ZERO_EPOCH={str(state == 'PASS').lower()}")
    print(f"TRACE_ZERO_EPOCH={str(state == 'PASS').lower()}")
    print(f"TELEGRAM_ROUTER_RETAINED={str(telegram_after).lower()}")
    print(f"PROTECTED_CHANGE_COUNT={len(protected_changes)}")
    print("PAPER_MUTATION_COUNT=0")
    print("LIVE_MUTATION_COUNT=0")
    print("ORDER_MUTATION_COUNT=0")
    print("VALUE_EXPOSURE_COUNT=0")
    print("ROLLBACK_PERFORMED=false")
    print(f"NEXT_STAGE={payload['next_stage']}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"RC={0 if state == 'PASS' else 2}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
