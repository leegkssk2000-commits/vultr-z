from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_REGISTRY_RESTORE_V3"
V2_PATH = Path(__file__).with_name("zel_structural_premium_registry_restore_v2.py")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_v2() -> Any:
    spec = importlib.util.spec_from_file_location("zel_structural_premium_registry_restore_v2_base", V2_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"V2_MODULE_SPEC_FAILED:{V2_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_v2()
TARGETS = tuple(V2.TARGETS)
_ORIGINAL_CALLABLE_NAME_SCORE = V2.callable_name_score

_DATA_NAMES = {
    "current", "frame", "df", "data", "candles", "ohlcv", "bars", "history", "market_data"
}
_STATE_NAMES = {
    "state", "ctx", "context", "position", "position_state", "strategy_state"
}
_RISK_NAMES = {
    "risk_action", "risk", "posture", "mode"
}
_GENERIC_STRATEGY_NAMES = {
    "strategy", "signal", "generate_signal", "build_signal", "get_signal", "evaluate_signal",
    "decide", "decision", "evaluate", "run_strategy", "entry_signal", "setup"
}


def _import_roots(path: Path) -> list[str]:
    roots: list[Path] = [path.parent]
    for parent in path.parents:
        if parent.name in {"backend", "strategies", "tools", "source"}:
            roots.extend([parent, parent.parent])
        if parent.name == "source":
            roots.extend([parent / "backend", parent / "strategies", parent / "tools"])
            break
    out: list[str] = []
    seen: set[str] = set()
    for root in roots:
        value = str(root)
        if root.exists() and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def safe_load_module(path: Path, name: str) -> Any:
    """Import a candidate module without inheriting CLI state and with project-local dependency roots available."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    old_argv = list(sys.argv)
    old_cwd = Path.cwd()
    old_env = dict(os.environ)
    old_sys_path = list(sys.path)
    sys.modules[name] = module
    try:
        roots = _import_roots(path)
        sys.path[:] = roots + [item for item in old_sys_path if item not in roots]
        os.chdir(path.parent)
        sys.argv = [str(path), "--help"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                spec.loader.exec_module(module)
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise RuntimeError(f"MODULE_ARGPARSE_EXIT:{path}:{exc.code}") from exc
    except BaseException:
        sys.modules.pop(name, None)
        raise
    finally:
        sys.argv = old_argv
        sys.path[:] = old_sys_path
        try:
            os.chdir(old_cwd)
        except OSError:
            pass
        os.environ.clear()
        os.environ.update(old_env)
    return module


def adaptation_plan(fn: Any) -> list[tuple[str, str, str]] | None:
    """Return a deterministic call plan mapping a legacy callable onto replay's (current,state,risk_action) contract."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    plan: list[tuple[str, str, str]] = []
    fallback = ["current", "state", "risk_action"]
    fallback_index = 0
    for param in signature.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        name = param.name.lower()
        source: str | None = None
        if name in _DATA_NAMES:
            source = "current"
        elif name in _STATE_NAMES:
            source = "state"
        elif name in _RISK_NAMES or name == "action":
            source = "risk_action"
        elif param.default is not param.empty:
            continue
        elif param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD) and fallback_index < len(fallback):
            source = fallback[fallback_index]
            fallback_index += 1
        else:
            return None
        mode = "pos" if param.kind is param.POSITIONAL_ONLY else "kw"
        plan.append((mode, param.name, source))
    return plan


def adaptable_shape(candidate: Any, registry: dict[str, Any]) -> bool:
    del registry
    return callable(candidate) and adaptation_plan(candidate) is not None


def hardened_callable_name_score(target: str, name: str, body: str) -> int:
    score = int(_ORIGINAL_CALLABLE_NAME_SCORE(target, name, body))
    if score:
        return score
    if name.lower() in _GENERIC_STRATEGY_NAMES and V2.text_score(target, name, body) >= 8_000:
        return 9_600
    return 0


