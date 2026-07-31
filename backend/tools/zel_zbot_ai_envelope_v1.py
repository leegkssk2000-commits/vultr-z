from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "shadow_start_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("OBJECT_REQUIRED")
    return value


def normalize(payload: Mapping[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(dict(payload))
    hypothesis = row.get("hypothesis")
    if not isinstance(hypothesis, dict):
        raise ValueError("HYPOTHESIS_REQUIRED")
    if hypothesis.get("axis") != "ZBOT_PROFILE" or hypothesis.get("target") != "ZBot":
        raise ValueError("ZBOT_HYPOTHESIS_REQUIRED")
    for key, value in SAFETY.items():
        if row.get(key) != value:
            raise ValueError(f"SAFETY_MISMATCH:{key}")
    row["changed_axes"] = ["ADVISOR_PROFILE"]
    external = copy.deepcopy(hypothesis)
    external["axis"] = "ADVISOR_PROFILE"
    external["component_axis"] = "ZBOT_PROFILE"
    external["advisor_role"] = "ZBot"
    row["hypothesis"] = external
    row["component_replay_contract"] = {
        "internal_axis": "ZBOT_PROFILE",
        "external_review_axis": "ADVISOR_PROFILE",
        "target": "ZBot",
        "source_mutation_allowed": False,
    }
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = normalize(read_json(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print("PASS_ZBOT_AI_ENVELOPE_NORMALIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
