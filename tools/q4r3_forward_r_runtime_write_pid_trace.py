from __future__ import annotations

import argparse
import html
import json
import os
import re
import select
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"
AUTHORITY_IN = RUNTIME / "q4r3_forward_r_source_authority_latest.json"
OWNER_DECISION_IN = RUNTIME / "q4r3_forward_r_entry_writer_owner_decision_latest.json"
FREEZE_IN = RUNTIME / "q4r3_raschke_freeze_manifest_latest.json"

TRACE_OUT = RUNTIME / "q4r3_forward_r_runtime_write_pid_trace_latest.json"
DECISION_OUT = RUNTIME / "q4r3_forward_r_runtime_write_pid_decision_latest.json"
HTML_OUT = RUNTIME / "q4r3_forward_r_runtime_write_pid_trace_latest.html"

AUDIT_MSG_RE = re.compile(r"msg=audit\((?P<epoch>[0-9.]+):(?P<serial>[0-9]+)\)")
FIELD_RE_TEMPLATE = r"(?:^|\s){name}=(?:\"(?P<quoted>[^\"]*)\"|(?P<bare>[^\s]+))"
UNIT_RE = re.compile(r"(?P<unit>[A-Za-z0-9_.@\\x2d-]+\.(?:service|scope))")
SCRIPT_SUFFIXES = (".py", ".sh")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(errors="ignore"))


def field_value(line: str, name: str) -> Optional[str]:
    match = re.search(FIELD_RE_TEMPLATE.format(name=re.escape(name)), line)
    if not match:
        return None
    return match.group("quoted") if match.group("quoted") is not None else match.group("bare")


