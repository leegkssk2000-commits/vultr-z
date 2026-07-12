from __future__ import annotations

import difflib
import hashlib
import html
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"
COVERAGE_PATH = RUNTIME / "q4r3_25_strategy_realized_r_coverage_latest.json"
LEDGER_PATH = RUNTIME / "q4r3_25_strategy_realized_r_ledger_latest.json"
SOURCE_AUDIT_PATH = RUNTIME / "q4r3_25_strategy_realized_r_source_audit_latest.json"

TRACE_OUT = RUNTIME / "q4r3_missing_strategy_writer_trace_latest.json"
DECISION_OUT = RUNTIME / "q4r3_missing_strategy_writer_trace_decision_latest.json"
HANDOFF_OUT = RUNTIME / "q4r3_missing_strategy_writer_trace_handoff_latest.json"
HTML_OUT = RUNTIME / "q4r3_missing_strategy_writer_trace_latest.html"

SCAN_ROOTS = (
    ROOT / "backend",
    ROOT / "tools",
    ROOT / "config",
    ROOT / "configs",
    ROOT / "data",
    ROOT / "runtime",
)
ALLOWED_SUFFIXES = {".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".ini", ".md", ".txt"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "cache", "tmp"}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_HITS_PER_STRATEGY = 80

WRITER_TERMS = (
    "realized_r",
    "pnl_r",
    "net_r",
    "ledger",
    "closed",
    "close_ts",
    "exit_ts",
    "append",
    "write_text",
    "json.dump",
)
REGISTRY_TERMS = ("registry", "strategy_cards", "strategy_universe", "enabled_strategies", "candidate_strategies")
IMPLEMENTATION_HINTS = ("def strategy", "class ", "backend/strategies", "strategies/")
RUNTIME_TERMS = ("runtime/", "latest.json", "ledger", "closed", "pnl")
SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password|private[_-]?key)"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
)


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(errors="ignore"))


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)


def token_variants(strategy: str) -> List[str]:
    canonical = normalize(strategy)
    compact = canonical.replace("_", "")
    dashed = canonical.replace("_", "-")
    spaced = canonical.replace("_", " ")
    return list(dict.fromkeys([canonical, compact, dashed, spaced]))


def safe_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except Exception:
        return path.name


def iter_scan_files() -> Iterator[Path]:
    seen: set[Path] = set()
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            current_path = Path(current)
            for name in files:
                path = current_path / name
                if path in seen or path.suffix.lower() not in ALLOWED_SUFFIXES:
                    continue
                seen.add(path)
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if 0 < size <= MAX_FILE_BYTES:
                    yield path


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return None


def context_excerpt(text: str, index: int, width: int = 160) -> str:
    start = max(0, index - width)
    end = min(len(text), index + width)
    excerpt = " ".join(text[start:end].split())
    for pattern in SECRET_PATTERNS:
        if pattern.search(excerpt):
            return "[REDACTED_SENSITIVE_CONTEXT]"
    return excerpt[:360]


def classify_hit(path: Path, text_lower: str) -> Dict[str, bool]:
    relative = safe_relative(path).lower()
    implementation = (
        "backend/strategies/" in relative
        or "/strategies/" in relative
        or any(term in text_lower for term in IMPLEMENTATION_HINTS[:2])
    )
    registry = any(term in relative or term in text_lower for term in REGISTRY_TERMS)
    writer = any(term in text_lower for term in WRITER_TERMS)
    runtime_source = relative.startswith("runtime/") or any(term in relative for term in RUNTIME_TERMS)
    return {
        "implementation": implementation,
        "registry": registry,
        "writer": writer,
        "runtime_source": runtime_source,
    }


def scan_strategy(strategy: str, files: Sequence[Path]) -> Dict[str, Any]:
    variants = token_variants(strategy)
    hits: List[Dict[str, Any]] = []
    counts = Counter()
    for path in files:
        text = read_text(path)
        if text is None:
            continue
        lower = text.lower()
        matched_variant = next((variant for variant in variants if variant and variant in lower), None)
        if matched_variant is None:
            continue
        index = lower.find(matched_variant)
        flags = classify_hit(path, lower)
        for key, value in flags.items():
            counts[key] += int(value)
        hits.append(
            {
                "path": safe_relative(path),
                "variant": matched_variant,
                "flags": flags,
                "excerpt": context_excerpt(text, index),
            }
        )
        if len(hits) >= MAX_HITS_PER_STRATEGY:
            break
    return {
        "strategy": strategy,
        "variants": variants,
        "hit_count": len(hits),
        "classification_counts": dict(counts),
        "hits": hits,
    }


