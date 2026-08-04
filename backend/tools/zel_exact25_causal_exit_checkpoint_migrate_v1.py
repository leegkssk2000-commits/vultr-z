from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_EXACT25_CAUSAL_EXIT_CHECKPOINT_MIGRATE_V1"
PRESERVE_ORDINALS = (1, 2, 3)
INVALIDATE_ORDINALS = (4, 5, 6, 7)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def validate_baseline(body: Mapping[str, Any]) -> None:
    parity = body.get("baseline_parity")
    if not isinstance(parity, Mapping) or not parity or not all(parity.values()):
        raise RuntimeError("OLD_BASELINE_PARITY_NOT_ALL_TRUE")
    for field in ("baseline_integrity", "immutable_integrity"):
        row = body.get(field)
        if not isinstance(row, Mapping):
            raise RuntimeError(f"OLD_{field.upper()}_MISSING")
        if int(row.get("missing_identity_count") or 0) != 0:
            raise RuntimeError(f"OLD_{field.upper()}_MISSING_IDENTITY")
        if int(row.get("duplicate_trade_count") or 0) != 0:
            raise RuntimeError(f"OLD_{field.upper()}_DUPLICATES")
        if int(row.get("unknown_exit_count") or 0) != 0:
            raise RuntimeError(f"OLD_{field.upper()}_UNKNOWN_EXIT")
        if row.get("cost_lineage_complete") is not True:
            raise RuntimeError(f"OLD_{field.upper()}_COST_LINEAGE")


