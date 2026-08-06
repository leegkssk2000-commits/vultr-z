#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.inputs / "materialized_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("state") != "PASS_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("materialized input state mismatch")
    if manifest.get("file_count") != 60 or int(manifest.get("total_rows", 0)) <= 0:
        raise SystemExit("materialized market corpus incomplete")
    if manifest.get("protected_mutations") != 0:
        raise SystemExit("protected mutation detected")
    if manifest.get("execution_authority") != "NONE" or manifest.get("order_authority") != "BLOCKED":
        raise SystemExit("authority boundary mismatch")

    source = args.repo_root / "backend/research/momentum_breakout_continuation_v1.py"
    trial = args.repo_root / "backend/research/zel_scalp_momentum_generation1_trial_plan_v1.json"
    control = args.repo_root / "backend/research/zel_scalp_momentum_replay_control_plan_v1.json"
    design = args.repo_root / "backend/research/zel_scalp_momentum_breakout_continuation_design_v1.json"
    for path in (source, trial, control, design):
        if not path.is_file():
            raise SystemExit(f"missing momentum binding input: {path}")

    manifest["schema_version"] = "zel.scalp.momentum.materialized_dataset.v1"
    manifest["state"] = "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS"
    manifest["strategy_id"] = "momentum_breakout_continuation_v1"
    manifest["references"] = {
        "candidate_source_sha256": sha256_file(source),
        "trial_plan_sha256": sha256_file(trial),
        "control_plan_sha256": sha256_file(control),
        "design_receipt_sha256": sha256_file(design),
        "cost_receipt_sha256": manifest["references"]["cost_receipt_sha256"],
        "funding_receipt_sha256": manifest["references"]["funding_receipt_sha256"],
    }
    manifest["selection_authority"] = False
    manifest["promotion_authority"] = False
    manifest["execution_authority"] = "NONE"
    manifest["order_authority"] = "BLOCKED"
    manifest["protected_mutations"] = 0
    manifest["action"] = "hold"
    manifest.pop("manifest_receipt_sha256", None)
    manifest["manifest_receipt_sha256"] = canonical_sha256(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "state": manifest["state"],
        "strategy_id": manifest["strategy_id"],
        "file_count": manifest["file_count"],
        "total_rows": manifest["total_rows"],
        "receipt": manifest["manifest_receipt_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