def target_rows(authority: Dict[str, Any]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for item in authority.get("authoritative_files", []):
        path = Path(str(item.get("path", "")))
        row_count = int(item.get("rows", 0) or 0)
        open_rows = int(item.get("open_rows", 0) or 0)
        if not path.is_absolute() or not path.exists() or not path.is_file():
            continue
        if row_count <= 0 and open_rows <= 0:
            continue
        result.append({"path": str(path), "basename": path.name})
    unique = {item["path"]: item for item in result}
    return [unique[key] for key in sorted(unique)]


def path_matches_target(path_text: str, targets: Sequence[Dict[str, str]]) -> Optional[str]:
    if not path_text:
        return None
    cleaned = path_text.replace(" (deleted)", "")
    basename = Path(cleaned).name
    for target in targets:
        target_path = target["path"]
        target_base = target["basename"]
        if cleaned == target_path:
            return target_base
        if basename == target_base:
            return target_base
        if basename.startswith(target_base + ".") or basename.startswith("." + target_base + "."):
            return target_base
        if basename.endswith("." + target_base + ".tmp"):
            return target_base
    return None


def parse_audit_events(text: str) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = AUDIT_MSG_RE.search(line)
        if not match:
            continue
        serial = match.group("serial")
        event = grouped.setdefault(
            serial,
            {
                "serial": serial,
                "epoch": float(match.group("epoch")),
                "paths": [],
                "record_types": [],
            },
        )
        record_type = field_value(line, "type")
        if record_type is None and line.startswith("type="):
            record_type = line.split(None, 1)[0].split("=", 1)[1]
        if record_type:
            event["record_types"].append(record_type)
        if line.startswith("type=SYSCALL") or " type=SYSCALL" in line:
            for key in ("pid", "ppid", "comm", "exe", "syscall", "success", "exit"):
                value = field_value(line, key)
                if value is not None:
                    event[key] = value
        if line.startswith("type=PATH") or " type=PATH" in line or line.startswith("type=CWD"):
            name = field_value(line, "name")
            if name:
                event["paths"].append(name)
        cwd = field_value(line, "cwd")
        if cwd:
            event["cwd"] = cwd
    return sorted(grouped.values(), key=lambda item: (item["epoch"], int(item["serial"])))


def proc_snapshot(pid: int) -> Dict[str, Any]:
    proc = Path("/proc") / str(pid)
    payload: Dict[str, Any] = {"pid": pid, "alive": proc.exists()}
    if not proc.exists():
        return payload
    try:
        payload["exe"] = os.readlink(proc / "exe")
    except OSError:
        pass
    try:
        raw = (proc / "cmdline").read_bytes().split(b"\0")
        argv = [part.decode("utf-8", errors="replace") for part in raw if part]
        payload["argv"] = argv[:40]
        payload["cmdline"] = " ".join(argv)[:4096]
        payload["repo_scripts"] = [
            arg
            for arg in argv
            if arg.startswith("/home/z/z/") and arg.lower().endswith(SCRIPT_SUFFIXES)
        ]
    except OSError:
        pass
    try:
        cgroup = (proc / "cgroup").read_text(errors="ignore")
        payload["cgroup"] = cgroup[:4096]
        units = sorted(set(match.group("unit") for match in UNIT_RE.finditer(cgroup)))
        payload["systemd_units"] = units
    except OSError:
        pass
    try:
        stat_parts = (proc / "stat").read_text(errors="ignore").split()
        if len(stat_parts) > 3:
            payload["ppid"] = int(stat_parts[3])
    except (OSError, ValueError):
        pass
    return payload


def parent_chain(pid: int, limit: int = 6) -> List[Dict[str, Any]]:
    chain: List[Dict[str, Any]] = []
    seen = set()
    current = pid
    for _ in range(limit):
        if current <= 1 or current in seen:
            break
        seen.add(current)
        snapshot = proc_snapshot(current)
        chain.append(snapshot)
        parent = snapshot.get("ppid")
        if not isinstance(parent, int):
            break
        current = parent
    return chain


def owner_identity(event: Dict[str, Any]) -> str:
    units = event.get("systemd_units") or []
    scripts = event.get("repo_scripts") or []
    if units and scripts:
        return f"unit:{units[0]}|script:{scripts[0]}"
    if units:
        return f"unit:{units[0]}"
    if scripts:
        return f"script:{scripts[0]}"
    exe = event.get("exe") or event.get("audit_exe")
    comm = event.get("comm")
    if exe:
        return f"exe:{exe}"
    if comm:
        return f"comm:{comm}"
    return "UNKNOWN"


def enrich_audit_event(event: Dict[str, Any], targets: Sequence[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    matched = sorted(set(filter(None, (path_matches_target(path, targets) for path in event.get("paths", [])))))
    if not matched:
        return None
    pid_text = event.get("pid")
    pid = int(pid_text) if str(pid_text or "").isdigit() else None
    enriched: Dict[str, Any] = {
        "serial": event["serial"],
        "observed_at": datetime.fromtimestamp(event["epoch"], tz=timezone.utc).isoformat(),
        "matched_target_basenames": matched,
        "observed_paths": sorted(set(event.get("paths", [])))[:30],
        "pid": pid,
        "ppid": int(event["ppid"]) if str(event.get("ppid", "")).isdigit() else None,
        "comm": event.get("comm"),
        "audit_exe": event.get("exe"),
        "syscall": event.get("syscall"),
        "success": event.get("success"),
    }
    if pid is not None:
        snap = proc_snapshot(pid)
        enriched.update({key: value for key, value in snap.items() if key not in {"pid", "ppid"}})
        enriched["parent_chain"] = parent_chain(pid)
        parent_units: List[str] = []
        parent_scripts: List[str] = []
        for parent in enriched["parent_chain"]:
            parent_units.extend(parent.get("systemd_units") or [])
            parent_scripts.extend(parent.get("repo_scripts") or [])
        if not enriched.get("systemd_units") and parent_units:
            enriched["systemd_units"] = sorted(set(parent_units))
        if not enriched.get("repo_scripts") and parent_scripts:
            enriched["repo_scripts"] = sorted(set(parent_scripts))
    enriched["owner_identity"] = owner_identity(enriched)
    return enriched


def ausearch_text(key: str) -> str:
    process = subprocess.run(
        ["ausearch", "-k", key, "-ts", "today", "-i"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    return process.stdout or ""


def audit_monitor(key: str, duration: int, poll_seconds: float, targets: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    started = time.monotonic()
    seen_serials = set()
    relevant: List[Dict[str, Any]] = []
    while time.monotonic() - started < duration:
        try:
            events = parse_audit_events(ausearch_text(key))
        except (OSError, subprocess.SubprocessError):
            events = []
        for event in events:
            if event["serial"] in seen_serials:
                continue
            seen_serials.add(event["serial"])
            enriched = enrich_audit_event(event, targets)
            if enriched is not None:
                relevant.append(enriched)
        confirmed = [item for item in relevant if item.get("owner_identity") not in (None, "UNKNOWN")]
        if len(confirmed) >= 2:
            owner_counts = Counter(item["owner_identity"] for item in confirmed)
            if owner_counts.most_common(1)[0][1] >= 2:
                break
        time.sleep(max(poll_seconds, 0.25))
    return {
        "backend": "auditd",
        "audit_key": key,
        "duration_requested_sec": duration,
        "duration_actual_sec": round(time.monotonic() - started, 3),
        "audit_serials_seen": len(seen_serials),
        "events": relevant,
    }


def scan_target_fds(targets: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    results = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            pid = int(proc.name)
        except ValueError:
            continue
        fd_dir = proc / "fd"
        if not fd_dir.exists():
            continue
        matched = set()
        try:
            descriptors = list(fd_dir.iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                linked = os.readlink(descriptor)
            except OSError:
                continue
            target = path_matches_target(linked, targets)
            if target:
                matched.add(target)
        if matched:
            snapshot = proc_snapshot(pid)
            snapshot["matched_target_basenames"] = sorted(matched)
            snapshot["owner_identity"] = owner_identity(snapshot)
            results.append(snapshot)
    return results


def inotify_monitor(duration: int, targets: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    command = [
        "inotifywait", "-m", "-q", "-e", "create,modify,close_write,moved_to,attrib",
        "--format", "%T|%e|%w%f", "--timefmt", "%Y-%m-%dT%H:%M:%S%z", str(RUNTIME),
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    started = time.monotonic()
    events: List[Dict[str, Any]] = []
    try:
        while time.monotonic() - started < duration:
            if process.stdout is None:
                break
            readable, _, _ = select.select([process.stdout], [], [], 0.5)
            if not readable:
                continue
            line = process.stdout.readline().strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            observed_at, kinds, path_text = parts
            matched = path_matches_target(path_text, targets)
            if not matched:
                continue
            owners = scan_target_fds(targets)
            events.append({
                "observed_at": observed_at,
                "event_kinds": kinds,
                "observed_path": path_text,
                "matched_target_basenames": [matched],
                "fd_owner_snapshots": owners,
                "owner_identity": owners[0]["owner_identity"] if len(owners) == 1 else "UNKNOWN",
            })
            confirmed = [item for item in events if item.get("owner_identity") not in (None, "UNKNOWN")]
            if len(confirmed) >= 2:
                break
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return {
        "backend": "inotify_fd_snapshot",
        "duration_requested_sec": duration,
        "duration_actual_sec": round(time.monotonic() - started, 3),
        "events": events,
        "pid_proof_strength": "BEST_EFFORT_ONLY",
    }


def decide(trace: Dict[str, Any], targets: Sequence[Dict[str, str]], prior: Dict[str, Any]) -> Dict[str, Any]:
    events = trace.get("events", [])
    owner_counts = Counter(
        item.get("owner_identity")
        for item in events
        if item.get("owner_identity") not in (None, "UNKNOWN")
    )
    target_owners: Dict[str, set] = defaultdict(set)
    for item in events:
        owner = item.get("owner_identity")
        if owner in (None, "UNKNOWN"):
            continue
        for basename in item.get("matched_target_basenames", []):
            target_owners[basename].add(owner)
    observed_targets = sorted(target_owners)
    all_owners = sorted(owner_counts)
    backend = trace.get("backend")

    if backend == "unavailable":
        verdict = "RUNTIME_WRITE_TRACE_BACKEND_UNAVAILABLE"
        action = "HOLD"
        next_action = "INSTALL_OR_ENABLE_AUDITD_THEN_RERUN_TRACE"
    elif not events:
        verdict = "NO_AUTHORITATIVE_OPEN_WRITE_EVENT_OBSERVED"
        action = "HOLD"
        next_action = "KEEP_TRACE_ACTIVE_UNTIL_NEXT_FORWARD_OPEN_WRITE"
    elif not all_owners:
        verdict = "AUTHORITATIVE_WRITE_EVENT_SEEN_OWNER_UNRESOLVED"
        action = "HOLD"
        next_action = "RETRY_WITH_AUDITD_PID_PROOF"
    elif len(all_owners) == 1 and backend == "auditd":
        verdict = "RUNTIME_ENTRY_WRITER_OWNER_CONFIRMED"
        action = "HOLD"
        next_action = "READ_ONLY_INSPECT_CONFIRMED_OWNER_BEFORE_ENTRY_RISK_CANARY"
    elif len(all_owners) == 1:
        verdict = "RUNTIME_ENTRY_WRITER_OWNER_PROVISIONAL"
        action = "HOLD"
        next_action = "CONFIRM_OWNER_WITH_AUDITD_BEFORE_PATCH"
    else:
        verdict = "RUNTIME_ENTRY_WRITER_DISTRIBUTED"
        action = "HOLD"
        next_action = "DESIGN_APPEND_ONLY_ENTRY_RISK_SIDECAR_AT_AUTHORITY_BOUNDARY"

    return {
        "status": "PASS_Q4R3_FORWARD_R_RUNTIME_WRITE_PID_DECISION",
        "verdict": verdict,
        "action": action,
        "next_action": next_action,
        "trace_backend": backend,
        "target_file_count": len(targets),
        "observed_event_count": len(events),
        "observed_target_count": len(observed_targets),
        "observed_target_basenames": observed_targets,
        "owner_counts": dict(owner_counts),
        "target_owners": {key: sorted(value) for key, value in sorted(target_owners.items())},
        "prior_stable_id_join_rate_pct": prior.get("prior_stable_id_join_rate_pct"),
        "raw_trade_ids_emitted": False,
        "next_modules": [
            next_action,
            "FORWARD_ENTRY_RISK_CANARY_ONLY_AFTER_OWNER_PROOF",
            "VERIFY_NEW_CLOSE_REALIZED_R",
        ],
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
            "final_holdout_opened": False,
        },
    }


def write_html(trace: Dict[str, Any], decision: Dict[str, Any]) -> None:
    rows = []
    for item in trace.get("events", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('observed_at', '')))}</td>"
            f"<td>{html.escape(', '.join(item.get('matched_target_basenames', [])))}</td>"
            f"<td>{html.escape(str(item.get('pid', '')))}</td>"
            f"<td>{html.escape(str(item.get('owner_identity', 'UNKNOWN')))}</td>"
            f"<td>{html.escape(str(item.get('cmdline', item.get('audit_exe', ''))))}</td>"
            "</tr>"
        )
    page = "".join([
        "<!doctype html><html><head><meta charset='utf-8'><title>Runtime writer PID trace</title>",
        "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px;vertical-align:top}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
        "<h1>Authoritative runtime writer PID trace</h1>",
        "<table><thead><tr><th>Observed</th><th>Target</th><th>PID</th><th>Owner</th><th>Command</th></tr></thead><tbody>",
        "".join(rows), "</tbody></table><h2>Decision</h2><pre>",
        html.escape(json.dumps(decision, ensure_ascii=False, indent=2)),
        "</pre></body></html>",
    ])
    HTML_OUT.write_text(page, encoding="utf-8")


def unavailable_trace(reason: str, duration: int) -> Dict[str, Any]:
    return {
        "status": "PASS_Q4R3_FORWARD_R_RUNTIME_WRITE_TRACE_PRECHECK",
        "backend": "unavailable",
        "reason": reason,
        "duration_requested_sec": duration,
        "events": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("audit", "inotify", "unavailable"), required=True)
    parser.add_argument("--audit-key", default="")
    parser.add_argument("--duration", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--unavailable-reason", default="")
    args = parser.parse_args()

    authority = load_json(AUTHORITY_IN)
    prior = load_json(OWNER_DECISION_IN)
    freeze = load_json(FREEZE_IN)
    if freeze.get("raschke_state") != "FROZEN_OBSERVER_RESERVE":
        raise RuntimeError("RASCHKE_FREEZE_CONTRACT_MISSING")
    targets = target_rows(authority)
    if not targets:
        raise RuntimeError("AUTHORITATIVE_OPEN_TARGETS_MISSING")

    if args.backend == "audit":
        if not args.audit_key:
            raise RuntimeError("AUDIT_KEY_MISSING")
        trace = audit_monitor(args.audit_key, max(args.duration, 1), args.poll_seconds, targets)
    elif args.backend == "inotify":
        trace = inotify_monitor(max(args.duration, 1), targets)
    else:
        trace = unavailable_trace(args.unavailable_reason or "TRACE_BACKEND_NOT_AVAILABLE", max(args.duration, 1))

    trace.update({
        "status": "PASS_Q4R3_FORWARD_R_RUNTIME_WRITE_PID_TRACE",
        "generated_at": utc_now(),
        "targets": targets,
        "target_file_count": len(targets),
        "raw_trade_ids_emitted": False,
    })
    decision = decide(trace, targets, prior)
    atomic_json(TRACE_OUT, trace)
    atomic_json(DECISION_OUT, decision)
    write_html(trace, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
