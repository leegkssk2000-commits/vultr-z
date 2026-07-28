from __future__ import annotations

import ast
from dataclasses import replace
from typing import Any, Mapping

from backend.tools import zel_full_architecture_census_v2 as base

VERSION = "ZEL_FULL_ARCHITECTURE_CENSUS_V2_1"
_original_analyze_python = base.analyze_python


def analyze_python(text: str, relative: str, module_to_path: Mapping[str, str]) -> base.PyInfo:
    info = _original_analyze_python(text, relative, module_to_path)
    if info.parse_error:
        return info

    tree = ast.parse(text, filename=relative)
    definitions = set(info.definitions)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            definitions.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                definitions.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                definitions.add(alias.asname or alias.name)

    return replace(info, definitions=tuple(sorted(definitions)))


base.analyze_python = analyze_python
base.VERSION = VERSION


if __name__ == "__main__":
    raise SystemExit(base.main())
