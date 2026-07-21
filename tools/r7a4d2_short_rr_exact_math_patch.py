#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.input).resolve().read_text(encoding="utf-8")
    old = '''            if policy_applied:
                stop = fill + short_policy_loss_cap_r * raw_r_distance
                tp = max(fill - short_policy_full_tp_r * raw_r_distance, 1e-12)
                if not (0 < tp < fill < stop):
'''
    new = '''            if policy_applied:
                raw_r_fraction = raw_r_distance / fill
                stop_denominator = 1.0 - short_policy_loss_cap_r * raw_r_fraction
                if stop_denominator <= 0:
                    invalid_signal_count += 1
                    short_invalid_geometry_count += 1
                    return
                stop = fill / stop_denominator
                tp = fill / (1.0 + short_policy_full_tp_r * raw_r_fraction)
                if not (0 < tp < fill < stop):
'''
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"EXACT_RR_MATH_ANCHOR_INVALID:{count}")
    patched = source.replace(old, new, 1)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", delete=False
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)
    temp_path.replace(output)
    py_compile.compile(str(output), doraise=True)
    print("STATE=PASS_SHORT_RR_EXACT_MATH_PATCH")
    print("SHORT_RETURN_SPACE_RR_EXACT=true")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