def alias_candidates(strategy: str, observed_names: Sequence[str]) -> List[Dict[str, Any]]:
    target = normalize(strategy)
    target_compact = target.replace("_", "")
    candidates = []
    for observed in observed_names:
        normalized = normalize(observed)
        if normalized == target:
            continue
        compact = normalized.replace("_", "")
        ratio = difflib.SequenceMatcher(None, target_compact, compact).ratio()
        target_parts = set(target.split("_"))
        observed_parts = set(normalized.split("_"))
        overlap = len(target_parts & observed_parts) / max(len(target_parts | observed_parts), 1)
        if ratio >= 0.72 or overlap >= 0.50:
            candidates.append({"observed": observed, "ratio": round(ratio, 4), "token_overlap": round(overlap, 4)})
    candidates.sort(key=lambda row: (row["ratio"], row["token_overlap"]), reverse=True)
    return candidates[:5]


def diagnosis_for(scan: Dict[str, Any], aliases: Sequence[Dict[str, Any]]) -> Tuple[str, str]:
    counts = scan["classification_counts"]
    implementation = int(counts.get("implementation", 0))
    registry = int(counts.get("registry", 0))
    writer = int(counts.get("writer", 0))
    runtime_source = int(counts.get("runtime_source", 0))
    if aliases and implementation == 0 and runtime_source == 0:
        return "POSSIBLE_ALIAS_MISMATCH", "confirm alias mapping before changing writers"
    if scan["hit_count"] == 0:
        return "ABSENT_FROM_SCANNED_CODE_AND_RUNTIME", "locate archived branch or remove stale registry membership"
    if registry > 0 and implementation == 0:
        return "REGISTERED_WITHOUT_ACTIVE_IMPLEMENTATION", "trace registry source and implementation package"
    if implementation > 0 and writer == 0:
        return "IMPLEMENTATION_WITHOUT_REALIZED_R_WRITER_REFERENCE", "bind close event to canonical realized-R writer"
    if writer > 0 and runtime_source == 0:
        return "WRITER_CODE_PRESENT_NO_RUNTIME_SOURCE", "verify timer/service activation and output path"
    if runtime_source > 0:
        return "RUNTIME_REFERENCE_PRESENT_NO_ACCEPTED_CLOSED_ROWS", "inspect status/timestamp/realized-R contract and alias"
    return "UNRESOLVED_REFERENCE_PATTERN", "inspect top source hits"


