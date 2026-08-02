from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "ZEL_COMPOSITE_EXECUTABILITY_CENSUS_V1"
CALLABLE_TOKENS = (
    "evaluate",
    "resolve",
    "decide",
    "generate",
    "apply",
    "route",
    "build",
    "process",
    "run",
    "handle",
    "advise",
    "filter",
    "govern",
    "select",
    "score",
    "project",
    "dispatch",
    "emit",
)
HIGH_RISK_MARKERS = (
    "create_order",
    "cancel_order",
    "place_order",
    "submit_order",
    "set_leverage",
    "set_margin",
    "transfer_fund",
    "real_order_enabled",
    "/trade/order",
    "/trade/cancel",
    "requests.post",
    "requests.put",
    "requests.delete",
    "httpx.post",
    "subprocess.run",
    "os.system",
    "systemctl",
    "write_text(",
    "write_bytes(",
    "open(\"w",
    "open('w",
)
SOURCE_SUFFIXES = {".py", ".json", ".yaml", ".yml"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def source_path(root: Path, value: str) -> Path:
    if value.startswith("external:"):
        return Path(value[len("external:") :])
    return root / value


def bundle_sha(files: list[dict[str, str]]) -> str:
    payload = [{"path": row["path"], "sha256": row["sha256"]} for row in sorted(files, key=lambda row: row["path"])]
    return stable_sha(payload)


def arg_names(arguments: ast.arguments) -> list[str]:
    result = [arg.arg for arg in arguments.posonlyargs]
    result.extend(arg.arg for arg in arguments.args)
    if arguments.vararg:
        result.append("*" + arguments.vararg.arg)
    result.extend(arg.arg for arg in arguments.kwonlyargs)
    if arguments.kwarg:
        result.append("**" + arguments.kwarg.arg)
    return result


def callable_score(name: str, args: list[str], is_method: bool) -> int:
    compact = name.casefold()
    score = 0
    for index, token in enumerate(CALLABLE_TOKENS):
        if compact == token:
            score = max(score, 100 - index)
        elif compact.startswith(token + "_") or compact.endswith("_" + token):
            score = max(score, 85 - index)
        elif token in compact:
            score = max(score, 65 - index)
    if any(arg.casefold() in {"context", "market_context", "event", "signal", "proposal", "state", "payload"} for arg in args):
        score += 10
    if name.startswith("_"):
        score -= 100
    if is_method and args and args[0] in {"self", "cls"}:
        score += 2
    return score


def parse_python(path: Path, display_path: str) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    result: dict[str, Any] = {
        "path": display_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "parse_state": "PASS",
        "parse_error": None,
        "public_functions": [],
        "public_classes": [],
        "callable_candidates": [],
        "high_risk_markers": sorted({marker for marker in HIGH_RISK_MARKERS if marker.casefold() in text.casefold()}),
    }
    try:
        tree = ast.parse(text, filename=display_path)
    except SyntaxError as exc:
        result["parse_state"] = "HOLD_SYNTAX_ERROR"
        result["parse_error"] = f"{exc.__class__.__name__}:{exc.lineno}:{exc.offset}"
        return result

    candidates: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = arg_names(node.args)
            row = {
                "qualified_name": node.name,
                "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                "args": args,
                "line": node.lineno,
                "score": callable_score(node.name, args, False),
            }
            if not node.name.startswith("_"):
                result["public_functions"].append(row)
            if row["score"] > 0:
                candidates.append(row)
        elif isinstance(node, ast.ClassDef):
            class_row: dict[str, Any] = {"name": node.name, "line": node.lineno, "methods": []}
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                args = arg_names(child.args)
                method = {
                    "qualified_name": f"{node.name}.{child.name}",
                    "kind": "async_method" if isinstance(child, ast.AsyncFunctionDef) else "method",
                    "args": args,
                    "line": child.lineno,
                    "score": callable_score(child.name, args, True),
                }
                if not child.name.startswith("_"):
                    class_row["methods"].append(method)
                if method["score"] > 0:
                    candidates.append(method)
            if not node.name.startswith("_"):
                result["public_classes"].append(class_row)
    result["callable_candidates"] = sorted(
        candidates,
        key=lambda row: (-int(row["score"]), row["qualified_name"], int(row["line"])),
    )[:50]
    return result


def parse_non_python(path: Path, display_path: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": display_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "parse_state": "PASS_NON_PYTHON_SOURCE",
        "parse_error": None,
        "public_functions": [],
        "public_classes": [],
        "callable_candidates": [],
        "high_risk_markers": [],
    }


def read_sources(root: Path, module: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    files: list[dict[str, Any]] = []
    errors: list[str] = []
    for display_path in module.get("source_paths", []):
        path = source_path(root, str(display_path))
        if not path.is_file():
            errors.append(f"SOURCE_MISSING:{display_path}")
            continue
        if path.suffix.casefold() not in SOURCE_SUFFIXES:
            errors.append(f"SOURCE_SUFFIX_FORBIDDEN:{display_path}")
            continue
        try:
            row = parse_python(path, str(display_path)) if path.suffix.casefold() == ".py" else parse_non_python(path, str(display_path))
            files.append(row)
        except OSError as exc:
            errors.append(f"SOURCE_READ_ERROR:{display_path}:{exc.__class__.__name__}")
    return files, errors


def summarize_module(root: Path, module: dict[str, Any]) -> dict[str, Any]:
    module_id = str(module.get("module_id") or "")
    files, errors = read_sources(root, module)
    actual_bundle = bundle_sha([{"path": row["path"], "sha256": row["sha256"]} for row in files]) if files else None
    expected_bundle = str(module.get("source_bundle_sha256") or "")
    if actual_bundle != expected_bundle:
        errors.append("SOURCE_BUNDLE_SHA_MISMATCH")
    parse_error_count = sum(1 for row in files if row["parse_state"] == "HOLD_SYNTAX_ERROR")
    if parse_error_count:
        errors.append("PYTHON_PARSE_ERROR")
    candidates = []
    for file_row in files:
        for candidate in file_row["callable_candidates"]:
            candidates.append({**candidate, "path": file_row["path"], "file_high_risk_markers": file_row["high_risk_markers"]})
    candidates.sort(key=lambda row: (-int(row["score"]), row["path"], row["qualified_name"]))
    high_confidence = [row for row in candidates if int(row["score"]) >= 80 and not row["file_high_risk_markers"]]
    ambiguous = len(high_confidence) != 1
    if not high_confidence:
        adapter_state = "HOLD_ADAPTER_CALLABLE_MISSING"
    elif ambiguous:
        adapter_state = "HOLD_ADAPTER_CALLABLE_AMBIGUOUS"
    else:
        adapter_state = "PASS_SINGLE_OFFLINE_SAFE_ADAPTER_CANDIDATE"
    return {
        "module_id": module_id,
        "expected_source_bundle_sha256": expected_bundle,
        "actual_source_bundle_sha256": actual_bundle,
        "source_file_count": len(files),
        "parse_error_count": parse_error_count,
        "high_risk_file_count": sum(1 for row in files if row["high_risk_markers"]),
        "adapter_state": adapter_state,
        "selected_adapter_candidate": high_confidence[0] if len(high_confidence) == 1 else None,
        "high_confidence_candidate_count": len(high_confidence),
        "callable_candidate_count": len(candidates),
        "callable_candidates": candidates[:30],
        "files": files,
        "errors": sorted(set(errors)),
    }


def build(root: Path, pin: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    modules_raw = pin.get("modules") if isinstance(pin.get("modules"), list) else []
    modules = [summarize_module(root, row) for row in modules_raw if isinstance(row, dict)]
    if len(modules) != 12:
        errors.append("MODULE_COUNT_NOT_12")
    if len({row["module_id"] for row in modules}) != len(modules):
        errors.append("DUPLICATE_MODULE_ID")
    source_mismatch_count = sum(1 for row in modules if row["expected_source_bundle_sha256"] != row["actual_source_bundle_sha256"])
    parse_error_count = sum(int(row["parse_error_count"]) for row in modules)
    adapter_ready_count = sum(1 for row in modules if row["adapter_state"].startswith("PASS"))
    if source_mismatch_count:
        errors.append("SOURCE_PIN_PARITY_FAILED")
    if parse_error_count:
        errors.append("SOURCE_PARSE_FAILED")
    discovery_state = "PASS_COMPOSITE_EXECUTABILITY_CENSUS_DISCOVERY" if not errors else "HOLD_COMPOSITE_EXECUTABILITY_CENSUS_DISCOVERY"
    adapter_state = "PASS_COMPOSITE_EXECUTABLE_ADAPTER_SET" if adapter_ready_count == len(modules) == 12 else "HOLD_COMPOSITE_ADAPTER_CONTRACT_REQUIRED"
    result: dict[str, Any] = {
        "schema_version": "zel.composite.executability_census.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": discovery_state,
        "adapter_state": adapter_state,
        "module_count": len(modules),
        "source_pin_verified_count": len(modules) - source_mismatch_count,
        "source_mismatch_count": source_mismatch_count,
        "parse_error_count": parse_error_count,
        "adapter_ready_count": adapter_ready_count,
        "adapter_blocked_count": len(modules) - adapter_ready_count,
        "modules": modules,
        "errors": sorted(set(errors)),
        "economic_claim_allowed": False,
        "exact_replay_started": False,
        "w2_started": False,
        "w3_started": False,
        "portfolio_joint_risk_started": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        modules = []
        for index in range(12):
            module_id = f"M{index:02d}"
            relative = f"backend/{module_id.lower()}.py"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("def evaluate(context):\n    return context\n", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            modules.append(
                {
                    "module_id": module_id,
                    "source_paths": [relative],
                    "source_bundle_sha256": bundle_sha([{"path": relative, "sha256": digest}]),
                }
            )
        row = build(root, {"modules": modules})
        assert row["state"] == "PASS_COMPOSITE_EXECUTABILITY_CENSUS_DISCOVERY", row
        assert row["adapter_state"] == "PASS_COMPOSITE_EXECUTABLE_ADAPTER_SET", row
        assert row["adapter_ready_count"] == 12, row
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--pin", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.root or not args.pin:
        parser.error("root and pin are required")
    row = build(args.root.resolve(), json.loads(args.pin.read_text(encoding="utf-8")))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
