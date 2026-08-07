from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_REGISTRY_RESTORE_V2"
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


def text_score(target: str, candidate_id: str, text: str) -> int:
    target_norm = normalize(target)
    candidate_norm = normalize(candidate_id)
    text_norm = normalize(text)
    if candidate_id == target:
        return 10_000
    if candidate_norm == target_norm:
        return 9_800
    if target_norm and target_norm in text_norm:
        return 9_200
    text_tokens = tokens(text)
    best = 0
    for group in ALIASES[target]:
        if all(token in text_tokens or normalize(token) in text_norm for token in group):
            best = max(best, 8_200 + 10 * len(group))
    target_tokens = set(target.split("_"))
    overlap = len(target_tokens & text_tokens)
    if overlap:
        best = max(best, int(1_000 * overlap / len(target_tokens)))
    return best


def signature_shape(fn: Any) -> tuple[int, int | None, bool] | None:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    required = 0
    positional = 0
    variadic = False
    for param in sig.parameters.values():
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            positional += 1
            if param.default is param.empty:
                required += 1
        elif param.kind is param.VAR_POSITIONAL:
            variadic = True
    return required, None if variadic else positional, variadic


def compatible_shape(candidate: Any, registry: dict[str, Any]) -> bool:
    candidate_shape = signature_shape(candidate)
    if candidate_shape is None:
        return False
    shapes: set[tuple[int, int | None, bool]] = set()
    for owner in registry.values():
        fn = getattr(owner, "strategy", None)
        if callable(fn):
            shape = signature_shape(fn)
            if shape is not None:
                shapes.add(shape)
    if not shapes:
        return True
    cr, cm, cv = candidate_shape
    for required, maximum, variadic in shapes:
        if cr != required:
            continue
        if cv or variadic:
            return True
        if cm == maximum:
            return True
    return False


def callable_name_score(target: str, name: str, body: str) -> int:
    target_norm = normalize(target)
    name_norm = normalize(name)
    if name == target:
        return 12_000
    if name_norm == target_norm:
        return 11_900
    if target_norm and target_norm in name_norm:
        return 11_500
    name_tokens = tokens(name)
    best = 0
    for group in ALIASES[target]:
        if all(token in name_tokens or normalize(token) in name_norm for token in group):
            best = max(best, 10_500 + 10 * len(group))
    if name == "strategy" and text_score(target, name, body) >= 8_000:
        best = max(best, 9_300)
    if name.startswith("strategy") and text_score(target, name, body) >= 8_000:
        best = max(best, 9_000)
    return best


