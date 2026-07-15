#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping

ORIGINAL_PATH = Path(__file__).with_name("q4r3_team_advisor_tb11_owner_narrowing_audit.py")
spec = importlib.util.spec_from_file_location("q4r3_tb11_original", ORIGINAL_PATH)
assert spec and spec.loader
_original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_original)

SUPPORT_DIR_NAMES = {"test", "tests", "script", "scripts"}
SUPPORT_FILE_PREFIXES = (
    "test_", "verify_", "apply_", "install_", "bootstrap_", "run_",
    "audit_", "probe_", "smoke_", "check_",
)


def classify_kind(path: Path, exact_defs: Mapping[str, bool]) -> str:
    """Classify only repository-owned support surfaces as support files.

    The original regex matched any ancestor segment beginning with ``test_``.
    Pytest creates temporary parents such as ``test_environment_credential_ac0``;
    that incorrectly demoted a real ``backend/engine/zbot_core.py`` fixture to a
    verifier and suppressed its semantic authority evidence.
    """
    path_text = str(path).replace("\\", "/")
    if path.suffix in {".service", ".timer"} or path_text.startswith("/etc/systemd/system/"):
        return "systemd_unit"

    lowered_parts = {part.lower() for part in path.parts}
    support_directory = bool(lowered_parts.intersection(SUPPORT_DIR_NAMES))
    support_filename = path.stem.lower().startswith(SUPPORT_FILE_PREFIXES)
    if support_directory or support_filename:
        return "support_verifier_installer"

    if path.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}:
        return "config_contract"
    if any(exact_defs.values()):
        return "runtime_definition"
    return "reference"


# Re-export the audited implementation, then replace only the faulty classifier.
for _name in dir(_original):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_original, _name)
_original.classify_kind = classify_kind
globals()["classify_kind"] = classify_kind


def main() -> int:
    return _original.main()


if __name__ == "__main__":
    raise SystemExit(main())
