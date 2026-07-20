#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("STATUS_ROOT_NOT_OBJECT")
    return value


def atomic(path: Path, payload: dict[str, Any]) -> None:
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def eligible_strong(row: dict[str, Any]) -> bool:
    if row.get("strength") != "strong":
        return False
    if row.get("kind") == "DIRECT_STRATEGY_MODULE":
        return True
    if row.get("target_path_exists_in_git") is True:
        return True
    target_callable = str(row.get("target_callable") or "")
    shared = [str(value) for value in row.get("shared_engine_candidates", [])]
    config_keys = [str(value) for value in row.get("config_keys", [])]
    if target_callable and target_callable in shared:
        return True
    if len(config_keys) >= 2 and len(shared) == 1 and str(row.get("callable") or "") == shared[0]:
        return True
    return False


def token(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key) or "") for key in ("target_path", "target_callable", "source_path", "callable"))


def strict_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    evidence = mapping.get("evidence") if isinstance(mapping.get("evidence"), list) else []
    downgraded = 0
    for row in evidence:
        if not isinstance(row, dict):
            continue
        if row.get("strength") == "strong" and not eligible_strong(row):
            row["strength"] = "partial"
            row["strict_downgrade_reason"] = "UNRESOLVED_STRING_OR_EXTERNAL_CALLABLE_NOT_CANONICAL"
            downgraded += 1
    strong = [row for row in evidence if isinstance(row, dict) and eligible_strong(row)]
    conflicts = [row for row in evidence if isinstance(row, dict) and row.get("strength") == "conflict"]
    tokens = sorted({token(row) for row in strong if token(row).strip("|")})
    if conflicts or len(tokens) > 1:
        status = "CONFLICT"
    elif len(tokens) == 1:
        status = "PROVEN"
    elif evidence:
        status = "PARTIAL"
    else:
        status = "UNPROVEN"
    mapping["lineage_status"] = status
    mapping["canonical_token"] = tokens[0] if len(tokens) == 1 else None
    mapping["strong_evidence_count"] = len(strong)
    mapping["strict_downgraded_evidence_count"] = downgraded
    mapping["strict_canonical_rule_applied"] = True
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    status_path = Path(args.status)
    contract = load(Path(args.contract))
    payload = load(status_path)
    mappings = payload.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError("MAPPINGS_NOT_LIST")
    mappings = [strict_mapping(row) for row in mappings if isinstance(row, dict)]
    counts = Counter(str(row.get("lineage_status")) for row in mappings)
    expected = int(contract.get("expected_strategy_count", 25))
    proven = counts.get("PROVEN", 0)
    conflicts = counts.get("CONFLICT", 0)
    payload["mappings"] = mappings
    payload["lineage_counts"] = dict(sorted(counts.items()))
    payload["proven_lineage_count"] = proven
    payload["partial_lineage_count"] = counts.get("PARTIAL", 0)
    payload["unproven_lineage_count"] = counts.get("UNPROVEN", 0)
    payload["conflict_lineage_count"] = conflicts
    payload["strict_canonical_rule_applied"] = True
    payload["strict_rule"] = "DIRECT_MODULE_OR_EXISTING_GIT_PATH_OR_SAME_FILE_AST_CALLABLE_OR_CONFIG_WITH_SINGLE_SHARED_ENGINE"
    if payload.get("state") == "PASS":
        payload["next_stage"] = (
            contract.get("next_stage_all_proven")
            if proven == expected and conflicts == 0
            else contract.get("next_stage_gaps")
        )
    atomic(status_path, payload)
    print("R7A3D_STRICT_LINEAGE_POSTPROCESS_COMPLETE")
    print(f"PROVEN_LINEAGE_COUNT={proven}")
    print(f"PARTIAL_LINEAGE_COUNT={counts.get('PARTIAL', 0)}")
    print(f"UNPROVEN_LINEAGE_COUNT={counts.get('UNPROVEN', 0)}")
    print(f"CONFLICT_LINEAGE_COUNT={conflicts}")
    print(f"NEXT_STAGE={payload.get('next_stage')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
