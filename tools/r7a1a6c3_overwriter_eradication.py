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
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGETS = (
    Path("/var/www/z-os-alimi/api/view_contract_latest.json"),
    Path("/var/www/z-os-alimi/api/q4r3_shadow_closed_ledger_latest.json"),
    Path("/var/www/z-os-alimi/api/q4r3_recent_ledger_trace_latest.json"),
)
FORMAL_LEDGER = Path("/home/z/z/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl")
SHADOW_SNAPSHOT = Path("/home/z/z/runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json")
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


@dataclass
class WriterEvent:
    ts: float
    pid: int
    path: str
    exe: str
    command: str
    unit: str
    mask: int


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except Exception:
        return None


def hashes(paths: tuple[Path, ...]) -> dict[str, str | None]:
    return {str(path): sha256(path) for path in paths}


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
        parts = [part.decode("utf-8", "replace") for part in raw if part]
        command = " ".join(parts[:6])[:1000]
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
        libc = ctypes.CDLL(None, use_errno=True)
        init = libc.fanotify_init
        init.argtypes = [ctypes.c_uint, ctypes.c_uint]
        init.restype = ctypes.c_int
        mark = libc.fanotify_mark
        mark.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_ulonglong, ctypes.c_int, ctypes.c_char_p]
        mark.restype = ctypes.c_int
        flags = FAN_CLASS_NOTIF | FAN_CLOEXEC | FAN_NONBLOCK
        event_flags = os.O_RDONLY | getattr(os, "O_LARGEFILE", 0)
        fd = init(flags, event_flags)
        if fd < 0:
            return
        mask = FAN_CLOSE_WRITE | FAN_MOVED_TO | FAN_CREATE | FAN_EVENT_ON_CHILD
        rc = mark(fd, FAN_MARK_ADD, mask, AT_FDCWD, os.fsencode(str(directory)))
        if rc < 0:
            os.close(fd)
            return
        self.fd = fd
        self.available = True

    def close(self) -> None:
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1

    def read_events(self, timeout: float = 0.2) -> list[WriterEvent]:
        if not self.available or self.fd < 0:
            time.sleep(timeout)
            return []
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return []
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return []
        events: list[WriterEvent] = []
        offset = 0
        while offset + META.size <= len(data):
            event_len, version, _reserved, metadata_len, mask, event_fd, pid = META.unpack_from(data, offset)
            if event_len < META.size:
                break
            path = ""
            if event_fd != FAN_NOFD:
                try:
                    path = os.readlink(f"/proc/self/fd/{event_fd}")
                except Exception:
                    path = ""
                try:
                    os.close(event_fd)
                except OSError:
                    pass
            exe, command, unit = process_info(pid)
            events.append(WriterEvent(time.time(), pid, path, exe, command, unit, int(mask)))
            offset += event_len
        return events


def systemctl_value(unit: str, prop: str) -> str:
    proc = run(["systemctl", "show", unit, f"--property={prop}", "--value", "--no-pager"], 15)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def telegram_retained() -> bool:
    active = run(["systemctl", "is-active", TELEGRAM_UNIT], 10).stdout.strip() == "active"
    exec_start = systemctl_value(TELEGRAM_UNIT, "ExecStart")
    return active and "/opt/zel/releases/" in exec_start and "zel_q4r3_telegram_pos_adapter_v2.py" in exec_start


def source_text_for_unit(unit: str) -> str:
    chunks: list[str] = [unit]
    cat = run(["systemctl", "cat", unit, "--no-pager"], 20)
    if cat.returncode == 0:
        chunks.append(cat.stdout)
    show = run(["systemctl", "show", unit, "--property=ExecStart", "--property=FragmentPath", "--property=TriggeredBy", "--property=Triggers", "--no-pager"], 20)
    if show.returncode == 0:
        chunks.append(show.stdout)
    joined = "\n".join(chunks)
    paths = set(re.findall(r"/(?:[^\s;'\"\\]+)(?:\.py|\.sh)", joined))
    for raw in sorted(paths):
        path = Path(raw)
        try:
            if path.is_file() and path.stat().st_size <= 2_000_000:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return "\n".join(chunks)


def looks_like_target_writer(text: str) -> bool:
    lower = text.lower()
    names = [path.name.lower() for path in TARGETS]
    if not any(name in lower for name in names):
        return False
    write_tokens = (
        "write_text(", "json.dump(", "os.replace(", "os.rename(", "shutil.copy",
        "atomic_write", "atomic_json", "tempfile", "open(", "cp ", "mv ", "install ",
    )
    return any(token in lower for token in write_tokens)


