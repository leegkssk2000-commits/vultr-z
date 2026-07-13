from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Set, Tuple

MANIFEST_REL = "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
CANARY_STATUS_REL = "runtime/exact25_edge_v1/first_real_forward_canary/status_latest.json"
PRODUCER_AUDIT_STATUS_REL = "runtime/q4r3_exact25_shadow_producer_lineage_audit_job_latest.json"
MEASUREMENT_UNIT = "q4r3-exact25-forward-measurement-writer.service"
WATCHER_UNIT = "q4r3-forward-r-persistent-write-watch.service"

STRATEGY_KEYS = ("strategy_id", "strategy", "strategy_name", "last_strategy")
EVENT_KEYS = (
    "event_id", "shadow_id", "trade_id", "position_id", "request_id",
    "last_close_event_id", "last_closed_shadow_id",
)
STATE_KEYS = ("state", "status", "position_status", "last_close_status")
EXIT_KEYS = ("exit_ts", "closed_at", "close_ts", "closed_ts")
TIME_KEYS = (
    "timestamp", "ts", "updated_at", "created_at", "started_at", "entry_ts",
    "open_ts", "opened_at", "exit_ts", "closed_at", "close_ts", "closed_ts",
)
PNL_KEYS = ("realized_pnl_usdt", "realized_pnl", "pnl_usdt", "pnl")
RISK_KEYS = (
    "initial_risk_usdt", "risk_usdt", "stop_price", "sl", "entry_price",
    "entry", "base_qty", "qty", "quantity", "position_size",
)
MODE_KEYS = (
    "mode", "execution_mode", "trade_mode", "account_type", "environment",
    "source_mode", "run_mode", "portfolio_mode", "position_mode",
)
BOOLEAN_MODE_KEYS = {
    "paper": "PAPER",
    "paper_enabled": "PAPER",
    "paper_filled": "PAPER",
    "is_paper": "PAPER",
    "shadow": "SHADOW",
    "shadow_enabled": "SHADOW",
    "is_shadow": "SHADOW",
    "live": "LIVE",
    "live_enabled": "LIVE",
    "is_live": "LIVE",
    "real_order_enabled": "LIVE",
}
NON_PRODUCER_UNIT_TOKENS = (
    "audit", "trace", "probe", "test", "report", "canary", "writer", "watch",
    "doctor", "coverage", "forensic", "replay", "tournament",
)
DERIVED_PATH_TOKENS = (
    "/runtime_results/", "/exact25_edge_v1/", "audit", "trace", "probe",
    "report", "replay", "tournament", "coverage", "decision", "snapshot",
)
SOURCE_SUFFIXES = {".py", ".sh", ".service", ".timer", ".json", ".yaml", ".yml", ".toml"}


def utc_now_iso() -> str:
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


