from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Tuple

ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"

COVERAGE_CANDIDATES = (
    RUNTIME / "q4r3_25_strategy_realized_r_coverage_latest.json",
    RUNTIME / "q4r3_25_strategy_realized_r_extended_coverage_latest.json",
    RUNTIME / "q4r3_25_strategy_realized_r_bind_decision_latest.json",
    RUNTIME / "q4r3_missing_strategy_writer_trace_handoff_latest.json",
)

SCAN_ROOT_NAMES = (
    "backend",
    "tools",
    "tests",
    "config",
    "configs",
    "data",
    "services",
    "systemd",
    "docs",
    "knowledge",
    "research",
    "skills",
)

ALLOWED_SUFFIXES = {
    ".py",
    ".sh",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".md",
    ".txt",
    ".service",
}

HARD_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "site-packages",
    "dist-packages",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "vendor",
    "third_party",
    "build",
    "dist",
    "static",
    "frontend",
    "templates",
}

EXCLUDED_NAME_PATTERNS = (
    re.compile(r"^_TRASH", re.I),
    re.compile(r"(^|[_\-.])(backup|bak|old|archive|archived|quarantine|trash)([_\-.]|$)", re.I),
    re.compile(r"\.disabled(?:_|\.|$)", re.I),
)

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_LOCATIONS_PER_CATEGORY = 20

ENTRY_TERMS = (
    "entry_price",
    "entry_ts",
    "entry_time",
    "signal_ts",
    "initial_stop",
    "stop_price",
    "stop_loss",
    "side",
    "symbol",
)
RISK_EXIT_TERMS = (
    "initial_risk_usdt",
    "position_risk_usdt",
    "risk_usdt",
    "realized_r",
    "pnl_r",
    "realized_pnl",
    "take_profit",
    "stop_loss",
    "trailing",
    "partial",
    "runner",
    "mfe",
    "mae",
    "time_stop",
)
WRITER_TERMS = (
    "write_text",
    "json.dump",
    "json.dumps",
    "append(",
    "open(",
    "atomic_json",
    "replace(",
    "ledger",
    "journal",
)
VALIDATION_TERMS = (
    "ablation",
    "walk_forward",
    "walk-forward",
    "holdout",
    "out_of_sample",
    "out-of-sample",
    "forward_shadow",
    "forward shadow",
    "bootstrap",
    "monte_carlo",
    "monte carlo",
    "profit_factor",
    "drawdown",
    "slippage",
    "latency",
    "fee",
    "regime",
    "mfe",
    "mae",
    "bocpd",
    "competing_risk",
)
KNOWLEDGE_PATTERNS = (
    re.compile(r"https?://(?:www\.)?(?:arxiv\.org|doi\.org|reddit\.com|youtube\.com|youtu\.be|tradingview\.com|medium\.com)", re.I),
    re.compile(r"\b(?:research paper|academic paper|peer[- ]reviewed|transcript|gemini|reddit|youtube|community|forum)\b", re.I),
    re.compile(r"\b(?:raschke|larry connors|wyckoff|livermore|turtle trading|bollinger|elder|market microstructure|order flow)\b", re.I),
)
SKILL_TERMS = (
    "long_beam",
    "short_beam",
    "scale_in",
    "pyramiding",
    "dca",
    "runner_hold",
    "trailing",
    "partial",
    "mfe_runner",
    "hedge",
    "reversal",
)

PUBLISHED_AUDIT_DIR = Path("runtime_results/q4r3/strategy_canonical_audit")
PUBLISHED_LIST_FILES = (
    "strategy_registry_policy_files.txt",
    "strategy_definition_locations.txt",
    "external_knowledge_locations.txt",
    "validation_evidence_locations.txt",
    "temporary_legacy_candidate_files.txt",
)


@dataclass(frozen=True)
class FileRecord:
    path: Path
    relative: str
    text: str
    lower: str
    lines: Tuple[str, ...]
    sha256: str


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)


