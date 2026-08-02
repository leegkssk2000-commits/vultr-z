from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_EMA_MFE_MAE_SEMANTICS_PROBE_V1"
SCHEMA = "zel.ema_mfe_mae_semantics_probe.receipt.v1"
TARGET_KEYS = {
    "MFE_R",
    "MAE_R",
    "mfe_R",
    "mae_R",
    "mfe_r",
    "mae_r",
    "max_favorable_excursion_R",
    "max_adverse_excursion_R",
}
SEARCH_TOKENS = (
    "MFE_R",
    "MAE_R",
    "mfe_r",
    "mae_r",
    "max_favorable",
    "max_adverse",
    "favorable_excursion",
    "adverse_excursion",
)
MAX_FILE_BYTES = 2_000_000


def stable_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


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


def constants(node: ast.AST | None) -> dict[str, list[Any]]:
    strings: set[str] = set()
    numbers: set[float | int] = set()
    if node is not None:
        for child in ast.walk(node):
            if not isinstance(child, ast.Constant):
                continue
            value = child.value
            if isinstance(value, str) and value.strip() and len(value.strip()) <= 160:
                strings.add(value.strip())
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                if -1_000_000 <= float(value) <= 1_000_000:
                    numbers.add(value)
    return {"strings": sorted(strings), "numbers": sorted(numbers, key=float)}


def loaded_names(node: ast.AST | None) -> list[str]:
    values: set[str] = set()
    if node is not None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                values.add(child.id)
            elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
                values.add(child.attr)
    return sorted(values)


def fingerprint(node: ast.AST | None) -> dict[str, Any] | None:
    if node is None:
        return None
    values = constants(node)
    operators: set[str] = set()
    compare_operators: set[str] = set()
    calls: set[str] = set()
    subscripts: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.BinOp):
            operators.add(type(child.op).__name__)
        elif isinstance(child, ast.BoolOp):
            operators.add(type(child.op).__name__)
        elif isinstance(child, ast.UnaryOp):
            operators.add(type(child.op).__name__)
        elif isinstance(child, ast.Compare):
            compare_operators.update(type(value).__name__ for value in child.ops)
        elif isinstance(child, ast.Call):
            calls.add(call_name(child))
        elif isinstance(child, ast.Subscript):
            base = dotted_name(child.value) or type(child.value).__name__
            key = None
            if isinstance(child.slice, ast.Constant) and isinstance(child.slice.value, str):
                key = child.slice.value
            subscripts.add(f"{base}[{key!r}]" if key is not None else f"{base}[<dynamic>]")
    return {
        "node_type": type(node).__name__,
        "loaded_names": loaded_names(node)[:160],
        "calls": sorted(calls)[:160],
        "strings": values["strings"][:160],
        "numbers": values["numbers"],
        "operators": sorted(operators),
        "compare_operators": sorted(compare_operators),
        "subscripts": sorted(subscripts)[:160],
        "uses_high": "high" in loaded_names(node) or any("['high']" in value or '["high"]' in value for value in subscripts),
        "uses_low": "low" in loaded_names(node) or any("['low']" in value or '["low"]' in value for value in subscripts),
        "uses_close": "close" in loaded_names(node) or any("['close']" in value or '["close"]' in value for value in subscripts),
        "uses_open": "open" in loaded_names(node) or any("['open']" in value or '["open"]' in value for value in subscripts),
        "uses_entry": any("entry" in value.lower() for value in loaded_names(node)) or any("entry" in value.lower() for value in subscripts),
        "uses_stop": any("stop" in value.lower() or value.lower() in {"sl", "risk"} for value in loaded_names(node)) or any("stop" in value.lower() or "risk" in value.lower() for value in subscripts),
    }


def target_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id in TARGET_KEYS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in TARGET_KEYS:
        return node.attr
    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Constant) and node.slice.value in TARGET_KEYS:
            return str(node.slice.value)
    return None


def function_facts(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                key = target_key(target)
                if key:
                    rows.append({"kind": "assign", "key": key, "line": int(child.lineno), "value": fingerprint(child.value)})
        elif isinstance(child, ast.AnnAssign):
            key = target_key(child.target)
            if key:
                rows.append({"kind": "ann_assign", "key": key, "line": int(child.lineno), "value": fingerprint(child.value)})
        elif isinstance(child, ast.Dict):
            for key_node, value_node in zip(child.keys, child.values):
                if isinstance(key_node, ast.Constant) and key_node.value in TARGET_KEYS:
                    rows.append({"kind": "dict", "key": str(key_node.value), "line": int(getattr(key_node, "lineno", child.lineno)), "value": fingerprint(value_node)})
        elif isinstance(child, ast.Call):
            name = call_name(child)
            if name.endswith(".update") and child.args and isinstance(child.args[0], ast.Dict):
                for key_node, value_node in zip(child.args[0].keys, child.args[0].values):
                    if isinstance(key_node, ast.Constant) and key_node.value in TARGET_KEYS:
                        rows.append({"kind": "update", "key": str(key_node.value), "line": int(child.lineno), "value": fingerprint(value_node)})
            for keyword in child.keywords:
                if keyword.arg in TARGET_KEYS:
                    rows.append({"kind": "keyword", "key": str(keyword.arg), "line": int(child.lineno), "value": fingerprint(keyword.value)})
    return sorted(rows, key=lambda row: (row["line"], row["key"], row["kind"]))


def candidate_paths(root: Path) -> Iterable[Path]:
    if root.is_file() and root.suffix == ".py":
        yield root
        return
    if not root.is_dir():
        return
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "archive", "archives", "backup", "backups"}
    for base, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name not in skip]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(base) / name
            try:
                stat = path.stat()
                if stat.st_size <= 0 or stat.st_size > MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(token in text for token in SEARCH_TOKENS):
                yield path


