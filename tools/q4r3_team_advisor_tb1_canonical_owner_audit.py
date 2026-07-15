#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

UTC = timezone.utc
MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_MATCH_FILES = 1200
MAX_HITS_PER_FILE = 40
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".env", ".service", ".timer", ".sh", ".md", ".txt",
}
SKIP_DIR_NAMES = {
    ".git", "node_modules", "vendor", "dist", "build", "__pycache__", ".venv", "venv",
    "backups", "backup", "archive", "archives", "snapshots", "snapshot", "golden_backups",
}
SKIP_SUFFIXES = {".log", ".jsonl", ".sqlite", ".sqlite3", ".db", ".gz", ".zip", ".tar", ".tgz"}

COMPONENTS: dict[str, tuple[str, ...]] = {
    "LBot": ("lbot", "lead bot", "lead_bot"),
    "MBot": ("mbot", "method bot", "method_bot"),
    "OBot": ("obot", "observer bot", "observer_bot"),
    "SBot": ("sbot", "safety bot", "safety_bot", "guard bot"),
    "ZBot": ("zbot", "z bot", "advisor bot"),
    "ZICO": ("zico",),
    "LiCo": ("lico", "li co"),
    "Zlice": ("zlice",),
    "Alpha": ("alpha team", "alpha_lane", "team alpha"),
    "Beta": ("beta team", "beta_lane", "team beta"),
    "Gamma": ("gamma team", "gamma_lane", "team gamma"),
    "Delta": ("delta team", "delta_lane", "team delta"),
}
CORE_COMPONENTS = ("LBot", "MBot", "OBot", "SBot", "ZBot", "ZICO", "LiCo", "Zlice")
TOKEN_REGEX = {
    component: re.compile("|".join(re.escape(alias) for alias in aliases), re.IGNORECASE)
    for component, aliases in COMPONENTS.items()
}
DEFINITION_RE = re.compile(r"\b(class|def|function|const|let|var|interface|type|enum|registry|owner|canonical|ssot)\b", re.I)
CALL_RE = re.compile(r"\b(import|from|require|invoke|call|execute|handler|adapter|bridge|client|service)\b", re.I)
AUTHORITY_RE = re.compile(
    r"\b(place_order|cancel_order|create_order|private_api|api_key|secret|paper_enabled|live_enabled|"
    r"order_enabled|order_authority|execution_authority|ledger|append|write_text|open\s*\(|requests\.(post|put|delete)|"
    r"subprocess|systemctl)\b",
    re.I,
)
CANONICAL_RE = re.compile(r"\b(canonical|owner|registry|manifest|ssot|single writer|single_writer|contract)\b", re.I)
STALE_RE = re.compile(r"\b(legacy|deprecated|obsolete|archive|backup|old|stale|w\d{2,4})\b", re.I)
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|authorization|bearer)\s*[:=]\s*([^\s,;]+)"
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize(text: str) -> str:
    value = SECRET_RE.sub(lambda match: f"{match.group(1)}=<REDACTED>", text)
    value = re.sub(r"gh[pousr]_[A-Za-z0-9_]{20,}", "<REDACTED_GITHUB_TOKEN>", value)
    value = re.sub(r"[A-Za-z0-9+/]{40,}={0,2}", "<REDACTED_LONG_TOKEN>", value)
    return value[:500]


