#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}")
PROCESS_TOKEN_KEYS = (
    "ZEL_TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "BOT_TOKEN",
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scoped_protected_snapshot(root: Path, base: Any) -> dict[str, str | None]:
    paths = {
        "formal_ledger": root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
        "shadow_snapshot": root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json",
        "deployed_source": base.DEPLOYED_SOURCE,
    }
    return {name: base.sha256_file(path) for name, path in paths.items()}


def token_from_active_process(base: Any) -> str | None:
    environment = base.process_environment()
    for key in PROCESS_TOKEN_KEYS:
        value = str(environment.get(key) or "").strip()
        if TOKEN_RE.fullmatch(value):
            return value
    return None


def token_from_isolated_find_token(source: Path, timeout_seconds: int = 25) -> str:
    helper = r'''
import ast
import os
import re
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
source = source_path.read_text(encoding="utf-8", errors="replace")
tree = ast.parse(source, filename=str(source_path))
functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "find_token"]
if len(functions) != 1 or isinstance(functions[0], ast.AsyncFunctionDef):
    raise SystemExit(21)
module = ast.Module(body=[functions[0]], type_ignores=[])
ast.fix_missing_locations(module)
namespace = {"os": os, "re": re, "Path": Path}
exec(compile(module, str(source_path) + ":find_token_only", "exec"), namespace, namespace)
resolved = namespace["find_token"]()
token = resolved[0] if isinstance(resolved, tuple) else resolved
token = token.strip() if isinstance(token, str) else ""
if not re.fullmatch(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}", token):
    raise SystemExit(22)
sys.stdout.write(token)
'''
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", helper, str(source)],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env=dict(os.environ),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("DEPLOYED_TOKEN_RESOLVER_TIMEOUT") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"DEPLOYED_TOKEN_RESOLVER_FAILED_{proc.returncode}")
    token = proc.stdout.strip()
    if not TOKEN_RE.fullmatch(token):
        raise RuntimeError("DEPLOYED_TOKEN_RESOLVER_OUTPUT_INVALID")
    return token


def safe_load_token(base: Any) -> str:
    active = token_from_active_process(base)
    if active:
        return active
    return token_from_isolated_find_token(base.DEPLOYED_SOURCE, timeout_seconds=25)


def annotate_status(root: Path, base: Any) -> dict[str, Any]:
    status_path = root / "runtime/exact25_edge_v1/r7a1a4c_environment_binding_canary/status_latest.json"
    payload = base.load_json(status_path)
    if not payload:
        return {}
    payload["scope_patch_stage"] = "R7.A1A4C3"
    payload["token_resolver_mode"] = "ACTIVE_PROCESS_OR_ISOLATED_AST_FIND_TOKEN"
    payload["deployed_module_imported"] = False
    payload["resolver_timeout_seconds"] = 25
    payload["stable_protected_paths"] = ["formal_ledger", "shadow_snapshot", "deployed_source"]
    payload["volatile_excluded_paths"] = ["view_contract"]
    base.atomic_json(status_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--base-runner", required=True)
    parser.add_argument("--bind-timeout", type=int, default=180)
    args = parser.parse_args()

    root = Path(args.root)
    base = load_module(Path(args.base_runner), "r7a1a4c_base")

    original_scope = set(base.protected_snapshot(root))
    expected_scope = {"formal_ledger", "shadow_snapshot", "view_contract", "deployed_source"}
    if original_scope != expected_scope:
        print("R7A1A4C3_SAFE_TOKEN_RESOLVER_CANARY_FAILED")
        print('BLOCKERS=["BASE_PROTECTED_SCOPE_UNEXPECTED"]')
        return 2

    base.protected_snapshot = lambda target_root: scoped_protected_snapshot(Path(target_root), base)
    base.load_token_from_deployed = lambda: safe_load_token(base)

    previous_argv = list(sys.argv)
    try:
        sys.argv = [
            str(args.base_runner),
            "--root", str(root),
            "--sha", args.sha,
            "--bind-timeout", str(max(30, args.bind_timeout)),
        ]
        rc = int(base.main())
    finally:
        sys.argv = previous_argv

    payload = annotate_status(root, base)
    print("R7A1A4C3_SAFE_TOKEN_RESOLVER_CANARY_COMPLETE")
    print("TOKEN_RESOLVER_MODE=ACTIVE_PROCESS_OR_ISOLATED_AST_FIND_TOKEN")
    print("DEPLOYED_MODULE_IMPORTED=false")
    print("RESOLVER_TIMEOUT_SECONDS=25")
    print("STABLE_PROTECTED_PATH_COUNT=3")
    print("VOLATILE_EXCLUDED_PATH_COUNT=1")
    print("STATE=" + str(payload.get("state")))
    print("BLOCKER_COUNT=" + str(payload.get("blocker_count")))
    print("NEXT_STAGE=" + str(payload.get("next_stage")))
    print("RC=" + str(rc))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
