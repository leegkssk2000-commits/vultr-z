from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_REGISTRY_RESTORE_V1"
TARGETS = (
    "vwap_revert",
    "support_resistance",
    "liquidity_sweep",
    "trend_rider",
    "market_structure",
)
ALIASES = {
    "vwap_revert": (("vwap", "revert"), ("vwap", "reversion"), ("vwap", "mean", "reversion")),
    "support_resistance": (("support", "resistance"), ("support", "retest"), ("resistance", "retest"), ("sr", "retest")),
    "liquidity_sweep": (("liquidity", "sweep"), ("sweep", "reversal"), ("stop", "hunt")),
    "trend_rider": (("trend", "rider"), ("trend", "following"), ("trend", "follow")),
    "market_structure": (("market", "structure"), ("structure", "break"), ("break", "structure"), ("bos", "choch")),
}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def owner_text(source_root: Path, key: str, owner: Any) -> str:
    fields = [key]
    for attr in ("owner_path", "strategy_id", "name", "owner_sha256"):
        value = getattr(owner, attr, None)
        if value:
            fields.append(str(value))
    strategy = getattr(owner, "strategy", None)
    if strategy is not None:
        fields.extend([getattr(strategy, "__name__", ""), getattr(strategy, "__module__", "")])
    owner_path = getattr(owner, "owner_path", None)
    if owner_path:
        path = source_root / str(owner_path)
        if path.is_file() and path.stat().st_size <= 2_000_000:
            try:
                fields.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
    return "\n".join(fields)


def score(target: str, candidate_id: str, text: str) -> int:
    target_norm = normalize(target)
    candidate_norm = normalize(candidate_id)
    text_norm = normalize(text)
    if candidate_id == target:
        return 10_000
    if candidate_norm == target_norm:
        return 9_500
    if target_norm and target_norm in text_norm:
        return 9_000
    text_tokens = tokens(text)
    best = 0
    for group in ALIASES[target]:
        if all(token in text_tokens or normalize(token) in text_norm for token in group):
            best = max(best, 8_000 + 10 * len(group))
    target_tokens = set(target.split("_"))
    overlap = len(target_tokens & text_tokens)
    if overlap:
        best = max(best, int(1_000 * overlap / len(target_tokens)))
    return best


