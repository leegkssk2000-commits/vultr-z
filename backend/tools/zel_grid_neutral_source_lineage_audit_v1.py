from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_GRID_NEUTRAL_SOURCE_LINEAGE_AUDIT_V1"
SCHEMA = "zel.grid_neutral.source_lineage_audit.receipt.v1"
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "backup",
    "backups",
}
TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".service", ".sh", ".md"}
SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|secret|token|password|private[_-]?key)\s*[:=]\s*\S+")
UNSAFE_PATTERNS = {
    "negative_shift": re.compile(r"\.shift\(\s*-\d+"),
    "centered_rolling": re.compile(r"rolling\([^\n)]*center\s*=\s*True"),
    "future_index": re.compile(r"(?:iloc|loc)?\s*\[[^\]]*\bi\s*\+\s*\d+"),
    "future_keyword": re.compile(r"(?i)\b(future|lookahead|look_ahead|next_bar|forward_return)\b"),
}
CAUSAL_PATTERNS = {
    "positive_shift": re.compile(r"\.shift\(\s*[1-9]\d*"),
    "past_rolling": re.compile(r"rolling\("),
    "expanding": re.compile(r"expanding\("),
    "current_or_past_slice": re.compile(r"(?:iloc|loc)?\s*\[[^\]]*:\s*(?:i|index|idx)?\s*\+?\s*1?\s*\]"),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_sha(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path.resolve())


def allowed_file(path: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return path.is_file() and size <= 2_000_000 and path.suffix.lower() in TEXT_SUFFIXES


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if allowed_file(path):
            yield path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def redact(text: str, limit: int = 500) -> str:
    value = SECRET_PATTERN.sub(r"\1=<redacted>", text)
    value = re.sub(r"(?i)(Authorization:\s*)\S+", r"\1<redacted>", value)
    return value[:limit]


def matching_lines(text: str, pattern: re.Pattern[str], limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            rows.append({"line": line_number, "text": redact(line.strip(), 260)})
            if len(rows) >= limit:
                break
    return rows


def classify_file(path: Path, text: str) -> list[str]:
    lower_path = str(path).lower()
    lower_text = text.lower()
    roles: list[str] = []
    if path.name == "grid_rebalance.py" or "strategy_name = \"grid_rebalance\"" in lower_text:
        roles.append("strategy_source")
    if "grid_rebalance" in lower_text and any(token in lower_path for token in ("registry", "manifest", "mapping", "owner")):
        roles.append("registry_or_manifest")
    if "grid_rebalance" in lower_text and any(token in lower_path for token in ("replay", "historical", "simulation", "data_b", "data-b")):
        roles.append("replay_or_simulation")
    if "regime" in lower_text and any(token in lower_path for token in ("replay", "feature", "context", "regime", "dataset")):
        roles.append("regime_derivation_candidate")
    if "data-b-1m-v2" in lower_text or "data_b_1m_v2" in lower_text:
        roles.append("terminal_pipeline_reference")
    return sorted(set(roles))


def scan_runtime(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matches: list[dict[str, Any]] = []
    regime_candidates: list[dict[str, Any]] = []
    grid_pattern = re.compile(r"(?i)grid[_-]?rebalance")
    regime_pattern = re.compile(r"(?i)\bregime\b")
    for path in iter_text_files(root):
        try:
            text = read_text(path)
        except OSError:
            continue
        roles = classify_file(path, text)
        if not roles and not grid_pattern.search(text):
            continue
        data = path.read_bytes()
        row = {
            "path": safe_rel(path, root),
            "absolute_path": str(path.resolve()),
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
            "roles": roles,
            "grid_matches": matching_lines(text, grid_pattern),
        }
        matches.append(row)
        if "regime_derivation_candidate" in roles or (regime_pattern.search(text) and "replay_or_simulation" in roles):
            unsafe = {
                name: len(pattern.findall(text))
                for name, pattern in UNSAFE_PATTERNS.items()
                if pattern.search(text)
            }
            causal = {
                name: len(pattern.findall(text))
                for name, pattern in CAUSAL_PATTERNS.items()
                if pattern.search(text)
            }
            regime_candidates.append(
                {
                    "path": row["path"],
                    "sha256": row["sha256"],
                    "regime_matches": matching_lines(text, regime_pattern, 20),
                    "unsafe_pattern_counts": unsafe,
                    "causal_pattern_counts": causal,
                    "static_no_lookahead": not unsafe,
                }
            )
    matches.sort(key=lambda row: ("strategy_source" not in row["roles"], row["path"]))
    regime_candidates.sort(key=lambda row: (not row["static_no_lookahead"], row["path"]))
    return matches, regime_candidates


def load_json_if_exists(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "INVALID_JSON", "sha256": sha256_bytes(path.read_bytes())}


def compact_manifest(value: Any, keyword_pattern: re.Pattern[str], path: str = "$") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if keyword_pattern.search(str(key)) or (isinstance(child, str) and keyword_pattern.search(child)):
                rendered = child if isinstance(child, (str, int, float, bool)) or child is None else type(child).__name__
                rows.append({"path": child_path, "value": redact(str(rendered), 300)})
            rows.extend(compact_manifest(child, keyword_pattern, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:5000]):
            rows.extend(compact_manifest(child, keyword_pattern, f"{path}[{index}]"))
    return rows[:300]


def normalize_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric / 1000.0 if numeric > 10_000_000_000 else numeric
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def analyze_grid_trades(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"state": "HOLD_TRADES_MISSING", "path": str(path)}
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            strategy_id = str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "")
            if strategy_id == "grid_rebalance":
                rows.append(row)
    regime_counts = Counter(str(row.get("regime") or row.get("market_regime") or "unknown") for row in rows)
    window_counts = Counter(str(row.get("window_id") or row.get("window") or "unknown") for row in rows)
    window_regime_counts = Counter(
        (
            str(row.get("window_id") or row.get("window") or "unknown"),
            str(row.get("regime") or row.get("market_regime") or "unknown"),
        )
        for row in rows
    )
    net_r = sum(float(row.get("realized_R") or row.get("net_R") or row.get("pnl_r") or 0.0) for row in rows)
    neutral_rows = [row for row in rows if str(row.get("regime") or row.get("market_regime") or "unknown") == "neutral"]
    neutral_net_r = sum(float(row.get("realized_R") or row.get("net_R") or row.get("pnl_r") or 0.0) for row in neutral_rows)
    missing_entry_ts = sum(normalize_timestamp(row.get("entry_ts") or row.get("entry_time")) is None for row in rows)
    event_digest = stable_sha(sorted(str(row.get("event_id") or row.get("trade_id") or "") for row in rows))
    neutral_event_digest = stable_sha(sorted(str(row.get("event_id") or row.get("trade_id") or "") for row in neutral_rows))
    field_counts = Counter(key for row in rows for key in row.keys())
    return {
        "state": "PASS_GRID_TRADE_LEDGER_ANALYZED" if rows else "HOLD_GRID_TRADES_EMPTY",
        "trade_count": len(rows),
        "neutral_trade_count": len(neutral_rows),
        "net_R": net_r,
        "neutral_net_R": neutral_net_r,
        "regime_counts": dict(sorted(regime_counts.items())),
        "window_counts": dict(sorted(window_counts.items())),
        "window_regime_counts": {
            f"{window}|{regime}": count
            for (window, regime), count in sorted(window_regime_counts.items())
        },
        "missing_entry_timestamp_count": missing_entry_ts,
        "event_id_set_sha256": event_digest,
        "neutral_event_id_set_sha256": neutral_event_digest,
        "common_fields": [key for key, count in field_counts.most_common() if count == len(rows)][:100],
        "raw_rows_published": False,
    }


def service_inventory() -> dict[str, Any]:
    commands: dict[str, Any] = {}
    try:
        completed = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        relevant_units = []
        for line in completed.stdout.splitlines():
            unit = line.split(maxsplit=1)[0] if line.strip() else ""
            if unit and re.search(r"(?i)(zel|replay|strategy|shadow|data)", unit):
                relevant_units.append(unit)
        for unit in relevant_units[:80]:
            show = subprocess.run(
                ["systemctl", "show", unit, "-p", "FragmentPath", "-p", "ExecStart", "-p", "ActiveState", "-p", "SubState"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            commands[unit] = redact(show.stdout, 1600)
    except Exception as exc:
        return {"state": "HOLD_SYSTEMD_INVENTORY_ERROR", "error": f"{type(exc).__name__}:{exc}"}
    return {"state": "PASS_SYSTEMD_INVENTORY", "units": commands}


def process_inventory() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,etimes=,args="],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        rows = []
        for line in completed.stdout.splitlines():
            if re.search(r"(?i)(zel|data-b|replay|strategy)", line) and "zel_grid_neutral_source_lineage_audit" not in line:
                rows.append(redact(line.strip(), 1200))
        return {"state": "PASS_PROCESS_INVENTORY", "processes": rows[:100]}
    except Exception as exc:
        return {"state": "HOLD_PROCESS_INVENTORY_ERROR", "error": f"{type(exc).__name__}:{exc}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    terminal_root = args.terminal_root.resolve()
    source_matches, regime_candidates = scan_runtime(runtime_root)
    manifests: dict[str, Any] = {}
    keyword_pattern = re.compile(r"(?i)(grid[_-]?rebalance|regime|replay|source|registry)")
    for name in (
        "artifact_manifest.json",
        "report.json",
        "summary.json",
        "progress.json",
        "terminal_receipt.json",
    ):
        path = terminal_root / name
        value = load_json_if_exists(path)
        manifests[name] = {
            "exists": path.is_file(),
            "sha256": sha256_bytes(path.read_bytes()) if path.is_file() else None,
            "matches": compact_manifest(value, keyword_pattern) if value is not None else [],
        }

    strategy_sources = [row for row in source_matches if "strategy_source" in row["roles"]]
    registry_refs = [row for row in source_matches if "registry_or_manifest" in row["roles"]]
    replay_refs = [row for row in source_matches if "replay_or_simulation" in row["roles"] or "terminal_pipeline_reference" in row["roles"]]
    no_unsafe_regime_candidates = [row for row in regime_candidates if row["static_no_lookahead"]]
    trade_ledger = analyze_grid_trades(terminal_root / "trades.jsonl.gz")

    blockers: list[str] = []
    if len(strategy_sources) != 1:
        blockers.append("GRID_STRATEGY_SOURCE_NOT_UNIQUE")
    if not registry_refs:
        blockers.append("GRID_REGISTRY_BINDING_NOT_FOUND")
    if not replay_refs:
        blockers.append("REPLAY_RUNNER_NOT_FOUND")
    if not regime_candidates:
        blockers.append("REGIME_DERIVATION_NOT_FOUND")
    elif not no_unsafe_regime_candidates:
        blockers.append("REGIME_STATIC_LOOKAHEAD_NOT_CLEARED")
    if trade_ledger.get("trade_count") != 580:
        blockers.append("GRID_LEDGER_TRADE_COUNT_MISMATCH")
    if trade_ledger.get("neutral_trade_count") != 248:
        blockers.append("GRID_NEUTRAL_TRADE_COUNT_MISMATCH")

    state = "PASS_GRID_NEUTRAL_SOURCE_LINEAGE_READY_FOR_STAGED_REPLAY" if not blockers else "HOLD_GRID_NEUTRAL_SOURCE_LINEAGE_INCOMPLETE"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "runtime_root": str(runtime_root),
        "terminal_root": str(terminal_root),
        "strategy_id": "grid_rebalance",
        "source_match_count": len(source_matches),
        "strategy_source_count": len(strategy_sources),
        "registry_reference_count": len(registry_refs),
        "replay_reference_count": len(replay_refs),
        "regime_candidate_count": len(regime_candidates),
        "static_no_lookahead_regime_candidate_count": len(no_unsafe_regime_candidates),
        "strategy_sources": strategy_sources,
        "registry_references": registry_refs[:40],
        "replay_references": replay_refs[:80],
        "regime_derivation_candidates": regime_candidates[:80],
        "terminal_manifests": manifests,
        "trade_ledger": trade_ledger,
        "systemd": service_inventory(),
        "processes": process_inventory(),
        "blockers": blockers,
        "source_level_replay_allowed": not blockers,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "STAGE_GRID_NEUTRAL_FORK_IN_TMP_AND_RUN_EXACT_SOURCE_REPLAY" if not blockers else "RESOLVE_SINGLE_LINEAGE_BLOCKER_BEFORE_REPLAY",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