def parse_timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return number if 1_500_000_000 <= number <= 2_100_000_000 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_timestamp(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    epoch = parsed.timestamp()
    return epoch if 1_500_000_000 <= epoch <= 2_100_000_000 else None


def first(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_mode_text(value: Any) -> Set[str]:
    text = str(value or "").strip().lower()
    modes: Set[str] = set()
    if "paper" in text or "paper_filled" in text:
        modes.add("PAPER")
    if "shadow" in text:
        modes.add("SHADOW")
    if "live" in text or "real_order" in text:
        modes.add("LIVE")
    return modes


def row_modes(row: Mapping[str, Any], inherited: Set[str], path: Path) -> Set[str]:
    modes = set(inherited)
    for key in MODE_KEYS:
        if key in row:
            modes.update(normalize_mode_text(row.get(key)))
    for key, mode in BOOLEAN_MODE_KEYS.items():
        value = row.get(key)
        if value is True or (isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}):
            modes.add(mode)
    state = first(row, STATE_KEYS)
    modes.update(normalize_mode_text(state))
    path_text = path.name.lower()
    if "paper_order_ledger" in path_text:
        modes.add("PAPER")
    return modes


def is_close_row(row: Mapping[str, Any]) -> bool:
    for key in ("closed", "is_closed", "shadow_closed", "actual_close_written", "closed_phase_written"):
        if row.get(key) is True:
            return True
    state = str(first(row, STATE_KEYS) or "").upper()
    if any(token in state for token in ("CLOSED", "EXITED", "CLOSE_WRITTEN")):
        return True
    return first(row, EXIT_KEYS) is not None and first(row, STRATEGY_KEYS) is not None


def newest_timestamp(row: Mapping[str, Any]) -> float | None:
    values: List[float] = []
    for key in TIME_KEYS:
        if key in row:
            parsed = parse_timestamp(row.get(key))
            if parsed is not None:
                values.append(parsed)
    return max(values) if values else None


def walk_rows(value: Any, path: Path, inherited_modes: Set[str] | None = None, depth: int = 0) -> Iterable[Tuple[Mapping[str, Any], Set[str]]]:
    if depth > 14:
        return
    inherited = set(inherited_modes or set())
    if isinstance(value, dict):
        modes = row_modes(value, inherited, path)
        yield value, modes
        for child in value.values():
            yield from walk_rows(child, path, modes, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from walk_rows(child, path, inherited, depth + 1)


def inspect_candidate(path: Path, exact25: Set[str], canary_started_epoch: float, now_epoch: float) -> Dict[str, Any]:
    stat = path.stat()
    payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    strategies: Set[str] = set()
    exact_hits: Set[str] = set()
    all_modes: Set[str] = set()
    qualifying_modes: Set[str] = set()
    states: Set[str] = set()
    event_ids: Set[str] = set()
    close_rows = 0
    recent_close_rows = 0
    qualifying_recent_rows = 0
    recent_shadow_rows = 0
    recent_paper_rows = 0
    recent_live_rows = 0
    recent_unknown_rows = 0
    pnl_ready_rows = 0
    risk_ready_rows = 0
    stable_id_rows = 0
    latest_content_ts: float | None = None

    for row, modes in walk_rows(payload, path):
        all_modes.update(modes)
        strategy = first(row, STRATEGY_KEYS)
        if strategy:
            strategy_text = str(strategy)
            strategies.add(strategy_text)
            if strategy_text in exact25:
                exact_hits.add(strategy_text)
        state = first(row, STATE_KEYS)
        if state:
            states.add(str(state))
        event = first(row, EVENT_KEYS)
        if event:
            event_ids.add(str(event))
        row_ts = newest_timestamp(row)
        if row_ts is not None and (latest_content_ts is None or row_ts > latest_content_ts):
            latest_content_ts = row_ts
        if not is_close_row(row):
            continue
        close_rows += 1
        recent = row_ts is not None and row_ts >= canary_started_epoch
        if recent:
            recent_close_rows += 1
        if not recent or not strategy or str(strategy) not in exact25:
            continue
        qualifying_recent_rows += 1
        qualifying_modes.update(modes)
        if modes == {"SHADOW"}:
            recent_shadow_rows += 1
        elif "LIVE" in modes:
            recent_live_rows += 1
        elif "PAPER" in modes:
            recent_paper_rows += 1
        else:
            recent_unknown_rows += 1
        if first(row, PNL_KEYS) is not None:
            pnl_ready_rows += 1
        if any(row.get(key) not in (None, "") for key in RISK_KEYS):
            risk_ready_rows += 1
        if event is not None:
            stable_id_rows += 1

    content_age = now_epoch - latest_content_ts if latest_content_ts is not None else None
    path_text = str(path).lower()
    derived = any(token in path_text for token in DERIVED_PATH_TOKENS)
    pure_shadow = (
        not derived
        and qualifying_recent_rows > 0
        and recent_shadow_rows == qualifying_recent_rows
        and recent_paper_rows == 0
        and recent_live_rows == 0
        and recent_unknown_rows == 0
        and stable_id_rows == qualifying_recent_rows
        and pnl_ready_rows == qualifying_recent_rows
    )
    mixed_filterable = (
        not derived
        and qualifying_recent_rows > 0
        and recent_shadow_rows > 0
        and (recent_paper_rows > 0 or recent_unknown_rows > 0)
        and recent_live_rows == 0
    )
    paper_only_or_mixed = recent_paper_rows > 0 and recent_shadow_rows == 0

    if pure_shadow:
        classification = "PROVEN_PURE_SHADOW_CLOSE_SOURCE"
    elif mixed_filterable:
        classification = "MIXED_SOURCE_FILTERED_SIDECAR_REQUIRED"
    elif paper_only_or_mixed:
        classification = "PAPER_LEDGER_NOT_SHADOW_AUTHORITY"
    elif derived:
        classification = "DERIVED_OR_AUDIT_NOT_AUTHORITY"
    elif qualifying_recent_rows == 0:
        classification = "NO_RECENT_EXACT25_CLOSE_ROWS"
    elif recent_live_rows > 0:
        classification = "LIVE_CONTAMINATION_BLOCK"
    else:
        classification = "UNRESOLVED_MODE_OR_CONTRACT"

    score = 0
    if pure_shadow:
        score += 1000
    elif mixed_filterable:
        score += 500
    score += min(len(exact_hits), 25) * 10
    score += min(qualifying_recent_rows, 100)
    score += min(stable_id_rows, 50)
    score += min(pnl_ready_rows, 50)
    score -= recent_live_rows * 100
    score -= recent_paper_rows * 2
    if derived:
        score -= 1000

    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
        "mtime_age_sec": round(now_epoch - stat.st_mtime, 3),
        "latest_content_ts": datetime.fromtimestamp(latest_content_ts, timezone.utc).isoformat() if latest_content_ts else None,
        "content_age_sec": round(content_age, 3) if content_age is not None else None,
        "classification": classification,
        "score": score,
        "strategies": sorted(strategies)[:50],
        "exact25_hits": sorted(exact_hits),
        "exact25_coverage_count": len(exact_hits),
        "states": sorted(states)[:30],
        "event_count": len(event_ids),
        "close_row_count": close_rows,
        "recent_close_row_count": recent_close_rows,
        "qualifying_recent_exact25_close_count": qualifying_recent_rows,
        "recent_shadow_rows": recent_shadow_rows,
        "recent_paper_rows": recent_paper_rows,
        "recent_live_rows": recent_live_rows,
        "recent_unknown_mode_rows": recent_unknown_rows,
        "stable_id_ready_rows": stable_id_rows,
        "pnl_ready_rows": pnl_ready_rows,
        "risk_context_ready_rows": risk_ready_rows,
        "all_mode_signals": sorted(all_modes),
        "qualifying_mode_signals": sorted(qualifying_modes),
        "derived_or_audit_path": derived,
        "pure_shadow_authority": pure_shadow,
        "filtered_sidecar_candidate": mixed_filterable,
    }


def safe_text(path: Path, max_bytes: int = 3_000_000) -> str:
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def source_references(root: Path, basenames: Sequence[str]) -> List[Dict[str, Any]]:
    roots = [root / "backend", root / "tools", root / "services", Path("/etc/systemd/system")]
    excluded = {".git", ".venv", "venv", "node_modules", "__pycache__", "runtime", "backups", "archive", "_TRASH"}
    results: List[Dict[str, Any]] = []
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
            matched = [name for name in basenames if name and name in text]
            if not matched:
                continue
            lines = [index for index, line in enumerate(text.splitlines(), 1) if any(name in line for name in matched)]
            writer_signals = [
                token for token in ("write_text", "json.dump", "os.replace", "atomic", "rename", "open(", "Path(")
                if token in text
            ]
            results.append({
                "path": str(path),
                "sha256": sha256_file(path),
                "matched_basenames": matched,
                "line_numbers": lines[:60],
                "writer_signals": writer_signals,
            })
    return sorted(results, key=lambda row: row["path"])


def command_output(args: Sequence[str]) -> str:
    completed = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return completed.stdout.strip()


def unit_snapshot(unit: str) -> Dict[str, Any]:
    keys = ("LoadState", "ActiveState", "SubState", "MainPID", "ExecMainStatus", "FragmentPath", "ExecStart")
    args: List[str] = ["systemctl", "show", unit]
    for key in keys:
        args.extend(["-p", key])
    text = command_output(args)
    result: Dict[str, Any] = {"unit": unit}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def running_units() -> List[str]:
    text = command_output(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"])
    units: List[str] = []
    for line in text.splitlines():
        fields = line.strip().split()
        if fields and fields[0].endswith(".service"):
            units.append(fields[0])
    return sorted(set(units))


def eligible_producer_units(units: Sequence[Mapping[str, Any]], reference_paths: Set[str]) -> List[str]:
    eligible: List[str] = []
    for row in units:
        name = str(row.get("unit") or "")
        lower_name = name.lower()
        if name in {MEASUREMENT_UNIT, WATCHER_UNIT}:
            continue
        if any(token in lower_name for token in NON_PRODUCER_UNIT_TOKENS):
            continue
        if row.get("ActiveState") != "active" or row.get("SubState") != "running":
            continue
        fragment = str(row.get("FragmentPath") or "")
        exec_start = str(row.get("ExecStart") or "")
        if fragment in reference_paths or "exact25" in exec_start.lower():
            eligible.append(name)
    return sorted(set(eligible))


def candidate_paths(root: Path, now_epoch: float) -> List[Path]:
    paths: Set[Path] = set()
    audit_status_path = root / PRODUCER_AUDIT_STATUS_REL
    if audit_status_path.exists():
        try:
            status = load_json(audit_status_path)
            result_path = Path(str(status.get("result_path") or ""))
            if result_path.exists():
                result = load_json(result_path)
                for row in result.get("fresh_close_candidates", []):
                    if isinstance(row, dict) and row.get("path"):
                        paths.add(Path(str(row["path"])))
        except Exception:
            pass
    runtime = root / "runtime"
    name_tokens = ("close", "closed", "ledger", "position", "shadow", "pnl", "admission")
    count = 0
    for path in runtime.rglob("*.json"):
        count += 1
        if count > 6000:
            break
        if not any(token in path.name.lower() for token in name_tokens):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size <= 0 or stat.st_size > 16 * 1024 * 1024:
            continue
        if now_epoch - stat.st_mtime > 72 * 3600:
            continue
        paths.add(path)
    return sorted(path for path in paths if path.exists())


def audit(root: Path) -> Dict[str, Any]:
    now_epoch = time.time()
    manifest_path = root / MANIFEST_REL
    canary_status_path = root / CANARY_STATUS_REL
    manifest = load_json(manifest_path)
    canary_status = load_json(canary_status_path)
    strategies = manifest.get("strategies")
    if not isinstance(strategies, list) or len(strategies) != 25:
        raise RuntimeError("MANIFEST_NOT_EXACT25")
    exact25 = {str(row.get("strategy_id") or "").strip() for row in strategies if isinstance(row, dict)}
    if len(exact25) != 25 or "" in exact25:
        raise RuntimeError("MANIFEST_IDENTITY_GAP")
    canary_started_epoch = parse_timestamp(canary_status.get("started_at"))
    if canary_started_epoch is None:
        raise RuntimeError("CANARY_STARTED_AT_INVALID")

    candidates: List[Dict[str, Any]] = []
    for path in candidate_paths(root, now_epoch):
        try:
            candidates.append(inspect_candidate(path, exact25, canary_started_epoch, now_epoch))
        except Exception:
            continue
    candidates.sort(key=lambda row: (-int(row["score"]), float(row["mtime_age_sec"])))

    pure = [row for row in candidates if row["classification"] == "PROVEN_PURE_SHADOW_CLOSE_SOURCE"]
    filterable = [row for row in candidates if row["classification"] == "MIXED_SOURCE_FILTERED_SIDECAR_REQUIRED"]
    paper = [row for row in candidates if row["classification"] == "PAPER_LEDGER_NOT_SHADOW_AUTHORITY"]

    basenames = [Path(str(row["path"])).name for row in candidates[:20]]
    references = source_references(root, basenames)
    reference_paths = {str(row["path"]) for row in references}
    unit_names = sorted(set(running_units()) | {MEASUREMENT_UNIT, WATCHER_UNIT, "z-worker.service", "zel-w286w7t5-position-canonical-firewall.service"})
    units = [unit_snapshot(unit) for unit in unit_names]
    producers = eligible_producer_units(units, reference_paths)

    if pure:
        verdict = "PROVEN_PURE_SHADOW_CLOSE_AUTHORITY_FOUND"
        next_action = "BIND_TOP_PROVEN_SHADOW_SOURCE_TO_FIRST_REAL_FORWARD_CANARY_WITH_ROLLBACK_GUARD"
    elif filterable:
        verdict = "MIXED_CLOSE_SOURCE_REQUIRES_SHADOW_ONLY_FILTER_SIDECAR"
        next_action = "BUILD_FORWARD_ONLY_EXACT25_SHADOW_CLOSE_FILTER_SIDECAR_THEN_BIND_CANARY"
    elif paper:
        verdict = "PAPER_LEDGER_REJECTED_AS_SHADOW_AUTHORITY"
        next_action = "TRACE_OR_BUILD_DEDICATED_EXACT25_SHADOW_CLOSE_PRODUCER"
    else:
        verdict = "NO_PROVEN_EXACT25_SHADOW_CLOSE_AUTHORITY"
        next_action = "BUILD_DEDICATED_EXACT25_SHADOW_PRODUCER_AND_CLOSE_SURFACE"

    return {
        "schema": "q4r3_exact25_close_source_authority_lock_v1",
        "created_at": utc_now_iso(),
        "status": "PASS_Q4R3_EXACT25_CLOSE_SOURCE_AUTHORITY_LOCK",
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
        "canary_source_modified": False,
        "persistent_forward_r_watcher_modified": False,
        "production_measurement_write_enabled": False,
        "manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
            "strategy_count": len(exact25),
        },
        "canary": {
            "path": str(canary_status_path),
            "state": canary_status.get("state"),
            "started_at": canary_status.get("started_at"),
            "heartbeat_count": canary_status.get("heartbeat_count"),
            "writer_invocation_count": canary_status.get("writer_invocation_count"),
            "write_enabled": canary_status.get("write_enabled"),
            "canary_enabled": canary_status.get("canary_enabled"),
            "close_sources": canary_status.get("close_sources"),
        },
        "pure_shadow_authority_count": len(pure),
        "filterable_mixed_source_count": len(filterable),
        "paper_rejected_count": len(paper),
        "top_pure_shadow_authorities": pure[:10],
        "top_filterable_sources": filterable[:10],
        "top_paper_rejections": paper[:10],
        "candidate_count": len(candidates),
        "candidates": candidates[:60],
        "eligible_active_producer_units": producers,
        "source_references": references,
        "unit_snapshots": units,
    }


def render_html(payload: Mapping[str, Any]) -> str:
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2)
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "<!doctype html><meta charset='utf-8'><title>Exact25 Close Source Authority Lock</title><pre>" + escaped + "</pre>"


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
        "pure_shadow_authority_count": payload["pure_shadow_authority_count"],
        "filterable_mixed_source_count": payload["filterable_mixed_source_count"],
        "paper_rejected_count": payload["paper_rejected_count"],
        "eligible_active_producer_units": payload["eligible_active_producer_units"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
