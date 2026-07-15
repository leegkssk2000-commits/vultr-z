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
MAX_FILES = 500
MAX_HITS = 12
TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".service", ".timer", ".sh", ".md", ".txt"}
CORE_COMPONENTS = ("LBot", "MBot", "OBot", "SBot", "ZBot", "ZICO", "LiCo", "Zlice")
LANES = ("Alpha", "Beta", "Gamma", "Delta")
COMPONENTS = CORE_COMPONENTS + LANES
ALIASES: dict[str, tuple[str, ...]] = {
    "LBot": ("lbot", "lead bot", "lead_bot"),
    "MBot": ("mbot", "method bot", "method_bot"),
    "OBot": ("obot", "observer bot", "observer_bot"),
    "SBot": ("sbot", "safety bot", "safety_bot", "guard bot"),
    "ZBot": ("zbot", "z bot", "advisor bot"),
    "ZICO": ("zico",),
    "LiCo": ("lico", "li co"),
    "Zlice": ("zlice",),
    "Alpha": ("alpha team", "alpha lane", "alpha_lane", "team alpha"),
    "Beta": ("beta team", "beta lane", "beta_lane", "team beta"),
    "Gamma": ("gamma team", "gamma lane", "gamma_lane", "team gamma"),
    "Delta": ("delta team", "delta lane", "delta_lane", "team delta"),
}
ALIAS_RE = {name: re.compile("|".join(re.escape(value) for value in values), re.I) for name, values in ALIASES.items()}
EXCLUDE_FRAGMENT_RE = re.compile(r"(^|[._/-])(backup|restore|rollback|archive|snapshot|quarantine|trash|golden[_-]?backup|locked[_-]?baseline|live[_-]?backup|patch[_-]?backup|old|copy)([._/-]|$)", re.I)
EXCLUDE_PARTS = {".git", "node_modules", "vendor", "dist", "build", "__pycache__", ".venv", "venv", "coverage", ".pytest_cache"}
SUPPORT_PATH_RE = re.compile(r"/(tests?|scripts?)/|(^|/)(test|verify|apply|install|bootstrap|run|audit|probe|smoke|check)[_-]", re.I)
STALE_RE = re.compile(r"\b(legacy|deprecated|obsolete|stale|retired)\b|w\d{2,4}", re.I)
CANONICAL_RE = re.compile(r"\b(canonical|owner|registry|manifest|ssot|contract|single[_ -]?writer)\b", re.I)
IMPORT_CALL_RE = re.compile(r"\b(import|from|require|invoke|execute|handler|adapter|bridge|client|service|resolve|dispatch)\b", re.I)
DIRECT_ORDER_RE = re.compile(r"\b(create_order|place_order|cancel_order|submit_order|send_order|private_api|private_endpoint)\b", re.I)
PRIVATE_CREDENTIAL_RE = re.compile(r"\b(api[_-]?key|apiKey|secret|private[_-]?key|passphrase)\b", re.I)
FILE_WRITE_RE = re.compile(r"write_text\s*\(|write_bytes\s*\(|open\s*\([^\n]{0,160}[\"'][awx+][^\"']*[\"']|append_jsonl|os\.replace\s*\(", re.I)
POLICY_ONLY_RE = re.compile(r"\b(paper_enabled|live_enabled|order_enabled|order_authority|execution_authority|observer_only)\b", re.I)
SECRET_RE = re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|authorization|bearer)\s*[:=]\s*([^\s,;]+)")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def sanitize(value: str, limit: int = 700) -> str:
    value = SECRET_RE.sub(lambda match: f"{match.group(1)}=<REDACTED>", value)
    value = re.sub(r"gh[pousr]_[A-Za-z0-9_]{20,}", "<REDACTED_GITHUB_TOKEN>", value)
    return value[:limit]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_raw(command: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        return 255, f"{type(exc).__name__}:{exc}"


def canonical_roots(root: Path) -> list[Path]:
    candidates = [root / "backend", root / "tools", root / "services", root / "systemd", root / "config", Path("/etc/systemd/system")]
    return [path for path in candidates if path.exists()]


def contaminated_path(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts.intersection(EXCLUDE_PARTS):
        return True
    text = str(path).replace("\\", "/")
    if EXCLUDE_FRAGMENT_RE.search(text):
        return True
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return True
    try:
        return not path.is_file() or path.stat().st_size > MAX_FILE_SIZE
    except OSError:
        return True


def exact_definition(component: str, line: str) -> bool:
    names = [normalize(alias) for alias in ALIASES[component]]
    compact = normalize(line)
    declaration = bool(re.search(r"\b(class|def|function|interface|type|enum|const|let|var)\b", line, re.I))
    assignment = bool(re.search(r"[:=]", line))
    return any(name and name in compact for name in names) and (declaration or assignment)


def file_kind(path: Path, text: str, components: list[str]) -> str:
    path_text = str(path).replace("\\", "/")
    if path.suffix in {".service", ".timer"} or path_text.startswith("/etc/systemd/system/"):
        return "systemd_unit"
    if SUPPORT_PATH_RE.search(path_text):
        return "support_verifier_installer"
    if path.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}:
        return "config_contract"
    if any(exact_definition(component, line) for component in components for line in text.splitlines()[:2000]):
        return "runtime_definition"
    return "reference"


def filename_signal(component: str, path: Path) -> bool:
    name = normalize(path.stem)
    return any(normalize(alias) in name for alias in ALIASES[component] if normalize(alias))


def analyze_file(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    components = sorted(component for component, regex in ALIAS_RE.items() if regex.search(text) or regex.search(path.name))
    if not components:
        return None
    kind = file_kind(path, text, components)
    hits: list[dict[str, Any]] = []
    exact_defs: dict[str, bool] = {component: False for component in components}
    caller = False
    canonical = False
    direct_order = False
    private_credentials = False
    file_write = False
    policy_reference = False
    for line_no, line in enumerate(text.splitlines(), 1):
        line_components = [component for component in components if ALIAS_RE[component].search(line)]
        if not line_components:
            continue
        caller = caller or bool(IMPORT_CALL_RE.search(line))
        canonical = canonical or bool(CANONICAL_RE.search(line))
        direct_order = direct_order or bool(DIRECT_ORDER_RE.search(line))
        private_credentials = private_credentials or bool(PRIVATE_CREDENTIAL_RE.search(line))
        file_write = file_write or bool(FILE_WRITE_RE.search(line))
        policy_reference = policy_reference or bool(POLICY_ONLY_RE.search(line))
        for component in line_components:
            exact_defs[component] = exact_defs[component] or exact_definition(component, line)
        if len(hits) < MAX_HITS:
            hits.append({"line": line_no, "components": line_components, "snippet": sanitize(line.strip())})
    try:
        stat = path.stat()
        digest = sha256_file(path)
    except Exception:
        return None
    return {
        "path": str(path),
        "sha256": digest,
        "size_bytes": stat.st_size,
        "mtime_epoch": stat.st_mtime,
        "components": components,
        "kind": kind,
        "filename_signals": {component: filename_signal(component, path) for component in components},
        "exact_definitions": exact_defs,
        "caller_signal": caller,
        "canonical_signal": canonical,
        "direct_order_signal": direct_order,
        "private_credential_signal": private_credentials,
        "file_write_signal": file_write,
        "policy_reference_signal": policy_reference,
        "stale_signal": bool(STALE_RE.search(str(path)) or STALE_RE.search(text[:10000])),
        "hits": hits,
    }


def scan(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stats = {"visited": 0, "excluded": 0, "read": 0, "matched": 0, "capped": False, "roots": []}
    for base in canonical_roots(root):
        stats["roots"].append(str(base))
        iterator: Iterable[Path] = [base] if base.is_file() else base.rglob("*")
        for path in iterator:
            stats["visited"] += 1
            if contaminated_path(path):
                stats["excluded"] += 1
                continue
            stats["read"] += 1
            row = analyze_file(path)
            if row is None:
                continue
            rows.append(row)
            stats["matched"] += 1
            if len(rows) >= MAX_FILES:
                stats["capped"] = True
                return rows, stats
    return rows, stats


def parse_show(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key] = sanitize(value, 4000)
    return fields


def systemd_inventory(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, unit_file_text = run_raw(["systemctl", "list-unit-files", "--no-legend", "--no-pager"], 30)
    _, active_text = run_raw(["systemctl", "list-units", "--all", "--no-legend", "--no-pager"], 30)
    names: set[str] = set()
    generic = re.compile(r"bot|team|advisor|zico|lico|zlice", re.I)
    for line in (unit_file_text + "\n" + active_text).splitlines():
        token = line.split(maxsplit=1)[0] if line.strip() else ""
        if token.endswith((".service", ".timer")) and generic.search(token):
            names.add(token)
    rows: list[dict[str, Any]] = []
    file_by_path = {row["path"]: row for row in files}
    for name in sorted(names):
        _, show = run_raw([
            "systemctl", "show", name, "--no-pager",
            "-p", "Id", "-p", "LoadState", "-p", "UnitFileState", "-p", "ActiveState", "-p", "SubState",
            "-p", "MainPID", "-p", "FragmentPath", "-p", "ExecStart", "-p", "WorkingDirectory",
        ])
        fields = parse_show(show)
        combined = name + " " + fields.get("ExecStart", "") + " " + fields.get("FragmentPath", "")
        components = sorted(component for component, regex in ALIAS_RE.items() if regex.search(combined))
        exec_paths = re.findall(r"(/[A-Za-z0-9_./-]+)", fields.get("ExecStart", ""))
        for exec_path in exec_paths:
            row = file_by_path.get(exec_path)
            if row:
                components = sorted(set(components).union(row["components"]))
        rows.append({"unit": name, "components": components, "exec_paths": exec_paths, **fields})
    return rows


def score(component: str, row: Mapping[str, Any], active_exec_paths: set[str]) -> int:
    value = 0
    path = str(row["path"])
    if path in active_exec_paths:
        value += 30
    if bool((row.get("filename_signals") or {}).get(component)):
        value += 12
    if bool((row.get("exact_definitions") or {}).get(component)):
        value += 10
    if row.get("canonical_signal"):
        value += 5
    if row.get("caller_signal"):
        value += 2
    if row.get("kind") == "config_contract":
        value += 4
    if row.get("kind") == "systemd_unit":
        value += 3
    if row.get("kind") == "support_verifier_installer":
        value -= 12
    if row.get("kind") == "reference":
        value -= 4
    if row.get("stale_signal"):
        value -= 8
    return value


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        grouped[str(row["sha256"])].append(row)
    result: list[dict[str, Any]] = []
    for digest, rows in grouped.items():
        rows.sort(key=lambda item: (-int(item["score"]), len(str(item["path"])), str(item["path"])))
        primary = dict(rows[0])
        primary["same_sha_paths"] = sorted(str(item["path"]) for item in rows[1:])[:20]
        primary["sha256"] = digest
        result.append(primary)
    result.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return result


def build_matrix(files: list[dict[str, Any]], units: list[dict[str, Any]]) -> dict[str, Any]:
    active_exec_paths = {path for unit in units if unit.get("ActiveState") == "active" for path in unit.get("exec_paths", [])}
    active_units: defaultdict[str, list[str]] = defaultdict(list)
    for unit in units:
        if unit.get("ActiveState") == "active":
            for component in unit.get("components", []):
                active_units[component].append(str(unit["unit"]))
    matrix: dict[str, Any] = {}
    for component in COMPONENTS:
        candidates: list[dict[str, Any]] = []
        for row in files:
            if component not in row.get("components", []):
                continue
            candidates.append({
                "path": row["path"],
                "sha256": row["sha256"],
                "kind": row["kind"],
                "score": score(component, row, active_exec_paths),
                "filename_signal": bool((row.get("filename_signals") or {}).get(component)),
                "exact_definition": bool((row.get("exact_definitions") or {}).get(component)),
                "canonical_signal": row["canonical_signal"],
                "caller_signal": row["caller_signal"],
                "stale_signal": row["stale_signal"],
                "hits": row["hits"][:6],
            })
        candidates = dedupe_candidates(candidates)
        top = candidates[0] if candidates else None
        second = int(candidates[1]["score"]) if len(candidates) > 1 else -999
        if top is None:
            confidence, decision = "NONE", "OWNER_NOT_FOUND"
        elif str(top["path"]) in active_exec_paths and int(top["score"]) >= 25:
            confidence, decision = "HIGH", "ACTIVE_OWNER_CANDIDATE_REQUIRES_CONTRACT_HARNESS"
        elif int(top["score"]) >= 16 and int(top["score"]) - second >= 4:
            confidence, decision = "MEDIUM", "SINGLE_SOURCE_CANDIDATE_REQUIRES_CONTRACT_HARNESS"
        else:
            confidence, decision = "LOW", "AMBIGUOUS_OR_WEAK_OWNER_EVIDENCE"
        matrix[component] = {
            "confidence": confidence,
            "decision": decision,
            "active_units": sorted(set(active_units.get(component, []))),
            "unique_candidate_count": len(candidates),
            "top_candidates": candidates[:5],
        }
    return matrix


def authority_matrix(files: list[dict[str, Any]], units: list[dict[str, Any]]) -> dict[str, Any]:
    active_exec_paths = {path for unit in units if unit.get("ActiveState") == "active" for path in unit.get("exec_paths", [])}
    direct: list[dict[str, Any]] = []
    output_writers: list[dict[str, Any]] = []
    policy_refs: list[str] = []
    for row in files:
        core = sorted(set(row.get("components", [])).intersection(CORE_COMPONENTS))
        if not core:
            continue
        runtime_owner = row.get("kind") == "runtime_definition" or row.get("path") in active_exec_paths
        support = row.get("kind") == "support_verifier_installer"
        if runtime_owner and not support and (row.get("direct_order_signal") or row.get("private_credential_signal")):
            direct.append({
                "path": row["path"], "components": core, "active_exec": row["path"] in active_exec_paths,
                "direct_order_signal": row["direct_order_signal"], "private_credential_signal": row["private_credential_signal"],
                "hits": row["hits"][:8],
            })
        if runtime_owner and not support and row.get("file_write_signal"):
            output_writers.append({"path": row["path"], "components": core, "active_exec": row["path"] in active_exec_paths, "hits": row["hits"][:8]})
        if row.get("policy_reference_signal") and not row.get("direct_order_signal") and not row.get("private_credential_signal"):
            policy_refs.append(str(row["path"]))
    return {
        "direct_execution_candidates": direct[:50],
        "direct_execution_candidate_count": len(direct),
        "component_output_writer_candidates": output_writers[:50],
        "component_output_writer_candidate_count": len(output_writers),
        "policy_reference_count": len(set(policy_refs)),
        "policy_reference_sample": sorted(set(policy_refs))[:30],
        "generic_ledger_or_policy_mentions_count_as_direct_authority": False,
    }


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def cadence_snapshot(root: Path) -> dict[str, Any]:
    status = read_json(root / "runtime/exact25_edge_v1/lineage_cadence_repair/status_latest.json") or {}
    return {
        "state": status.get("state"),
        "verdict": status.get("verdict"),
        "post_repair_close_count": status.get("post_repair_close_count"),
        "post_repair_uncovered_count": status.get("post_repair_uncovered_count"),
        "post_repair_coverage_pct": status.get("post_repair_coverage_pct"),
        "remaining_to_canary": status.get("remaining_to_canary"),
    }


def audit(root: Path) -> dict[str, Any]:
    files, stats = scan(root)
    units = systemd_inventory(files)
    matrix = build_matrix(files, units)
    authority = authority_matrix(files, units)
    ambiguous = [component for component in CORE_COMPONENTS if matrix[component]["confidence"] in {"NONE", "LOW"}]
    active = sorted({component for unit in units if unit.get("ActiveState") == "active" for component in unit.get("components", [])})
    if authority["direct_execution_candidate_count"]:
        state, verdict, route = "HOLD", "TB11_DIRECT_AUTHORITY_REQUIRES_CALLER_PERMISSION_TRACE", "DIRECT_AUTHORITY_CALLER_PERMISSION_TRACE"
    elif ambiguous:
        state, verdict, route = "HOLD", "TB11_OWNER_AMBIGUITY_REMAINS_AFTER_CLEAN_SCAN", "TARGETED_COMPONENT_CONTRACT_HARNESS"
    else:
        state, verdict, route = "PASS", "TB11_OWNER_CANDIDATES_NARROWED", "TARGETED_COMPONENT_CONTRACT_HARNESS"
    return {
        "schema": "q4r3_team_advisor_tb11_owner_narrowing_audit_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "scan_stats": stats,
        "component_matrix": matrix,
        "active_components": active,
        "ambiguous_core_components": ambiguous,
        "authority": authority,
        "systemd_units": units,
        "cadence_repair": cadence_snapshot(root),
        "excluded_surfaces": ["frontend", "web", "runtime-wide scan", "backup/restore/rollback/archive/snapshot paths", "dist/build assets", "tests and installers as owner candidates"],
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
        "next_route": route,
    }


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = audit(args.root)
    atomic_json(args.output, payload)
    print(json.dumps({
        "state": payload["state"],
        "verdict": payload["verdict"],
        "matched": payload["scan_stats"]["matched"],
        "capped": payload["scan_stats"]["capped"],
        "active_components": payload["active_components"],
        "ambiguous_core_components": payload["ambiguous_core_components"],
        "direct_execution_candidate_count": payload["authority"]["direct_execution_candidate_count"],
        "output_writer_candidate_count": payload["authority"]["component_output_writer_candidate_count"],
        "next_route": payload["next_route"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
