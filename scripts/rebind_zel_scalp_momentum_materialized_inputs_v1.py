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

    bindings = {
        "candidate_source_sha256": args.repo_root / "backend/research/momentum_breakout_continuation_v1.py",
        "trial_plan_sha256": args.repo_root / "backend/research/zel_scalp_momentum_generation1_trial_plan_v1.json",
        "control_plan_sha256": args.repo_root / "backend/research/zel_scalp_momentum_replay_control_plan_v1.json",
        "design_receipt_sha256": args.repo_root / "backend/research/zel_scalp_momentum_breakout_continuation_design_v1.json",
        "feature_strategy_ssot_sha256": args.repo_root / "backend/research/zel_feature_strategy_ssot_v1.py",
        "intent_adapters_sha256": args.repo_root / "backend/research/zel_strategy_intent_adapters_v1.py",
        "feature_contribution_plan_sha256": args.repo_root / "backend/research/zel_momentum_feature_contribution_plan_v1.json",
        "feature_contribution_disposition_sha256": args.repo_root / "backend/research/zel_momentum_feature_contribution_disposition_v1.json",
        "cost_geometry_plan_sha256": args.repo_root / "backend/research/zel_momentum_cost_geometry_plan_v1.json",
        "cost_geometry_disposition_sha256": args.repo_root / "backend/research/zel_momentum_cost_geometry_disposition_v1.json",
        "target_geometry_plan_sha256": args.repo_root / "backend/research/zel_momentum_target_geometry_plan_v1.json",
        "target_geometry_disposition_sha256": args.repo_root / "backend/research/zel_momentum_target_geometry_disposition_v1.json",
        "timeout_geometry_plan_sha256": args.repo_root / "backend/research/zel_momentum_timeout_geometry_plan_v1.json",
        "timeout_geometry_disposition_sha256": args.repo_root / "backend/research/zel_momentum_timeout_geometry_disposition_v1.json",
        "stop_geometry_plan_sha256": args.repo_root / "backend/research/zel_momentum_stop_geometry_plan_v1.json",
        "stop_geometry_disposition_sha256": args.repo_root / "backend/research/zel_momentum_stop_geometry_disposition_v1.json",
        "early_invalidation_plan_sha256": args.repo_root / "backend/research/zel_momentum_early_invalidation_plan_v1.json",
        "early_invalidation_disposition_sha256": args.repo_root / "backend/research/zel_momentum_early_invalidation_disposition_v1.json",
        "breakeven_plan_sha256": args.repo_root / "backend/research/zel_momentum_breakeven_plan_v1.json",
    }
    for path in bindings.values():
        if not path.is_file():
            raise SystemExit(f"missing momentum binding input: {path}")

    prior_references = manifest["references"]
    manifest["schema_version"] = "zel.scalp.momentum.materialized_dataset.v1"
    manifest["state"] = "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS"
    manifest["strategy_id"] = "momentum_breakout_continuation_v1"
    manifest["references"] = {
        key: sha256_file(path) for key, path in bindings.items()
    } | {
        "cost_receipt_sha256": prior_references["cost_receipt_sha256"],
        "funding_receipt_sha256": prior_references["funding_receipt_sha256"],
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
        "binding_count": len(manifest["references"]),
        "receipt": manifest["manifest_receipt_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
