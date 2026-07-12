from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

ROOT = Path("/home/z/z")
WRITER_REL = "tools/q4r3_vwap_mfe_mae_capture_sidecar.py"
EXPECTED_WRITER_SHA256 = "d8120a2b8b4d7ed2ac4d37734eb4d6e37c973dfb163572a6553bd91a13b19e50"
BINDING_REL = "backend/config/q4r3_exact25_shadow_binding_v1.json"
EPOCH_REL = "runtime/exact25_edge_v1/epoch_latest.json"
CANARY_STATUS_REL = "runtime/q4r3_exact25_edge_v1_shadow_canary_job_latest.json"
IO_LOCK_RESULT_REL = "runtime_results/q4r3/exact25_forward_writer_io_contract_lock/q4r3_exact25_forward_writer_io_contract_lock_latest.json"
MAX_SCAN_BYTES = 2 * 1024 * 1024
MAX_REFERENCE_FILES = 5000
REFERENCE_ROOTS = (
    Path("/etc/systemd/system"),
    Path("/usr/lib/systemd/system"),
    Path("/lib/systemd/system"),
)
REPO_REFERENCE_SUFFIXES = {".service", ".timer", ".path", ".sh", ".py", ".conf", ".ini", ".json", ".yaml", ".yml"}
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "site-packages", "dist-packages", "__pycache__", "runtime_results"}


@dataclass
class FunctionSurface:
    name: str
    line: int
    parameters: List[str]
    required_parameters: List[str]
    async_function: bool
    score: int


