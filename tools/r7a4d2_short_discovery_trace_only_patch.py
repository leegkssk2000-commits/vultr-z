#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"DISCOVERY_PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "SHORT_CANDIDATE_TRACE_V1" not in source:
        raise RuntimeError("SHORT_CANDIDATE_TRACE_RUNNER_REQUIRED")
    if "SHORT_DISCOVERY_TRACE_ONLY_V1" in source:
        raise RuntimeError("RUNNER_ALREADY_DISCOVERY_PATCHED")
    source = replace_once(
        source,
        "SHORT_CANDIDATE_TRACE_V1 = True\n",
        "SHORT_CANDIDATE_TRACE_V1 = True\nSHORT_DISCOVERY_TRACE_ONLY_V1 = True\n",
        "DISCOVERY_MARKER",
    )
    source = replace_once(
        source,
        'SHORT_POLICY_ALLOWED_REGIMES = frozenset({"trend_down"})',
        'SHORT_POLICY_ALLOWED_REGIMES = frozenset()',
        "BLOCK_ALL_SHORT_EXECUTION",
    )
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    patched = apply_patch(input_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    py_compile.compile(str(output_path), doraise=True)
    print("STATE=PASS_SHORT_DISCOVERY_TRACE_ONLY_PATCH")
    print("SHORT_EXECUTION_ALLOWED=false")
    print("SHORT_CANDIDATE_TRACE_ALLOWED=true")
    print("MUTATION_SCOPE=temporary_runner_only")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
