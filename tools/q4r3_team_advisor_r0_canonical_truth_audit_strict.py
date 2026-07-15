#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping

BASE_PATH = Path(__file__).with_name("q4r3_team_advisor_r0_canonical_truth_audit.py")
spec = importlib.util.spec_from_file_location("q4r3_r0_base", BASE_PATH)
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def owner_proof(candidate: Mapping[str, Any]) -> bool:
    evidence = set(candidate.get("identity_evidence", []))
    kind = candidate.get("owner_kind")
    if candidate.get("direct_order_calls") or candidate.get("sensitive_credential_access"):
        return False
    if kind in {"test_support", "ui_consumer", "service_wrapper"}:
        return False
    identity_proven = bool({"exact_path_identity", "structured_team_assignment"}.intersection(evidence))
    if "active_unit_binding" in evidence and identity_proven:
        return True
    if identity_proven and candidate.get("git", {}).get("tracked") and candidate.get("contract_version"):
        return True
    return False


# The base analyze function resolves owner_proof from its module globals.
# Replace it explicitly and assert the binding so the strict function cannot be shadowed.
base.owner_proof = owner_proof
assert base.owner_proof is owner_proof

# Re-export the tested public helpers while preserving the strict binding.
for name in dir(base):
    if name.startswith("__") or name in {"owner_proof", "main"}:
        continue
    globals()[name] = getattr(base, name)


def main() -> int:
    assert base.owner_proof is owner_proof
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