def validate_candidate(
    body: Mapping[str, Any],
    *,
    expected_config: Mapping[str, Any],
    stable_sha: Any,
    ordinal: int,
) -> None:
    if body.get("config_sha256") != stable_sha(expected_config):
        raise RuntimeError(f"OLD_CANDIDATE_CONFIG_SHA_MISMATCH:{ordinal}")
    if dict(body.get("config") or {}) != dict(expected_config):
        raise RuntimeError(f"OLD_CANDIDATE_CONFIG_MISMATCH:{ordinal}")
    counters = body.get("counters")
    integrity = body.get("integrity")
    if not isinstance(counters, Mapping) or not isinstance(integrity, Mapping):
        raise RuntimeError(f"OLD_CANDIDATE_INTEGRITY_MISSING:{ordinal}")
    if int(counters.get("error_count") or 0) != 0:
        raise RuntimeError(f"OLD_CANDIDATE_ERRORS:{ordinal}")
    if int(counters.get("censored_open_at_window_end") or 0) != 0:
        raise RuntimeError(f"OLD_CANDIDATE_CENSORED:{ordinal}")
    if int(integrity.get("missing_identity_count") or 0) != 0:
        raise RuntimeError(f"OLD_CANDIDATE_MISSING_IDENTITY:{ordinal}")
    if int(integrity.get("duplicate_trade_count") or 0) != 0:
        raise RuntimeError(f"OLD_CANDIDATE_DUPLICATES:{ordinal}")
    if int(integrity.get("unknown_exit_count") or 0) != 0:
        raise RuntimeError(f"OLD_CANDIDATE_UNKNOWN_EXIT:{ordinal}")
    if integrity.get("cost_lineage_complete") is not True:
        raise RuntimeError(f"OLD_CANDIDATE_COST_LINEAGE:{ordinal}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-runner", type=Path, required=True)
    parser.add_argument("--guard", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--terminal-root", type=Path, required=True)
    parser.add_argument("--source-owner", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--old-input-manifest", type=Path, required=True)
    parser.add_argument("--old-checkpoint-dir", type=Path, required=True)
    parser.add_argument("--new-input-manifest-out", type=Path, required=True)
    parser.add_argument("--new-checkpoint-dir", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()

    base = load_module(args.base_runner.resolve(), f"zel_checkpoint_base_{os.getpid()}")
    guard = load_module(args.guard.resolve(), f"zel_checkpoint_guard_{os.getpid()}")
    policy = base.read_json(args.policy.resolve())
    old_manifest = base.read_json(args.old_input_manifest.resolve())
    old_fingerprint = base.stable_sha(
        {
            "schema_version": "zel.exact25.causal_exit_screen.input_fingerprint.v2",
            "input_manifest_sha256": old_manifest["manifest_sha256"],
            "strategy_id": policy["strategy_id"],
            "axis_id": policy["axis_id"],
        }
    )
    new_manifest = guard.build_input_manifest(
        base_runner_path=args.base_runner.resolve(),
        screen_path=args.screen.resolve(),
        engine_path=args.engine.resolve(),
        policy_path=args.policy.resolve(),
        source_root=args.source_root.resolve(),
        data_root=args.data_root.resolve(),
        terminal_root=args.terminal_root.resolve(),
        source_owner_path=args.source_owner.resolve(),
        route_path=args.route.resolve(),
        commit_sha=args.commit_sha,
    )
    new_fingerprint = base.stable_sha(
        {
            "schema_version": "zel.exact25.causal_exit_screen.input_fingerprint.v2",
            "input_manifest_sha256": new_manifest["manifest_sha256"],
            "strategy_id": policy["strategy_id"],
            "axis_id": policy["axis_id"],
        }
    )
    if new_fingerprint == old_fingerprint:
        raise RuntimeError("NEW_FINGERPRINT_MUST_DIFFER_AFTER_PATCH")

    args.new_checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for ordinal in INVALIDATE_ORDINALS:
        invalid = args.new_checkpoint_dir / f"candidate-{ordinal:02d}.json"
        if invalid.exists():
            invalid.unlink()

    migrated: list[str] = []
    baseline_body = base.validate_checkpoint(
        args.old_checkpoint_dir / "baseline.json",
        fingerprint=old_fingerprint,
        kind="baseline",
    )
    validate_baseline(baseline_body)
    baseline_payload = base.checkpoint_payload(
        kind="baseline", fingerprint=new_fingerprint, body=baseline_body
    )
    baseline_payload.update(guard.SAFETY)
    baseline_payload["checkpoint_sha256"] = base.stable_sha(
        {key: value for key, value in baseline_payload.items() if key != "checkpoint_sha256"}
    )
    atomic_write_json(args.new_checkpoint_dir / "baseline.json", baseline_payload)
    migrated.append("baseline")

    configs = policy["candidate_configs"]
    for ordinal in PRESERVE_ORDINALS:
        kind = f"candidate-{ordinal:02d}"
        body = base.validate_checkpoint(
            args.old_checkpoint_dir / f"candidate-{ordinal:02d}.json",
            fingerprint=old_fingerprint,
            kind=kind,
        )
        validate_candidate(
            body,
            expected_config=configs[ordinal - 1],
            stable_sha=base.stable_sha,
            ordinal=ordinal,
        )
        payload = base.checkpoint_payload(
            kind=kind, fingerprint=new_fingerprint, body=body
        )
        payload.update(guard.SAFETY)
        payload["checkpoint_sha256"] = base.stable_sha(
            {key: value for key, value in payload.items() if key != "checkpoint_sha256"}
        )
        atomic_write_json(
            args.new_checkpoint_dir / f"candidate-{ordinal:02d}.json", payload
        )
        migrated.append(kind)

    atomic_write_json(args.new_input_manifest_out, new_manifest)
    receipt = {
        "schema_version": "zel.exact25.causal_exit_checkpoint_migration.receipt.v1",
        "version": VERSION,
        "state": "PASS_SELECTIVE_CHECKPOINT_MIGRATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy_id": policy["strategy_id"],
        "axis_id": policy["axis_id"],
        "old_input_manifest_sha256": old_manifest["manifest_sha256"],
        "new_input_manifest_sha256": new_manifest["manifest_sha256"],
        "old_fingerprint": old_fingerprint,
        "new_fingerprint": new_fingerprint,
        "migrated_units": migrated,
        "invalidated_units": [f"candidate-{value:02d}" for value in INVALIDATE_ORDINALS],
        "baseline_recomputed": False,
        "preserved_candidate_count": len(PRESERVE_ORDINALS),
        "replay_candidate_count": len(INVALIDATE_ORDINALS),
        **guard.SAFETY,
    }
    receipt["receipt_sha256"] = base.stable_sha(receipt)
    atomic_write_json(args.receipt_out, receipt)
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "migrated_units": migrated,
                "invalidated_units": receipt["invalidated_units"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
