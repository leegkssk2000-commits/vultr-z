"""Verify this exact saved handoff; never execute economics or grant authority."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REQUIRED = (
    "original_native_4h_ohlc_sha256",
    "original_observed_availability_sha256",
    "separate_dev_input_sha256",
    "causal_fill_funding_witness_sha256",
)


def inspect_binding(path: Path, expected_sha256: str) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("INPUT_BINDING_SHA_MISMATCH")
    binding = json.loads(raw)
    if binding.get("schema") != "zel.supertrend4h.stage4.input_binding.v1":
        raise ValueError("INPUT_BINDING_SCHEMA_MISMATCH")
    for item in binding["pinned_artifacts"]:
        name = item["path"]
        if Path(name).name != name:
            raise ValueError("OUTSIDE_STAGE4_ARTIFACT")
        artifact = path.parent / name
        if artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("PREPARED_ARTIFACT_CHANGED:" + name)
    missing = [key for key in REQUIRED if binding["market_bindings"].get(key) is None]
    return {
        "state": "HOLD_SOURCE_FEATURE_NOT_BOUND" if missing else "HOLD_OWNER_SOURCE_REVALIDATION_REQUIRED",
        "first_missing": missing[0] if missing else None,
        "missing": missing,
        "policy_id": binding["policy_id"],
        "binding_sha256": expected_sha256,
        "prepared_code_verified": True,
        "eligible_candidate_count": 0,
        "economic_command": None,
        "economic_runs": 0,
        "stage1_2_3_reruns": 0,
        "actions_dispatch": 0,
        "orders": 0,
        "source_readiness_granted": False,
        "next": "Existing owner A receives source-blocked preparation only; no FULL queued."
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect_binding(args.binding, args.sha256)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"state": "HOLD_INTEGRITY", "reason": str(exc), "economic_runs": 0}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 2  # Deliberate source/owner gate, never economic success.


if __name__ == "__main__":
    raise SystemExit(main())