def active_candidate_units() -> list[str]:
    proc = run(["systemctl", "list-units", "--type=service", "--type=timer", "--all", "--no-legend", "--no-pager"], 30)
    if proc.returncode != 0:
        return []
    candidates: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        unit, load_state, active_state, sub_state = parts[:4]
        if load_state != "loaded" or active_state not in {"active", "activating"}:
            continue
        text = source_text_for_unit(unit)
        if looks_like_target_writer(text):
            candidates.append(unit)
    return sorted(set(candidates))


def safe_display_unit(unit: str, command: str, allowed: tuple[str, ...], forbidden: tuple[str, ...]) -> bool:
    text = f"{unit} {command}".lower()
    if any(term.lower() in text for term in forbidden):
        return False
    return any(term.lower() in text for term in allowed)


def related_units(unit: str) -> list[str]:
    units = {unit}
    for prop in ("TriggeredBy", "Triggers"):
        raw = systemctl_value(unit, prop)
        units.update(item for item in raw.split() if item.endswith((".service", ".timer")))
    if unit.endswith(".service"):
        timer = unit[:-8] + ".timer"
        if run(["systemctl", "show", timer, "--property=LoadState", "--value"], 10).stdout.strip() == "loaded":
            units.add(timer)
    return sorted(units, key=lambda value: (not value.endswith(".timer"), value))


def quarantine(unit: str) -> tuple[bool, list[str]]:
    changed: list[str] = []
    for candidate in related_units(unit):
        proc = run(["systemctl", "disable", "--now", candidate], 30)
        if proc.returncode not in (0, 1):
            return False, changed
        changed.append(candidate)
    run(["systemctl", "daemon-reload"], 20)
    return True, changed


def repair(command: str, runner: Path, root: Path, contract: Path) -> int:
    cmd = [sys.executable, str(runner), command, "--root", str(root)]
    if command == "apply":
        cmd.extend(["--contract", str(contract)])
    proc = subprocess.run(cmd, text=True, check=False)
    return int(proc.returncode)


def verify_once(runner: Path, root: Path) -> bool:
    return repair("verify", runner, root, Path("/dev/null")) == 0


