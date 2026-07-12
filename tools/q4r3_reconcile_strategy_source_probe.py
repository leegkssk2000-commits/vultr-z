from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Sequence, Tuple

DEFAULT_ROOT = Path("/home/z/z")
CONVENTIONAL_PATTERNS: Tuple[str, ...] = (
    "backend/strategies/{strategy}.py",
    "backend/legendary_rebuild/strategies/{strategy}_legendary.py",
    "backend/strategies_v4/{strategy}_v4.py",
)
REGISTRY_INVENTORY_PATH = "data/strategy_registry_latest.json"


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text).strip("_"))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def strategy_from_path(path: str) -> str:
    stem = Path(path).stem
    stem = re.sub(r"_(?:legendary|v\d+)$", "", stem, flags=re.I)
    return normalize(stem)


def expected_strategy_items(probe: Mapping[str, Any]) -> List[MutableMapping[str, Any]]:
    surface = probe.get("contract_surface")
    if not isinstance(surface, Mapping):
        return []
    items = surface.get("strategies")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, MutableMapping)]


def inventory_paths(root: Path, expected: Sequence[str]) -> Dict[str, List[str]]:
    expected_set = set(expected)
    inventory = root / REGISTRY_INVENTORY_PATH
    discovered: Dict[str, List[str]] = {strategy: [] for strategy in expected}
    if not inventory.is_file() or inventory.stat().st_size <= 0:
        return discovered
    try:
        payload = load_json(inventory)
    except Exception:
        return discovered
    candidates = payload.get("candidates_top") if isinstance(payload, Mapping) else None
    if not isinstance(candidates, list):
        return discovered
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        rel_path = str(item.get("path") or "").strip()
        if not rel_path:
            continue
        strategy = strategy_from_path(rel_path)
        if strategy not in expected_set:
            continue
        source = root / rel_path
        if source.is_file() and rel_path not in discovered[strategy]:
            discovered[strategy].append(rel_path)
    return discovered


def conventional_paths(root: Path, strategy: str) -> List[str]:
    paths: List[str] = []
    for pattern in CONVENTIONAL_PATTERNS:
        rel_path = pattern.format(strategy=strategy)
        if (root / rel_path).is_file():
            paths.append(rel_path)
    return paths


def reconcile(root: Path, probe: Mapping[str, Any]) -> Dict[str, Any]:
    output = deepcopy(dict(probe))
    items = expected_strategy_items(output)
    names = [normalize(item.get("strategy")) for item in items]
    names = [name for name in names if name]
    if len(names) != 25 or len(set(names)) != 25:
        raise RuntimeError(f"EXPECTED_EXACT_25_STRATEGIES:{len(names)}:{len(set(names))}")

    inventory = inventory_paths(root, names)
    report: Dict[str, Any] = {}
    omission_count = 0
    original_total = 0
    reconciled_total = 0

    for item in items:
        strategy = normalize(item.get("strategy"))
        original_modules = item.get("modules") if isinstance(item.get("modules"), list) else []
        original_paths: List[str] = []
        for module in original_modules:
            if not isinstance(module, Mapping):
                continue
            path = str(module.get("path") or "").strip()
            if path and path not in original_paths:
                original_paths.append(path)
        original_total += len(original_paths)

        candidates: Dict[str, List[str]] = {}
        for path in original_paths:
            candidates.setdefault(path, []).append("runtime_probe")
        for path in conventional_paths(root, strategy):
            candidates.setdefault(path, []).append("conventional_active_path")
        for path in inventory.get(strategy, []):
            candidates.setdefault(path, []).append("readonly_registry_inventory")

        reconciled_paths = sorted(
            path for path in candidates if (root / path).is_file()
        )
        if not reconciled_paths:
            raise RuntimeError(f"NO_ACTIVE_SOURCE_FOR_STRATEGY:{strategy}")

        newly_discovered = sorted(set(reconciled_paths) - set(original_paths))
        omission_count += len(newly_discovered)
        reconciled_total += len(reconciled_paths)
        item["modules"] = [
            {
                "path": path,
                "discovery_sources": sorted(set(candidates[path])),
            }
            for path in reconciled_paths
        ]
        report[strategy] = {
            "original_paths": original_paths,
            "reconciled_paths": reconciled_paths,
            "newly_discovered_paths": newly_discovered,
            "removed_missing_paths": sorted(set(original_paths) - set(reconciled_paths)),
            "canonical_present": f"backend/strategies/{strategy}.py" in reconciled_paths,
        }

    output["source_reconciliation"] = {
        "schema": "q4r3_strategy_source_reconciliation_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_strategy_count": len(names),
        "original_module_count": original_total,
        "reconciled_module_count": reconciled_total,
        "probe_omission_count": omission_count,
        "registry_inventory_path": REGISTRY_INVENTORY_PATH,
        "strategies": report,
        "all_25_have_active_source": all(item["reconciled_paths"] for item in report.values()),
        "all_25_have_canonical_source": all(item["canonical_present"] for item in report.values()),
    }
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    probe = load_json(args.probe)
    result = reconcile(args.root, probe)
    atomic_json(args.output, result)
    summary = result["source_reconciliation"]
    print(json.dumps({
        "status": "PASS_Q4R3_STRATEGY_SOURCE_RECONCILIATION",
        "expected_strategy_count": summary["expected_strategy_count"],
        "original_module_count": summary["original_module_count"],
        "reconciled_module_count": summary["reconciled_module_count"],
        "probe_omission_count": summary["probe_omission_count"],
        "all_25_have_active_source": summary["all_25_have_active_source"],
        "all_25_have_canonical_source": summary["all_25_have_canonical_source"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
