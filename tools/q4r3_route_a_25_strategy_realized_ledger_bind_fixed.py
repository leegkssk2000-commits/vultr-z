from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_PATH = Path(__file__).with_name("q4r3_route_a_25_strategy_realized_ledger_bind.py")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_module("q4r3_25_strategy_realized_ledger_bind_base", BASE_PATH)


def object_strategy_names(obj: Dict[str, Any]) -> Tuple[List[str], Dict[str, str]]:
    """Return one canonical strategy name and keep every alternate label as an alias.

    The original binder counted aliases inside the strategy universe, so a registry
    with 25 strategy IDs plus 25 aliases appeared to contain 50 strategies. This
    overlay preserves the canonical universe cardinality while retaining explicit
    alias-to-canonical mappings.
    """
    preferred = BASE.first_value(
        obj,
        ("strategy_id", "strategy_key", "strategy_slug", "slug", "name", "strategy_name", "strategy"),
    )
    canonical = BASE.normalize_name(preferred) if BASE.plausible_strategy_name(preferred) else ""

    if not canonical:
        for key in BASE.STRATEGY_KEYS:
            value = obj.get(key)
            if BASE.plausible_strategy_name(value):
                canonical = BASE.normalize_name(value)
                break

    names: List[str] = [canonical] if canonical else []
    aliases: Dict[str, str] = {}

    if canonical:
        for key in BASE.STRATEGY_KEYS:
            value = obj.get(key)
            if not BASE.plausible_strategy_name(value):
                continue
            normalized = BASE.normalize_name(value)
            if normalized != canonical:
                aliases[normalized] = canonical

        for key in BASE.ALIAS_KEYS:
            value = obj.get(key)
            values = value if isinstance(value, list) else [value]
            for item in values:
                if not BASE.plausible_strategy_name(item):
                    continue
                normalized = BASE.normalize_name(item)
                if normalized != canonical:
                    aliases[normalized] = canonical

    return names, aliases


BASE.object_strategy_names = object_strategy_names

# Re-export the base module API so the existing tests and runner can use the
# corrected overlay without mutating the original diagnostic file.
for attribute in dir(BASE):
    if attribute.startswith("__"):
        continue
    if attribute == "object_strategy_names":
        continue
    globals()[attribute] = getattr(BASE, attribute)


def main() -> None:
    BASE.main()


if __name__ == "__main__":
    main()
