from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

EXACT25_MANIFEST = "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
EXACT25_BINDING = "backend/config/q4r3_exact25_shadow_binding_v1.json"
EXACT25_LOADER = "q4r3_exact25_shadow_manifest_loader"
MEASUREMENT_UNIT = "q4r3-exact25-forward-measurement-writer.service"
WATCHER_UNIT = "q4r3-forward-r-persistent-write-watch.service"

STRATEGY_KEYS = ("strategy_id", "strategy", "strategy_name", "last_strategy")
EVENT_KEYS = (
    "event_id", "shadow_id", "trade_id", "position_id", "request_id",
    "last_close_event_id", "last_closed_shadow_id",
)
EXIT_KEYS = ("exit_ts", "closed_at", "close_ts")
TIME_KEYS = (
    "timestamp", "ts", "updated_at", "created_at", "started_at", "entry_ts",
    "open_ts", "opened_at", "exit_ts", "closed_at", "close_ts",
)
STATE_KEYS = ("state", "status", "position_status", "last_close_status")
CLOSE_VALUE_KEYS = (
    "realized_pnl_usdt", "realized_pnl", "pnl_usdt", "pnl",
    "realized_R", "realized_r", "pnl_r", "effective_pnl_r",
    "initial_risk_usdt", "risk_usdt", "stop_price", "sl",
)
AUDIT_NAME_TOKENS = (
    "audit", "coverage", "decision", "handoff", "manifest", "surface",
    "trace", "probe", "report", "test", "candidate", "roadmap", "forensic",
    "raschke", "route_a", "replay", "tournament", "snapshot", "completeness",
)
SOURCE_SUFFIXES = {".py", ".sh", ".service", ".timer", ".json", ".yaml", ".yml", ".toml"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def walk_dicts(value: Any, depth: int = 0) -> Iterable[Mapping[str, Any]]:
    if depth > 12:
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child, depth + 1)


