from __future__ import annotations

import argparse
import ast
import hashlib
import html
import io
import json
import os
import re
import subprocess
import tarfile
import zipfile
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

ROOT = Path("/home/z/z")
TARGETS: Mapping[str, Mapping[str, Any]] = {
    "ema_ribbon_scalp": {
        "canonical_path": "backend/strategies/ema_ribbon_scalp.py",
        "terms": (
            "ema_ribbon_scalp",
            "ema ribbon",
            "ribbon",
            "ema_fast",
            "ema_slow",
            "alignment",
            "pullback",
            "slope",
            "atr",
            "stop_loss",
            "take_profit",
        ),
    },
    "vol_spike_fade": {
        "canonical_path": "backend/strategies/vol_spike_fade.py",
        "terms": (
            "vol_spike_fade",
            "volume spike",
            "volume_z",
            "zscore",
            "fade",
            "mean_reversion",
            "rsi",
            "atr",
            "stop_loss",
            "take_profit",
        ),
    },
}
EXPECTED_25: Tuple[str, ...] = (
    "alpha_combo",
    "anchor_vwap_trend",
    "bb_revert",
    "break_and_continue",
    "ema_ribbon_scalp",
    "fvg_revert",
    "grid_rebalance",
    "keltner_trend",
    "liquidity_sweep",
    "mfi_rsi_div",
    "obv_trend",
    "pivot_reversal",
    "range_fade",
    "rbreaker_like",
    "rsi_swing_fail",
    "scalp_snap",
    "session_bias",
    "squeeze_break",
    "sr_levels",
    "supertrend_pullback",
    "trend_ma_macd",
    "trend_rider",
    "turtle_trend",
    "vol_spike_fade",
    "vwap_revert",
)
TEXT_SUFFIXES = {".py", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt", ".service", ".sh"}
ARCHIVE_SUFFIXES = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz"}
DEPENDENCY_PARTS = {".git", ".venv", "venv", "env", "node_modules", "site-packages", "dist-packages", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "vendor", "third_party", "build", "dist"}
BACKUP_MARKERS = ("backup", "bak", "archive", "archived", "trash", "quarantine", "legacy", "old", "disabled")
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_ARCHIVES = 200
MAX_ARCHIVE_MEMBER_BYTES = 2 * 1024 * 1024
MAX_CANDIDATES_PER_TARGET = 20
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        rb"(?ix)\b(api[_-]?key|secret(?:[_-]?key)?|password|private[_-]?key|access[_-]?token|refresh[_-]?token)\b\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9._~+/=-]{8,})"
    ),
)