def source_root(terminal_root: Path) -> Path | None:
    report_path = terminal_root / "report.json"
    if not report_path.is_file():
        return None
    value = json.loads(report_path.read_text(encoding="utf-8"))
    source = value.get("source") if isinstance(value, Mapping) else None
    root = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(root, str):
        return None
    path = Path(root)
    return path.resolve() if path.is_absolute() else None


def scan_roots(runtime_root: Path, terminal_root: Path) -> list[tuple[str, Path]]:
    frozen = source_root(terminal_root)
    rows: list[tuple[str, Path]] = [
        ("research_runtime", Path("/opt/zel/research-runtime/data-b-v2")),
        ("runtime_tools", runtime_root / "tools"),
        ("runtime_backend", runtime_root / "backend"),
        ("runtime_engine", runtime_root / "engine"),
    ]
    if frozen is not None:
        rows.extend(
            [
                ("frozen_source", frozen),
                ("frozen_tools", frozen / "tools"),
                ("frozen_backend", frozen / "backend"),
                ("frozen_engine", frozen / "engine"),
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

    files: list[dict[str, Any]] = []
    writers: list[dict[str, Any]] = []
    candidate_counts: dict[str, int] = {}
    seen_paths: set[str] = set()
    for label, root in scan_roots(args.runtime_root.resolve(), args.terminal_root.resolve()):
        count = 0
        for path in candidate_paths(root):
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            count += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            source_sha = sha256_file(path)
            parent_class: dict[int, str] = {}
            for class_node in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
                for child in ast.walk(class_node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        parent_class[id(child)] = class_node.name
            function_rows: list[dict[str, Any]] = []
            for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                facts = function_facts(function)
                if not facts:
                    continue
                meta = {
                    "class_name": parent_class.get(id(function)),
                    "function_name": function.name,
                    "function_line": int(function.lineno),
                }
                function_rows.append({**meta, "writes": facts})
                for fact in facts:
                    writers.append(
                        {
                            "root_label": label,
                            "path": resolved,
                            "sha256": source_sha,
                            **meta,
                            **fact,
                        }
                    )
            files.append(
                {
                    "root_label": label,
                    "path": resolved,
                    "sha256": source_sha,
                    "functions": function_rows,
                    "raw_code_published": False,
                }
            )
        candidate_counts[label] = count

    writers.sort(key=lambda row: (row["path"], row["line"], row["key"]))
    key_counts = Counter(row["key"] for row in writers)
    semantic_modes = Counter()
    for row in writers:
        value = row.get("value") or {}
        if value.get("uses_high") or value.get("uses_low"):
            semantic_modes["intrabar_high_low"] += 1
        if value.get("uses_close"):
            semantic_modes["close_price"] += 1
        if value.get("uses_open"):
            semantic_modes["open_price"] += 1
        if value.get("uses_entry"):
            semantic_modes["entry_reference"] += 1
        if value.get("uses_stop"):
            semantic_modes["stop_or_risk_reference"] += 1

    blockers: list[str] = []
    if not any(row["key"] in {"MFE_R", "mfe_R", "mfe_r", "max_favorable_excursion_R"} for row in writers):
        blockers.append("MFE_WRITER_NOT_FOUND")
    if not any(row["key"] in {"MAE_R", "mae_R", "mae_r", "max_adverse_excursion_R"} for row in writers):
        blockers.append("MAE_WRITER_NOT_FOUND")

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_EMA_MFE_MAE_WRITER_SEMANTICS_FOUND" if not blockers else "HOLD_EMA_MFE_MAE_WRITER_SEMANTICS_INCOMPLETE",
        "candidate_counts": candidate_counts,
        "candidate_file_count": len(files),
        "writer_count": len(writers),
        "key_counts": dict(sorted(key_counts.items())),
        "semantic_mode_counts": dict(sorted(semantic_modes.items())),
        "writers": writers[:300],
        "files": files[:300],
        "blockers": blockers,
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
        "next": "RECONCILE_PATH_REPLAY_TO_LEDGER_SEMANTICS" if not blockers else "RESOLVE_WRITER_SEMANTICS_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
