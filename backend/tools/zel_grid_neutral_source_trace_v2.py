from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_GRID_NEUTRAL_SOURCE_TRACE_V2"
SCHEMA = "zel.grid_neutral.source_trace.receipt.v2"
KEY_TOKENS = (
    "grid_rebalance",
    "derive_regime",
    "market_regime",
    "entry_features",
    "entry_ts",
    "event_id",
    "trades.jsonl",
    "historical_oos",
    "exact25_replay",
    "preentry",
)
CALL_TOKENS = (
    "regime",
    "feature",
    "entry",
    "event",
    "trade",
    "replay",
    "strategy",
    "signal",
    "load",
    "write",
    "append",
)
MAX_FILE_BYTES = 2_000_000
MAX_FILES_PER_ROOT = 6000


def stable_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def call_name(node: ast.Call) -> str:
    value: ast.AST = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else type(node.func).__name__


def import_names(tree: ast.AST) -> list[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                names.add(f"{module}.{alias.name}".strip("."))
    return sorted(names)


def safe_strings(node: ast.AST) -> list[str]:
    rows: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
            continue
        value = child.value.strip()
        lower = value.lower()
        if len(value) <= 160 and any(token in lower for token in KEY_TOKENS + CALL_TOKENS):
            rows.add(value)
    return sorted(rows)


def loaded_names(node: ast.AST) -> list[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            names.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
            names.add(child.attr)
    return sorted(names)


def assigned_names(node: ast.AST) -> list[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            names.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Store):
            names.add(child.attr)
    return sorted(names)


def dict_keys(node: ast.AST) -> list[str]:
    keys: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key in child.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                lower = key.value.lower()
                if any(token in lower for token in KEY_TOKENS + CALL_TOKENS):
                    keys.add(key.value)
    return sorted(keys)


def relevant_calls(node: ast.AST) -> list[str]:
    calls = {call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)}
    return sorted(
        value
        for value in calls
        if any(token in value.lower() for token in CALL_TOKENS + KEY_TOKENS)
    )


def slice_facts(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Subscript):
            continue
        base = (
            child.value.attr
            if isinstance(child.value, ast.Attribute)
            else child.value.id
            if isinstance(child.value, ast.Name)
            else type(child.value).__name__
        )
        slices = list(child.slice.elts) if isinstance(child.slice, ast.Tuple) else [child.slice]
        for value in slices:
            if not isinstance(value, ast.Slice):
                continue
            rows.append(
                {
                    "base": base,
                    "lower_names": loaded_names(value.lower) if value.lower else [],
                    "upper_names": loaded_names(value.upper) if value.upper else [],
                    "upper_plus_one": isinstance(value.upper, ast.BinOp)
                    and isinstance(value.upper.op, ast.Add),
                }
            )
    return rows


def function_facts(function: ast.AST, class_name: str | None) -> dict[str, Any]:
    name = str(getattr(function, "name", "<anonymous>"))
    args: list[str] = []
    arguments = getattr(function, "args", None)
    if arguments is not None:
        args = [arg.arg for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]]
    calls = relevant_calls(function)
    assigned = assigned_names(function)
    loaded = loaded_names(function)
    keys = dict_keys(function)
    strings = safe_strings(function)
    slices = slice_facts(function)
    relevance_values = [name, *calls, *assigned, *loaded, *keys, *strings]
    relevant = any(
        token in value.lower()
        for value in relevance_values
        for token in KEY_TOKENS + CALL_TOKENS
    ) or bool(slices)
    return {
        "relevant": relevant,
        "class_name": class_name,
        "function_name": name,
        "line": int(getattr(function, "lineno", 0) or 0),
        "args": args[:40],
        "calls": calls[:120],
        "assigned": [value for value in assigned if any(token in value.lower() for token in KEY_TOKENS + CALL_TOKENS)][:80],
        "loaded": [value for value in loaded if any(token in value.lower() for token in KEY_TOKENS + CALL_TOKENS)][:120],
        "dict_keys": keys[:120],
        "safe_strings": strings[:120],
        "slices": slices[:120],
    }


def classify_roles(path: Path, text_lower: str) -> list[str]:
    name = path.name.lower()
    roles: list[str] = []
    if "grid_rebalance" in text_lower or "grid_rebalance" in name:
        roles.append("grid_strategy_or_binding")
    if "derive_regime" in text_lower or "market_regime" in text_lower:
        roles.append("regime_deriver_or_consumer")
    if "entry_features" in text_lower or "preentry" in text_lower:
        roles.append("entry_feature_capture_or_consumer")
    if "historical_oos" in text_lower or "exact25_replay" in text_lower or "replay" in name:
        roles.append("historical_replay_runner_or_helper")
    if "trades.jsonl" in text_lower or "event_id" in text_lower:
        roles.append("trade_ledger_writer_or_reader")
    if "data_source_path" in text_lower or "candles" in text_lower or "ohlcv" in text_lower:
        roles.append("market_data_loader_or_lineage")
    return roles