@dataclass
class Candidate:
    strategy: str
    origin_kind: str
    source_path: str
    source_ref: Optional[str]
    object_sha: Optional[str]
    content_sha256: str
    size_bytes: int
    line_count: int
    ast_valid: bool
    function_count: int
    class_count: int
    matched_terms: List[str]
    score_100: int
    wrapper_like: bool
    secret_safe: bool
    compile_error: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    published_path: Optional[str] = None
    content: str = field(default="", repr=False)

    def public(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("content", None)
        return payload


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text).strip("_"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_command(args: Sequence[str], cwd: Path, timeout: int = 120, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"COMMAND_FAILED:{result.returncode}:{' '.join(args)}:{result.stderr[-500:]}")
    return result


def safe_read(path: Path, max_bytes: int = MAX_TEXT_BYTES) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            return None
        return path.read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return None


def has_secret(data: bytes) -> bool:
    return any(pattern.search(data) for pattern in SECRET_PATTERNS)


def classify_origin_path(path: str) -> str:
    lower = path.lower().replace("\\", "/")
    if lower.startswith("backend/strategies/") and not any(marker in lower for marker in BACKUP_MARKERS):
        return "active_canonical_path"
    if lower.startswith("backend/legendary_rebuild/strategies/"):
        return "legendary_reserve_path"
    if lower.startswith("backend/strategies_v4/"):
        return "v4_overlay_path"
    if any(marker in lower for marker in BACKUP_MARKERS):
        return "backup_or_archive_path"
    if lower.startswith("runtime/") or lower.startswith("runtime_results/"):
        return "runtime_generated_path"
    return "other_working_path"


def inspect_python(text: str) -> Tuple[bool, int, int, Optional[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return False, 0, 0, f"{exc.__class__.__name__}:{exc.lineno}:{exc.msg}"
    functions = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
    classes = sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    return True, functions, classes, None


def candidate_score(strategy: str, origin_kind: str, path: str, text: str) -> Candidate:
    data = text.encode("utf-8", errors="ignore")
    lower = text.lower()
    lines = text.splitlines()
    target = TARGETS[strategy]
    matched = [term for term in target["terms"] if term.lower() in lower]
    ast_valid, function_count, class_count, compile_error = inspect_python(text) if path.lower().endswith(".py") else (False, 0, 0, "NOT_PYTHON")
    exact_identity = strategy in normalize(Path(path).stem) or strategy in normalize(text[:10000])
    wrapper_like = len(lines) < 45 or (function_count <= 1 and class_count == 0)

    score = 0
    if exact_identity:
        score += 22
    if path.replace("\\", "/").endswith(str(target["canonical_path"])):
        score += 24
    if origin_kind in {"active_canonical_path", "historical_reachable_blob_exact", "historical_commit_exact"}:
        score += 12
    if ast_valid:
        score += 10
    score += min(20, len(set(matched)) * 3)
    if function_count >= 3:
        score += 5
    if class_count >= 1:
        score += 5
    if len(lines) >= 100:
        score += 6
    elif len(lines) >= 50:
        score += 3
    if any(term in lower for term in ("stop_loss", "initial_stop", "sl_price", "stop_price")):
        score += 4
    if any(term in lower for term in ("take_profit", "tp_price", "trailing", "partial")):
        score += 4
    if wrapper_like:
        score -= 22
    if origin_kind in {"legendary_reserve_path", "runtime_generated_path"}:
        score -= 8
    secret_safe = not has_secret(data)
    if not secret_safe:
        score = 0
    score = max(0, min(100, score))

    return Candidate(
        strategy=strategy,
        origin_kind=origin_kind,
        source_path=path,
        source_ref=None,
        object_sha=None,
        content_sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        line_count=len(lines),
        ast_valid=ast_valid,
        function_count=function_count,
        class_count=class_count,
        matched_terms=sorted(set(matched)),
        score_100=score,
        wrapper_like=wrapper_like,
        secret_safe=secret_safe,
        compile_error=compile_error,
        content=text,
    )


def merge_candidate(target: MutableMapping[str, Candidate], candidate: Candidate) -> None:
    existing = target.get(candidate.content_sha256)
    if existing is None:
        target[candidate.content_sha256] = candidate
        return
    if candidate.score_100 > existing.score_100:
        candidate.provenance = {**existing.provenance, **candidate.provenance}
        target[candidate.content_sha256] = candidate
    else:
        existing.provenance.update(candidate.provenance)


def iter_working_text_files(root: Path) -> Iterator[Path]:
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in DEPENDENCY_PARTS]
        for filename in files:
            path = current_path / filename
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size <= 0 or path.stat().st_size > MAX_TEXT_BYTES:
                    continue
            except OSError:
                continue
            yield path


def scan_working_tree(root: Path) -> Dict[str, Dict[str, Candidate]]:
    found: Dict[str, Dict[str, Candidate]] = {strategy: {} for strategy in TARGETS}
    for path in iter_working_text_files(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        normalized_path = normalize(rel)
        likely = [strategy for strategy in TARGETS if strategy in normalized_path]
        text: Optional[str] = None
        if not likely:
            text = safe_read(path)
            if text is None:
                continue
            lower = text.lower()
            likely = [strategy for strategy, spec in TARGETS.items() if strategy in normalize(lower[:20000]) or any(term in lower for term in spec["terms"][:3])]
        if not likely:
            continue
        if text is None:
            text = safe_read(path)
        if text is None:
            continue
        for strategy in likely:
            candidate = candidate_score(strategy, classify_origin_path(rel), rel, text)
            candidate.provenance["working_tree"] = True
            merge_candidate(found[strategy], candidate)
    return found


def git_object_rows(root: Path) -> List[Tuple[str, str]]:
    result = run_command(["git", "rev-list", "--objects", "--all"], root, timeout=300)
    rows: List[Tuple[str, str]] = []
    if result.returncode != 0:
        return rows
    for line in result.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        sha, path = parts
        if path.lower().endswith(".py"):
            rows.append((sha.strip(), path.strip()))
    return rows


def cat_git_blob(root: Path, sha: str) -> Optional[str]:
    type_result = run_command(["git", "cat-file", "-t", sha], root, timeout=30)
    if type_result.returncode != 0 or type_result.stdout.strip() != "blob":
        return None
    size_result = run_command(["git", "cat-file", "-s", sha], root, timeout=30)
    try:
        size = int(size_result.stdout.strip())
    except Exception:
        return None
    if size <= 0 or size > MAX_BLOB_BYTES:
        return None
    content = run_command(["git", "cat-file", "-p", sha], root, timeout=60)
    if content.returncode != 0:
        return None
    return content.stdout


def commit_lineage_for_path(root: Path, path: str) -> List[Dict[str, str]]:
    result = run_command(
        ["git", "log", "--all", "--follow", "--date=iso-strict", "--format=%H%x09%ad%x09%s", "--", path],
        root,
        timeout=180,
    )
    lineage: List[Dict[str, str]] = []
    if result.returncode != 0:
        return lineage
    for line in result.stdout.splitlines()[:50]:
        parts = line.split("\t", 2)
        if len(parts) == 3:
            lineage.append({"commit": parts[0], "date": parts[1], "subject": parts[2]})
    return lineage


def scan_reachable_git_history(root: Path) -> Dict[str, Dict[str, Candidate]]:
    found: Dict[str, Dict[str, Candidate]] = {strategy: {} for strategy in TARGETS}
    rows = git_object_rows(root)
    for sha, path in rows:
        normalized_path = normalize(path)
        path_targets = [strategy for strategy in TARGETS if strategy in normalized_path]
        if not path_targets and not (path.startswith("backend/strateg") or path.startswith("backend/legendary")):
            continue
        text = cat_git_blob(root, sha)
        if text is None:
            continue
        lower = text.lower()
        targets = path_targets or [
            strategy
            for strategy, spec in TARGETS.items()
            if strategy in normalize(lower[:30000]) or any(term in lower for term in spec["terms"][:3])
        ]
        for strategy in targets:
            exact = path == TARGETS[strategy]["canonical_path"]
            kind = "historical_reachable_blob_exact" if exact else "historical_reachable_blob_fuzzy"
            candidate = candidate_score(strategy, kind, path, text)
            candidate.object_sha = sha
            candidate.source_ref = f"git-object:{sha}"
            candidate.provenance["commit_lineage"] = commit_lineage_for_path(root, path)
            merge_candidate(found[strategy], candidate)
    return found


def scan_dangling_blobs(root: Path) -> Dict[str, Dict[str, Candidate]]:
    found: Dict[str, Dict[str, Candidate]] = {strategy: {} for strategy in TARGETS}
    result = run_command(["git", "fsck", "--full", "--unreachable", "--no-reflogs"], root, timeout=300)
    if result.returncode not in (0, 1):
        return found
    blob_shas: List[str] = []
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        match = re.search(r"unreachable blob ([0-9a-f]{40})", line)
        if match:
            blob_shas.append(match.group(1))
    for sha in blob_shas[:5000]:
        text = cat_git_blob(root, sha)
        if text is None:
            continue
        lower = text.lower()
        for strategy, spec in TARGETS.items():
            if strategy not in normalize(lower[:50000]) and not any(term in lower for term in spec["terms"][:3]):
                continue
            candidate = candidate_score(strategy, "dangling_git_blob", f"dangling/{sha}.py", text)
            candidate.object_sha = sha
            candidate.source_ref = f"git-dangling:{sha}"
            merge_candidate(found[strategy], candidate)
    return found


def iter_archive_paths(root: Path) -> Iterator[Path]:
    count = 0
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in DEPENDENCY_PARTS]
        for filename in files:
            path = current_path / filename
            lower = filename.lower()
            if any(lower.endswith(suffix) for suffix in ARCHIVE_SUFFIXES):
                yield path
                count += 1
                if count >= MAX_ARCHIVES:
                    return


def scan_archives(root: Path) -> Dict[str, Dict[str, Candidate]]:
    found: Dict[str, Dict[str, Candidate]] = {strategy: {} for strategy in TARGETS}
    for archive_path in iter_archive_paths(root):
        rel_archive = str(archive_path.relative_to(root)).replace("\\", "/")
        try:
            if zipfile.is_zipfile(archive_path):
                with zipfile.ZipFile(archive_path) as archive:
                    members = [(info.filename, info.file_size, lambda info=info: archive.read(info)) for info in archive.infolist() if not info.is_dir()]
                    for member_name, member_size, reader in members:
                        if member_size <= 0 or member_size > MAX_ARCHIVE_MEMBER_BYTES or not member_name.lower().endswith(".py"):
                            continue
                        normalized_name = normalize(member_name)
                        likely = [strategy for strategy in TARGETS if strategy in normalized_name]
                        if not likely:
                            continue
                        data = reader()
                        text = data.decode("utf-8", errors="ignore")
                        for strategy in likely:
                            candidate = candidate_score(strategy, "archive_member", f"{rel_archive}!{member_name}", text)
                            candidate.source_ref = rel_archive
                            merge_candidate(found[strategy], candidate)
            elif tarfile.is_tarfile(archive_path):
                with tarfile.open(archive_path, "r:*") as archive:
                    for member in archive.getmembers():
                        if not member.isfile() or member.size <= 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES or not member.name.lower().endswith(".py"):
                            continue
                        normalized_name = normalize(member.name)
                        likely = [strategy for strategy in TARGETS if strategy in normalized_name]
                        if not likely:
                            continue
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            continue
                        text = extracted.read().decode("utf-8", errors="ignore")
                        for strategy in likely:
                            candidate = candidate_score(strategy, "archive_member", f"{rel_archive}!{member.name}", text)
                            candidate.source_ref = rel_archive
                            merge_candidate(found[strategy], candidate)
        except (OSError, zipfile.BadZipFile, tarfile.TarError):
            continue
    return found


def combine_candidate_maps(*maps: Mapping[str, Mapping[str, Candidate]]) -> Dict[str, List[Candidate]]:
    combined: Dict[str, Dict[str, Candidate]] = {strategy: {} for strategy in TARGETS}
    for source_map in maps:
        for strategy, candidates in source_map.items():
            for candidate in candidates.values():
                merge_candidate(combined[strategy], candidate)
    ranked: Dict[str, List[Candidate]] = {}
    for strategy, candidates in combined.items():
        ranked[strategy] = sorted(
            candidates.values(),
            key=lambda item: (item.secret_safe, item.score_100, item.ast_valid, item.line_count),
            reverse=True,
        )[:MAX_CANDIDATES_PER_TARGET]
    return ranked


def publish_candidate_sources(output_dir: Path, ranked: Mapping[str, Sequence[Candidate]]) -> None:
    source_root = output_dir / "candidate_sources"
    source_root.mkdir(parents=True, exist_ok=True)
    for strategy, candidates in ranked.items():
        published = 0
        for candidate in candidates:
            if published >= 5 or not candidate.secret_safe or not candidate.ast_valid or candidate.score_100 < 35:
                continue
            filename = f"{published + 1:02d}_{candidate.origin_kind}_{candidate.content_sha256[:12]}.py"
            filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)
            target = source_root / strategy / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(candidate.content, encoding="utf-8")
            candidate.published_path = str(target.relative_to(output_dir.parent.parent.parent)).replace("\\", "/")
            published += 1


def active_source_files(root: Path) -> List[Path]:
    roots = [root / name for name in ("backend", "scripts", "services", "systemd", "tools", "config", "configs", "data")]
    paths: List[Path] = []
    for scan_root in roots:
        if not scan_root.exists():
            continue
        for current, dirs, files in os.walk(scan_root):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if name not in DEPENDENCY_PARTS and not any(marker in name.lower() for marker in BACKUP_MARKERS)]
            for filename in files:
                path = current_path / filename
                if path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                try:
                    if 0 < path.stat().st_size <= MAX_TEXT_BYTES:
                        paths.append(path)
                except OSError:
                    continue
    return sorted(set(paths))


