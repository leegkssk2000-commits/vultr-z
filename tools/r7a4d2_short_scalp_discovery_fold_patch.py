#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


LOOP_OLD = "        for start in window_starts(len(trigger)):\n"
LOOP_NEW = "        for fold, start in enumerate(window_starts(len(trigger))):\n"
SCENARIO_ANCHOR_OLD = '''            scenario = {
                "scenario_id": scenario_id,
                "strategy_id": "scalp_snap",
'''
SCENARIO_ANCHOR_NEW = '''            scenario = {
                "scenario_id": scenario_id,
                "fold": fold,
                "strategy_id": "scalp_snap",
'''


def apply_patch(source: str) -> str:
    if source.count(LOOP_OLD) != 1:
        raise ValueError(f"FOLD_LOOP_ANCHOR_COUNT_INVALID:{source.count(LOOP_OLD)}")
    if source.count(SCENARIO_ANCHOR_OLD) != 1:
        raise ValueError(f"FOLD_SCENARIO_ANCHOR_COUNT_INVALID:{source.count(SCENARIO_ANCHOR_OLD)}")
    if '"fold": fold' in source:
        raise ValueError("FOLD_ALREADY_PRESENT")
    patched = source.replace(LOOP_OLD, LOOP_NEW, 1)
    patched = patched.replace(SCENARIO_ANCHOR_OLD, SCENARIO_ANCHOR_NEW, 1)
    if patched.count(LOOP_NEW) != 1 or patched.count('"fold": fold') != 1:
        raise ValueError("FOLD_PATCH_POSTCONDITION_FAILED")
    return patched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    source = input_path.read_text(encoding="utf-8")
    patched = apply_patch(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(patched, encoding="utf-8")

    print("STATE=PASS_SHORT_SCALP_DISCOVERY_FOLD_PATCH")
    print("FOLD_SOURCE=window_enumeration")
    print("FOLD_KEY_BOUND=true")
    print("SOURCE_MUTATION_ALLOWED=false")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