def first(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        if 1_500_000_000 <= number <= 2_100_000_000:
            return number
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_timestamp(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        epoch = parsed.timestamp()
        if 1_500_000_000 <= epoch <= 2_100_000_000:
            return epoch
    except ValueError:
        return None
    return None


def closed_marker(row: Mapping[str, Any]) -> bool:
    for key in ("closed", "is_closed", "shadow_closed", "closed_phase_written", "actual_close_written"):
        if row.get(key) is True:
            return True
    state = str(first(row, STATE_KEYS) or "").upper()
    if any(token in state for token in ("CLOSED", "EXITED", "CLOSE_WRITTEN")):
        return True
    return first(row, EXIT_KEYS) is not None and first(row, STRATEGY_KEYS) is not None


def inspect_runtime_json(path: Path, exact25: Set[str], now_epoch: float) -> Dict[str, Any]:
    stat = path.stat()
    payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    strategies: Set[str] = set()
    events: Set[str] = set()
    states: Set[str] = set()
    timestamps: List[float] = []
    close_markers = 0
    close_value_hits = 0

    for row in walk_dicts(payload):
        strategy = first(row, STRATEGY_KEYS)
        event = first(row, EVENT_KEYS)
        state = first(row, STATE_KEYS)
        if strategy:
            strategies.add(str(strategy))
        if event:
            events.add(str(event))
        if state:
            states.add(str(state))
        if closed_marker(row):
            close_markers += 1
        close_value_hits += sum(1 for key in CLOSE_VALUE_KEYS if row.get(key) not in (None, ""))
        for key in TIME_KEYS:
            if key in row:
                parsed = parse_timestamp(row.get(key))
                if parsed is not None:
                    timestamps.append(parsed)

    latest_content_ts = max(timestamps) if timestamps else None
    content_age = now_epoch - latest_content_ts if latest_content_ts is not None else None
    mtime_age = now_epoch - stat.st_mtime
    exact_hits = sorted(strategies & exact25)
    audit_like = any(token in path.name.lower() for token in AUDIT_NAME_TOKENS)
    has_close_evidence = close_markers > 0 or bool(first({"x": None}, ())) or close_value_hits > 0

    if audit_like:
        classification = "AUDIT_OR_DERIVED"
    elif has_close_evidence and content_age is not None and content_age <= 6 * 3600:
        classification = "FRESH_CLOSE_CANDIDATE"
    elif has_close_evidence:
        classification = "STALE_OR_UNTIMED_CLOSE"
    elif mtime_age <= 6 * 3600:
        classification = "FRESH_NON_CLOSE"
    else:
        classification = "OTHER"

    score = 0
    if classification == "FRESH_CLOSE_CANDIDATE":
        score += 80
    score += min(len(exact_hits), 25) * 5
    score += min(len(events), 20)
    score += min(close_markers, 10) * 3
    score += min(close_value_hits, 20)
    if any(token in path.name.lower() for token in ("close", "closed", "ledger", "position", "shadow")):
        score += 8

    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
        "mtime_age_sec": round(mtime_age, 3),
        "latest_content_ts": datetime.fromtimestamp(latest_content_ts, timezone.utc).isoformat() if latest_content_ts else None,
        "content_age_sec": round(content_age, 3) if content_age is not None else None,
        "classification": classification,
        "score": score,
        "strategies": sorted(strategies)[:50],
        "exact25_hits": exact_hits,
        "event_count": len(events),
        "states": sorted(states)[:30],
        "close_marker_count": close_markers,
        "close_value_hits": close_value_hits,
    }


def run_command(args: Sequence[str]) -> str:
    completed = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return completed.stdout.strip()


def unit_snapshot(unit: str) -> Dict[str, Any]:
    keys = ("LoadState", "ActiveState", "SubState", "MainPID", "ExecMainStatus", "FragmentPath", "ExecStart")
    text = run_command(["systemctl", "show", unit, *sum((["-p", key] for key in keys), [])])
    result: Dict[str, Any] = {"unit": unit}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def running_units() -> List[str]:
    text = run_command(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"])
    units: List[str] = []
    for line in text.splitlines():
        token = line.strip().split(maxsplit=1)
        if token and token[0].endswith(".service"):
            units.append(token[0])
    return sorted(set(units))


def safe_text(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def source_references(root: Path, needles: Sequence[str]) -> List[Dict[str, Any]]:
    locations: List[Dict[str, Any]] = []
    roots = [root / "backend", root / "tools", root / "services", Path("/etc/systemd/system")]
    excluded = {".git", ".venv", "venv", "node_modules", "__pycache__", "runtime", "backups", "archive", "_TRASH"}
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if any(part in excluded for part in path.parts):
                continue
            text = safe_text(path)
            if not text:
                continue
            matched = [needle for needle in needles if needle in text]
            if not matched:
                continue
            line_numbers: List[int] = []
            for index, line in enumerate(text.splitlines(), 1):
                if any(needle in line for needle in matched):
                    line_numbers.append(index)
            locations.append({
                "path": str(path),
                "sha256": sha256_file(path),
                "matched_tokens": matched,
                "line_numbers": line_numbers[:40],
            })
    return sorted(locations, key=lambda row: row["path"])


def active_exact25_producer_units(units: Sequence[Mapping[str, Any]], references: Sequence[Mapping[str, Any]]) -> List[str]:
    reference_paths = {str(row.get("path")) for row in references}
    producers: List[str] = []
    for unit in units:
        name = str(unit.get("unit") or "")
        if name in {MEASUREMENT_UNIT, WATCHER_UNIT}:
            continue
        if unit.get("ActiveState") != "active" or unit.get("SubState") != "running":
            continue
        fragment = str(unit.get("FragmentPath") or "")
        exec_start = str(unit.get("ExecStart") or "")
        combined = fragment + " " + exec_start
        exact_ref = any(token in combined for token in (EXACT25_MANIFEST, EXACT25_BINDING, EXACT25_LOADER, "exact25"))
        fragment_ref = fragment in reference_paths
        if exact_ref or fragment_ref:
            producers.append(name)
    return sorted(set(producers))


def audit(root: Path, max_runtime_files: int = 5000) -> Dict[str, Any]:
    manifest_path = root / EXACT25_MANIFEST
    binding_path = root / EXACT25_BINDING
    manifest = load_json(manifest_path)
    binding = load_json(binding_path)
    entries = manifest.get("strategies")
    if not isinstance(entries, list) or len(entries) != 25:
        raise RuntimeError("MANIFEST_NOT_EXACT25")
    exact25 = {str(row.get("strategy_id") or "").strip() for row in entries if isinstance(row, dict)}
    if len(exact25) != 25 or "" in exact25:
        raise RuntimeError("MANIFEST_IDENTITY_GAP")

    unit_names = running_units()
    priority_units = {MEASUREMENT_UNIT, WATCHER_UNIT, "z-worker.service", "zel-w286w7t5-position-canonical-firewall.service"}
    snapshots = [unit_snapshot(unit) for unit in sorted(set(unit_names) | priority_units)]

    needles = (
        EXACT25_MANIFEST,
        Path(EXACT25_MANIFEST).name,
        EXACT25_BINDING,
        Path(EXACT25_BINDING).name,
        EXACT25_LOADER,
    )
    references = source_references(root, needles)
    producer_units = active_exact25_producer_units(snapshots, references)

    runtime_root = root / "runtime"
    inspected: List[Dict[str, Any]] = []
    now_epoch = time.time()
    count = 0
    for path in runtime_root.rglob("*.json"):
        if count >= max_runtime_files:
            break
        count += 1
        text_path = str(path)
        if "/exact25_edge_v1/" in text_path:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size <= 0 or stat.st_size > 12 * 1024 * 1024:
            continue
        if now_epoch - stat.st_mtime > 7 * 24 * 3600:
            continue
        try:
            row = inspect_runtime_json(path, exact25, now_epoch)
        except Exception:
            continue
        if row["score"] > 0 or row["classification"] in {"FRESH_CLOSE_CANDIDATE", "STALE_OR_UNTIMED_CLOSE"}:
            inspected.append(row)

    inspected.sort(key=lambda row: (-int(row["score"]), float(row["mtime_age_sec"])))
    top_runtime = inspected[:50]
    fresh_close = [row for row in top_runtime if row["classification"] == "FRESH_CLOSE_CANDIDATE"]

    canary_status_path = root / "runtime/exact25_edge_v1/first_real_forward_canary/status_latest.json"
    canary_status = load_json(canary_status_path) if canary_status_path.exists() else None
    measurement = next((row for row in snapshots if row.get("unit") == MEASUREMENT_UNIT), {})
    watcher = next((row for row in snapshots if row.get("unit") == WATCHER_UNIT), {})

    if not producer_units:
        verdict = "EXACT25_SHADOW_PRODUCER_NOT_BOUND"
        next_action = "BUILD_ROLLBACK_GUARDED_DEDICATED_EXACT25_SHADOW_PRODUCER_USING_ACTIVE_MARKET_FEED"
    elif not fresh_close:
        verdict = "EXACT25_PRODUCER_BOUND_BUT_CLOSE_OUTPUT_UNRESOLVED"
        next_action = "TRACE_BOUND_PRODUCER_CLOSE_OUTPUT_AND_BIND_CANARY_SOURCE"
    else:
        verdict = "EXACT25_PRODUCER_AND_FRESH_CLOSE_SURFACE_FOUND"
        next_action = "BIND_ONLY_PROVEN_CLOSE_SURFACE_TO_FIRST_REAL_FORWARD_CANARY"

    return {
        "schema": "q4r3_exact25_shadow_producer_lineage_audit_v1",
        "created_at": now_iso(),
        "status": "PASS_Q4R3_EXACT25_SHADOW_PRODUCER_LINEAGE_AUDIT",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "read_only": True,
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "paper_request_written": False,
        "live_execution_allowed": False,
        "production_strategy_modified": False,
        "owner_manifest_modified": False,
        "binding_modified": False,
        "epoch_modified": False,
        "writer_modified": False,
        "persistent_forward_r_watcher_modified": False,
        "production_measurement_write_enabled": False,
        "manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
            "strategy_count": len(exact25),
        },
        "binding": {
            "path": str(binding_path),
            "sha256": sha256_file(binding_path),
            "shadow_enabled": binding.get("shadow_enabled"),
            "write_enabled": binding.get("write_enabled"),
            "canary_enabled": binding.get("canary_enabled"),
            "paper_enabled": binding.get("paper_enabled"),
            "live_enabled": binding.get("live_enabled"),
            "order_enabled": binding.get("order_enabled"),
        },
        "measurement_service": measurement,
        "watcher_service": watcher,
        "canary_status": canary_status,
        "active_exact25_producer_units": producer_units,
        "exact25_reference_locations": references,
        "fresh_close_candidate_count": len(fresh_close),
        "fresh_close_candidates": fresh_close[:15],
        "runtime_candidate_count": len(inspected),
        "runtime_candidates": top_runtime,
    }


def render_html(payload: Mapping[str, Any]) -> str:
    escaped = json.dumps(dict(payload), ensure_ascii=False, indent=2).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "<!doctype html><meta charset='utf-8'><title>Exact25 Shadow Producer Lineage</title><pre>" + escaped + "</pre>"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    args = parser.parse_args()
    payload = audit(args.root.resolve())
    atomic_json(args.output, payload)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "verdict": payload["verdict"],
        "next_action": payload["next_action"],
        "active_exact25_producer_units": payload["active_exact25_producer_units"],
        "fresh_close_candidate_count": payload["fresh_close_candidate_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