def trace_file(path: Path, root_label: str) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_size <= 0 or stat.st_size > MAX_FILE_BYTES:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lower = text.lower()
    matched = sorted(token for token in KEY_TOKENS if token in lower)
    name_match = any(token in path.name.lower() for token in ("replay", "regime", "grid", "preentry"))
    if len(matched) < 2 and not name_match:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {
            "root_label": root_label,
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "size_bytes": stat.st_size,
            "matched_tokens": matched,
            "roles": classify_roles(path, lower),
            "parse_error": f"{type(exc).__name__}:{exc.lineno}",
            "imports": [],
            "functions": [],
            "raw_code_published": False,
        }

    parent_classes: dict[int, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent_classes[id(child)] = node.name

    functions: list[dict[str, Any]] = []
    for function in [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]:
        fact = function_facts(function, parent_classes.get(id(function)))
        if fact.pop("relevant"):
            functions.append(fact)
    functions.sort(key=lambda row: (row["line"], row["class_name"] or "", row["function_name"]))
    return {
        "root_label": root_label,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
        "matched_tokens": matched,
        "roles": classify_roles(path, lower),
        "imports": [
            value
            for value in import_names(tree)
            if any(token in value.lower() for token in KEY_TOKENS + CALL_TOKENS)
        ][:160],
        "functions": functions[:300],
        "raw_code_published": False,
    }


def iter_python_files(root: Path) -> Iterable[Path]:
    if root.is_file() and root.suffix == ".py":
        yield root
        return
    if not root.is_dir():
        return
    count = 0
    for path in root.rglob("*.py"):
        parts = {part.lower() for part in path.parts}
        if parts.intersection({".git", ".venv", "venv", "node_modules", "__pycache__"}):
            continue
        yield path
        count += 1
        if count >= MAX_FILES_PER_ROOT:
            break


def root_candidates(runtime_root: Path, source_root: Path | None) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = [
        ("research_runtime", Path("/opt/zel/research-runtime/data-b-v2")),
        ("runtime_tools", runtime_root / "backend/tools"),
        ("runtime_engine", runtime_root / "backend/engine"),
        ("runtime_engine_alt", runtime_root / "engine"),
        ("runtime_strategies", runtime_root / "backend/strategies"),
    ]
    if source_root is not None:
        roots.extend(
            [
                ("terminal_source", source_root),
                ("terminal_source_tools", source_root / "backend/tools"),
                ("terminal_source_engine", source_root / "backend/engine"),
                ("terminal_source_strategies", source_root / "backend/strategies"),
            ]
        )
    unique: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for label, root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append((label, root))
    return unique


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    terminal_root = args.terminal_root.resolve()
    report_path = terminal_root / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    source_root: Path | None = None
    source = report.get("source") if isinstance(report, Mapping) else None
    if isinstance(source, Mapping) and isinstance(source.get("root"), str):
        candidate = Path(str(source["root"]))
        if candidate.is_absolute():
            source_root = candidate.resolve()

    files: list[dict[str, Any]] = []
    scanned_counts: dict[str, int] = {}
    seen_paths: set[str] = set()
    for label, root in root_candidates(runtime_root, source_root):
        scanned = 0
        for path in iter_python_files(root):
            scanned += 1
            key = str(path.resolve())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            traced = trace_file(path, label)
            if traced is not None:
                files.append(traced)
        scanned_counts[label] = scanned

    files.sort(key=lambda row: (-len(row["matched_tokens"]), row["path"]))
    role_counts: dict[str, int] = {}
    for row in files:
        for role in row["roles"]:
            role_counts[role] = role_counts.get(role, 0) + 1

    required_roles = {
        "grid_strategy_or_binding",
        "regime_deriver_or_consumer",
        "entry_feature_capture_or_consumer",
        "historical_replay_runner_or_helper",
    }
    missing_roles = sorted(required_roles - set(role_counts))
    candidate_summary = [
        {
            "path": row["path"],
            "roles": row["roles"],
            "matched_tokens": row["matched_tokens"],
            "functions": [
                {
                    "class_name": fact["class_name"],
                    "function_name": fact["function_name"],
                    "line": fact["line"],
                    "calls": fact["calls"][:30],
                    "dict_keys": fact["dict_keys"][:30],
                    "slices": fact["slices"][:20],
                }
                for fact in row["functions"][:30]
            ],
        }
        for row in files[:120]
    ]

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_CAUSAL_CALLCHAIN_INVENTORY" if not missing_roles else "HOLD_GRID_CAUSAL_CALLCHAIN_INCOMPLETE",
        "terminal_source_root": str(source_root) if source_root else None,
        "scanned_python_counts": scanned_counts,
        "candidate_file_count": len(files),
        "role_counts": dict(sorted(role_counts.items())),
        "missing_roles": missing_roles,
        "candidates": candidate_summary,
        "files": files[:300],
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_code_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "BUILD_ENTRY_TIME_REGIME_RECOMPUTATION_FROM_CALLCHAIN" if not missing_roles else "RESOLVE_MISSING_CALLCHAIN_ROLES",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if not missing_roles else 1


if __name__ == "__main__":
    raise SystemExit(main())
