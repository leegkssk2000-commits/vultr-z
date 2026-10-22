#!/usr/bin/env python3
"""One offline invocation for A: exact saved attribution and terminal source proof."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import native_lifecycle_counterexamples as native
import trend256_attribution as attribution
import trend256_overlap as overlap
import trend256_source_gate as source_gate

ROOT = Path(__file__).resolve().parent
CONTRIBUTION_PATH = "research/campaigns/scalp7_20261021/portfolio_coverage_v1/work_d/contribution_report.py"


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False, default=attribution._json_default) + "\n"


def run(repo_root, output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("New exclusive output directory required: " + str(output_dir))
    long_path = ROOT / "inputs/long_only_prospective.json"
    liquid_path = ROOT / "inputs/liquid6_child.json"
    engine_path = Path(repo_root) / CONTRIBUTION_PATH
    # All inputs validate and all deterministic computations finish before any output.
    gate = source_gate.run(long_path, ROOT / "inputs/long256.zip", ROOT)
    lifecycle = native.run_diagnostics(ROOT / "frozen_source" / native.NATIVE_BASENAME)
    long_receipt = attribution.load_verified(long_path, "long256")
    liquid_receipt = attribution.load_verified(liquid_path, "liquid123")
    outputs = attribution.build_attribution(long_receipt)
    outputs["SUMMARY.json"]["liquid123_separate_identity_only"] = attribution.liquid_identity_note(liquid_receipt)
    outputs.update({"SOURCE_GATE.json": gate, "LIFECYCLE_COUNTEREXAMPLES.json": lifecycle,
                    "OVERLAP.json": overlap.run(long_path, liquid_path, engine_path)})
    serialized = {name: dump(value) for name, value in outputs.items()}
    receipt = {
        "schema": "zel.work_d.trend256.offline_handoff.v1",
        "state": "NO_CAUSAL_CHILD", "first_blocker": "SOURCE_FEATURE_BLOCKED",
        "classification": "SAVED_LEDGER_DIAGNOSTIC_AND_SYNTHETIC_SOURCE_COUNTEREXAMPLES",
        "files": {name: {"sha256": hashlib.sha256(data.encode()).hexdigest(),
                          "bytes": len(data.encode())} for name, data in sorted(serialized.items())},
        "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(ROOT.glob("*.py")) if not p.name.startswith("test_")},
        "existing_D_module": {"path": CONTRIBUTION_PATH,
                              "sha256": hashlib.sha256(engine_path.read_bytes()).hexdigest()},
        "input_raw_sha256": {"long256": attribution.PINS["long256"]["raw_sha256"],
                             "liquid123": attribution.PINS["liquid123"]["raw_sha256"],
                             "long256_zip": source_gate.ZIP_SHA},
        "new_full_runs": 0, "economic_comparisons": 0, "market_api_calls": 0,
        "child_adapters": 0, "new_orders": 0, "order_authority": "BLOCKED",
        "shared_account_net_or_nav": None, "economic_improvement": "UNMEASURED_NO_CHILD",
        "owner": "CLOUD_WORK_COORDINATOR_ISSUE1358_V1",
        "K117": "CLOSED_FROZEN_NO_CAUSAL_CHILD_UNTOUCHED",
    }
    serialized["RUN_RECEIPT.json"] = dump(receipt)
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, data in serialized.items():
        with (output_dir / name).open("x", encoding="utf-8") as handle:
            handle.write(data)
    # Read back exact serialized bytes immediately; no mutable ledger writes.
    for name, data in serialized.items():
        if (output_dir / name).read_bytes() != data.encode():
            raise RuntimeError("OUTPUT_READBACK_MISMATCH:" + name)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.repo_root, args.output_dir)
    print(json.dumps({"state": result["state"], "first_blocker": result["first_blocker"],
                      "output_files": len(result["files"]) + 1,
                      "new_full_runs": 0, "orders": 0}))


if __name__ == "__main__":
    main()
