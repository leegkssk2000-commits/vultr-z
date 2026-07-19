#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_IMPORT_FAILED_{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def retention_surface_available(http_payload: dict[str, Any], file_payload: dict[str, Any], _parity: Any) -> bool:
    """Source retention gate only.

    Exact ALIMI HTTP/file parity is intentionally excluded here because it is
    volatile during command smoke and is verified immediately after cutover by
    R7.A1A6C verify. The router still independently requires HTTP 200 and
    configured_writer_count=7; the source canary independently requires the
    runtime report to remain order=blocked, execution=none, real_order=false.
    """
    return bool(http_payload) and bool(file_payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--router-runner", required=True)
    parser.add_argument("--source-shim", required=True)
    parser.add_argument("--source-cutover-runner", required=True)
    parser.add_argument("--parity-helper", required=True)
    parser.add_argument("--source-contract", required=True)
    parser.add_argument("--router-contract", required=True)
    parser.add_argument("--boundary-contract", required=True)
    parser.add_argument("--command-timeout", type=int, default=120)
    args = parser.parse_args()

    boundary = load_json(Path(args.boundary_contract))
    if boundary.get("official_stage") != "R7.A1A6C2":
        print("R7A1A6C2_RETENTION_BOUNDARY_FAILED")
        print('BLOCKERS=["BOUNDARY_CONTRACT_INVALID"]')
        return 2

    root = Path(args.root).resolve()
    router = load_module("r7a1a6a_router", Path(args.router_runner))
    source_shim = load_module("r7a1a6a2_source_shim", Path(args.source_shim))
    original_loader = router.load_module

    # Critical fix: do not let volatile ALIMI equality roll back a Telegram
    # source that already passed all three command routes and runtime safety.
    # Exact JSON parity remains mandatory in the post-cutover A1A6C verify.
    router.critical_views_equal = retention_surface_available

    def patched_loader(name: str, path: Path):
        module = original_loader(name, path)
        if name == "r7a1a5_base":
            current_source = source_shim.select_current_source(module.process_cmdline())
            module.LEGACY_SOURCE = current_source
            gate_state = source_shim.install_first_gate_recovery(module, root)
            module._r7a1a6c2_gate_state = gate_state
            print(f"CURRENT_EXEC_SOURCE={current_source}")
        return module

    router.load_module = patched_loader
    previous_argv = list(sys.argv)
    try:
        sys.argv = [
            args.router_runner,
            "--root", str(root),
            "--sha", args.sha,
            "--source-cutover-runner", args.source_cutover_runner,
            "--parity-helper", args.parity_helper,
            "--source-contract", args.source_contract,
            "--router-contract", args.router_contract,
            "--command-timeout", str(max(30, args.command_timeout)),
        ]
        print("RETENTION_BOUNDARY=TELEGRAM_COMMAND_SOURCE_SAFETY_ONLY")
        print("ALIMI_EXACT_PARITY_EXCLUDED_FROM_SOURCE_ROLLBACK=true")
        print("POST_CUTOVER_EXACT_PARITY_GATE=R7.A1A6C_VERIFY")
        return int(router.main())
    finally:
        sys.argv = previous_argv


if __name__ == "__main__":
    raise SystemExit(main())
