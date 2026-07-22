#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"FAILURE_AUDIT_PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "r7a4d2_market_segment_expansion_for_short_candidates_v1" not in source:
        raise RuntimeError("MARKET_EXPANSION_SCRIPT_REQUIRED")
    if '"failure_error_histogram"' in source:
        raise RuntimeError("MARKET_EXPANSION_ALREADY_FAILURE_AUDITED")
    source = replace_once(
        source,
        '''        "event_replay_2880_allowed": False,
        "failures": failures[:20],
        "next_stage": next_stage,
''',
        '''        "event_replay_2880_allowed": False,
        "failure_count": len(failures),
        "failure_error_histogram": dict(sorted(Counter(
            str(row.get("error") or "") for row in failures
        ).items())),
        "failures": failures[:20],
        "next_stage": next_stage,
''',
        "EVIDENCE_FAILURE_AUDIT",
    )
    source = replace_once(
        source,
        '''    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false")
''',
        '''    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("FAILURE_COUNT=" + str(len(failures)))
    print("FAILURE_ERROR_HISTOGRAM=" + json.dumps(
        evidence["failure_error_histogram"], ensure_ascii=False, sort_keys=True
    ))
    print("PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false")
''',
        "PRINT_FAILURE_AUDIT",
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
    print("STATE=PASS_MARKET_EXPANSION_FAILURE_AUDIT_PATCH")
    print("FULL_FAILURE_COUNT_PERSISTED=true")
    print("FAILURE_ERROR_HISTOGRAM_PERSISTED=true")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
