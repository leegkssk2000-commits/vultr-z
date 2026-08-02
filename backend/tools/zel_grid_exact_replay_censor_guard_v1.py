from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_EXACT_REPLAY_CENSOR_GUARD_V1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def censored_count(meta: Mapping[str, Any]) -> int:
    return sum(
        int(row.get("censored_open_at_window_end") or 0)
        for row in meta.get("lane_receipts", [])
        if isinstance(row, Mapping)
    )


def apply_guard(receipt: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(receipt)
    baseline_censored = censored_count(output.get("baseline_meta") or {})
    candidate_censored = censored_count(output.get("candidate_meta") or {})
    checks = dict(output.get("candidate_checks") or {})
    checks.update(
        {
            "baseline_censored_open_count_zero": baseline_censored == 0,
            "candidate_censored_open_count_zero": candidate_censored == 0,
        }
    )
    output["candidate_checks"] = checks
    output["baseline_censored_open_count"] = baseline_censored
    output["candidate_censored_open_count"] = candidate_censored
    output["censor_guard_version"] = VERSION

    base_pass = bool(output.get("candidate_pass"))
    guarded_pass = base_pass and all(checks.values())
    output["candidate_pass"] = guarded_pass
    if not guarded_pass:
        output["selected_research_fork"] = None
        if baseline_censored:
            output["state"] = "HOLD_GRID_BLOCK_TREND_SHORT_BASELINE_CENSORED_OPEN"
            output["next"] = "RESOLVE_SINGLE_BASELINE_CENSOR_CAUSE"
        elif candidate_censored:
            output["state"] = "HOLD_GRID_BLOCK_TREND_SHORT_CANDIDATE_CENSORED_OPEN"
            output["next"] = "RETAIN_INCUMBENT_AND_REDESIGN_WINDOW_END_POLICY"
    output.pop("receipt_sha256", None)
    output["receipt_sha256"] = stable_sha(output)
    return output


def self_test() -> int:
    base = {
        "candidate_pass": True,
        "selected_research_fork": "x",
        "candidate_checks": {"a": True},
        "baseline_meta": {"lane_receipts": [{"censored_open_at_window_end": 0}]},
        "candidate_meta": {"lane_receipts": [{"censored_open_at_window_end": 1}]},
    }
    held = apply_guard(base)
    assert held["candidate_pass"] is False
    assert held["selected_research_fork"] is None
    assert held["candidate_censored_open_count"] == 1
    passed = apply_guard(
        {
            **base,
            "candidate_meta": {"lane_receipts": [{"censored_open_at_window_end": 0}]},
        }
    )
    assert passed["candidate_pass"] is True
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.input or not args.output:
        parser.error("--input and --output required")
    receipt = json.loads(args.input.read_text(encoding="utf-8"))
    guarded = apply_guard(receipt)
    args.output.write_text(
        json.dumps(guarded, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
