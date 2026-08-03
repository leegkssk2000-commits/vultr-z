from __future__ import annotations

import argparse
import copy
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import zel_alpha_unattended_champion_v2 as engine


def read_previous(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    value = engine.read_json(path)
    return value if value.get("schema_version") == engine.STATE_SCHEMA else None


def choose_epoch_policy(
    policy: Mapping[str, Any], previous: Mapping[str, Any] | None
) -> tuple[dict[str, Any], str, Any]:
    epoch = int((previous or {}).get("epoch") or 0)
    axis = engine.choose_axis(policy, previous, epoch)
    axis_id = str(axis["axis_id"])
    values = list(axis.get("values") or [])
    if not values:
        raise RuntimeError(f"AXIS_VALUES_EMPTY:{axis_id}")
    tested = set(str(v) for v in (previous or {}).get("tested_config_sha256", []))
    control = engine.normalized_config(
        (previous or {}).get("best_config") or policy["initial_control"]
    )
    selected = None
    for offset in range(len(values)):
        value = values[(epoch + offset) % len(values)]
        candidate = engine.config_for_axis(control, axis, value)
        digest = engine.config_sha(candidate)
        if digest != engine.config_sha(control) and digest not in tested:
            selected = value
            break
    if selected is None:
        selected = values[epoch % len(values)]
    bounded = copy.deepcopy(dict(policy))
    for row in bounded["axes"]:
        if str(row.get("axis_id")) == axis_id:
            row["values"] = [selected]
    bounded["runtime_epoch_bound"] = {
        "one_candidate_only": True,
        "axis_id": axis_id,
        "value": selected,
        "epoch": epoch + 1,
    }
    return bounded, axis_id, selected


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--previous-state", type=Path)
    known, _ = parser.parse_known_args()
    original_policy = known.policy.resolve()
    policy = engine.read_json(original_policy)
    previous = read_previous(known.previous_state)
    bounded, axis_id, selected = choose_epoch_policy(policy, previous)

    with tempfile.TemporaryDirectory(prefix="zel-alpha-epoch-") as tmp:
        epoch_policy = Path(tmp) / "policy.json"
        engine.write_json(epoch_policy, bounded)
        original_fingerprint = engine.fingerprint

        def stable_fingerprint(
            *,
            data_root: Path,
            baseline_path: Path,
            authority_root: Path,
            policy_path: Path,
        ) -> str:
            return original_fingerprint(
                data_root=data_root,
                baseline_path=baseline_path,
                authority_root=authority_root,
                policy_path=original_policy,
            )

        engine.fingerprint = stable_fingerprint
        argv = list(sys.argv)
        index = argv.index("--policy") + 1
        argv[index] = str(epoch_policy)
        sys.argv = argv
        print(
            f"ALPHA_EPOCH_BOUND axis={axis_id} value={selected} one_candidate_only=true",
            flush=True,
        )
        return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