def source_writers(source_audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for item in source_audit.get("files", []):
        if int(item.get("accepted_rows", 0) or 0) <= 0:
            continue
        rows.append(
            {
                "path": safe_relative(Path(item.get("path", ""))),
                "accepted_rows": int(item.get("accepted_rows", 0)),
                "strategies": list(item.get("strategies", [])),
            }
        )
    rows.sort(key=lambda row: row["accepted_rows"], reverse=True)
    return rows


def sanitize_handoff(trace: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    strategies = []
    for item in trace["strategies"]:
        strategies.append(
            {
                "strategy": item["strategy"],
                "diagnosis": item["diagnosis"],
                "next_action": item["next_action"],
                "hit_count": item["scan"]["hit_count"],
                "classification_counts": item["scan"]["classification_counts"],
                "candidate_aliases": item["candidate_aliases"],
                "top_paths": [hit["path"] for hit in item["scan"]["hits"][:8]],
            }
        )
    return {
        "schema": "q4r3_runtime_handoff_v1",
        "job": "q4r3_missing_strategy_writer_trace",
        "status": decision["status"],
        "verdict": decision["verdict"],
        "action": decision["action"],
        "expected_strategy_count": trace["coverage_summary"]["expected_strategy_count"],
        "covered_expected_strategy_count": trace["coverage_summary"]["covered_expected_strategy_count"],
        "canonical_row_count": trace["coverage_summary"]["canonical_row_count"],
        "missing_strategy_count": len(strategies),
        "diagnosis_counts": trace["diagnosis_counts"],
        "strategies": strategies,
        "writer_sources": trace["writer_sources"][:20],
        "next_modules": decision["next_modules"],
        "authority": decision["authority"],
        "safety": {
            "sanitized": True,
            "raw_trade_rows_included": False,
            "credentials_included": False,
            "context_excerpts_included": False,
        },
    }


def write_html(trace: Dict[str, Any], decision: Dict[str, Any]) -> None:
    rows = []
    for item in trace["strategies"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['strategy'])}</td>"
            f"<td>{html.escape(item['diagnosis'])}</td>"
            f"<td>{item['scan']['hit_count']}</td>"
            f"<td>{html.escape(', '.join(hit['path'] for hit in item['scan']['hits'][:5]))}</td>"
            f"<td>{html.escape(item['next_action'])}</td>"
            "</tr>"
        )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Missing strategy writer trace</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px;vertical-align:top}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Missing strategy realized-R writer trace</h1>",
            "<table><thead><tr><th>Strategy</th><th>Diagnosis</th><th>Hits</th><th>Top paths</th><th>Next</th></tr></thead><tbody>",
            "".join(rows),
            "</tbody></table><h2>Decision</h2><pre>",
            html.escape(json.dumps(decision, ensure_ascii=False, indent=2)),
            "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    coverage = load_json(COVERAGE_PATH)
    ledger = load_json(LEDGER_PATH)
    source_audit = load_json(SOURCE_AUDIT_PATH)
    missing = [normalize(name) for name in coverage.get("missing_expected_strategies", [])]
    observed = [normalize(name) for name in coverage.get("unexpected_observed_strategies", [])]
    observed.extend(normalize(item.get("strategy")) for item in coverage.get("by_strategy", []))
    observed = sorted({name for name in observed if name})

    files = list(iter_scan_files())
    strategy_results = []
    for strategy in missing:
        scan = scan_strategy(strategy, files)
        aliases = alias_candidates(strategy, observed)
        diagnosis, next_action = diagnosis_for(scan, aliases)
        strategy_results.append(
            {
                "strategy": strategy,
                "diagnosis": diagnosis,
                "next_action": next_action,
                "candidate_aliases": aliases,
                "scan": scan,
            }
        )

    diagnosis_counts = dict(Counter(item["diagnosis"] for item in strategy_results))
    writer_sources = source_writers(source_audit)
    trace = {
        "status": "PASS_Q4R3_MISSING_STRATEGY_WRITER_TRACE",
        "verdict": "MISSING_STRATEGY_WRITER_AND_ALIAS_CAUSES_CLASSIFIED_NO_MUTATION",
        "coverage_summary": {
            "expected_strategy_count": int(coverage.get("expected_strategy_count", 0)),
            "covered_expected_strategy_count": int(coverage.get("covered_expected_strategy_count", 0)),
            "canonical_row_count": int(coverage.get("total_rows", ledger.get("row_count", 0))),
            "missing_strategy_count": len(missing),
            "missing_strategies": missing,
        },
        "scan_contract": {
            "roots": [safe_relative(path) for path in SCAN_ROOTS],
            "files_scanned": len(files),
            "max_file_bytes": MAX_FILE_BYTES,
            "read_only": True,
            "production_strategy_modified": False,
        },
        "diagnosis_counts": diagnosis_counts,
        "strategies": strategy_results,
        "writer_sources": writer_sources,
    }
    unresolved = sum(1 for item in strategy_results if item["diagnosis"] in {"ABSENT_FROM_SCANNED_CODE_AND_RUNTIME", "UNRESOLVED_REFERENCE_PATTERN"})
    decision = {
        "status": "PASS_Q4R3_MISSING_STRATEGY_WRITER_TRACE_DECISION",
        "verdict": "WRITER_TRACE_COMPLETE_TARGETED_REPAIR_MAP_READY",
        "action": "HOLD",
        "missing_strategy_count": len(missing),
        "diagnosis_counts": diagnosis_counts,
        "unresolved_count": unresolved,
        "priority_order": [
            "POSSIBLE_ALIAS_MISMATCH",
            "RUNTIME_REFERENCE_PRESENT_NO_ACCEPTED_CLOSED_ROWS",
            "WRITER_CODE_PRESENT_NO_RUNTIME_SOURCE",
            "IMPLEMENTATION_WITHOUT_REALIZED_R_WRITER_REFERENCE",
            "REGISTERED_WITHOUT_ACTIVE_IMPLEMENTATION",
            "ABSENT_FROM_SCANNED_CODE_AND_RUNTIME",
        ],
        "next_modules": [
            "PATCH_ONLY_CONFIRMED_ALIAS_OR_WRITER_GAPS",
            "RERUN_CANONICAL_LEDGER_ONCE",
            "FINAL_RASCHKE_PORTFOLIO_ROLE_DECISION_OR_FREEZE",
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
    handoff = sanitize_handoff(trace, decision)
    write_html(trace, decision)
    atomic_json(TRACE_OUT, trace)
    atomic_json(DECISION_OUT, decision)
    atomic_json(HANDOFF_OUT, handoff)
    print(json.dumps(handoff, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
