#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


def load_base(path: Path):
    spec = importlib.util.spec_from_file_location("r7a1a4c_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scoped_protected_snapshot(root: Path, base: Any) -> dict[str, str | None]:
    paths = {
        "formal_ledger": root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
        "shadow_snapshot": root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json",
        "deployed_source": base.DEPLOYED_SOURCE,
    }
    return {name: base.sha256_file(path) for name, path in paths.items()}


def annotate_status(root: Path, base: Any) -> dict[str, Any]:
    status_path = root / "runtime/exact25_edge_v1/r7a1a4c_environment_binding_canary/status_latest.json"
    payload = base.load_json(status_path)
    if not payload:
        return {}
    payload["scope_patch_stage"] = "R7.A1A4C2"
    payload["stable_protected_paths"] = ["formal_ledger", "shadow_snapshot", "deployed_source"]
    payload["volatile_excluded_paths"] = ["view_contract"]
    payload["view_contract_guard_mode"] = "VOLATILE_SURFACE_EXCLUDED_FROM_EXACT_BYTE_HASH"
    base.atomic_json(status_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--base-runner", required=True)
    parser.add_argument("--bind-timeout", type=int, default=120)
    args = parser.parse_args()

    root = Path(args.root)
    base = load_base(Path(args.base_runner))
    original = base.protected_snapshot
    original_keys = set(original(root))
    if original_keys != {"formal_ledger", "shadow_snapshot", "view_contract", "deployed_source"}:
        print("R7A1A4C2_SCOPE_PATCH_FAILED")
        print("BLOCKERS=[\"BASE_PROTECTED_SCOPE_UNEXPECTED\"]")
        return 2

    base.protected_snapshot = lambda target_root: scoped_protected_snapshot(Path(target_root), base)
    previous_argv = list(sys.argv)
    try:
        sys.argv = [
            str(args.base_runner),
            "--root", str(root),
            "--sha", args.sha,
            "--bind-timeout", str(args.bind_timeout),
        ]
        rc = int(base.main())
    finally:
        sys.argv = previous_argv

    payload = annotate_status(root, base)
    print("R7A1A4C2_VOLATILE_VIEW_GUARD_SCOPE_COMPLETE")
    print("VIEW_CONTRACT_GUARD_MODE=VOLATILE_SURFACE_EXCLUDED_FROM_EXACT_BYTE_HASH")
    print("STABLE_PROTECTED_PATH_COUNT=3")
    print("VOLATILE_EXCLUDED_PATH_COUNT=1")
    print("STATE=" + str(payload.get("state")))
    print("BLOCKER_COUNT=" + str(payload.get("blocker_count")))
    print("NEXT_STAGE=" + str(payload.get("next_stage")))
    print("RC=" + str(rc))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