def run_command(command: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return completed.returncode, sanitize((completed.stdout or "") + (completed.stderr or ""))
    except Exception as exc:
        return 255, f"{type(exc).__name__}:{exc}"


def candidate_roots(root: Path) -> list[Path]:
    requested = [
        root / "backend", root / "tools", root / "services", root / "systemd", root / "config",
        root / "data", root / "skills", root / "alimi", root / "frontend", root / "web",
        root / "runtime", Path("/etc/systemd/system"),
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for path in requested:
        if not path.exists():
            continue
        resolved = str(path.resolve())
        if resolved not in seen:
            result.append(path)
            seen.add(resolved)
    return result


def should_skip(path: Path) -> bool:
    if any(part.lower() in SKIP_DIR_NAMES for part in path.parts):
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if path.suffix and path.suffix.lower() not in TEXT_SUFFIXES:
        return True
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_SIZE:
            return True
    except OSError:
        return True
    if "/runtime/" in str(path).replace("\\", "/"):
        lowered = path.name.lower()
        if not any(alias.replace(" ", "") in lowered.replace("_", "").replace("-", "") for aliases in COMPONENTS.values() for alias in aliases):
            return True
    return False


def scan_files(roots: Iterable[Path]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    matches: list[dict[str, Any]] = []
    stats = {"visited_files": 0, "read_files": 0, "matched_files": 0, "read_errors": 0, "capped": 0}
    for root in roots:
        iterator = [root] if root.is_file() else root.rglob("*")
        for path in iterator:
            stats["visited_files"] += 1
            if should_skip(path):
                continue
            stats["read_files"] += 1
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                stats["read_errors"] += 1
                continue
            components = sorted(component for component, regex in TOKEN_REGEX.items() if regex.search(text) or regex.search(path.name))
            if not components:
                continue
            hits: list[dict[str, Any]] = []
            definition = False
            caller = False
            authority = False
            canonical = False
            stale = bool(STALE_RE.search(str(path)))
            for line_no, line in enumerate(text.splitlines(), 1):
                line_components = sorted(component for component, regex in TOKEN_REGEX.items() if regex.search(line))
                if not line_components:
                    continue
                definition = definition or bool(DEFINITION_RE.search(line))
                caller = caller or bool(CALL_RE.search(line))
                authority = authority or bool(AUTHORITY_RE.search(line))
                canonical = canonical or bool(CANONICAL_RE.search(line))
                if len(hits) < MAX_HITS_PER_FILE:
                    hits.append({
                        "line": line_no,
                        "components": line_components,
                        "snippet": sanitize(line.strip()),
                    })
            try:
                stat = path.stat()
                file_sha = sha256_file(path)
            except Exception:
                stats["read_errors"] += 1
                continue
            matches.append({
                "path": str(path),
                "size_bytes": stat.st_size,
                "mtime_epoch": stat.st_mtime,
                "sha256": file_sha,
                "components": components,
                "definition_signal": definition,
                "caller_signal": caller,
                "authority_signal": authority,
                "canonical_signal": canonical,
                "stale_signal": stale,
                "hit_count": sum(1 for line in text.splitlines() if any(regex.search(line) for regex in TOKEN_REGEX.values())),
                "hits": hits,
            })
            stats["matched_files"] += 1
            if len(matches) >= MAX_MATCH_FILES:
                stats["capped"] = 1
                return matches, stats
    return matches, stats


def systemd_inventory() -> list[dict[str, Any]]:
    code_files, unit_files = run_command(["systemctl", "list-unit-files", "--no-legend", "--no-pager"], 30)
    code_units, units = run_command(["systemctl", "list-units", "--all", "--no-legend", "--no-pager"], 30)
    text = unit_files + "\n" + units
    names: set[str] = set()
    for line in text.splitlines():
        first = line.split(maxsplit=1)[0] if line.strip() else ""
        if first.endswith((".service", ".timer")) and any(regex.search(first) for regex in TOKEN_REGEX.values()):
            names.add(first)
    rows: list[dict[str, Any]] = []
    for name in sorted(names):
        _, detail = run_command([
            "systemctl", "show", name, "--no-pager",
            "-p", "Id", "-p", "LoadState", "-p", "UnitFileState", "-p", "ActiveState", "-p", "SubState",
            "-p", "MainPID", "-p", "FragmentPath", "-p", "ExecStart", "-p", "WorkingDirectory",
        ])
        fields: dict[str, str] = {}
        for line in detail.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key] = sanitize(value)
        components = sorted(component for component, regex in TOKEN_REGEX.items() if regex.search(name + " " + detail))
        rows.append({"unit": name, "components": components, **fields})
    if code_files != 0 or code_units != 0:
        rows.append({"unit": "<SYSTEMD_INVENTORY_ERROR>", "unit_files_code": code_files, "units_code": code_units})
    return rows


def process_inventory() -> dict[str, Any]:
    _, process_text = run_command(["ps", "-eo", "pid=,comm=,args="], 20)
    _, listener_text = run_command(["ss", "-ltnp"], 20)
    process_rows = [sanitize(line.strip()) for line in process_text.splitlines() if any(regex.search(line) for regex in TOKEN_REGEX.values())][:200]
    listener_rows = [sanitize(line.strip()) for line in listener_text.splitlines() if any(regex.search(line) for regex in TOKEN_REGEX.values())][:100]
    return {"processes": process_rows, "listeners": listener_rows}


def score_file(component: str, row: Mapping[str, Any], active_exec_paths: set[str]) -> int:
    path = str(row.get("path") or "")
    score = 0
    if TOKEN_REGEX[component].search(Path(path).name):
        score += 5
    if row.get("canonical_signal"):
        score += 4
    if row.get("definition_signal"):
        score += 3
    if row.get("caller_signal"):
        score += 1
    if any(path in exec_path or exec_path in path for exec_path in active_exec_paths if exec_path):
        score += 5
    if row.get("authority_signal"):
        score += 1
    if row.get("stale_signal"):
        score -= 5
    return score


def build_matrix(files: list[dict[str, Any]], units: list[dict[str, Any]]) -> dict[str, Any]:
    active_exec_paths: set[str] = set()
    active_units_by_component: defaultdict[str, list[str]] = defaultdict(list)
    for unit in units:
        if unit.get("ActiveState") == "active":
            exec_start = str(unit.get("ExecStart") or "")
            for token in re.findall(r"(/[A-Za-z0-9_./-]+)", exec_start):
                active_exec_paths.add(token)
            for component in unit.get("components") or []:
                active_units_by_component[component].append(str(unit.get("unit")))

    matrix: dict[str, Any] = {}
    for component in COMPONENTS:
        candidates = []
        for row in files:
            if component not in row.get("components", []):
                continue
            score = score_file(component, row, active_exec_paths)
            candidates.append({
                "path": row["path"],
                "sha256": row["sha256"],
                "score": score,
                "definition_signal": row["definition_signal"],
                "caller_signal": row["caller_signal"],
                "authority_signal": row["authority_signal"],
                "canonical_signal": row["canonical_signal"],
                "stale_signal": row["stale_signal"],
            })
        candidates.sort(key=lambda item: (-int(item["score"]), item["path"]))
        top = candidates[0] if candidates else None
        second_score = int(candidates[1]["score"]) if len(candidates) > 1 else -999
        if not top:
            confidence = "NONE"
            decision = "OWNER_NOT_FOUND"
        elif int(top["score"]) >= 10 and int(top["score"]) - second_score >= 3:
            confidence = "HIGH"
            decision = "SINGLE_OWNER_CANDIDATE"
        elif int(top["score"]) >= 6 and int(top["score"]) - second_score >= 2:
            confidence = "MEDIUM"
            decision = "OWNER_CANDIDATE_REQUIRES_CONTRACT_CHECK"
        else:
            confidence = "LOW"
            decision = "AMBIGUOUS_OR_WEAK_OWNER_EVIDENCE"
        matrix[component] = {
            "confidence": confidence,
            "decision": decision,
            "active_units": sorted(set(active_units_by_component.get(component, []))),
            "candidate_count": len(candidates),
            "top_candidates": candidates[:10],
        }
    return matrix


def git_snapshot(root: Path) -> dict[str, Any]:
    commands = {
        "head": ["git", "-C", str(root), "rev-parse", "HEAD"],
        "branch": ["git", "-C", str(root), "branch", "--show-current"],
        "status": ["git", "-C", str(root), "status", "--short"],
        "worktrees": ["git", "-C", str(root), "worktree", "list", "--porcelain"],
    }
    result: dict[str, Any] = {}
    for key, command in commands.items():
        code, text = run_command(command, 30)
        result[key] = text.strip()[:40000]
        result[f"{key}_exit_code"] = code
    return result


def audit(root: Path) -> dict[str, Any]:
    roots = candidate_roots(root)
    files, scan_stats = scan_files(roots)
    units = systemd_inventory()
    processes = process_inventory()
    matrix = build_matrix(files, units)

    authority_candidates = sorted({
        row["path"] for row in files if row.get("authority_signal") and any(component in CORE_COMPONENTS for component in row.get("components", []))
    })
    ambiguous = [component for component in CORE_COMPONENTS if matrix[component]["confidence"] in {"NONE", "LOW"}]
    active_components = sorted({component for unit in units if unit.get("ActiveState") == "active" for component in unit.get("components", [])})

    if authority_candidates:
        state = "HOLD"
        verdict = "TB1_AUTHORITY_SURFACES_REQUIRE_MANUAL_CONTRACT_AUDIT"
    elif ambiguous:
        state = "HOLD"
        verdict = "TB1_CANONICAL_OWNER_AMBIGUITY_REMAINS"
    else:
        state = "PASS"
        verdict = "TB1_CANONICAL_OWNER_MATRIX_EVIDENCE_READY"

    return {
        "schema": "q4r3_team_advisor_tb1_canonical_owner_audit_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "root": str(root),
        "scan_roots": [str(path) for path in roots],
        "scan_stats": scan_stats,
        "component_matrix": matrix,
        "active_components": active_components,
        "ambiguous_core_components": ambiguous,
        "authority_candidate_count": len(authority_candidates),
        "authority_candidate_paths": authority_candidates[:200],
        "systemd_units": units,
        "runtime_process_inventory": processes,
        "matched_files": files,
        "git": git_snapshot(root),
        "policy": {
            "observer_only": True,
            "team_advisor_binding_enabled": False,
            "comparison_decision_enabled": False,
            "ranking_enabled": False,
            "promotion_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
            "automatic_patch_allowed": False,
            "action": "hold",
        },
        "next_route": "CONTRACT_HARNESS_FOR_TOP_OWNER_CANDIDATES" if not authority_candidates else "AUTHORITY_SURFACE_READ_ONLY_TRACE",
    }


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--root", type=Path, default=Path("/home/z/z"))
    value.add_argument("--output", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    payload = audit(args.root)
    atomic_json(args.output, payload)
    print(json.dumps({
        "state": payload["state"],
        "verdict": payload["verdict"],
        "matched_files": payload["scan_stats"]["matched_files"],
        "active_components": payload["active_components"],
        "ambiguous_core_components": payload["ambiguous_core_components"],
        "authority_candidate_count": payload["authority_candidate_count"],
        "output": str(args.output),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