def hardened_helper_source(mapping: dict[str, dict[str, Any]]) -> str:
    encoded = json.dumps(mapping, sort_keys=True)
    data_names = sorted(_DATA_NAMES)
    state_names = sorted(_STATE_NAMES)
    risk_names = sorted(_RISK_NAMES | {"action"})
    return f'''\n\ndef _restore_structural_premium_registry(source_root, raw_registry):\n    import contextlib as _contextlib\n    import hashlib as _hashlib\n    import importlib.util as _importlib_util\n    import inspect as _inspect\n    import io as _io\n    import json as _json\n    import os as _os\n    import sys as _sys\n    from pathlib import Path as _Path\n    from types import SimpleNamespace as _SimpleNamespace\n    mapping = _json.loads({encoded!r})\n    data_names = set({_json_literal(data_names)})\n    state_names = set({_json_literal(state_names)})\n    risk_names = set({_json_literal(risk_names)})\n\n    def _adapt_strategy(fn, logical_id):\n        try:\n            signature = _inspect.signature(fn)\n        except (TypeError, ValueError) as exc:\n            raise RuntimeError(f"RESTORE_SIGNATURE_UNAVAILABLE:{{logical_id}}") from exc\n        spec_rows = []\n        fallback = ["current", "state", "risk_action"]\n        fallback_index = 0\n        for param in signature.parameters.values():\n            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):\n                continue\n            name = param.name.lower()\n            source = None\n            if name in data_names:\n                source = "current"\n            elif name in state_names:\n                source = "state"\n            elif name in risk_names:\n                source = "risk_action"\n            elif param.default is not param.empty:\n                continue\n            elif param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD) and fallback_index < len(fallback):\n                source = fallback[fallback_index]\n                fallback_index += 1\n            else:\n                raise RuntimeError(f"RESTORE_UNADAPTABLE_PARAMETER:{{logical_id}}:{{param.name}}")\n            mode = "pos" if param.kind is param.POSITIONAL_ONLY else "kw"\n            spec_rows.append((mode, param.name, source))\n\n        def wrapped(current, state=None, risk_action="hold"):\n            values = {{"current": current, "state": state, "risk_action": risk_action}}\n            args = []\n            kwargs = {{}}\n            for mode, name, source in spec_rows:\n                if mode == "pos":\n                    args.append(values[source])\n                else:\n                    kwargs[name] = values[source]\n            return fn(*args, **kwargs)\n\n        wrapped.__name__ = getattr(fn, "__name__", f"adapted_{{logical_id}}")\n        return wrapped\n\n    restored = {{}}\n    for logical_id, row in mapping.items():\n        if row["kind"] == "registry":\n            actual_id = row["actual_id"]\n            if actual_id not in raw_registry:\n                raise RuntimeError(f"RESTORE_ACTUAL_ID_MISSING:{{logical_id}}:{{actual_id}}")\n            restored[logical_id] = raw_registry[actual_id]\n            continue\n        path = _Path(source_root) / row["owner_path"]\n        if not path.is_file():\n            raise RuntimeError(f"RESTORE_SOURCE_FILE_MISSING:{{logical_id}}:{{path}}")\n        digest = _hashlib.sha256(path.read_bytes()).hexdigest()\n        if digest != row["owner_sha256"]:\n            raise RuntimeError(f"RESTORE_SOURCE_SHA_MISMATCH:{{logical_id}}")\n        name = f"zel_structural_restored_v3_{{logical_id}}_{{digest[:12]}}"\n        spec = _importlib_util.spec_from_file_location(name, path)\n        if spec is None or spec.loader is None:\n            raise RuntimeError(f"RESTORE_IMPORT_SPEC_FAILED:{{logical_id}}")\n        module = _importlib_util.module_from_spec(spec)\n        old_argv = list(_sys.argv)\n        old_cwd = _Path.cwd()\n        old_env = dict(_os.environ)\n        old_sys_path = list(_sys.path)\n        roots = [path.parent]\n        for parent in path.parents:\n            if parent.name in {{"backend", "strategies", "tools", "source"}}:\n                roots.extend([parent, parent.parent])\n            if parent.name == "source":\n                roots.extend([parent / "backend", parent / "strategies", parent / "tools"])\n                break\n        root_strings = []\n        for root in roots:\n            value = str(root)\n            if root.exists() and value not in root_strings:\n                root_strings.append(value)\n        _sys.modules[name] = module\n        try:\n            _sys.path[:] = root_strings + [item for item in old_sys_path if item not in root_strings]\n            _os.chdir(path.parent)\n            _sys.argv = [str(path), "--help"]\n            with _contextlib.redirect_stdout(_io.StringIO()), _contextlib.redirect_stderr(_io.StringIO()):\n                try:\n                    spec.loader.exec_module(module)\n                except SystemExit as exc:\n                    if exc.code not in (0, None):\n                        raise RuntimeError(f"RESTORE_IMPORT_ARGPARSE_EXIT:{{logical_id}}:{{exc.code}}") from exc\n        except BaseException:\n            _sys.modules.pop(name, None)\n            raise\n        finally:\n            _sys.argv = old_argv\n            _sys.path[:] = old_sys_path\n            try:\n                _os.chdir(old_cwd)\n            except OSError:\n                pass\n            _os.environ.clear()\n            _os.environ.update(old_env)\n        resolver = row["resolver"]\n        kind = resolver["kind"]\n        if kind == "module_attr":\n            strategy = getattr(module, resolver["attr"], None)\n        elif kind == "dict_item_callable":\n            strategy = getattr(module, resolver["attr"])[resolver["key"]]\n        elif kind == "dict_item_owner_strategy":\n            strategy = getattr(getattr(module, resolver["attr"])[resolver["key"]], "strategy", None)\n        elif kind == "object_attr_strategy":\n            strategy = getattr(getattr(module, resolver["attr"]), "strategy", None)\n        else:\n            raise RuntimeError(f"RESTORE_RESOLVER_KIND_UNKNOWN:{{logical_id}}:{{kind}}")\n        if not callable(strategy):\n            raise RuntimeError(f"RESTORE_STRATEGY_CALLABLE_MISSING:{{logical_id}}:{{resolver}}")\n        strategy = _adapt_strategy(strategy, logical_id)\n        restored[logical_id] = _SimpleNamespace(strategy=strategy, owner_path=row["owner_path"], owner_sha256=digest)\n    if sorted(restored) != sorted({list(TARGETS)!r}):\n        raise RuntimeError(f"RESTORE_LOGICAL_SET_MISMATCH:{{sorted(restored)}}")\n    return restored\n'''


