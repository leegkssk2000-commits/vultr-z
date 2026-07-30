from __future__ import annotations

from pathlib import Path

from backend.tools import strategy11_internal_organic_audit_v1 as v1


_original_import_graph = v1.import_graph


def import_graph(files):
    graph, unresolved = _original_import_graph(files)
    filtered = []
    for row in unresolved:
        imported = str(row.get("import") or "")
        relative = Path(*imported.split("."))
        module_file = v1.ROOT / relative.with_suffix(".py")
        package_file = v1.ROOT / relative / "__init__.py"
        if module_file.is_file() or package_file.is_file():
            continue
        filtered.append(row)
    return graph, filtered


v1.import_graph = import_graph


if __name__ == "__main__":
    raise SystemExit(v1.main())
