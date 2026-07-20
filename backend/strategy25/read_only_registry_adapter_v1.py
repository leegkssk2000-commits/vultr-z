from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


class RegistryContractError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Strategy25Descriptor:
    strategy_id: str
    implementation_path: str
    callable_name: str
    source_sha256: str
    config_ref: str
    config: Mapping[str, Any]
    active_allowed: bool
    fail_closed: bool

    def router_view(self) -> Mapping[str, Any]:
        return MappingProxyType({
            "strategy_id": self.strategy_id,
            "implementation_path": self.implementation_path,
            "callable": self.callable_name,
            "source_sha256": self.source_sha256,
            "config_ref": self.config_ref,
            "config": self.config,
            "read_only": True,
            "route_allowed": False,
            "execution_allowed": False,
            "active_allowed": False,
            "fail_closed": True,
            "decision": "hold",
            "reason": "R7_A3E4_REGISTRY_INACTIVE_FAIL_CLOSED",
        })


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RegistryContractError(f"JSON_READ_FAILED:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise RegistryContractError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise RegistryContractError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RegistryContractError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def _split_config_ref(value: str) -> tuple[str, str]:
    if "#" not in value:
        raise RegistryContractError(f"CONFIG_REF_INVALID:{value}")
    path, pointer = value.split("#", 1)
    if not pointer.startswith("/"):
        raise RegistryContractError(f"CONFIG_POINTER_INVALID:{value}")
    return _safe_repo_path(path), pointer


def _json_pointer(value: Any, pointer: str) -> Any:
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise RegistryContractError(f"CONFIG_POINTER_UNRESOLVED:{pointer}")
    return current


def _callable_names(source: str, filename: str) -> set[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise RegistryContractError(f"SOURCE_SYNTAX_INVALID:{filename}:{exc}") from exc
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}.{child.name}")
    return names


class ReadOnlyStrategy25RegistryAdapter:
    """Fail-closed metadata adapter. It never imports or executes strategy modules."""

    def __init__(self, root: str | Path, registry_path: str = "backend/strategy25/canonical_strategy_registry_v1.json", expected_count: int = 25) -> None:
        self._root = Path(root).resolve()
        self._registry_repo_path = _safe_repo_path(registry_path)
        self._expected_count = expected_count
        self._descriptors = self._load()

    def _load(self) -> Mapping[str, Strategy25Descriptor]:
        registry = _load_json(self._root / self._registry_repo_path)
        if registry.get("schema") != "canonical_strategy25_registry_v1":
            raise RegistryContractError("REGISTRY_SCHEMA_INVALID")
        if registry.get("fail_closed") is not True or int(registry.get("active_entry_count", -1)) != 0:
            raise RegistryContractError("REGISTRY_AUTHORITY_INVALID")
        entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
        if len(entries) != self._expected_count:
            raise RegistryContractError(f"REGISTRY_COUNT_INVALID:{len(entries)}")

        result: dict[str, Strategy25Descriptor] = {}
        for row in entries:
            strategy_id = str(row.get("strategy_id") or "")
            if not strategy_id or strategy_id in result:
                raise RegistryContractError(f"STRATEGY_ID_INVALID_OR_DUPLICATE:{strategy_id}")
            if row.get("active_allowed") is not False or row.get("fail_closed") is not True:
                raise RegistryContractError(f"ENTRY_AUTHORITY_INVALID:{strategy_id}")
            engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
            implementation_path = _safe_repo_path(str(engine.get("implementation_path") or ""))
            if not implementation_path.startswith("backend/strategies/"):
                raise RegistryContractError(f"SOURCE_PREFIX_INVALID:{strategy_id}:{implementation_path}")
            callable_name = str(engine.get("callable") or "")
            expected_sha = str(engine.get("source_sha256") or "")
            source_path = self._root / implementation_path
            if not source_path.is_file() or source_path.is_symlink():
                raise RegistryContractError(f"SOURCE_FILE_INVALID:{strategy_id}:{implementation_path}")
            source_bytes = source_path.read_bytes()
            actual_sha = hashlib.sha256(source_bytes).hexdigest()
            if not expected_sha or actual_sha != expected_sha:
                raise RegistryContractError(f"SOURCE_SHA_MISMATCH:{strategy_id}")
            if callable_name not in _callable_names(source_bytes.decode("utf-8", errors="replace"), implementation_path):
                raise RegistryContractError(f"CALLABLE_UNRESOLVED:{strategy_id}:{callable_name}")

            config_ref = str(row.get("config_ref") or "")
            config_path, pointer = _split_config_ref(config_ref)
            if config_path != "backend/strategy25/canonical_strategy25_config_v1.json":
                raise RegistryContractError(f"CONFIG_PATH_NOT_CANONICAL:{strategy_id}:{config_path}")
            config_value = _json_pointer(_load_json(self._root / config_path), pointer)
            if config_value is None:
                raise RegistryContractError(f"CONFIG_VALUE_NULL:{strategy_id}")
            frozen_config = MappingProxyType(dict(config_value) if isinstance(config_value, dict) else {"value": config_value})
            result[strategy_id] = Strategy25Descriptor(
                strategy_id=strategy_id,
                implementation_path=implementation_path,
                callable_name=callable_name,
                source_sha256=actual_sha,
                config_ref=config_ref,
                config=frozen_config,
                active_allowed=False,
                fail_closed=True,
            )
        if len(result) != self._expected_count:
            raise RegistryContractError(f"RESOLVED_COUNT_INVALID:{len(result)}")
        return MappingProxyType(dict(sorted(result.items())))

    def strategy_ids(self) -> tuple[str, ...]:
        return tuple(self._descriptors)

    def descriptors(self) -> tuple[Strategy25Descriptor, ...]:
        return tuple(self._descriptors.values())

    def get(self, strategy_id: str) -> Strategy25Descriptor:
        try:
            return self._descriptors[strategy_id]
        except KeyError as exc:
            raise RegistryContractError(f"UNKNOWN_STRATEGY_ID:{strategy_id}") from exc

    def resolve_for_router(self, strategy_id: str) -> Mapping[str, Any]:
        return self.get(strategy_id).router_view()

    def resolve_all_for_router(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(descriptor.router_view() for descriptor in self._descriptors.values())
