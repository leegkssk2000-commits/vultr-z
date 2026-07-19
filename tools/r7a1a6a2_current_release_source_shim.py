#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

TARGET_BASENAME = "zel_q4r3_telegram_pos_adapter_v2.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_IMPORT_FAILED_{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select_current_source(argv: list[str]) -> Path:
    candidates = [Path(item) for item in argv if Path(item).name == TARGET_BASENAME]
    if len(candidates) != 1:
        raise RuntimeError(f"CURRENT_EXEC_SOURCE_COUNT_{len(candidates)}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--router-runner", required=True)
    parser.add_argument("--source-cutover-runner", required=True)
    parser.add_argument("--parity-helper", required=True)
    parser.add_argument("--source-contract", required=True)
    parser.add_argument("--router-contract", required=True)
    parser.add_argument("--command-timeout", type=int, default=90)
    args = parser.parse_args()

    router = load_module("r7a1a6a_router", Path(args.router_runner))
    original_loader = router.load_module

    def patched_loader(name: str, path: Path):
        module = original_loader(name, path)
        if name == "r7a1a5_base":
            current_source = select_current_source(module.process_cmdline())
            module.LEGACY_SOURCE = current_source
            print(f"CURRENT_EXEC_SOURCE={current_source}")
        return module

    router.load_module = patched_loader
    previous_argv = list(sys.argv)
    try:
        sys.argv = [
            args.router_runner,
            "--root", args.root,
            "--sha", args.sha,
            "--source-cutover-runner", args.source_cutover_runner,
            "--parity-helper", args.parity_helper,
            "--source-contract", args.source_contract,
            "--router-contract", args.router_contract,
            "--command-timeout", str(args.command_timeout),
        ]
        return int(router.main())
    finally:
        sys.argv = previous_argv


if __name__ == "__main__":
    raise SystemExit(main())
