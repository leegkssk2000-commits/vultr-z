#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

BASE = Path(__file__).with_name("q4r3_exact25_r73b0_audit_display_binding_residue.py")
SPEC = importlib.util.spec_from_file_location("r73b0_base", BASE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
MAX_BYTES = module.MAX_BYTES


def matching_lines(path: Path) -> list[dict[str, object]]:
    module.MAX_BYTES = MAX_BYTES
    return module.matching_lines(path)


def classify(path: str, hits: list[dict[str, object]], active_names: set[str]) -> str:
    lower = path.lower()
    joined = " ".join(str(hit.get("text", "")).lower() for hit in hits)
    name = Path(path).name
    active = name in active_names or any(name in item for item in active_names)
    if any(token in lower for token in ("backup", "archive", ".bak", ".disabled", "legacy")):
        return "ARCHIVE_OR_BACKUP"
    if "telegram_only_6c_lock" in joined or "s4g8r7f8t" in joined or "6c_lock" in joined:
        return "STATIC_DISPLAY_LOCK"
    writer_signal = "writer" in lower or "writer" in joined or any(
        token in joined for token in ("write_text", "json.dump", "atomic", "replace(", "open(")
    )
    if active and writer_signal:
        return "ACTIVE_OVERWRITER_CANDIDATE"
    if active:
        return "CANONICAL_OWNER_CANDIDATE"
    if any(token in lower for token in ("view", "telegram", "pnl", "trace")):
        return "DISABLED_RESIDUE"
    return "UNCLASSIFIED_REVIEW_REQUIRED"


module.classify = classify

if __name__ == "__main__":
    raise SystemExit(module.main())
