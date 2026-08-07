from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_REGISTRY_RESTORE_V4_CALLABLE_FIX"
V3_PATH = Path(__file__).with_name("zel_structural_premium_registry_restore_v3.py")
ENTRY_TARGETS = (
    "vwap_revert",
    "support_resistance",
    "liquidity_sweep",
    "trend_rider",
)
FILTER_ONLY = ("market_structure",)
SUPPORT_RESISTANCE_REGISTRY_ALIAS = "sr_levels"


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
_BASE_HARDENED_HELPER_SOURCE = V3.hardened_helper_source
_BASE_RESOLVE = V3.V2.resolve


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hardened_helper_source_with_registry_adapters(mapping: dict[str, dict[str, Any]]) -> str:
    """Extend V3's deterministic adapter to registry owners too.

    V3 adapted only source-discovered callables. Exact registry owners were returned raw,
    so replay called one-positional/keyword-only strategies as (current,state,risk_action)
    and every bar failed with TypeError. This wraps both registry and source owners onto
    the same replay contract without touching canonical strategy files.
    """
    text = _BASE_HARDENED_HELPER_SOURCE(mapping)
    old = '''        if row["kind"] == "registry":
            actual_id = row["actual_id"]
            if actual_id not in raw_registry:
                raise RuntimeError(f"RESTORE_ACTUAL_ID_MISSING:{logical_id}:{actual_id}")
            restored[logical_id] = raw_registry[actual_id]
            continue
'''
    new = '''        if row["kind"] == "registry":
            actual_id = row["actual_id"]
            if actual_id not in raw_registry:
                raise RuntimeError(f"RESTORE_ACTUAL_ID_MISSING:{logical_id}:{actual_id}")
            owner = raw_registry[actual_id]
            strategy = getattr(owner, "strategy", None)
            if not callable(strategy):
                raise RuntimeError(f"RESTORE_REGISTRY_STRATEGY_CALLABLE_MISSING:{logical_id}:{actual_id}")
            strategy = _adapt_strategy(strategy, logical_id)
            restored[logical_id] = _SimpleNamespace(
                strategy=strategy,
                owner_path=str(getattr(owner, "owner_path", row.get("owner_path", ""))),
                owner_sha256=str(getattr(owner, "owner_sha256", row.get("owner_sha256", ""))),
            )
            continue
'''
    if text.count(old) != 1:
        raise RuntimeError(f"V3_REGISTRY_ADAPTER_ANCHOR:{text.count(old)}")
    return text.replace(old, new)


def resolve_entry_owner_mapping(source_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Resolve entry owners, but forbid the non-trading support_resistance_v4 evaluator.

    The old heuristic selected backend/strategies_v4/support_resistance_v4.py:evaluate,
    whose contract is candidate evaluation rather than OHLCV entry generation. The actual
    support/resistance trading owner in the canonical 25-strategy registry is sr_levels.
    """
    mapping, available = _BASE_RESOLVE(source_root)
    producer_path = source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"
    producer = V3.V2.load_module(producer_path, "zel_structural_premium_v4_alias_producer")
    _, registry = producer.load_registry(source_root)
    if SUPPORT_RESISTANCE_REGISTRY_ALIAS not in registry:
        raise RuntimeError(f"SUPPORT_RESISTANCE_ALIAS_MISSING:{SUPPORT_RESISTANCE_REGISTRY_ALIAS}")
    owner = registry[SUPPORT_RESISTANCE_REGISTRY_ALIAS]
    owner_path = str(getattr(owner, "owner_path", ""))
    owner_sha = str(getattr(owner, "owner_sha256", ""))
    if not owner_path or not owner_sha:
        raise RuntimeError("SUPPORT_RESISTANCE_ALIAS_OWNER_METADATA_MISSING")
    mapping["support_resistance"] = {
        "kind": "registry",
        "actual_id": SUPPORT_RESISTANCE_REGISTRY_ALIAS,
        "owner_path": owner_path,
        "owner_sha256": owner_sha,
        "score": 20_000,
        "resolver": {"kind": "explicit_registry_alias", "alias": SUPPORT_RESISTANCE_REGISTRY_ALIAS},
    }
    return mapping, available


def patch_engines_entry_owners_only(engine_v1: Path, engine_v2: Path, mapping: dict[str, dict[str, Any]]) -> None:
    """Replay only the four actual entry-owner contracts; market_structure stays FILTER_ONLY."""
    if set(mapping) != set(ENTRY_TARGETS):
        raise RuntimeError(f"ENTRY_OWNER_MAPPING_SET:{sorted(mapping)}")
    if any(key in mapping for key in FILTER_ONLY):
        raise RuntimeError("FILTER_ONLY_PROMOTED_TO_ENTRY_OWNER")
    if mapping["support_resistance"].get("kind") != "registry" or mapping["support_resistance"].get("actual_id") != SUPPORT_RESISTANCE_REGISTRY_ALIAS:
        raise RuntimeError(f"SUPPORT_RESISTANCE_MAPPING_NOT_EXPLICIT:{mapping['support_resistance']}")

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
    V3.hardened_helper_source = hardened_helper_source_with_registry_adapters
    V3.install_hardening()
    V3.V2.resolve = resolve_entry_owner_mapping
    V3.V2.patch_engines = patch_engines_entry_owners_only


def self_test() -> None:
    # Preserve V3 import isolation/signature hardening, then prove the registry branch is adapted too.
    V3.self_test()
    helper = hardened_helper_source_with_registry_adapters({
        "vwap_revert": {"kind": "registry", "actual_id": "vwap_revert", "owner_path": "x.py", "owner_sha256": "x"},
        "support_resistance": {"kind": "registry", "actual_id": "sr_levels", "owner_path": "y.py", "owner_sha256": "y"},
        "liquidity_sweep": {"kind": "registry", "actual_id": "liquidity_sweep", "owner_path": "z.py", "owner_sha256": "z"},
        "trend_rider": {"kind": "registry", "actual_id": "trend_rider", "owner_path": "t.py", "owner_sha256": "t"},
    })
    assert "RESTORE_REGISTRY_STRATEGY_CALLABLE_MISSING" in helper
    assert "strategy = _adapt_strategy(strategy, logical_id)" in helper
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
        "registry_signature_adapter": True,
        "support_resistance_actual_id": SUPPORT_RESISTANCE_REGISTRY_ALIAS,
        "support_resistance_nontrading_evaluator_forbidden": True,
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
    if mapping["support_resistance"].get("actual_id") != SUPPORT_RESISTANCE_REGISTRY_ALIAS:
        raise RuntimeError(f"SUPPORT_RESISTANCE_ALIAS_NOT_BOUND:{mapping['support_resistance']}")

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
        "registry_signature_adapter": True,
        "support_resistance_actual_id": SUPPORT_RESISTANCE_REGISTRY_ALIAS,
        "support_resistance_nontrading_evaluator_forbidden": True,
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
        "registry_signature_adapter": True,
        "support_resistance_actual_id": payload["support_resistance_actual_id"],
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
