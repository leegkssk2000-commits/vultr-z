from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_REGISTRY_RESTORE_V4"
V3_PATH = Path(__file__).with_name("zel_structural_premium_registry_restore_v3.py")
ENTRY_TARGETS = (
    "vwap_revert",
    "support_resistance",
    "liquidity_sweep",
    "trend_rider",
)
FILTER_ONLY = ("market_structure",)


def _load_v3() -> Any:
    spec = importlib.util.spec_from_file_location("zel_structural_premium_registry_restore_v3_base", V3_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"V3_MODULE_SPEC_FAILED:{V3_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V3 = _load_v3()
_BASE_PATCH_ENGINES = V3.V2.patch_engines


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def patch_engines_entry_owners_only(engine_v1: Path, engine_v2: Path, mapping: dict[str, dict[str, Any]]) -> None:
    """Use the hardened V3 resolver but replay only the four actual entry owners.

    market_structure is explicitly FILTER_ONLY in the coverage contract and must not be
    fabricated into an entry-producing strategy merely to satisfy a strategy-count gate.
    """
    if set(mapping) != set(ENTRY_TARGETS):
        raise RuntimeError(f"ENTRY_OWNER_MAPPING_SET:{sorted(mapping)}")
    if any(key in mapping for key in FILTER_ONLY):
        raise RuntimeError("FILTER_ONLY_PROMOTED_TO_ENTRY_OWNER")

    _BASE_PATCH_ENGINES(engine_v1, engine_v2, mapping)
    for path in (engine_v1, engine_v2):
        text = path.read_text(encoding="utf-8")
        anchor = "EXPECTED_STRATEGY_COUNT = 5"
        if text.count(anchor) != 1:
            raise RuntimeError(f"POST_V3_EXPECTED_COUNT_ANCHOR:{path}:{text.count(anchor)}")
        text = text.replace(anchor, "EXPECTED_STRATEGY_COUNT = 4")
        path.write_text(text, encoding="utf-8")


def install_entry_owner_contract() -> None:
    V3.TARGETS = ENTRY_TARGETS
    V3.V2.TARGETS = ENTRY_TARGETS
    V3.install_hardening()
    V3.V2.patch_engines = patch_engines_entry_owners_only


def self_test() -> None:
    # First preserve every hardening check already established by V3.
    V3.self_test()
    install_entry_owner_contract()
    assert tuple(V3.TARGETS) == ENTRY_TARGETS
    assert tuple(V3.V2.TARGETS) == ENTRY_TARGETS
    assert set(ENTRY_TARGETS).isdisjoint(FILTER_ONLY)
    assert len(ENTRY_TARGETS) == 4 and len(FILTER_ONLY) == 1
    print(json.dumps({
        "state": "PASS_SELF_TEST",
        "version": VERSION,
        "entry_owner_count": len(ENTRY_TARGETS),
        "entry_targets": list(ENTRY_TARGETS),
        "filter_only": list(FILTER_ONLY),
        "filter_only_replayed_as_entry_owner": False,
        "v3_hardening_preserved": True,
    }, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--engine-v1", type=Path)
    parser.add_argument("--engine-v2", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not all((args.source_root, args.engine_v1, args.engine_v2, args.output)):
        parser.error("source-root, engine-v1, engine-v2 and output are required")

    install_entry_owner_contract()
    mapping, available = V3.V2.resolve(args.source_root.resolve())
    if set(mapping) != set(ENTRY_TARGETS):
        raise RuntimeError(f"ENTRY_OWNER_RESOLUTION_COUNT:{sorted(mapping)}")
    if "market_structure" in mapping:
        raise RuntimeError("FILTER_ONLY_MARKET_STRUCTURE_MUST_NOT_BE_ENTRY_OWNER")

    V3.V2.patch_engines(args.engine_v1.resolve(), args.engine_v2.resolve(), mapping)

    payload = {
        "schema_version": "zel.structural_premium.registry_restore.v4",
        "state": "PASS_STRUCTURAL_PREMIUM_ENTRY_OWNER_COVERAGE_RESTORED",
        "version": VERSION,
        "entry_targets": list(ENTRY_TARGETS),
        "filter_only": list(FILTER_ONLY),
        "mapping": mapping,
        "available_registry_ids": available,
        "restored_count": len(mapping),
        "registered_contract_count": len(ENTRY_TARGETS) + len(FILTER_ONLY),
        "entry_owner_count": len(ENTRY_TARGETS),
        "filter_only_count": len(FILTER_ONLY),
        "filter_only_replayed_as_entry_owner": False,
        "market_structure_entry_owner": False,
        "engine_v1_sha256": sha256_path(args.engine_v1),
        "engine_v2_sha256": sha256_path(args.engine_v2),
        "import_argv_isolated": True,
        "import_env_isolated": True,
        "import_cwd_isolated": True,
        "import_sys_path_isolated": True,
        "project_local_import_roots_enabled": True,
        "signature_adapter_enabled": True,
        "generic_strategy_callable_resolution_enabled": True,
        "canonical_source_mutations": 0,
        "isolated_replay_patch_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    material = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["receipt_sha256"] = hashlib.sha256(material).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "version": VERSION,
        "entry_owner_count": payload["entry_owner_count"],
        "filter_only": payload["filter_only"],
        "filter_only_replayed_as_entry_owner": False,
        "mapping": {
            key: {
                "kind": row["kind"],
                "actual_id": row["actual_id"],
                "owner_path": row["owner_path"],
                "callable_name": row.get("callable_name"),
                "resolver": row.get("resolver"),
            }
            for key, row in mapping.items()
        },
        "receipt_sha256": payload["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
