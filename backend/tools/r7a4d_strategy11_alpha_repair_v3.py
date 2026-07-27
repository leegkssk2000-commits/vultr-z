from __future__ import annotations

import runpy
import tempfile
from pathlib import Path


def main() -> None:
    source = Path(__file__).with_name("r7a4d_strategy11_alpha_repair_v2.py").read_text(encoding="utf-8")
    replacements = {
        "R7A4D_STRATEGY11_ALPHA_REPAIR_V2": "R7A4D_STRATEGY11_ALPHA_REPAIR_V3",
        "--iteration1-summary": "--iteration2-summary",
        "iteration1_path": "iteration2_path",
        "iteration1 =": "iteration2 =",
        "iteration1.get": "iteration2.get",
        "ITERATION1_": "ITERATION2_",
        "ITERATION_2_PARTIAL_OR_TRAILING": "ITERATION_3_TIME_STOP_OR_SINGLE_GATE",
        '"PARTIAL30_R075"': '"TIME_STOP_48"',
        'exit_id="RR150_PARTIAL30_R075"': 'exit_id="RR150_TIME_STOP_48"',
        "partial_r=0.75,\n                partial_fraction=0.30,": "time_stop_bars=48,",
        '"TRAIL_R100_ATR100"': '"TIME_STOP_72"',
        'exit_id="RR150_TRAIL_R100_ATR100"': 'exit_id="RR150_TIME_STOP_72"',
        "trail_activate_r=1.0,\n                trail_atr_mult=1.0,": "time_stop_bars=72,",
        '"iteration1_run_id": "30262701736"': '"iteration2_run_id": "30264493769"',
        '"iteration1_summary_sha256"': '"iteration2_summary_sha256"',
        '"HOLD" if eligible else "HOLD"': '"PASS_TO_SEALED" if eligible else "COMPLETE_NO_PROMOTION"',
        '"ITERATION_3_TIME_STOP_OR_SINGLE_GATE"': '"KEEP_INCUMBENT_AND_START_TURTLE_TREND"',
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    source = source.replace('"next": "SEALED_HOLDBACK_ONE_SHOT" if eligible else "KEEP_INCUMBENT_AND_START_TURTLE_TREND"', '"next": "SEALED_HOLDBACK_ONE_SHOT" if eligible else "KEEP_INCUMBENT_AND_START_TURTLE_TREND"')
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(source)
        target = handle.name
    runpy.run_path(target, run_name="__main__")


if __name__ == "__main__":
    main()
