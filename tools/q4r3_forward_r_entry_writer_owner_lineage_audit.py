from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"
SOURCE_AUTHORITY_IN = RUNTIME / "q4r3_forward_r_source_authority_latest.json"
ENTRY_AUDIT_IN = RUNTIME / "q4r3_forward_r_entry_risk_authority_latest.json"
ENTRY_DECISION_IN = RUNTIME / "q4r3_forward_r_entry_risk_decision_latest.json"
FREEZE_IN = RUNTIME / "q4r3_raschke_freeze_manifest_latest.json"

LINEAGE_OUT = RUNTIME / "q4r3_forward_r_entry_writer_owner_lineage_latest.json"
DECISION_OUT = RUNTIME / "q4r3_forward_r_entry_writer_owner_decision_latest.json"
HTML_OUT = RUNTIME / "q4r3_forward_r_entry_writer_owner_lineage_latest.html"

MAX_CODE_BYTES = 3 * 1024 * 1024
CODE_ROOTS = (
    ROOT / "backend",
    ROOT / "tools",
    ROOT / "services",
    ROOT / "scripts",
    ROOT / "systemd",
    Path("/etc/systemd/system"),
)
CODE_SUFFIXES = {".py", ".sh", ".service", ".timer"}
EXCLUDED_PARTS = {
    ".venv", "venv", "env", "site-packages", "dist-packages", "node_modules", ".git",
    "__pycache__", "vendor", "vendors", "third_party", "third-party", "build", "dist",
}
DIAGNOSTIC_TOKENS = (
    "/tests/", "/test_", "_test.py", "probe", "replay", "audit", "forensic", "tournament",
    "diagnostic", "research", "capture", "backfill", "route_a", "raschke_v", "factorial", "snapshot",
)
WRITER_TERMS = ("write_text", "json.dump", "json.dumps", "open(", "append", "replace(", "os.replace", "rename(")
IDENTITY_TERMS = ("trade_id", "position_id", "event_id", "request_id", "order_id", "client_order_id")
ENTRY_TERMS = ("entry_ts", "open_ts", "opened_at", "signal_ts", "status_open", "is_open")
ENTRY_PRICE_TERMS = ("entry_price", "avg_entry_price", "average_entry_price", "open_price", "fill_price")
STOP_TERMS = ("initial_stop_price", "stop_loss_price", "sl_price", "stop_price", "stop_loss", "native_stop")
QTY_TERMS = (
    "quantity", "qty", "position_qty", "base_qty", "filled_qty", "contracts", "contract_qty",
    "position_notional_usdt", "notional_usdt", "position_value_usdt", "position_size_usdt",
)
RISK_TERMS = ("initial_risk_usdt", "position_risk_usdt", "risk_usdt", "planned_risk_usdt")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(errors="ignore"))


def normalized_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def is_repo_owned_path(path: Path) -> bool:
    text = normalized_path(path)
    parts = {part.lower() for part in path.parts}
    if parts & EXCLUDED_PARTS:
        return False
    if text.startswith("/etc/systemd/system/"):
        return True
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except (ValueError, OSError):
        return False


def is_diagnostic_path(path: Path) -> bool:
    lower = normalized_path(path).lower()
    return any(token in lower for token in DIAGNOSTIC_TOKENS)


def code_paths() -> List[Path]:
    result: List[Path] = []
    for root in CODE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            if not is_repo_owned_path(path):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if 0 < size <= MAX_CODE_BYTES:
                result.append(path)
    return sorted(set(result))


def line_hits(text: str, terms: Iterable[str]) -> List[int]:
    lowered = tuple(term.lower() for term in terms)
    return [index for index, line in enumerate(text.splitlines(), start=1) if any(term in line.lower() for term in lowered)]


def authoritative_open_sources(source_authority: Dict[str, Any], entry_audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    open_by_path = {
        str(item.get("path")): int(item.get("open_contract_rows", 0))
        for item in entry_audit.get("files", [])
        if int(item.get("open_contract_rows", 0)) > 0
    }
    sources = []
    for item in source_authority.get("authoritative_files", []):
        path = str(item.get("path", ""))
        open_rows = int(open_by_path.get(path, item.get("open_rows", 0) or 0))
        if not path or open_rows <= 0:
            continue
        sources.append({"path": path, "basename": Path(path).name, "open_rows": open_rows})
    sources.sort(key=lambda item: (int(item["open_rows"]), item["basename"]), reverse=True)
    return sources


def extract_exec_paths(text: str) -> Set[str]:
    result: Set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("ExecStart=") or stripped.startswith("ExecStartPre=")):
            continue
        for token in re.findall(r"/[A-Za-z0-9_./-]+\.(?:py|sh)", stripped):
            result.add(token)
    return result


