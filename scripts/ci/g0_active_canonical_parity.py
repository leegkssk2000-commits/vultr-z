#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()
ESCROW = Path(os.environ.get("G0_ESCROW_ROOT", "/home/z/.zel-g0-source-escrow")).resolve()
PIN = ESCROW / "canonical_source_pin_candidate.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def runtime_path(source_path: str) -> Path:
    if source_path.startswith("external:"):
        return Path(source_path[len("external:"):])
    return ROOT / source_path


def canonical_path(source_path: str) -> Path:
    if source_path.startswith("external:"):
        return ESCROW / "sources_external" / source_path[len("external:"):].lstrip("/")
    return ESCROW / "sources" / source_path


def main() -> int:
    if not PIN.is_file():
        raise SystemExit("canonical source pin missing")
    pin = json.loads(PIN.read_text())

    source_rows: list[dict[str, Any]] = []
    module_rows: list[dict[str, Any]] = []
    total_present = total_missing = total_mismatch = 0

    for module in pin.get("modules", []):
        module_id = str(module.get("module_id") or "")
        sources = [str(x) for x in module.get("source_paths", [])]
        module_present = module_missing = module_mismatch = 0
        files = []
        for source in sources:
            rp = runtime_path(source)
            cp = canonical_path(source)
            c_exists = cp.is_file()
            r_exists = rp.is_file()
            c_sha = sha256_file(cp) if c_exists else None
            r_sha = sha256_file(rp) if r_exists else None
            status = "MATCH"
            if not c_exists:
                status = "CANONICAL_MISSING"
            elif not r_exists:
                status = "RUNTIME_MISSING"
                module_missing += 1
                total_missing += 1
            elif r_sha != c_sha:
                status = "HASH_MISMATCH"
                module_mismatch += 1
                total_mismatch += 1
            else:
                module_present += 1
                total_present += 1
            row = {
                "module_id": module_id,
                "source_path": source,
                "status": status,
                "runtime_sha256": r_sha,
                "canonical_sha256": c_sha,
            }
            files.append(row)
            source_rows.append(row)
        module_match = module_missing == 0 and module_mismatch == 0 and module_present == len(sources)
        module_rows.append({
            "module_id": module_id,
            "source_count": len(sources),
            "match_count": module_present,
            "missing_count": module_missing,
            "mismatch_count": module_mismatch,
            "module_parity": "PASS" if module_match else "HOLD",
            "files": files,
        })

    total_sources = len(source_rows)
    module_pass = sum(r["module_parity"] == "PASS" for r in module_rows)
    missing_paths = [r["source_path"] for r in source_rows if r["status"] == "RUNTIME_MISSING"]
    mismatch_paths = [r["source_path"] for r in source_rows if r["status"] == "HASH_MISMATCH"]

    if total_missing == 0 and total_mismatch == 0 and total_present == total_sources and module_pass == len(module_rows):
        state = "PASS_ACTIVE_RUNTIME_CANONICAL_PARITY"
    elif total_missing == 1 and total_mismatch == 0 and missing_paths == ["backend/research/strategy11_portfolio_governor_v1.py"]:
        state = "HOLD_ONLY_PORTFOLIO_GOVERNOR_MISSING"
    else:
        state = "HOLD_ACTIVE_RUNTIME_CANONICAL_PARITY_GAPS"

    receipt = {
        "schema_version": "zel.g0.active_canonical_parity.v1",
        "state": state,
        "canonical_source_pin_sha256": pin.get("source_pin_sha256"),
        "source_path_total": total_sources,
        "source_match_count": total_present,
        "source_missing_count": total_missing,
        "source_hash_mismatch_count": total_mismatch,
        "missing_source_paths": missing_paths,
        "hash_mismatch_source_paths": mismatch_paths,
        "module_total": len(module_rows),
        "module_parity_pass_count": module_pass,
        "module_rows": module_rows,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "destructive_cleanup_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold" if state != "PASS_ACTIVE_RUNTIME_CANONICAL_PARITY" else "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