def module_callable_candidates(module: Any, target: str, text: str, registry: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    module_name = getattr(module, "__name__", "")

    exact = getattr(module, target, None)
    if callable(exact) and compatible_shape(exact, registry):
        rows.append({"score": 13_000, "resolver": {"kind": "module_attr", "attr": target}, "callable": exact})

    for attr_name, value in vars(module).items():
        if isinstance(value, dict) and target in value:
            item = value[target]
            if callable(item) and compatible_shape(item, registry):
                rows.append({
                    "score": 12_900,
                    "resolver": {"kind": "dict_item_callable", "attr": attr_name, "key": target},
                    "callable": item,
                })
            item_strategy = getattr(item, "strategy", None)
            if callable(item_strategy) and compatible_shape(item_strategy, registry):
                rows.append({
                    "score": 12_850,
                    "resolver": {"kind": "dict_item_owner_strategy", "attr": attr_name, "key": target},
                    "callable": item_strategy,
                })

        strategy_id = getattr(value, "strategy_id", None)
        object_name = getattr(value, "name", None)
        item_strategy = getattr(value, "strategy", None)
        if (strategy_id == target or object_name == target) and callable(item_strategy) and compatible_shape(item_strategy, registry):
            rows.append({
                "score": 12_800,
                "resolver": {"kind": "object_attr_strategy", "attr": attr_name},
                "callable": item_strategy,
            })

    declared_ids = {
        getattr(module, "STRATEGY_ID", None),
        getattr(module, "strategy_id", None),
        getattr(module, "NAME", None),
        getattr(module, "name", None),
    }
    generic = getattr(module, "strategy", None)
    if target in declared_ids and callable(generic) and compatible_shape(generic, registry):
        rows.append({"score": 12_700, "resolver": {"kind": "module_attr", "attr": "strategy"}, "callable": generic})

    for attr_name, value in vars(module).items():
        if not inspect.isfunction(value):
            continue
        if getattr(value, "__module__", None) != module_name:
            continue
        if attr_name.startswith("_") or not compatible_shape(value, registry):
            continue
        try:
            source = inspect.getsource(value)
        except (OSError, TypeError):
            source = ""
        score = callable_name_score(target, attr_name, text + "\n" + source)
        if score >= 9_000:
            rows.append({
                "score": score,
                "resolver": {"kind": "module_attr", "attr": attr_name},
                "callable": value,
            })

    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = json.dumps(row["resolver"], sort_keys=True)
        if key not in dedup or int(row["score"]) > int(dedup[key]["score"]):
            dedup[key] = row
    return sorted(dedup.values(), key=lambda row: (-int(row["score"]), json.dumps(row["resolver"], sort_keys=True)))


def resolve_source_callable(source_root: Path, target: str, registry: dict[str, Any], used_paths: set[str]) -> dict[str, Any]:
    roots = [source_root / "backend", source_root / "strategies", source_root / "tools"]
    file_rows: list[tuple[int, str, Path, str]] = []
    seen: set[Path] = set()
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path in seen or not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            seen.add(path)
            relative = path.relative_to(source_root).as_posix()
            if relative in used_paths:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            value = text_score(target, relative, relative + "\n" + text)
            if value >= 8_000:
                file_rows.append((value, relative, path, text))
    file_rows.sort(key=lambda row: (-row[0], row[1]))

    candidates: list[dict[str, Any]] = []
    import_errors: list[str] = []
    for file_score, relative, path, text in file_rows[:40]:
        try:
            module = load_module(path, f"zel_structural_restore_v2_{normalize(target)}_{hashlib.sha256(relative.encode()).hexdigest()[:10]}")
        except Exception as exc:
            import_errors.append(f"{relative}:{type(exc).__name__}")
            continue
        for row in module_callable_candidates(module, target, text, registry):
            combined = int(row["score"]) * 100 + int(file_score)
            candidates.append({
                "combined_score": combined,
                "path": relative,
                "resolver": row["resolver"],
                "callable_name": getattr(row["callable"], "__name__", ""),
                "owner_sha256": sha256_path(path),
            })

    candidates.sort(key=lambda row: (-int(row["combined_score"]), str(row["path"]), json.dumps(row["resolver"], sort_keys=True)))
    if not candidates:
        raise RuntimeError(
            f"TARGET_COMPATIBLE_CALLABLE_NOT_FOUND:{target}:FILES={[row[1] for row in file_rows[:10]]}:IMPORT_ERRORS={import_errors[:10]}"
        )
    top = candidates[0]
    second = int(candidates[1]["combined_score"]) if len(candidates) > 1 else -1
    if int(top["combined_score"]) - second < 50:
        raise RuntimeError(f"TARGET_CALLABLE_AMBIGUOUS:{target}:{candidates[:5]}")
    return {
        "kind": "source_callable",
        "actual_id": target,
        "owner_path": top["path"],
        "owner_sha256": top["owner_sha256"],
        "callable_name": top["callable_name"],
        "resolver": top["resolver"],
        "score": int(top["combined_score"]),
    }


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


def resolve(source_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    producer_path = source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"
    if not producer_path.is_file():
        raise RuntimeError(f"PRODUCER_MISSING:{producer_path}")
    producer = load_module(producer_path, "zel_structural_premium_restore_v2_producer")
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

        registry_candidates: list[tuple[int, str, Any]] = []
        for key, owner in registry.items():
            actual = str(key)
            if actual in used_actual:
                continue
            value = text_score(target, actual, owner_text(source_root, actual, owner))
            if value >= 8_000:
                registry_candidates.append((value, actual, owner))
        registry_candidates.sort(key=lambda row: (-row[0], row[1]))
        if registry_candidates:
            top = registry_candidates[0]
            second = registry_candidates[1][0] if len(registry_candidates) > 1 else -1
            if top[0] - second >= 50:
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

        source_row = resolve_source_callable(source_root, target, registry, used_paths)
        resolved[target] = source_row
        used_paths.add(str(source_row["owner_path"]))

    if len(resolved) != len(TARGETS):
        raise RuntimeError(f"RESOLUTION_COUNT:{len(resolved)}")
    return resolved, available


def helper_source(mapping: dict[str, dict[str, Any]]) -> str:
    encoded = json.dumps(mapping, sort_keys=True)
    return f'''\n\ndef _restore_structural_premium_registry(source_root, raw_registry):\n    import hashlib as _hashlib\n    import importlib.util as _importlib_util\n    import json as _json\n    import sys as _sys\n    from pathlib import Path as _Path\n    from types import SimpleNamespace as _SimpleNamespace\n    mapping = _json.loads({encoded!r})\n    restored = {{}}\n    for logical_id, row in mapping.items():\n        if row["kind"] == "registry":\n            actual_id = row["actual_id"]\n            if actual_id not in raw_registry:\n                raise RuntimeError(f"RESTORE_ACTUAL_ID_MISSING:{{logical_id}}:{{actual_id}}")\n            restored[logical_id] = raw_registry[actual_id]\n            continue\n        path = _Path(source_root) / row["owner_path"]\n        if not path.is_file():\n            raise RuntimeError(f"RESTORE_SOURCE_FILE_MISSING:{{logical_id}}:{{path}}")\n        digest = _hashlib.sha256(path.read_bytes()).hexdigest()\n        if digest != row["owner_sha256"]:\n            raise RuntimeError(f"RESTORE_SOURCE_SHA_MISMATCH:{{logical_id}}")\n        name = f"zel_structural_restored_v2_{{logical_id}}_{{digest[:12]}}"\n        spec = _importlib_util.spec_from_file_location(name, path)\n        if spec is None or spec.loader is None:\n            raise RuntimeError(f"RESTORE_IMPORT_SPEC_FAILED:{{logical_id}}")\n        module = _importlib_util.module_from_spec(spec)\n        _sys.modules[name] = module\n        spec.loader.exec_module(module)\n        resolver = row["resolver"]\n        kind = resolver["kind"]\n        if kind == "module_attr":\n            strategy = getattr(module, resolver["attr"], None)\n        elif kind == "dict_item_callable":\n            strategy = getattr(module, resolver["attr"])[resolver["key"]]\n        elif kind == "dict_item_owner_strategy":\n            strategy = getattr(getattr(module, resolver["attr"])[resolver["key"]], "strategy", None)\n        elif kind == "object_attr_strategy":\n            strategy = getattr(getattr(module, resolver["attr"]), "strategy", None)\n        else:\n            raise RuntimeError(f"RESTORE_RESOLVER_KIND_UNKNOWN:{{logical_id}}:{{kind}}")\n        if not callable(strategy):\n            raise RuntimeError(f"RESTORE_STRATEGY_CALLABLE_MISSING:{{logical_id}}:{{resolver}}")\n        restored[logical_id] = _SimpleNamespace(strategy=strategy, owner_path=row["owner_path"], owner_sha256=digest)\n    if sorted(restored) != sorted({list(TARGETS)!r}):\n        raise RuntimeError(f"RESTORE_LOGICAL_SET_MISMATCH:{{sorted(restored)}}")\n    return restored\n'''


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
    def support_resistance(frame: Any, state: Any) -> None:
        return None

    class Owner:
        strategy_id = "support_resistance"
        strategy = staticmethod(support_resistance)

    fake = type("Fake", (), {})()
    fake.__name__ = "fake_module"
    support_resistance.__module__ = "fake_module"
    fake.SR_OWNER = Owner()
    base_registry = {"x": type("Base", (), {"strategy": staticmethod(lambda frame, state: None)})()}
    rows = module_callable_candidates(fake, "support_resistance", "support resistance", base_registry)
    assert rows and rows[0]["score"] >= 12_000
    assert text_score("market_structure", "bos_choch_filter", "market structure BOS CHOCH") >= 8_000
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
        "schema_version": "zel.structural_premium.registry_restore.v2",
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