@dataclass
class Reference:
    path: str
    line: int
    unit_kind: str
    active_state: Optional[str]
    sub_state: Optional[str]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def literal_string(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def verify_prerequisites(root: Path, worktree: Path) -> Dict[str, Any]:
    writer = root / WRITER_REL
    if not writer.is_file():
        raise FileNotFoundError(f"AUTHORITATIVE_WRITER_MISSING:{writer}")
    actual_sha = sha256(writer)
    if actual_sha != EXPECTED_WRITER_SHA256:
        raise ValueError(f"AUTHORITATIVE_WRITER_SHA_MISMATCH:{actual_sha}")

    binding = load_object(root / BINDING_REL)
    epoch = load_object(root / EPOCH_REL)
    canary = load_object(root / CANARY_STATUS_REL)
    io_lock = load_object(worktree / IO_LOCK_RESULT_REL)

    if binding.get("epoch_id") != "EXACT25_EDGE_V1":
        raise ValueError("BINDING_EPOCH_MISMATCH")
    if binding.get("write_enabled") is not False or binding.get("canary_enabled") is not False:
        raise ValueError("BINDING_MUST_REMAIN_WRITE_DISABLED")
    if binding.get("authoritative_lifecycle_writer") != WRITER_REL:
        raise ValueError("BINDING_WRITER_PATH_MISMATCH")
    if binding.get("authoritative_lifecycle_writer_sha256") != EXPECTED_WRITER_SHA256:
        raise ValueError("BINDING_WRITER_SHA_MISMATCH")

    if epoch.get("epoch_id") != "EXACT25_EDGE_V1":
        raise ValueError("EPOCH_ID_MISMATCH")
    if epoch.get("write_enabled") is not False:
        raise ValueError("EPOCH_MUST_REMAIN_WRITE_DISABLED")

    if canary.get("status") != "PASS_Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY":
        raise ValueError("CANARY_NOT_PASS")
    if canary.get("production_measurement_write_enabled") is not False:
        raise ValueError("CANARY_STATUS_WRITE_FLAG_UNSAFE")

    if io_lock.get("status") != "PASS_Q4R3_EXACT25_FORWARD_WRITER_IO_CONTRACT_LOCK":
        raise ValueError("IO_LOCK_STATUS_NOT_PASS")
    gaps = list(io_lock.get("gaps") or [])
    if gaps != ["AUTHORITATIVE_WRITER_SYSTEMD_REFERENCE_NOT_FOUND"]:
        raise ValueError(f"UNEXPECTED_IO_GAPS:{gaps}")
    if io_lock.get("open_surface", {}).get("path") != io_lock.get("close_surface", {}).get("path"):
        raise ValueError("IO_LOCK_OPEN_CLOSE_SURFACE_DIVERGED")
    if "event_id" not in (io_lock.get("common_join_keys") or []):
        raise ValueError("IO_LOCK_EVENT_ID_JOIN_NOT_LOCKED")

    return {
        "writer_path": str(writer),
        "writer_sha256": actual_sha,
        "binding_state": binding.get("binding_state"),
        "epoch_state": epoch.get("state"),
        "canary_status": canary.get("status"),
        "io_lock_verdict": io_lock.get("verdict"),
        "reported_gap": gaps[0],
        "open_close_surface": io_lock.get("open_surface", {}).get("path"),
        "common_join_keys": io_lock.get("common_join_keys"),
    }


def function_surface(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionSurface:
    args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
    names = [item.arg for item in args]
    defaults = len(node.args.defaults)
    positional_count = len(node.args.posonlyargs) + len(node.args.args)
    required_positional = max(0, positional_count - defaults)
    required = [item.arg for item in (list(node.args.posonlyargs) + list(node.args.args))[:required_positional]]
    required.extend(
        arg.arg
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
        if default is None
    )
    lower = node.name.lower()
    score = 0
    for token, points in (
        ("main", 20),
        ("run", 12),
        ("capture", 10),
        ("write", 10),
        ("append", 8),
        ("process", 7),
        ("update", 5),
        ("collect", 5),
    ):
        if token in lower:
            score += points
    return FunctionSurface(
        name=node.name,
        line=node.lineno,
        parameters=names,
        required_parameters=required,
        async_function=isinstance(node, ast.AsyncFunctionDef),
        score=score,
    )


def inspect_writer(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    functions: List[FunctionSurface] = []
    classes: List[Dict[str, Any]] = []
    argparse_flags: Set[str] = set()
    imports: Set[str] = set()
    path_literals: Set[str] = set()
    call_names: Set[str] = set()
    main_guard = False
    persistent_loop = False
    sleep_calls = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(function_surface(node))
        elif isinstance(node, ast.ClassDef):
            classes.append({"name": node.name, "line": node.lineno, "method_count": sum(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) for item in node.body)})
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name:
                call_names.add(name)
            if name.endswith("add_argument"):
                for arg in node.args:
                    value = literal_string(arg)
                    if value and value.startswith("-"):
                        argparse_flags.add(value)
            if name.endswith("sleep"):
                sleep_calls += 1
        elif isinstance(node, ast.While):
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                persistent_loop = True
        elif isinstance(node, ast.If):
            source = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
            if "__name__" in source and "__main__" in source:
                main_guard = True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if any(token in value for token in ("/runtime/", "runtime/", ".json", ".jsonl")) and len(value) < 500:
                path_literals.add(value)

    top_functions = sorted(functions, key=lambda item: (item.score, -len(item.required_parameters), -item.line), reverse=True)
    flag_tokens = {flag.lstrip("-").replace("-", "_") for flag in argparse_flags}
    persistent_flags = sorted(flag for flag in argparse_flags if any(token in flag.lower() for token in ("watch", "loop", "follow", "interval", "poll", "daemon")))
    one_shot_flags = sorted(flag for flag in argparse_flags if any(token in flag.lower() for token in ("once", "input", "output", "source", "ledger", "state")))

    if main_guard and (persistent_loop or persistent_flags):
        execution_shape = "DIRECT_PERSISTENT_SERVICE_SUPPORTED"
    elif main_guard:
        execution_shape = "DIRECT_ONESHOT_TIMER_SUPPORTED"
    elif any(item.score >= 10 for item in top_functions):
        execution_shape = "THIN_ADAPTER_REQUIRED"
    else:
        execution_shape = "NO_SAFE_EXECUTION_ENTRY_IDENTIFIED"

    return {
        "ast_valid": True,
        "line_count": len(text.splitlines()),
        "main_guard": main_guard,
        "persistent_loop": persistent_loop,
        "sleep_call_count": sleep_calls,
        "argparse_flags": sorted(argparse_flags),
        "persistent_flags": persistent_flags,
        "one_shot_flags": one_shot_flags,
        "flag_tokens": sorted(flag_tokens),
        "top_level_functions": [asdict(item) for item in top_functions[:30]],
        "classes": classes[:30],
        "imports": sorted(item for item in imports if item)[:100],
        "path_literals": sorted(path_literals)[:100],
        "call_names": sorted(call_names)[:200],
        "execution_shape": execution_shape,
    }


def systemctl_state(unit_name: str) -> Tuple[Optional[str], Optional[str]]:
    result = subprocess.run(
        ["systemctl", "show", unit_name, "-p", "ActiveState", "-p", "SubState"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        return None, None
    values: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values.get("ActiveState"), values.get("SubState")


def iter_reference_files(root: Path) -> Iterable[Path]:
    count = 0
    for base in REFERENCE_ROOTS:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".service", ".timer", ".path"}:
                yield path
                count += 1
                if count >= MAX_REFERENCE_FILES:
                    return

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in SKIP_PARTS]
        for name in files:
            path = current_path / name
            if path.suffix.lower() not in REPO_REFERENCE_SUFFIXES:
                continue
            yield path
            count += 1
            if count >= MAX_REFERENCE_FILES:
                return


def scan_references(root: Path, writer_path: Path) -> List[Reference]:
    needles = {WRITER_REL, writer_path.name, str(writer_path)}
    found: List[Reference] = []
    seen: Set[Tuple[str, int]] = set()
    for path in iter_reference_files(root):
        try:
            size = path.stat().st_size
            if size <= 0 or size > MAX_SCAN_BYTES:
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, start=1):
            if not any(needle in line for needle in needles):
                continue
            key = (str(path), index)
            if key in seen:
                continue
            seen.add(key)
            kind = path.suffix.lstrip(".") or "file"
            unit_name = path.name if path.suffix in {".service", ".timer", ".path"} else ""
            active, sub = systemctl_state(unit_name) if unit_name else (None, None)
            found.append(Reference(path=str(path), line=index, unit_kind=kind, active_state=active, sub_state=sub))
    return found


def build_service_plan(writer: Mapping[str, Any], references: Sequence[Reference]) -> Dict[str, Any]:
    shape = str(writer.get("execution_shape"))
    if references:
        verdict = "EXISTING_WRITER_SERVICE_REFERENCE_FOUND"
        next_action = "VERIFY_EXISTING_SERVICE_IS_SHADOW_ONLY_THEN_ENABLE_FORWARD_WRITES"
        deployment = "REUSE_EXISTING_REFERENCE_AFTER_SAFETY_AUDIT"
    elif shape == "DIRECT_PERSISTENT_SERVICE_SUPPORTED":
        verdict = "DEDICATED_PERSISTENT_SHADOW_SERVICE_READY_TO_BUILD"
        next_action = "BUILD_ROLLBACK_GUARDED_SHADOW_ONLY_WRITER_SERVICE"
        deployment = "SYSTEMD_SERVICE"
    elif shape == "DIRECT_ONESHOT_TIMER_SUPPORTED":
        verdict = "DEDICATED_ONESHOT_TIMER_READY_TO_BUILD"
        next_action = "BUILD_ROLLBACK_GUARDED_SHADOW_ONLY_WRITER_SERVICE_AND_TIMER"
        deployment = "SYSTEMD_SERVICE_PLUS_TIMER"
    elif shape == "THIN_ADAPTER_REQUIRED":
        verdict = "THIN_SHADOW_ADAPTER_REQUIRED_BEFORE_SERVICE_INSTALL"
        next_action = "BUILD_MINIMAL_ADAPTER_AROUND_TOP_RANKED_WRITER_CALLABLE"
        deployment = "THIN_ADAPTER_PLUS_SYSTEMD_SERVICE"
    else:
        verdict = "WRITER_SERVICE_CONTRACT_UNRESOLVED"
        next_action = "TRACE_WRITER_CALLERS_AT_RUNTIME_WITHOUT_ENABLING_WRITES"
        deployment = "RUNTIME_CALLER_TRACE_REQUIRED"

    return {
        "verdict": verdict,
        "next_action": next_action,
        "deployment_shape": deployment,
        "proposed_unit": "q4r3-exact25-forward-measurement-writer.service",
        "proposed_timer": "q4r3-exact25-forward-measurement-writer.timer" if "TIMER" in deployment else None,
        "required_environment": {
            "Q4R3_EPOCH_ID": "EXACT25_EDGE_V1",
            "Q4R3_MEASUREMENT_NAMESPACE": "EXACT25_EDGE_V1",
            "Q4R3_SHADOW_ONLY": "1",
            "Q4R3_PAPER_ENABLED": "0",
            "Q4R3_LIVE_ENABLED": "0",
            "Q4R3_ORDER_ENABLED": "0",
            "Q4R3_HISTORICAL_BACKFILL_ALLOWED": "0",
        },
        "activation_gate": [
            "binding.write_enabled remains false until unit dry-run passes",
            "epoch.write_enabled remains false until first forward open/close canary passes",
            "authoritative writer SHA remains pinned",
            "secondary close writer remains observer-only",
            "paper/live/order stay disabled",
        ],
    }


def run(root: Path, worktree: Path, output: Path) -> Dict[str, Any]:
    prereq = verify_prerequisites(root, worktree)
    writer_path = root / WRITER_REL
    writer = inspect_writer(writer_path)
    references = scan_references(root, writer_path)
    plan = build_service_plan(writer, references)

    result: Dict[str, Any] = {
        "schema": "q4r3_exact25_writer_service_contract_trace_v1",
        "status": "PASS_Q4R3_EXACT25_WRITER_SERVICE_CONTRACT_TRACE",
        "verdict": plan["verdict"],
        "action": "HOLD",
        "next_action": plan["next_action"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "epoch_id": "EXACT25_EDGE_V1",
        "strategy_count": 25,
        "prerequisites": prereq,
        "writer_structure": writer,
        "reference_count": len(references),
        "references": [asdict(item) for item in references],
        "service_plan": plan,
        "safety": {
            "read_only": True,
            "production_strategy_modified": False,
            "owner_manifest_modified": False,
            "binding_modified": False,
            "epoch_modified": False,
            "writer_modified": False,
            "service_installed": False,
            "production_measurement_write_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "historical_backfill_performed": False,
            "raw_trade_rows_published": False,
            "raw_writer_source_published": False,
        },
    }
    atomic_json(output, result)
    print(json.dumps({"status": result["status"], "verdict": result["verdict"], "execution_shape": writer["execution_shape"], "reference_count": len(references), "next_action": result["next_action"]}, ensure_ascii=False))
    return result


def self_test() -> None:
    sample_persistent = ast.parse('''\nimport argparse\nimport time\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument("--watch", action="store_true")\n    while True:\n        time.sleep(1)\nif __name__ == "__main__":\n    main()\n''')
    temporary = Path("/tmp/q4r3_writer_service_contract_self_test.py")
    temporary.write_text(ast.unparse(sample_persistent), encoding="utf-8")
    try:
        result = inspect_writer(temporary)
        assert result["main_guard"] is True
        assert result["persistent_loop"] is True
        assert "--watch" in result["argparse_flags"]
        assert result["execution_shape"] == "DIRECT_PERSISTENT_SERVICE_SUPPORTED"
        plan = build_service_plan(result, [])
        assert plan["deployment_shape"] == "SYSTEMD_SERVICE"
    finally:
        temporary.unlink(missing_ok=True)
    print("SELF_TEST_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.worktree is None or args.output is None:
        parser.error("--worktree and --output are required")
    run(args.root.resolve(), args.worktree.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
