from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import zel_alpha_unattended_champion_v2 as core


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--alpha-root", type=Path, required=True)
    parser.add_argument("--baseline-summary", type=Path, required=True)
    parser.add_argument("--multiobjective-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--previous-state", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy = read_json(args.policy)
    previous = None
    if args.previous_state and args.previous_state.is_file():
        previous = read_json(args.previous_state)

    epoch = int((previous or {}).get("epoch") or 0)
    control = core.normalized_config(
        (previous or {}).get("best_config") or policy["initial_control"]
    )
    tested = set(str(v) for v in (previous or {}).get("tested_config_sha256", []))
    axis = core.choose_axis(policy, previous, epoch)

    selected_value = None
    for value in axis.get("values", []):
        config = core.config_for_axis(control, axis, value)
        digest = core.config_sha(config)
        if digest != core.config_sha(control) and digest not in tested:
            selected_value = value
            break

    if selected_value is None:
        axes = [row for row in policy.get("axes", []) if isinstance(row, dict)]
        if not axes:
            raise RuntimeError("AXIS_CATALOG_EMPTY")
        current = next(
            (i for i, row in enumerate(axes) if row.get("axis_id") == axis.get("axis_id")),
            0,
        )
        for offset in range(1, len(axes) + 1):
            candidate_axis = axes[(current + offset) % len(axes)]
            for value in candidate_axis.get("values", []):
                config = core.config_for_axis(control, candidate_axis, value)
                digest = core.config_sha(config)
                if digest != core.config_sha(control) and digest not in tested:
                    axis = candidate_axis
                    selected_value = value
                    break
            if selected_value is not None:
                break

    if selected_value is None:
        raise RuntimeError("NO_UNTESTED_BOUNDED_CANDIDATE")

    bounded = dict(policy)
    bounded_axes = []
    for row in policy.get("axes", []):
        clone = dict(row)
        if clone.get("axis_id") == axis.get("axis_id"):
            clone["values"] = [selected_value]
        bounded_axes.append(clone)
    bounded["axes"] = bounded_axes
    bounded["bounded_epoch"] = {
        "axis_id": axis.get("axis_id"),
        "selected_value": selected_value,
        "maximum_candidates_this_epoch": 1,
    }

    with tempfile.TemporaryDirectory() as tmp:
        bounded_path = Path(tmp) / "policy.json"
        bounded_path.write_text(json.dumps(bounded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        argv = [
            "zel_alpha_unattended_champion_v2.py",
            "--policy", str(bounded_path),
            "--alpha-root", str(args.alpha_root),
            "--baseline-summary", str(args.baseline_summary),
            "--multiobjective-root", str(args.multiobjective_root),
            "--data-root", str(args.data_root),
            "--out", str(args.out),
        ]
        if args.previous_state and args.previous_state.is_file():
            argv.extend(["--previous-state", str(args.previous_state)])
        old = sys.argv
        try:
            sys.argv = argv
            return core.main()
        finally:
            sys.argv = old


if __name__ == "__main__":
    raise SystemExit(main())
