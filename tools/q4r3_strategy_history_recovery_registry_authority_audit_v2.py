from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple


HERE = Path(__file__).resolve().parent
BASE_PATH = HERE / "q4r3_strategy_history_recovery_registry_authority_audit.py"
SPEC = importlib.util.spec_from_file_location(
    "q4r3_strategy_history_recovery_registry_authority_base",
    BASE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"BASE_ANALYZER_LOAD_FAILED:{BASE_PATH}")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)


def import_graph(root: Path, py_files: Sequence[Path]) -> Tuple[Dict[str, str], Dict[str, Set[str]]]:
    """Resolve direct imports and `from package import module` aliases.

    The v1 graph only recorded the base package for ImportFrom nodes. That
    misses imports such as `from backend.engine import canonical_registry`,
    causing a valid exact-25 registry to look unreachable.
    """
    module_to_path: Dict[str, str] = {}
    path_to_module: Dict[str, str] = {}
    for path in py_files:
        module = BASE.module_name(root, path)
        if module:
            rel = str(path.relative_to(root)).replace("\\", "/")
            module_to_path[module] = rel
            path_to_module[rel] = module

    graph: Dict[str, Set[str]] = defaultdict(set)
    for path in py_files:
        rel = str(path.relative_to(root)).replace("\\", "/")
        text = BASE.safe_read(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        current_module = path_to_module.get(rel, "")
        current_package = current_module.rsplit(".", 1)[0] if "." in current_module else ""

        for node in ast.walk(tree):
            names: List[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level and current_package:
                    package_parts = current_package.split(".")
                    prefix = package_parts[: max(0, len(package_parts) - node.level + 1)]
                    base = ".".join(prefix + ([base] if base else []))
                if base:
                    names.append(base)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    names.append(f"{base}.{alias.name}" if base else alias.name)

            for name in names:
                candidate = name
                while candidate:
                    target = module_to_path.get(candidate)
                    if target:
                        graph[rel].add(target)
                        break
                    candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""

    return module_to_path, graph


BASE.import_graph = import_graph


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=BASE.ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = BASE.run(args.root, args.output_dir)
    print(
        json.dumps(
            {
                "status": result["status"],
                "verdict": result["verdict"],
                "next_action": result["next_action"],
                "candidate_summary": result["candidate_summary"],
                "registry_authority_found": bool(
                    result["registry_authority"].get("authoritative_candidate")
                ),
                "analyzer_version": "v2_importfrom_alias_fix",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
