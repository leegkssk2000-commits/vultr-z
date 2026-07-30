from __future__ import annotations

from pathlib import Path
from typing import Iterable

from backend.tools import strategy11_runtime_system_audit_v1 as v1


# V1 omitted HTML/CSS reference surfaces and included generated artifacts and audit files.
v1.SKIP_PARTS.add("artifacts")
v1.TEXT_SUFFIXES.update({".html", ".css"})


def runtime_named_files(files: Iterable[v1.TextFile]) -> list[v1.TextFile]:
    allowed_suffixes = {".py", ".js", ".ts", ".tsx", ".json", ".service", ".timer", ".sh"}
    result: list[v1.TextFile] = []
    for row in files:
        name = row.path.name.lower()
        if "runtime" not in name or row.path.suffix.lower() not in allowed_suffixes:
            continue
        if row.rel.startswith(".github/workflows/"):
            continue
        if row.rel in {
            "backend/tools/strategy11_runtime_system_audit_v1.py",
            "backend/tools/strategy11_runtime_system_audit_v2.py",
        }:
            continue
        result.append(row)
    return result


v1.runtime_named_files = runtime_named_files


if __name__ == "__main__":
    raise SystemExit(v1.main())