def _json_literal(value: Any) -> str:
    return repr(json.dumps(value, separators=(",", ":")))


def install_hardening() -> None:
    V2.load_module = safe_load_module
    V2.compatible_shape = adaptable_shape
    V2.callable_name_score = hardened_callable_name_score
    V2.helper_source = hardened_helper_source


def self_test() -> None:
    install_hardening()
    V2.self_test()
    before_argv = list(sys.argv)
    before_env = dict(os.environ)
    before_cwd = Path.cwd()
    before_sys_path = list(sys.path)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sibling_dep.py").write_text("VALUE = 7\n", encoding="utf-8")
        p = root / "argparse_side_effect.py"
        p.write_text(
            "import argparse, os\n"
            "from sibling_dep import VALUE\n"
            "def generate_signal(df, context=None):\n"
            "    return {'action':'hold','value':VALUE}\n"
            "parser=argparse.ArgumentParser()\n"
            "parser.add_argument('--sandbox', action='store_true')\n"
            "args=parser.parse_args()\n"
            "os.environ['ZEL_IMPORT_SIDE_EFFECT_SHOULD_NOT_PERSIST']='1'\n",
            encoding="utf-8",
        )
        module = safe_load_module(p, "zel_v3_self_test_side_effect")
        fn = getattr(module, "generate_signal")
        assert adaptation_plan(fn) is not None
        assert adaptable_shape(fn, {}) is True
        assert fn(None, None)["value"] == 7
        assert hardened_callable_name_score("support_resistance", "generate_signal", "support resistance strategy") >= 9_000
    assert sys.argv == before_argv
    assert dict(os.environ) == before_env
    assert Path.cwd() == before_cwd
    assert sys.path == before_sys_path
    print(json.dumps({
        "state": "PASS_SELF_TEST",
        "version": VERSION,
        "argv_isolation": True,
        "env_isolation": True,
        "cwd_isolation": True,
        "sys_path_isolation": True,
        "sibling_import_resolution": True,
        "signature_adapter": True,
        "generic_strategy_callable_resolution": True,
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

    install_hardening()
    mapping, available = V2.resolve(args.source_root.resolve())
    V2.patch_engines(args.engine_v1.resolve(), args.engine_v2.resolve(), mapping)
    payload = {
        "schema_version": "zel.structural_premium.registry_restore.v3",
        "state": "PASS_STRUCTURAL_PREMIUM_REGISTRY_COVERAGE_RESTORED",
        "version": VERSION,
        "targets": list(TARGETS),
        "mapping": mapping,
        "available_registry_ids": available,
        "restored_count": len(mapping),
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
