from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import List, Tuple

BASE_PATH = Path(__file__).with_name("q4r3_forward_r_source_authority_lineage_audit.py")


def load_base():
    spec = importlib.util.spec_from_file_location("q4r3_forward_r_source_authority_lineage_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_base()

# `test` must never be used as an unrestricted substring token because every
# normal `*_latest.json` path contains the letters "test" across "latest".
REPLAY_TOKENS = tuple(token for token in BASE.REPLAY_TOKENS if token != "test")
TEST_PATH_PATTERNS = (
    "/tests/",
    "\\tests\\",
    "/test_",
    "\\test_",
    "_test.py",
    "_test.json",
    ".test.",
)


def classify_source(path: Path) -> Tuple[str, List[str]]:
    lower = str(path).lower()
    reasons: List[str] = []
    if any(pattern in lower for pattern in TEST_PATH_PATTERNS):
        reasons.append("bounded_test_path")
        return "REPLAY_DIAGNOSTIC", reasons
    if any(token in lower for token in REPLAY_TOKENS):
        reasons.append("replay_or_diagnostic_token")
        return "REPLAY_DIAGNOSTIC", reasons
    if any(token in lower for token in BASE.DERIVED_TOKENS):
        reasons.append("derived_or_aggregate_token")
        return "DERIVED", reasons
    if any(token in lower for token in BASE.AUTHORITATIVE_TOKENS):
        reasons.append("authoritative_ledger_token")
        return "AUTHORITATIVE_FORWARD", reasons
    if any(token in lower for token in BASE.FORWARD_TOKENS):
        reasons.append("forward_like_token_without_authority_proof")
        return "FORWARD_CANDIDATE", reasons
    reasons.append("no_forward_authority_evidence")
    return "OTHER", reasons


# Patch only the classification boundary. All inventory, lineage, decision and
# output behavior remains the audited base implementation.
BASE.classify_source = classify_source

# Re-export the public surface used by tests and the runner.
iter_contract_rows = BASE.iter_contract_rows
lineage_metrics = BASE.lineage_metrics
decide = BASE.decide
source_inventory = BASE.source_inventory
code_lineage = BASE.code_lineage
main = BASE.main


if __name__ == "__main__":
    main()