def module_name(root: Path, path: Path) -> Optional[str]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if rel.suffix != ".py":
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def import_graph(root: Path, py_files: Sequence[Path]) -> Tuple[Dict[str, str], Dict[str, Set[str]]]:
    module_to_path: Dict[str, str] = {}
    path_to_module: Dict[str, str] = {}
    for path in py_files:
        module = module_name(root, path)
        if module:
            rel = str(path.relative_to(root)).replace("\\", "/")
            module_to_path[module] = rel
            path_to_module[rel] = module

    graph: Dict[str, Set[str]] = defaultdict(set)
    for path in py_files:
        rel = str(path.relative_to(root)).replace("\\", "/")
        text = safe_read(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        current_module = path_to_module.get(rel, "")
        current_package = current_module.rsplit(".", 1)[0] if "." in current_module else ""
        for node in ast.walk(tree):
            names: List[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level and current_package:
                    package_parts = current_package.split(".")
                    prefix = package_parts[: max(0, len(package_parts) - node.level + 1)]
                    base = ".".join(prefix + ([base] if base else []))
                names.append(base)
            for name in names:
                candidate = name
                while candidate:
                    target = module_to_path.get(candidate)
                    if target:
                        graph[rel].add(target)
                        break
                    candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
    return module_to_path, graph


def runtime_entrypoints(root: Path) -> Dict[str, Any]:
    paths: Set[str] = set()
    processes: List[Dict[str, Any]] = []
    proc_root = Path("/proc")
    if proc_root.exists():
        for child in proc_root.iterdir():
            if not child.name.isdigit():
                continue
            try:
                raw = (child / "cmdline").read_bytes()
            except OSError:
                continue
            args = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\0") if part]
            repo_paths: List[str] = []
            for arg in args:
                if arg.startswith(str(root)):
                    try:
                        rel = str(Path(arg).resolve().relative_to(root.resolve())).replace("\\", "/")
                    except Exception:
                        continue
                    repo_paths.append(rel)
                    if rel.endswith(".py"):
                        paths.add(rel)
            if repo_paths:
                processes.append({"pid": int(child.name), "args": args[:20], "repo_paths": repo_paths})
    for known in ("backend/run_server.py", "scripts/learn/router_learner.py"):
        if (root / known).is_file():
            paths.add(known)
    return {"entrypoint_paths": sorted(paths), "processes": processes}


def reachable_paths(entrypoints: Sequence[str], graph: Mapping[str, Set[str]]) -> Set[str]:
    visited: Set[str] = set()
    queue: deque[str] = deque(entrypoints)
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for child in graph.get(current, set()):
            if child not in visited:
                queue.append(child)
    return visited


def strategy_coverage(text: str) -> Tuple[int, List[str]]:
    lower = normalize(text)
    matched = [strategy for strategy in EXPECTED_25 if strategy in lower]
    return len(matched), matched


def registry_candidates(root: Path, files: Sequence[Path], reachable: Set[str]) -> Dict[str, Any]:
    text_cache: Dict[str, str] = {}
    for path in files:
        rel = str(path.relative_to(root)).replace("\\", "/")
        text = safe_read(path)
        if text is not None:
            text_cache[rel] = text

    candidates: List[Dict[str, Any]] = []
    for rel, text in text_cache.items():
        name = Path(rel).name.lower()
        lower = text.lower()
        if not any(token in name for token in ("registry", "catalog", "manifest", "strategies")) and not (
            "importlib" in lower and "strategy" in lower
        ):
            continue
        coverage_count, matched = strategy_coverage(text)
        if coverage_count == 0:
            continue
        importers: List[str] = []
        module = rel[:-3].replace("/", ".") if rel.endswith(".py") else None
        basename = Path(rel).name
        for other_rel, other_text in text_cache.items():
            if other_rel == rel:
                continue
            if (module and module in other_text) or basename in other_text or rel in other_text:
                importers.append(other_rel)
        reachable_direct = rel in reachable
        reachable_reader = any(importer in reachable for importer in importers)
        structural_loader = any(token in lower for token in ("importlib", "module_path", "strategy_id", "load_strategy", "get_strategy", "strategy_map"))
        exact_25 = coverage_count == 25
        if exact_25 and structural_loader and (reachable_direct or reachable_reader):
            role = "RUNTIME_EXACT_25_AUTHORITY_CANDIDATE"
        elif exact_25 and not (reachable_direct or reachable_reader):
            role = "EXACT_25_DISCOVERY_OR_HISTORY_SURFACE"
        elif structural_loader and (reachable_direct or reachable_reader):
            role = "PARTIAL_RUNTIME_REGISTRY"
        else:
            role = "NONAUTHORITATIVE_REFERENCE_SURFACE"
        candidates.append(
            {
                "path": rel,
                "sha256": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest(),
                "coverage_count": coverage_count,
                "coverage_pct": round(coverage_count / 25 * 100, 3),
                "matched_strategies": matched,
                "runtime_reachable_direct": reachable_direct,
                "runtime_reachable_reader": reachable_reader,
                "importer_count": len(importers),
                "importers": sorted(importers)[:50],
                "structural_loader": structural_loader,
                "role": role,
            }
        )
    candidates.sort(
        key=lambda item: (
            item["role"] == "RUNTIME_EXACT_25_AUTHORITY_CANDIDATE",
            item["coverage_count"],
            item["runtime_reachable_direct"],
            item["runtime_reachable_reader"],
        ),
        reverse=True,
    )
    authoritative = next((item for item in candidates if item["role"] == "RUNTIME_EXACT_25_AUTHORITY_CANDIDATE"), None)
    return {
        "authoritative_candidate": authoritative,
        "candidate_count": len(candidates),
        "candidates": candidates[:100],
    }


def decide_recovery(ranked: Mapping[str, Sequence[Candidate]], registry: Mapping[str, Any]) -> Dict[str, Any]:
    decisions: Dict[str, Any] = {}
    recoverable_count = 0
    for strategy, candidates in ranked.items():
        qualified = [candidate for candidate in candidates if candidate.secret_safe and candidate.ast_valid and candidate.score_100 >= 60 and not candidate.wrapper_like]
        best = qualified[0] if qualified else None
        if best:
            recoverable_count += 1
            verdict = "RECOVERY_CANDIDATE_FOUND"
            next_action = "DIRECT_CODE_REVIEW_THEN_RESTORE_TO_CANONICAL_PATH"
        else:
            verdict = "NO_QUALIFIED_ORIGINAL_FOUND_REBUILD_REQUIRED"
            next_action = "DESIGN_STRATEGY_SPECIFIC_CANONICAL_IMPLEMENTATION"
        decisions[strategy] = {
            "verdict": verdict,
            "next_action": next_action,
            "qualified_candidate_count": len(qualified),
            "best_candidate": best.public() if best else None,
        }

    registry_found = registry.get("authoritative_candidate") is not None
    if recoverable_count == len(TARGETS) and registry_found:
        verdict = "ORIGINALS_RECOVERABLE_AND_RUNTIME_REGISTRY_AUTHORITY_FOUND"
        next_action = "RESTORE_TWO_CANONICALS_AND_BIND_EXISTING_EXACT_25_AUTHORITY"
    elif recoverable_count == len(TARGETS):
        verdict = "ORIGINALS_RECOVERABLE_EXACT_25_RUNTIME_REGISTRY_ABSENT"
        next_action = "RESTORE_TWO_CANONICALS_THEN_CREATE_SINGLE_EXACT_25_OWNER_MANIFEST"
    elif recoverable_count > 0:
        verdict = "PARTIAL_ORIGINAL_RECOVERY_REBUILD_REMAINDER_AND_CREATE_REGISTRY"
        next_action = "REVIEW_RECOVERED_SOURCE_REBUILD_MISSING_SOURCE_THEN_CREATE_MANIFEST"
    else:
        verdict = "NO_QUALIFIED_ORIGINALS_REBUILD_TWO_CANONICALS_AND_CREATE_REGISTRY"
        next_action = "DESIGN_TWO_CANONICALS_FROM_STRATEGY_SPEC_AND_EXTERNAL_EVIDENCE"
    return {
        "verdict": verdict,
        "next_action": next_action,
        "recoverable_strategy_count": recoverable_count,
        "registry_authority_found": registry_found,
        "strategies": decisions,
    }


def render_html(result: Mapping[str, Any]) -> str:
    rows: List[str] = []
    recovery = result.get("recovery_decision", {}).get("strategies", {})
    for strategy in TARGETS:
        item = recovery.get(strategy, {})
        best = item.get("best_candidate") or {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(strategy)}</td>"
            f"<td>{html.escape(str(item.get('verdict')))}</td>"
            f"<td>{html.escape(str(best.get('source_path') or '-'))}</td>"
            f"<td>{html.escape(str(best.get('score_100') or '-'))}</td>"
            "</tr>"
        )
    registry = result.get("registry_authority", {})
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Q4R3 Strategy Recovery</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px;background:#111;color:#eee}table{border-collapse:collapse;width:100%}th,td{border:1px solid #444;padding:8px;text-align:left}th{background:#222}</style>"
        "</head><body>"
        f"<h1>{html.escape(str(result.get('verdict')))}</h1>"
        f"<p>Registry authority: {html.escape(str(bool(registry.get('authoritative_candidate'))))}</p>"
        "<table><thead><tr><th>Strategy</th><th>Verdict</th><th>Best source</th><th>Score</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )


def run(root: Path, output_dir: Path) -> Dict[str, Any]:
    working = scan_working_tree(root)
    reachable_history = scan_reachable_git_history(root)
    dangling = scan_dangling_blobs(root)
    archives = scan_archives(root)
    ranked = combine_candidate_maps(working, reachable_history, dangling, archives)

    output_dir.mkdir(parents=True, exist_ok=True)
    publish_candidate_sources(output_dir, ranked)

    files = active_source_files(root)
    py_files = [path for path in files if path.suffix.lower() == ".py"]
    _module_map, graph = import_graph(root, py_files)
    runtime = runtime_entrypoints(root)
    reachable = reachable_paths(runtime["entrypoint_paths"], graph)
    registry = registry_candidates(root, files, reachable)
    decision = decide_recovery(ranked, registry)

    result: Dict[str, Any] = {
        "schema": "q4r3_strategy_history_recovery_registry_authority_v1",
        "status": "PASS_Q4R3_STRATEGY_HISTORY_RECOVERY_REGISTRY_AUTHORITY_AUDIT",
        "verdict": decision["verdict"],
        "action": "HOLD",
        "next_action": decision["next_action"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "targets": list(TARGETS),
        "expected_strategy_count": len(EXPECTED_25),
        "candidate_summary": {
            strategy: {
                "candidate_count": len(candidates),
                "qualified_count": sum(candidate.secret_safe and candidate.ast_valid and candidate.score_100 >= 60 and not candidate.wrapper_like for candidate in candidates),
                "top_score": candidates[0].score_100 if candidates else None,
                "origin_counts": dict(Counter(candidate.origin_kind for candidate in candidates)),
            }
            for strategy, candidates in ranked.items()
        },
        "candidates": {strategy: [candidate.public() for candidate in candidates] for strategy, candidates in ranked.items()},
        "runtime_entrypoints": runtime,
        "reachable_active_path_count": len(reachable),
        "registry_authority": registry,
        "recovery_decision": decision,
        "proposed_exact_25_manifest_design": {
            "path": "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json",
            "required_fields": [
                "schema",
                "strategy_id",
                "owner_module",
                "owner_sha256",
                "owner_kind",
                "enabled_for_shadow",
                "enabled_for_paper",
                "enabled_for_live",
                "entry_contract_version",
                "risk_writer_contract_version",
                "source_decision_refs",
            ],
            "authority_rule": "ONE_OWNER_PER_STRATEGY_EXACTLY_25_NO_DYNAMIC_FALLBACK",
            "mutation_status": "NOT_CREATED_READ_ONLY_DESIGN_ONLY",
        },
        "safety": {
            "read_only": True,
            "production_strategy_modified": False,
            "registry_modified": False,
            "paper_live_order_modified": False,
            "persistent_forward_r_watcher_modified": False,
            "raw_trade_rows_published": False,
            "credentials_published": False,
        },
    }

    atomic_json(output_dir / "q4r3_strategy_history_recovery_registry_authority_latest.json", result)
    atomic_json(output_dir / "q4r3_strategy_recovery_plan_latest.json", decision)
    atomic_json(output_dir / "q4r3_registry_authority_trace_latest.json", registry)
    (output_dir / "q4r3_strategy_history_recovery_registry_authority_latest.html").write_text(render_html(result), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root, args.output_dir)
    print(
        json.dumps(
            {
                "status": result["status"],
                "verdict": result["verdict"],
                "next_action": result["next_action"],
                "candidate_summary": result["candidate_summary"],
                "registry_authority_found": bool(result["registry_authority"].get("authoritative_candidate")),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