def scan_source_candidates(source_root: Path, target: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    roots = [source_root / "backend", source_root / "strategies", source_root / "tools"]
    seen: set[Path] = set()
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path in seen or not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "def strategy" not in text and "strategy =" not in text:
                continue
            relative = path.relative_to(source_root).as_posix()
            value = score(target, relative, relative + "\n" + text)
            if value >= 8_000:
                rows.append({"path": relative, "score": value})
    rows.sort(key=lambda row: (-int(row["score"]), str(row["path"])))
    return rows


def resolve(source_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    producer_path = source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"
    if not producer_path.is_file():
        raise RuntimeError(f"PRODUCER_MISSING:{producer_path}")
    producer = load_module(producer_path, "zel_structural_premium_restore_producer")
    _, registry = producer.load_registry(source_root)
    if not isinstance(registry, dict):
        raise RuntimeError("REGISTRY_NOT_DICT")

    available = sorted(str(key) for key in registry)
    resolved: dict[str, dict[str, Any]] = {}
    used_actual: set[str] = set()
    used_paths: set[str] = set()

    for target in TARGETS:
        if target in registry and target not in used_actual:
            owner = registry[target]
            resolved[target] = {
                "kind": "registry",
                "actual_id": target,
                "owner_path": str(getattr(owner, "owner_path", "")),
                "owner_sha256": str(getattr(owner, "owner_sha256", "")),
                "score": 10_000,
            }
            used_actual.add(target)
            continue

        candidates: list[tuple[int, str, Any]] = []
        for key, owner in registry.items():
            actual = str(key)
            if actual in used_actual:
                continue
            value = score(target, actual, owner_text(source_root, actual, owner))
            if value >= 8_000:
                candidates.append((value, actual, owner))
        candidates.sort(key=lambda row: (-row[0], row[1]))
        if candidates:
            top = candidates[0]
            second = candidates[1][0] if len(candidates) > 1 else -1
            if top[0] >= 8_000 and top[0] - second >= 50:
                owner = top[2]
                resolved[target] = {
                    "kind": "registry",
                    "actual_id": top[1],
                    "owner_path": str(getattr(owner, "owner_path", "")),
                    "owner_sha256": str(getattr(owner, "owner_sha256", "")),
                    "score": top[0],
                }
                used_actual.add(top[1])
                continue

        file_candidates = [row for row in scan_source_candidates(source_root, target) if row["path"] not in used_paths]
        if not file_candidates:
            raise RuntimeError(f"TARGET_SOURCE_NOT_FOUND:{target}:AVAILABLE={available}")
        top_file = file_candidates[0]
        second_score = int(file_candidates[1]["score"]) if len(file_candidates) > 1 else -1
        if int(top_file["score"]) - second_score < 50:
            raise RuntimeError(f"TARGET_SOURCE_AMBIGUOUS:{target}:{file_candidates[:5]}")
        path = source_root / str(top_file["path"])
        module = load_module(path, f"zel_structural_restore_probe_{normalize(target)}")
        strategy = getattr(module, "strategy", None)
        if not callable(strategy):
            raise RuntimeError(f"TARGET_STRATEGY_CALLABLE_MISSING:{target}:{path}")
        resolved[target] = {
            "kind": "source_file",
            "actual_id": target,
            "owner_path": str(top_file["path"]),
            "owner_sha256": sha256_path(path),
            "score": int(top_file["score"]),
        }
        used_paths.add(str(top_file["path"]))

    if len(resolved) != len(TARGETS):
        raise RuntimeError(f"RESOLUTION_COUNT:{len(resolved)}")
    return resolved, available


def helper_source(mapping: dict[str, dict[str, Any]]) -> str:
    encoded = json.dumps(mapping, sort_keys=True)
    return f'''\n\ndef _restore_structural_premium_registry(source_root, raw_registry):\n    import hashlib as _hashlib\n    import importlib.util as _importlib_util\n    import json as _json\n    import sys as _sys\n    from pathlib import Path as _Path\n    from types import SimpleNamespace as _SimpleNamespace\n    mapping = _json.loads({encoded!r})\n    restored = {{}}\n    for logical_id, row in mapping.items():\n        if row["kind"] == "registry":\n            actual_id = row["actual_id"]\n            if actual_id not in raw_registry:\n                raise RuntimeError(f"RESTORE_ACTUAL_ID_MISSING:{{logical_id}}:{{actual_id}}")\n            restored[logical_id] = raw_registry[actual_id]\n            continue\n        path = _Path(source_root) / row["owner_path"]\n        if not path.is_file():\n            raise RuntimeError(f"RESTORE_SOURCE_FILE_MISSING:{{logical_id}}:{{path}}")\n        digest = _hashlib.sha256(path.read_bytes()).hexdigest()\n        if digest != row["owner_sha256"]:\n            raise RuntimeError(f"RESTORE_SOURCE_SHA_MISMATCH:{{logical_id}}")\n        name = f"zel_structural_restored_{{logical_id}}_{{digest[:12]}}"\n        spec = _importlib_util.spec_from_file_location(name, path)\n        if spec is None or spec.loader is None:\n            raise RuntimeError(f"RESTORE_IMPORT_SPEC_FAILED:{{logical_id}}")\n        module = _importlib_util.module_from_spec(spec)\n        _sys.modules[name] = module\n        spec.loader.exec_module(module)\n        strategy = getattr(module, "strategy", None)\n        if not callable(strategy):\n            raise RuntimeError(f"RESTORE_STRATEGY_CALLABLE_MISSING:{{logical_id}}")\n        restored[logical_id] = _SimpleNamespace(\n            strategy=strategy, owner_path=row["owner_path"], owner_sha256=digest\n        )\n    if sorted(restored) != sorted({list(TARGETS)!r}):\n        raise RuntimeError(f"RESTORE_LOGICAL_SET_MISMATCH:{{sorted(restored)}}")\n    return restored\n'''


def patch_engines(engine_v1: Path, engine_v2: Path, mapping: dict[str, dict[str, Any]]) -> None:
    helper = helper_source(mapping)
    text1 = engine_v1.read_text(encoding="utf-8")
    if text1.count("EXPECTED_STRATEGY_COUNT = 25") != 1:
        raise RuntimeError("V1_EXPECTED_STRATEGY_COUNT_ANCHOR")
    if text1.count("EXPECTED_DATA_ROWS = 302_400") != 1:
        raise RuntimeError("V1_EXPECTED_DATA_ROWS_ANCHOR")
    text1 = text1.replace("EXPECTED_STRATEGY_COUNT = 25", "EXPECTED_STRATEGY_COUNT = 5")
    text1 = text1.replace("EXPECTED_DATA_ROWS = 302_400", "EXPECTED_DATA_ROWS = 960_150")
    anchor1 = "def init_worker(source_root: str, data_root: str, interval: str) -> None:\n"
    if text1.count(anchor1) != 1:
        raise RuntimeError("V1_INIT_WORKER_ANCHOR")
    text1 = text1.replace(anchor1, helper + "\n" + anchor1)
    old1 = "    _, _WORKER_REGISTRY = _WORKER_PRODUCER.load_registry(_WORKER_SOURCE_ROOT)\n    if len(_WORKER_REGISTRY) != EXPECTED_STRATEGY_COUNT:"
    new1 = "    _, _WORKER_REGISTRY = _WORKER_PRODUCER.load_registry(_WORKER_SOURCE_ROOT)\n    _WORKER_REGISTRY = _restore_structural_premium_registry(_WORKER_SOURCE_ROOT, _WORKER_REGISTRY)\n    if len(_WORKER_REGISTRY) != EXPECTED_STRATEGY_COUNT:"
    if text1.count(old1) != 1:
        raise RuntimeError("V1_REGISTRY_ANCHOR")
    engine_v1.write_text(text1.replace(old1, new1), encoding="utf-8")

    text2 = engine_v2.read_text(encoding="utf-8")
    if text2.count("EXPECTED_STRATEGY_COUNT = 25") != 1:
        raise RuntimeError("V2_EXPECTED_STRATEGY_COUNT_ANCHOR")
    text2 = text2.replace("EXPECTED_STRATEGY_COUNT = 25", "EXPECTED_STRATEGY_COUNT = 5")
    old2 = "    _, registry = producer.load_registry(source_root)\n    if len(registry) != EXPECTED_STRATEGY_COUNT:"
    new2 = "    _, registry = producer.load_registry(source_root)\n    registry = engine._restore_structural_premium_registry(source_root, registry)\n    if len(registry) != EXPECTED_STRATEGY_COUNT:"
    if text2.count(old2) != 1:
        raise RuntimeError("V2_REGISTRY_ANCHOR")
    engine_v2.write_text(text2.replace(old2, new2), encoding="utf-8")


def self_test() -> None:
    text = "support resistance retest strategy"
    assert score("support_resistance", "sr_retest_long", text) >= 8_000
    assert score("market_structure", "bos_choch_filter", "market structure BOS CHOCH") >= 8_000
    assert score("vwap_revert", "vwap_reversion_long", "vwap mean reversion") >= 8_000
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


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
    mapping, available = resolve(args.source_root.resolve())
    patch_engines(args.engine_v1.resolve(), args.engine_v2.resolve(), mapping)
    payload = {
        "schema_version": "zel.structural_premium.registry_restore.v1",
        "state": "PASS_STRUCTURAL_PREMIUM_REGISTRY_COVERAGE_RESTORED",
        "version": VERSION,
        "targets": list(TARGETS),
        "mapping": mapping,
        "available_registry_ids": available,
        "restored_count": len(mapping),
        "engine_v1_sha256": sha256_path(args.engine_v1),
        "engine_v2_sha256": sha256_path(args.engine_v2),
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
        "mapping": {key: {"kind": row["kind"], "actual_id": row["actual_id"], "owner_path": row["owner_path"]} for key, row in mapping.items()},
        "receipt_sha256": payload["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
