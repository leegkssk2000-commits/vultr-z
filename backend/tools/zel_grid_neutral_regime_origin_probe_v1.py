from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_GRID_NEUTRAL_REGIME_ORIGIN_PROBE_V1"
SCHEMA = "zel.grid_neutral.regime_origin_probe.receipt.v1"
EXACT_KEYS = {"regime", "market_regime"}
TARGET_FUNCTIONS = {
    "feature_snapshot",
    "replay_lane",
    "replay_strategy",
    "regime_scores",
    "derive_regime",
    "classify_regime",
    "detect_regime",
}
SCAN_TOKENS = (
    "grid_rebalance",
    "feature_snapshot",
    "entry_features",
    "entry_ts",
    "event_id",
    "market_regime",
    "regime_scores",
    "derive_regime",
    "trades.jsonl",
    "historical_oos",
    "exact25_replay",
)
MAX_FILE_BYTES = 2_000_000
MAX_FILES_PER_ROOT = 8000


def stable_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
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


def dotted_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    parts: list[str] = []
    value = node
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else None


def call_name(node: ast.Call) -> str:
    return dotted_name(node.func) or type(node.func).__name__


def names_in(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return sorted(names)


def calls_in(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    return sorted({call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)})


def safe_strings(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    allowed = {"regime", "market_regime", "neutral", "long", "short", "trend", "range", "unknown"}
    return sorted(
        {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and child.value.strip().lower() in allowed
        }
    )


def expression_fingerprint(node: ast.AST | None) -> dict[str, Any] | None:
    if node is None:
        return None
    operators = sorted(
        {
            type(child.op).__name__
            for child in ast.walk(node)
            if isinstance(child, (ast.BinOp, ast.BoolOp, ast.UnaryOp, ast.Compare))
            and hasattr(child, "op")
        }
    )
    compare_ops = sorted(
        {
            type(op).__name__
            for child in ast.walk(node)
            if isinstance(child, ast.Compare)
            for op in child.ops
        }
    )
    return {
        "node_type": type(node).__name__,
        "names": names_in(node)[:80],
        "calls": calls_in(node)[:80],
        "safe_strings": safe_strings(node),
        "operators": operators,
        "compare_operators": compare_ops,
        "has_slice": any(isinstance(child, ast.Slice) for child in ast.walk(node)),
        "has_if_expression": any(isinstance(child, ast.IfExp) for child in ast.walk(node)),
    }


def target_text(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted_name(node) or node.attr
    if isinstance(node, ast.Subscript):
        base = dotted_name(node.value) or type(node.value).__name__
        key = None
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            key = node.slice.value
        return f"{base}[{key!r}]" if key is not None else f"{base}[<dynamic>]"
    if isinstance(node, (ast.Tuple, ast.List)):
        return ",".join(target_text(child) for child in node.elts)
    return type(node).__name__


def exact_key_from_subscript(node: ast.Subscript) -> str | None:
    value = node.slice
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        key = value.value.strip().lower()
        return key if key in EXACT_KEYS else None
    return None


def dict_key_rows(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key_node, value_node in zip(child.keys, child.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            key = key_node.value.strip().lower()
            if key not in EXACT_KEYS:
                continue
            rows.append(
                {
                    "key": key,
                    "line": int(getattr(key_node, "lineno", getattr(child, "lineno", 0)) or 0),
                    "value": expression_fingerprint(value_node),
                }
            )
    return rows


def keyword_rows(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        for keyword in child.keywords:
            if keyword.arg and keyword.arg.strip().lower() in EXACT_KEYS:
                rows.append(
                    {
                        "call": call_name(child),
                        "key": keyword.arg.strip().lower(),
                        "line": int(getattr(keyword, "lineno", getattr(child, "lineno", 0)) or 0),
                        "value": expression_fingerprint(keyword.value),
                    }
                )
    return rows


def assignment_rows(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        elif isinstance(child, ast.NamedExpr):
            targets = [child.target]
            value = child.value
        else:
            continue
        for target in targets:
            relevant = False
            key = None
            if isinstance(target, ast.Name) and target.id.lower() in EXACT_KEYS:
                relevant = True
                key = target.id.lower()
            elif isinstance(target, ast.Attribute) and target.attr.lower() in EXACT_KEYS:
                relevant = True
                key = target.attr.lower()
            else:
                for candidate in ast.walk(target):
                    if isinstance(candidate, ast.Subscript):
                        exact = exact_key_from_subscript(candidate)
                        if exact:
                            relevant = True
                            key = exact
                            break
            if relevant:
                rows.append(
                    {
                        "target": target_text(target),
                        "key": key,
                        "line": int(getattr(child, "lineno", 0) or 0),
                        "value": expression_fingerprint(value),
                    }
                )
    return rows


def return_rows(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if not isinstance(child, ast.Return):
            continue
        keys: list[str] = []
        if isinstance(child.value, ast.Dict):
            for key_node in child.value.keys:
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    keys.append(key_node.value)
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "dict_keys": sorted(keys)[:160],
                "value": expression_fingerprint(child.value),
            }
        )
    return rows


def get_rows(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = call_name(child)
        if not name.endswith(".get") and name != "get":
            continue
        if not child.args or not isinstance(child.args[0], ast.Constant) or not isinstance(child.args[0].value, str):
            continue
        key = child.args[0].value.strip().lower()
        if key not in EXACT_KEYS:
            continue
        rows.append(
            {
                "call": name,
                "key": key,
                "line": int(getattr(child, "lineno", 0) or 0),
                "default": expression_fingerprint(child.args[1]) if len(child.args) > 1 else None,
            }
        )
    return rows


def import_rows(tree: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "regime" in alias.name.lower():
                    rows.append({"line": int(node.lineno), "module": alias.name, "name": None, "alias": alias.asname})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if "regime" in module.lower() or "regime" in alias.name.lower():
                    rows.append({"line": int(node.lineno), "module": module, "name": alias.name, "alias": alias.asname})
    return rows


def function_record(function: ast.AST, class_name: str | None) -> dict[str, Any]:
    name = str(getattr(function, "name", "<anonymous>"))
    calls = calls_in(function)
    exact_calls = [value for value in calls if "regime" in value.lower()]
    records = {
        "class_name": class_name,
        "function_name": name,
        "line": int(getattr(function, "lineno", 0) or 0),
        "args": [
            arg.arg
            for arg in [
                *getattr(getattr(function, "args", None), "posonlyargs", []),
                *getattr(getattr(function, "args", None), "args", []),
                *getattr(getattr(function, "args", None), "kwonlyargs", []),
            ]
        ][:60],
        "regime_calls": exact_calls[:100],
        "dict_key_writes": dict_key_rows(function),
        "assignments": assignment_rows(function),
        "keyword_writes": keyword_rows(function),
        "key_reads": get_rows(function),
        "returns": return_rows(function),
    }
    records["is_target_function"] = name in TARGET_FUNCTIONS or any(token in name.lower() for token in ("regime", "feature_snapshot", "replay_lane"))
    records["is_regime_writer"] = bool(records["dict_key_writes"] or records["assignments"] or records["keyword_writes"])
    records["is_regime_deriver"] = "regime" in name.lower() or bool(exact_calls)
    return records


def scan_file(path: Path, root_label: str) -> dict[str, Any] | None:
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
    matched = sorted(token for token in SCAN_TOKENS if token in lower)
    exact_key_present = '"regime"' in lower or "'regime'" in lower or '"market_regime"' in lower or "'market_regime'" in lower
    name_relevant = any(token in path.name.lower() for token in ("replay", "regime", "grid", "producer"))
    if not matched and not exact_key_present and not name_relevant:
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
            "parse_error": f"{type(exc).__name__}:{exc.lineno}",
            "imports": [],
            "module_regime_writes": [],
            "functions": [],
            "raw_code_published": False,
        }

    parent_class: dict[int, str] = {}
    for class_node in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
        for child in ast.walk(class_node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent_class[id(child)] = class_node.name

    functions: list[dict[str, Any]] = []
    for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        record = function_record(function, parent_class.get(id(function)))
        if record["is_target_function"] or record["is_regime_writer"] or record["is_regime_deriver"]:
            functions.append(record)
    functions.sort(key=lambda row: (row["line"], row["class_name"] or "", row["function_name"]))

    module_writes = {
        "dict_key_writes": dict_key_rows(tree),
        "assignments": assignment_rows(tree),
        "keyword_writes": keyword_rows(tree),
        "key_reads": get_rows(tree),
    }
    if not functions and not any(module_writes.values()) and not import_rows(tree) and not matched:
        return None
    return {
        "root_label": root_label,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
        "matched_tokens": matched,
        "imports": import_rows(tree),
        "module_regime_facts": module_writes,
        "functions": functions[:400],
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
        if {part.lower() for part in path.parts}.intersection({".git", ".venv", "venv", "node_modules", "__pycache__"}):
            continue
        yield path
        count += 1
        if count >= MAX_FILES_PER_ROOT:
            break


def roots(runtime_root: Path, source_root: Path | None) -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = [
        ("research_runtime", Path("/opt/zel/research-runtime/data-b-v2")),
        ("runtime_root", runtime_root),
        ("runtime_engine", runtime_root / "engine"),
        ("runtime_backend_engine", runtime_root / "backend/engine"),
    ]
    if source_root is not None:
        rows.extend(
            [
                ("terminal_source", source_root),
                ("terminal_source_tools", source_root / "tools"),
                ("terminal_source_engine", source_root / "engine"),
                ("terminal_source_backend_engine", source_root / "backend/engine"),
            ]
        )
    output: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for label, path in rows:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        output.append((label, path))
    return output


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
    for label, root in roots(runtime_root, source_root):
        count = 0
        for path in iter_python_files(root):
            count += 1
            key = str(path.resolve())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            row = scan_file(path, label)
            if row is not None:
                files.append(row)
        scanned_counts[label] = count

    writers: list[dict[str, Any]] = []
    derivers: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for file_row in files:
        for function in file_row.get("functions", []):
            summary = {
                "path": file_row["path"],
                "sha256": file_row["sha256"],
                "class_name": function["class_name"],
                "function_name": function["function_name"],
                "line": function["line"],
                "regime_calls": function["regime_calls"],
                "dict_key_writes": function["dict_key_writes"],
                "assignments": function["assignments"],
                "keyword_writes": function["keyword_writes"],
                "key_reads": function["key_reads"],
                "returns": function["returns"],
            }
            if function["is_regime_writer"]:
                writers.append(summary)
            if function["is_regime_deriver"]:
                derivers.append(summary)
            if function["is_target_function"]:
                targets.append(summary)

    writers.sort(key=lambda row: (row["path"], row["line"], row["function_name"]))
    derivers.sort(key=lambda row: (row["path"], row["line"], row["function_name"]))
    targets.sort(key=lambda row: (row["path"], row["line"], row["function_name"]))
    required_targets = {"feature_snapshot", "replay_lane", "regime_scores"}
    found_targets = {row["function_name"] for row in targets}
    missing_targets = sorted(required_targets - found_targets)

    blockers: list[str] = []
    if missing_targets:
        blockers.append("MISSING_TARGET_FUNCTIONS:" + ",".join(missing_targets))
    if not writers:
        blockers.append("REGIME_WRITER_NOT_FOUND")
    if not derivers:
        blockers.append("REGIME_DERIVER_NOT_FOUND")

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_REGIME_ORIGIN_FACTS_EXTRACTED" if not blockers else "HOLD_GRID_REGIME_ORIGIN_INCOMPLETE",
        "terminal_source_root": str(source_root) if source_root else None,
        "scanned_python_counts": scanned_counts,
        "candidate_file_count": len(files),
        "regime_writer_count": len(writers),
        "regime_deriver_count": len(derivers),
        "target_function_count": len(targets),
        "missing_targets": missing_targets,
        "blockers": blockers,
        "regime_writers": writers[:200],
        "regime_derivers": derivers[:200],
        "target_functions": targets[:200],
        "files": files[:400],
        "raw_code_published": False,
        "raw_trade_rows_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "BUILD_ENTRY_TIME_REGIME_RECOMPUTATION" if not blockers else "RESOLVE_EXACT_REGIME_ORIGIN_BLOCKERS",
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