def extract_local_file_refs(text: str) -> Set[str]:
    refs: Set[str] = set()
    for token in re.findall(r"[A-Za-z0-9_./-]+\.(?:py|sh)", text):
        refs.add(Path(token).name)
    for module in re.findall(r"(?:from|import)\s+([A-Za-z0-9_.]+)", text):
        refs.add(module.split(".")[-1] + ".py")
    return refs


def service_graph(paths: Sequence[Path]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    executable_to_units: Dict[str, List[str]] = defaultdict(list)
    unit_to_executables: Dict[str, List[str]] = defaultdict(list)
    for path in paths:
        if path.suffix not in {".service", ".timer"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for executable in sorted(extract_exec_paths(text)):
            basename = Path(executable).name
            executable_to_units[basename].append(str(path))
            unit_to_executables[str(path)].append(executable)
    return dict(executable_to_units), dict(unit_to_executables)


def caller_graph(paths: Sequence[Path]) -> Dict[str, List[str]]:
    by_basename = {path.name: str(path) for path in paths if path.suffix in {".py", ".sh"}}
    callers: Dict[str, List[str]] = defaultdict(list)
    for path in paths:
        if path.suffix not in {".py", ".sh", ".service"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for ref in extract_local_file_refs(text):
            target = by_basename.get(ref)
            if target and target != str(path):
                callers[target].append(str(path))
    return {key: sorted(set(value)) for key, value in callers.items()}


def candidate_rows(sources: Sequence[Dict[str, Any]], paths: Sequence[Path]) -> List[Dict[str, Any]]:
    basenames = {item["basename"] for item in sources}
    source_rows = {item["basename"]: int(item["open_rows"]) for item in sources}
    executable_to_units, _ = service_graph(paths)
    callers = caller_graph(paths)
    rows: List[Dict[str, Any]] = []

    for path in paths:
        if path.suffix.lower() not in {".py", ".sh"}:
            continue
        if is_diagnostic_path(path):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        source_refs = sorted(name for name in basenames if name in text)
        writer_hits = line_hits(text, WRITER_TERMS)
        identity_hits = line_hits(text, IDENTITY_TERMS)
        entry_hits = line_hits(text, ENTRY_TERMS)
        entry_price_hits = line_hits(text, ENTRY_PRICE_TERMS)
        stop_hits = line_hits(text, STOP_TERMS)
        qty_hits = line_hits(text, QTY_TERMS)
        risk_hits = line_hits(text, RISK_TERMS)
        services = sorted(set(executable_to_units.get(path.name, [])))
        owner_callers = [caller for caller in callers.get(str(path), []) if is_repo_owned_path(Path(caller)) and not is_diagnostic_path(Path(caller))]
        strict_owner_evidence = bool(source_refs or services)
        structural_writer_evidence = bool(writer_hits and identity_hits and entry_hits)
        if not strict_owner_evidence and not structural_writer_evidence:
            continue

        covered_rows = sum(source_rows.get(name, 0) for name in source_refs)
        score = 0
        score += min(len(source_refs), 3) * 20
        score += 15 if services else 0
        score += 6 if writer_hits else 0
        score += 6 if identity_hits else 0
        score += 4 if entry_hits else 0
        score += 4 if entry_price_hits else 0
        score += 4 if stop_hits else 0
        score += 4 if qty_hits else 0
        score += 8 if risk_hits else 0
        score += min(len(owner_callers), 4) * 3
        rows.append({
            "path": str(path),
            "score": score,
            "authoritative_open_source_refs": source_refs,
            "authoritative_open_rows_covered": covered_rows,
            "service_units": services,
            "owner_callers": sorted(set(owner_callers))[:20],
            "writer_lines": writer_hits[:20],
            "identity_lines": identity_hits[:20],
            "entry_lines": entry_hits[:20],
            "entry_price_lines": entry_price_hits[:20],
            "stop_lines": stop_hits[:20],
            "qty_or_notional_lines": qty_hits[:20],
            "risk_lines": risk_hits[:20],
            "strict_owner_evidence": strict_owner_evidence,
            "repo_owned": True,
        })

    rows.sort(
        key=lambda row: (
            bool(row["strict_owner_evidence"]),
            int(row["authoritative_open_rows_covered"]),
            int(row["score"]),
            len(row["service_units"]),
        ),
        reverse=True,
    )
    return rows


def source_owner_map(sources: Sequence[Dict[str, Any]], candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for source in sources:
        owners = [
            {
                "path": candidate["path"],
                "score": candidate["score"],
                "service_units": candidate["service_units"],
            }
            for candidate in candidates
            if source["basename"] in candidate["authoritative_open_source_refs"]
        ]
        owners.sort(key=lambda row: (int(row["score"]), len(row["service_units"])), reverse=True)
        result.append({**source, "owner_candidates": owners[:10], "owner_candidate_count": len(owners)})
    return result


def lineage_report(source_authority: Dict[str, Any], entry_audit: Dict[str, Any]) -> Dict[str, Any]:
    sources = authoritative_open_sources(source_authority, entry_audit)
    paths = code_paths()
    candidates = candidate_rows(sources, paths)
    owners = source_owner_map(sources, candidates)
    top = candidates[0] if candidates else None
    second_score = int(candidates[1]["score"]) if len(candidates) > 1 else 0
    total_open_rows = sum(int(item["open_rows"]) for item in sources)
    top_coverage_pct = round(int(top["authoritative_open_rows_covered"]) / max(total_open_rows, 1) * 100.0, 3) if top else 0.0
    dominant = bool(
        top
        and top["strict_owner_evidence"]
        and int(top["score"]) >= 30
        and int(top["score"]) >= second_score + 8
        and (top["service_units"] or top["authoritative_open_source_refs"])
    )
    unresolved_sources = [item["basename"] for item in owners if item["owner_candidate_count"] == 0]
    return {
        "status": "PASS_Q4R3_FORWARD_R_ENTRY_WRITER_OWNER_LINEAGE",
        "updated_at": utc_now(),
        "repo_owned_files_scanned": len(paths),
        "external_dependency_paths_excluded": True,
        "authoritative_open_source_count": len(sources),
        "authoritative_open_rows": total_open_rows,
        "source_owner_map": owners,
        "unresolved_authoritative_sources": unresolved_sources,
        "production_candidate_count": len(candidates),
        "production_candidates": candidates[:30],
        "dominant_single_entry_owner": dominant,
        "dominant_entry_owner": top,
        "second_score": second_score,
        "dominant_open_row_coverage_pct": top_coverage_pct,
        "forbidden_paths": sorted(EXCLUDED_PARTS),
    }


def decide(lineage: Dict[str, Any], entry_audit: Dict[str, Any], prior_decision: Dict[str, Any]) -> Dict[str, Any]:
    join_rate = float(prior_decision.get("prior_stable_id_join_rate_pct") or 0.0)
    formula_ready = int(entry_audit.get("formula_ready_unique_ids", 0))
    explicit_risk = int(entry_audit.get("explicit_risk_rows", 0))
    dominant = bool(lineage.get("dominant_single_entry_owner"))
    unresolved = list(lineage.get("unresolved_authoritative_sources", []))
    top = lineage.get("dominant_entry_owner")

    if join_rate < 80.0:
        verdict = "ENTRY_OWNER_PATCH_BLOCKED_BY_STABLE_ID_GATE"
        next_action = "PATCH_STABLE_ID_PROPAGATION_FIRST"
    elif explicit_risk > 0:
        verdict = "ENTRY_RISK_PRESENT_OWNER_PROPAGATION_AUDIT_READY"
        next_action = "VERIFY_INITIAL_RISK_USDT_PROPAGATION_TO_CLOSE"
    elif formula_ready > 0 and dominant:
        verdict = "ENTRY_OWNER_CONFIRMED_INITIAL_RISK_CANARY_READY"
        next_action = "PATCH_INITIAL_RISK_USDT_AT_CONFIRMED_ENTRY_OWNER_CANARY"
    elif dominant:
        verdict = "ENTRY_OWNER_CONFIRMED_MULTI_FIELD_PERSISTENCE_CANARY_READY"
        next_action = "PATCH_ENTRY_PRICE_STOP_SIZE_AND_INITIAL_RISK_AS_ATOMIC_ENTRY_CONTRACT_CANARY"
    elif unresolved:
        verdict = "ENTRY_WRITER_OWNER_NOT_FOUND_RUNTIME_WRITE_TRACE_REQUIRED"
        next_action = "TRACE_AUTHORITATIVE_OPEN_FILE_WRITES_WITH_SYSTEMD_PID_AND_INOTIFY_READ_ONLY"
    else:
        verdict = "ENTRY_WRITER_DISTRIBUTED_APPEND_ONLY_CANARY_REQUIRED"
        next_action = "DESIGN_APPEND_ONLY_ENTRY_RISK_SIDECAR_AT_STABLE_ID_BOUNDARY"

    return {
        "status": "PASS_Q4R3_FORWARD_R_ENTRY_WRITER_OWNER_DECISION",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "prior_stable_id_join_rate_pct": join_rate,
        "explicit_risk_rows": explicit_risk,
        "formula_ready_unique_ids": formula_ready,
        "dominant_single_entry_owner": dominant,
        "dominant_entry_owner": top,
        "unresolved_authoritative_sources": unresolved,
        "dominant_open_row_coverage_pct": lineage.get("dominant_open_row_coverage_pct"),
        "external_dependency_paths_excluded": lineage.get("external_dependency_paths_excluded"),
        "next_modules": [next_action, "FORWARD_ENTRY_RISK_CANARY", "VERIFY_CLOSE_R_FORMULA_ON_NEW_TRADES"],
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


def write_html(lineage: Dict[str, Any], decision: Dict[str, Any]) -> None:
    source_rows = []
    for item in lineage.get("source_owner_map", []):
        source_rows.append(
            "<tr>"
            f"<td>{html.escape(item['basename'])}</td><td>{item['open_rows']}</td>"
            f"<td>{item['owner_candidate_count']}</td>"
            f"<td>{html.escape(', '.join(owner['path'] for owner in item['owner_candidates'][:3]))}</td>"
            "</tr>"
        )
    candidate_rows_html = []
    for item in lineage.get("production_candidates", [])[:20]:
        candidate_rows_html.append(
            "<tr>"
            f"<td>{html.escape(item['path'])}</td><td>{item['score']}</td>"
            f"<td>{item['authoritative_open_rows_covered']}</td>"
            f"<td>{html.escape(', '.join(item['authoritative_open_source_refs']))}</td>"
            f"<td>{html.escape(', '.join(item['service_units']))}</td>"
            "</tr>"
        )
    page = "".join([
        "<!doctype html><html><head><meta charset='utf-8'><title>Entry writer owner lineage</title>",
        "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px;vertical-align:top}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
        "<h1>Repo-owned authoritative entry-writer lineage</h1>",
        "<h2>Authoritative source owners</h2><table><thead><tr><th>Source</th><th>Open rows</th><th>Owners</th><th>Top owners</th></tr></thead><tbody>",
        "".join(source_rows), "</tbody></table>",
        "<h2>Production candidates</h2><table><thead><tr><th>Path</th><th>Score</th><th>Rows covered</th><th>Source refs</th><th>Units</th></tr></thead><tbody>",
        "".join(candidate_rows_html), "</tbody></table>",
        "<h2>Decision</h2><pre>", html.escape(json.dumps(decision, ensure_ascii=False, indent=2)), "</pre></body></html>",
    ])
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    source_authority = load_json(SOURCE_AUTHORITY_IN)
    entry_audit = load_json(ENTRY_AUDIT_IN)
    prior_decision = load_json(ENTRY_DECISION_IN)
    freeze = load_json(FREEZE_IN) if FREEZE_IN.exists() else {}
    lineage = lineage_report(source_authority, entry_audit)
    lineage["raschke_state"] = freeze.get("state")
    decision = decide(lineage, entry_audit, prior_decision)
    write_html(lineage, decision)
    atomic_json(LINEAGE_OUT, lineage)
    atomic_json(DECISION_OUT, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(json.dumps(lineage, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
