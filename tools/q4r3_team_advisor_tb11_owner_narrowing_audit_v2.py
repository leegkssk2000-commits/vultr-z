#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

V1_PATH = Path(__file__).with_name("q4r3_team_advisor_tb11_owner_narrowing_audit.py")
_spec = importlib.util.spec_from_file_location("q4r3_team_advisor_tb11_owner_narrowing_audit_v1", V1_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load TB1.1 v1 module: {V1_PATH}")
_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v1)

# Support classification is intentionally path-structural, not substring-based.
# 1) Exact support directories: test/tests/script/scripts.
# 2) Support prefixes apply only to the final basename, never to ancestors such
#    as pytest's test_environment_credential_ac0 temporary directory.
_v1.SUPPORT_PATH_RE = re.compile(
    r"/(?:tests?|scripts?)/|(?:^|/)(?:test|verify|apply|install|bootstrap|run|audit|probe|smoke|check)[_-][^/]+$",
    re.I,
)

# Re-export the audited implementation after replacing the single defective
# classifier dependency. Function globals remain bound to _v1 and therefore
# read the corrected SUPPORT_PATH_RE above.
for _name in dir(_v1):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_v1, _name)

AUDIT_IMPLEMENTATION = "q4r3_team_advisor_tb11_owner_narrowing_audit_v2"

if __name__ == "__main__":
    raise SystemExit(_v1.main())