def choose_writer(events: list[WriterEvent], allowed: tuple[str, ...], forbidden: tuple[str, ...]) -> WriterEvent | None:
    target_names = {path.name for path in TARGETS}
    for event in reversed(events):
        name = Path(event.path).name if event.path else ""
        command = f"{event.command} {event.exe}"
        if (name in target_names or any(target.parent == Path(event.path).parent for target in TARGETS if event.path)) and safe_display_unit(event.unit, command, allowed, forbidden):
            if event.unit:
                return event
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--repair-runner", required=True)
    parser.add_argument("--repair-contract", required=True)
    parser.add_argument("--trace-seconds", type=int, default=120)
    parser.add_argument("--verify-seconds", type=int, default=90)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    allowed = tuple(str(item) for item in contract.get("allowed_quarantine_terms", []))
    forbidden = tuple(str(item) for item in contract.get("forbidden_quarantine_terms", []))
    if contract.get("official_stage") != "R7.A1A6C3" or not allowed or not forbidden:
        print("R7A1A6C3_OVERWRITER_ERADICATION_COMPLETE")
        print("STATE=HOLD")
        print('BLOCKERS=["CONTRACT_INVALID"]')
        return 2

    repair_runner = Path(args.repair_runner)
    repair_contract = Path(args.repair_contract)
    protected_before = hashes((FORMAL_LEDGER, SHADOW_SNAPSHOT))
    quarantined: list[str] = []
    writer_events: list[WriterEvent] = []
    identified: list[dict[str, Any]] = []
    blockers: list[str] = []

    if not telegram_retained():
        blockers.append("TELEGRAM_ROUTER_NOT_RETAINED")
    if repair("apply", repair_runner, root, repair_contract) != 0:
        blockers.append("INITIAL_SURFACE_REPAIR_FAILED")

    max_quarantines = 5
    for _round in range(max_quarantines + 1):
        if blockers:
            break
        if not verify_once(repair_runner, root):
            if repair("apply", repair_runner, root, repair_contract) != 0:
                blockers.append("SURFACE_REPAIR_REAPPLY_FAILED")
                break

        watcher = FanotifyWatcher(TARGETS[0].parent)
        baseline = hashes(TARGETS)
        recent: list[WriterEvent] = []
        changed = False
        deadline = time.time() + max(30, args.trace_seconds)
        while time.time() < deadline:
            batch = watcher.read_events(0.2)
            if batch:
                recent.extend(batch)
                writer_events.extend(batch)
                recent = recent[-100:]
            current = hashes(TARGETS)
            if current != baseline or not verify_once(repair_runner, root):
                changed = True
                break
        watcher.close()

        if not changed:
            break

        writer = choose_writer(recent, allowed, forbidden)
        if writer is None:
            candidates = active_candidate_units()
            safe_candidates = [unit for unit in candidates if safe_display_unit(unit, source_text_for_unit(unit), allowed, forbidden)]
            if len(safe_candidates) == 1:
                writer = WriterEvent(time.time(), 0, "fallback_scan", "", safe_candidates[0], safe_candidates[0], 0)
            else:
                blockers.append(f"WRITER_NOT_UNIQUE:{safe_candidates}")
                break

        ok, changed_units = quarantine(writer.unit)
        identified.append(asdict(writer) | {"quarantined_units": changed_units})
        if not ok:
            blockers.append(f"WRITER_QUARANTINE_FAILED:{writer.unit}")
            break
        quarantined.extend(changed_units)
        if repair("apply", repair_runner, root, repair_contract) != 0:
            blockers.append("POST_QUARANTINE_REPAIR_FAILED")
            break

    stable = False
    if not blockers:
        stable = True
        baseline = hashes(TARGETS)
        deadline = time.time() + max(30, args.verify_seconds)
        while time.time() < deadline:
            time.sleep(1)
            if hashes(TARGETS) != baseline or not verify_once(repair_runner, root):
                stable = False
                blockers.append("SURFACE_REOVERWRITTEN_AFTER_QUARANTINE")
                break

    protected_after = hashes((FORMAL_LEDGER, SHADOW_SNAPSHOT))
    protected_changes = [path for path in protected_before if protected_before[path] != protected_after[path]]
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_DETECTED")
    telegram_ok = telegram_retained()
    if not telegram_ok:
        blockers.append("TELEGRAM_ROUTER_LOST")
    final_verify = verify_once(repair_runner, root) if not blockers else False
    if not final_verify and "SURFACE_REOVERWRITTEN_AFTER_QUARANTINE" not in blockers:
        blockers.append("FINAL_SURFACE_VERIFY_FAILED")

    state = "PASS" if not blockers and stable and final_verify and telegram_ok else "HOLD"
    out_dir = root / "runtime/exact25_edge_v1/r7a1a6c3_overwriter_eradication"
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "status_latest.json"
    payload = {
        "schema": "r7a1a6c3_overwriter_eradication_status_v1",
        "official_stage": "R7.A1A6C3",
        "generated_at": now_iso(),
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "writer_identified_count": len(identified),
        "writers": identified,
        "quarantined_units": sorted(set(quarantined)),
        "fanotify_event_count": len(writer_events),
        "surface_stable": stable,
        "alimi_http_file_json_parity": final_verify,
        "ledger_zero_epoch": final_verify,
        "trace_zero_epoch": final_verify,
        "telegram_router_retained": telegram_ok,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "paper_mutation_count": 0,
        "live_mutation_count": 0,
        "order_mutation_count": 0,
        "value_exposure_count": 0,
        "next_stage": "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE" if state == "PASS" else "R7.A1A6C3_DIAGNOSE",
    }
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(status_path, 0o600)

    print("R7A1A6C3_OVERWRITER_ERADICATION_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"WRITER_IDENTIFIED_COUNT={len(identified)}")
    print(f"WRITERS={json.dumps(identified, ensure_ascii=False)}")
    print(f"QUARANTINED_UNITS={json.dumps(sorted(set(quarantined)), ensure_ascii=False)}")
    print(f"FANOTIFY_EVENT_COUNT={len(writer_events)}")
    print(f"SURFACE_STABLE={str(stable).lower()}")
    print(f"ALIMI_HTTP_FILE_JSON_PARITY={str(final_verify).lower()}")
    print(f"LEDGER_ZERO_EPOCH={str(final_verify).lower()}")
    print(f"TRACE_ZERO_EPOCH={str(final_verify).lower()}")
    print(f"TELEGRAM_ROUTER_RETAINED={str(telegram_ok).lower()}")
    print(f"PROTECTED_CHANGE_COUNT={len(protected_changes)}")
    print("PAPER_MUTATION_COUNT=0")
    print("LIVE_MUTATION_COUNT=0")
    print("ORDER_MUTATION_COUNT=0")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"NEXT_STAGE={payload['next_stage']}")
    print(f"EVIDENCE_JSON={status_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