def safe_relative(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def path_is_excluded(path: Path, root: Path = ROOT) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except Exception:
        rel = path
    for part in rel.parts:
        if part in HARD_EXCLUDED_PARTS:
            return True
        if any(pattern.search(part) for pattern in EXCLUDED_NAME_PATTERNS):
            return True
    return False


def iter_active_files(root: Path = ROOT) -> Iterator[Path]:
    seen: set[Path] = set()
    for name in SCAN_ROOT_NAMES:
        scan_root = root / name
        if not scan_root.exists():
            continue
        for current, dirs, files in os.walk(scan_root):
            current_path = Path(current)
            dirs[:] = [
                directory
                for directory in dirs
                if not path_is_excluded(current_path / directory, root)
            ]
            for filename in files:
                path = current_path / filename
                if path in seen or path_is_excluded(path, root):
                    continue
                if path.suffix.lower() not in ALLOWED_SUFFIXES:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size <= 0 or size > MAX_FILE_BYTES:
                    continue
                seen.add(path)
                yield path


def load_file_record(path: Path, root: Path = ROOT) -> Optional[FileRecord]:
    try:
        data = path.read_bytes()
        text = data.decode("utf-8", errors="ignore")
    except OSError:
        return None
    return FileRecord(
        path=path,
        relative=safe_relative(path, root),
        text=text,
        lower=text.lower(),
        lines=tuple(text.splitlines()),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def recursive_items(value: Any, path: Tuple[str, ...] = ()) -> Iterator[Tuple[Tuple[str, ...], Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from recursive_items(item, path + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from recursive_items(item, path + (str(index),))


def strategy_strings_from_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    names: List[str] = []
    for item in value:
        if isinstance(item, str):
            name = normalize(item)
        elif isinstance(item, Mapping):
            raw = None
            for key in ("strategy_id", "strategy", "strategy_name", "name", "id", "slug"):
                if item.get(key):
                    raw = item.get(key)
                    break
            name = normalize(raw)
        else:
            name = ""
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def universe_candidate_score(key_path: Sequence[str], names: Sequence[str], source: Path) -> int:
    key_text = ".".join(key_path).lower()
    score = 0
    if len(names) == 25:
        score += 100
    score -= abs(len(names) - 25) * 4
    if "expected" in key_text:
        score += 25
    if "universe" in key_text or "registry" in key_text:
        score += 20
    if "missing" in key_text or "unexpected" in key_text:
        score -= 80
    if "coverage" in source.name:
        score += 15
    if "handoff" in source.name:
        score += 5
    return score


def resolve_expected_universe(paths: Sequence[Path] = COVERAGE_CANDIDATES) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for path in paths:
        if not path.exists() or path.stat().st_size <= 0:
            continue
        try:
            payload = json.loads(path.read_text(errors="ignore"))
        except Exception:
            continue
        for key_path, value in recursive_items(payload):
            names = strategy_strings_from_list(value)
            if not names:
                continue
            score = universe_candidate_score(key_path, names, path)
            candidates.append(
                {
                    "source": str(path),
                    "key_path": ".".join(key_path),
                    "names": names,
                    "count": len(names),
                    "score": score,
                }
            )
    candidates.sort(key=lambda item: (item["score"], item["count"] == 25), reverse=True)
    selected = candidates[0] if candidates else None
    return {
        "selected": selected,
        "candidate_count": len(candidates),
        "top_candidates": candidates[:10],
        "resolved_exact_25": bool(selected and selected["count"] == 25),
    }


def strategy_pattern(strategy: str) -> re.Pattern[str]:
    canonical = normalize(strategy)
    parts = [re.escape(part) for part in canonical.split("_") if part]
    if not parts:
        return re.compile(r"a^")
    separator = r"[\s_\-./]*"
    return re.compile(r"(?<![a-z0-9])" + separator.join(parts) + r"(?![a-z0-9])", re.I)


def line_locations(record: FileRecord, pattern: re.Pattern[str], limit: int = MAX_LOCATIONS_PER_CATEGORY) -> List[str]:
    locations: List[str] = []
    for line_number, line in enumerate(record.lines, start=1):
        if pattern.search(line):
            locations.append(f"{record.relative}:{line_number}")
            if len(locations) >= limit:
                break
    return locations


def term_locations(record: FileRecord, terms: Sequence[str], limit: int = MAX_LOCATIONS_PER_CATEGORY) -> List[str]:
    locations: List[str] = []
    lowered_terms = tuple(term.lower() for term in terms)
    for line_number, line in enumerate(record.lines, start=1):
        lower = line.lower()
        if any(term in lower for term in lowered_terms):
            locations.append(f"{record.relative}:{line_number}")
            if len(locations) >= limit:
                break
    return locations


def knowledge_locations(record: FileRecord, limit: int = MAX_LOCATIONS_PER_CATEGORY) -> List[str]:
    locations: List[str] = []
    for line_number, line in enumerate(record.lines, start=1):
        if any(pattern.search(line) for pattern in KNOWLEDGE_PATTERNS):
            locations.append(f"{record.relative}:{line_number}")
            if len(locations) >= limit:
                break
    return locations


def file_role(relative: str) -> str:
    path = Path(relative)
    parts = set(path.parts)
    name = path.name.lower()
    if "tests" in parts or name.startswith("test_"):
        return "test"
    if "config" in parts or "configs" in parts or any(term in name for term in ("registry", "universe", "strategy_cards")):
        return "registry"
    if "docs" in parts or "knowledge" in parts or "research" in parts:
        return "knowledge"
    if "services" in parts or "systemd" in parts or name.endswith(".service"):
        return "service"
    if "backend" in parts:
        return "implementation"
    if "tools" in parts:
        return "tool"
    if "skills" in parts:
        return "skill"
    if "data" in parts:
        return "data"
    return "other"


def append_unique(target: MutableMapping[str, List[str]], key: str, values: Iterable[str], limit: int = MAX_LOCATIONS_PER_CATEGORY) -> None:
    existing = target.setdefault(key, [])
    for value in values:
        if value not in existing:
            existing.append(value)
        if len(existing) >= limit:
            break


def analyze_strategy(strategy: str, records: Sequence[FileRecord]) -> Dict[str, Any]:
    pattern = strategy_pattern(strategy)
    hits: List[FileRecord] = []
    by_role: Dict[str, List[str]] = defaultdict(list)
    evidence: Dict[str, List[str]] = defaultdict(list)
    hashes: Dict[str, List[str]] = defaultdict(list)

    for record in records:
        path_match = pattern.search(record.relative.replace("/", " "))
        text_match = pattern.search(record.text)
        if not path_match and not text_match:
            continue
        hits.append(record)
        role = file_role(record.relative)
        by_role[role].append(record.relative)
        hashes[record.sha256].append(record.relative)
        strategy_locs = line_locations(record, pattern)
        append_unique(evidence, "identity", strategy_locs or [record.relative])

        entry_locs = term_locations(record, ENTRY_TERMS)
        risk_locs = term_locations(record, RISK_EXIT_TERMS)
        writer_locs = term_locations(record, WRITER_TERMS)
        validation_locs = term_locations(record, VALIDATION_TERMS)
        knowledge_locs = knowledge_locations(record)
        skill_locs = term_locations(record, SKILL_TERMS)

        if entry_locs:
            append_unique(evidence, "entry_contract", entry_locs)
        if risk_locs:
            append_unique(evidence, "risk_exit_contract", risk_locs)
        if writer_locs and role in {"implementation", "tool", "service"}:
            append_unique(evidence, "writer_contract", writer_locs)
        if validation_locs and role in {"test", "tool", "knowledge", "data", "implementation"}:
            append_unique(evidence, "validation", validation_locs)
        if knowledge_locs:
            append_unique(evidence, "knowledge_trace", knowledge_locs)
        if skill_locs:
            append_unique(evidence, "skill_hooks", skill_locs)

    duplicate_groups = [paths for paths in hashes.values() if len(paths) > 1]
    implementation_paths = sorted(set(by_role.get("implementation", [])))
    registry_paths = sorted(set(by_role.get("registry", [])))
    test_paths = sorted(set(by_role.get("test", [])))

    gates = {
        "identity": bool(hits),
        "implementation": bool(implementation_paths),
        "registry": bool(registry_paths),
        "entry_contract": bool(evidence.get("entry_contract")),
        "risk_exit_contract": bool(evidence.get("risk_exit_contract")),
        "writer_contract": bool(evidence.get("writer_contract")),
        "tests": bool(test_paths),
        "validation": bool(evidence.get("validation")),
        "knowledge_trace": bool(evidence.get("knowledge_trace")),
        "skill_hooks": bool(evidence.get("skill_hooks")),
        "duplicate_conflict_free": len(duplicate_groups) == 0,
    }
    weights = {
        "identity": 5,
        "implementation": 20,
        "registry": 10,
        "entry_contract": 10,
        "risk_exit_contract": 15,
        "writer_contract": 10,
        "tests": 10,
        "validation": 10,
        "knowledge_trace": 5,
        "skill_hooks": 5,
    }
    score = sum(weight for key, weight in weights.items() if gates[key])
    if not gates["duplicate_conflict_free"]:
        score = max(0, score - 10)

    required = (
        "implementation",
        "registry",
        "entry_contract",
        "risk_exit_contract",
        "writer_contract",
        "tests",
        "validation",
    )
    missing_required = [key for key in required if not gates[key]]

    if not gates["identity"]:
        verdict = "MISSING_FROM_ACTIVE_SOURCE"
    elif not gates["implementation"] and gates["registry"]:
        verdict = "REGISTRY_ONLY"
    elif not gates["implementation"]:
        verdict = "REFERENCE_ONLY"
    elif duplicate_groups:
        verdict = "DUPLICATE_IMPLEMENTATION_REVIEW_REQUIRED"
    elif not missing_required:
        verdict = "COMPLETE_CANDIDATE_PENDING_ABLATION"
    else:
        verdict = "PARTIAL_ACTIVE_IMPLEMENTATION"

    return {
        "strategy": strategy,
        "score_100": score,
        "verdict": verdict,
        "gates": gates,
        "missing_required": missing_required,
        "active_reference_count": len(hits),
        "paths_by_role": {key: sorted(set(values))[:50] for key, values in sorted(by_role.items())},
        "evidence_locations": {key: values for key, values in sorted(evidence.items())},
        "duplicate_sha_groups": duplicate_groups[:20],
    }


def parse_location_path(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if " | " in line:
        candidate = line.rsplit(" | ", 1)[-1]
    else:
        candidate = line
    candidate = re.sub(r":\d+$", "", candidate)
    return candidate.lstrip("+").strip()


def pollution_bucket(path_text: str) -> str:
    lower = path_text.lower()
    if "/.venv/" in lower or lower.startswith("./.venv/") or "/site-packages/" in lower:
        return "dependency"
    if "_trash" in lower or "quarantine" in lower:
        return "trash_quarantine"
    if any(token in lower for token in ("backup", ".bak", "archive", "legacy", "old")):
        return "backup_legacy"
    if lower.startswith("./frontend/") or lower.startswith("./templates/") or lower.startswith("./static/"):
        return "frontend_display"
    if lower.startswith("./runtime/") or lower.startswith("./ledger/"):
        return "runtime_generated"
    if lower.startswith("./backend/") or lower.startswith("./tools/") or lower.startswith("./tests/") or lower.startswith("./config"):
        return "active_candidate"
    return "other"


def published_audit_pollution(worktree: Path) -> Dict[str, Any]:
    root = worktree / PUBLISHED_AUDIT_DIR
    reports: Dict[str, Any] = {}
    totals = Counter()
    for filename in PUBLISHED_LIST_FILES:
        path = root / filename
        counts = Counter()
        line_count = 0
        if path.exists():
            for line in path.read_text(errors="ignore").splitlines():
                candidate = parse_location_path(line)
                if not candidate:
                    continue
                line_count += 1
                bucket = pollution_bucket(candidate)
                counts[bucket] += 1
                totals[bucket] += 1
        reports[filename] = {
            "line_count": line_count,
            "buckets": dict(counts),
            "noise_count": line_count - counts.get("active_candidate", 0),
            "active_candidate_count": counts.get("active_candidate", 0),
            "noise_ratio": round((line_count - counts.get("active_candidate", 0)) / line_count, 6) if line_count else None,
        }
    return {"files": reports, "aggregate_buckets": dict(totals)}


def git_baseline_summary(worktree: Path) -> Dict[str, Any]:
    path = worktree / PUBLISHED_AUDIT_DIR / "git_baseline.txt"
    if not path.exists():
        return {"available": False}
    lines = path.read_text(errors="ignore").splitlines()
    status_lines = [line for line in lines if re.match(r"^(?:M|D|A|R|C|UU|\?\?)\s", line)]
    frontend = [line for line in status_lines if "frontend/" in line]
    return {
        "available": True,
        "root": lines[0] if len(lines) > 0 else None,
        "branch": lines[1] if len(lines) > 1 else None,
        "head": lines[2] if len(lines) > 2 else None,
        "dirty_status_count": len(status_lines),
        "frontend_status_count": len(frontend),
        "clean": len(status_lines) == 0,
    }


def render_html(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result.get("strategies", []):
        missing = ", ".join(item.get("missing_required", [])) or "-"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('strategy')))}</td>"
            f"<td>{item.get('score_100')}</td>"
            f"<td>{html.escape(str(item.get('verdict')))}</td>"
            f"<td>{html.escape(missing)}</td>"
            "</tr>"
        )
    return """<!doctype html><html><head><meta charset='utf-8'><title>Q4R3 Strategy Canonical Completeness</title>
<style>body{font-family:Arial,sans-serif;margin:24px;background:#111;color:#eee}table{border-collapse:collapse;width:100%}th,td{border:1px solid #444;padding:8px;text-align:left}th{background:#222}.mono{font-family:monospace;white-space:pre-wrap}</style></head><body>""" + (
        f"<h1>{html.escape(str(result.get('verdict')))}</h1>"
        f"<p>Expected strategies: {result.get('expected_strategy_count')} | Active files: {result.get('active_file_count')}</p>"
        "<table><thead><tr><th>Strategy</th><th>Score</th><th>Verdict</th><th>Missing required</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )


def summarize(strategies: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    verdict_counts = Counter(str(item.get("verdict")) for item in strategies)
    missing_counts = Counter()
    for item in strategies:
        missing_counts.update(item.get("missing_required", []))
    complete = verdict_counts.get("COMPLETE_CANDIDATE_PENDING_ABLATION", 0)
    return {
        "verdict_counts": dict(verdict_counts),
        "missing_gate_counts": dict(missing_counts),
        "complete_candidate_count": complete,
        "incomplete_count": len(strategies) - complete,
        "average_score": round(sum(int(item.get("score_100", 0)) for item in strategies) / len(strategies), 3) if strategies else 0.0,
    }


def write_csv(path: Path, strategies: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["strategy", "score_100", "verdict", "missing_required", "implementation_paths", "registry_paths", "test_paths"])
        for item in strategies:
            roles = item.get("paths_by_role", {})
            writer.writerow(
                [
                    item.get("strategy"),
                    item.get("score_100"),
                    item.get("verdict"),
                    ";".join(item.get("missing_required", [])),
                    ";".join(roles.get("implementation", [])),
                    ";".join(roles.get("registry", [])),
                    ";".join(roles.get("test", [])),
                ]
            )


def run(root: Path, worktree: Path, output_dir: Path) -> Dict[str, Any]:
    global ROOT, RUNTIME, COVERAGE_CANDIDATES
    ROOT = root
    RUNTIME = root / "runtime"
    COVERAGE_CANDIDATES = (
        RUNTIME / "q4r3_25_strategy_realized_r_coverage_latest.json",
        RUNTIME / "q4r3_25_strategy_realized_r_extended_coverage_latest.json",
        RUNTIME / "q4r3_25_strategy_realized_r_bind_decision_latest.json",
        RUNTIME / "q4r3_missing_strategy_writer_trace_handoff_latest.json",
    )

    universe = resolve_expected_universe(COVERAGE_CANDIDATES)
    selected = universe.get("selected") or {}
    expected = selected.get("names", []) if universe.get("resolved_exact_25") else []

    records: List[FileRecord] = []
    for path in iter_active_files(root):
        record = load_file_record(path, root)
        if record is not None:
            records.append(record)

    strategies = [analyze_strategy(strategy, records) for strategy in expected]
    strategies.sort(key=lambda item: (item["score_100"], item["strategy"]))
    summary = summarize(strategies)
    pollution = published_audit_pollution(worktree)
    baseline = git_baseline_summary(worktree)

    if not universe.get("resolved_exact_25"):
        verdict = "EXPECTED_25_STRATEGY_UNIVERSE_NOT_RESOLVED"
        next_action = "RESOLVE_EXACT_25_UNIVERSE_BEFORE_STRATEGY_MUTATION"
    elif summary["complete_candidate_count"] == 25:
        verdict = "ALL_25_COMPLETE_CANDIDATES_READY_FOR_CAUSAL_ABLATION"
        next_action = "FREEZE_FILE_SHAS_AND_START_PER_STRATEGY_ABLATION"
    else:
        verdict = "CANONICAL_25_STRATEGY_SET_INCOMPLETE"
        next_action = "PATCH_GAPS_IN_PRIORITY_ORDER_WITHOUT_ENSEMBLE_PROMOTION"

    result: Dict[str, Any] = {
        "schema": "q4r3_strategy_canonical_completeness_v1",
        "status": "PASS_Q4R3_STRATEGY_CANONICAL_COMPLETENESS_AUDIT",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_strategy_count": len(expected),
        "expected_universe": universe,
        "active_file_count": len(records),
        "active_file_role_counts": dict(Counter(file_role(record.relative) for record in records)),
        "git_baseline": baseline,
        "first_pass_pollution": pollution,
        "summary": summary,
        "strategies": strategies,
        "repair_priority": [
            "identity_and_single_canonical_file",
            "registry_binding",
            "entry_and_initial_risk_contract",
            "exit_and_realized_r_writer_contract",
            "strategy_specific_tests",
            "walk_forward_ablation_and_regime_validation",
            "external_knowledge_source_decision_trace",
            "skill_hooks_only_after_core_logic_passes",
        ],
        "safety": {
            "read_only": True,
            "raw_trade_rows_included": False,
            "source_excerpts_included": False,
            "strategy_files_modified": False,
            "registry_modified": False,
            "paper_live_order_modified": False,
            "persistent_forward_r_watcher_modified": False,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "q4r3_strategy_canonical_completeness_latest.json", result)
    atomic_json(
        output_dir / "q4r3_strategy_canonical_gap_plan_latest.json",
        {
            "schema": "q4r3_strategy_canonical_gap_plan_v1",
            "verdict": verdict,
            "action": "HOLD",
            "repair_priority": result["repair_priority"],
            "strategies": [
                {
                    "strategy": item["strategy"],
                    "score_100": item["score_100"],
                    "verdict": item["verdict"],
                    "missing_required": item["missing_required"],
                }
                for item in strategies
            ],
        },
    )
    write_csv(output_dir / "q4r3_strategy_canonical_matrix_latest.csv", strategies)
    (output_dir / "q4r3_strategy_canonical_completeness_latest.html").write_text(render_html(result), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root, args.worktree, args.output_dir)
    print(json.dumps({
        "status": result["status"],
        "verdict": result["verdict"],
        "expected_strategy_count": result["expected_strategy_count"],
        "active_file_count": result["active_file_count"],
        "summary": result["summary"],
        "next_action": result["next_action"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
