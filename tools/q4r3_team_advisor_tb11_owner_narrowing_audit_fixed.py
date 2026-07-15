#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Mapping

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


def _fixed_classify_kind(path: Path, exact_defs: Mapping[str, bool]) -> str:
    """Classify support surfaces from exact directories or the final basename.

    Ancestor names such as pytest's ``test_environment_credential_ac0`` are not
    support surfaces. Only an exact test/tests/script/scripts directory or a
    support-prefixed final filename is treated as verifier/installer code.
    """
    path_text = str(path).replace("\\", "/")
    if path.suffix in {".service", ".timer"} or path_text.startswith("/etc/systemd/system/"):
        return "systemd_unit"

    support_directory = any(part.lower() in SUPPORT_DIR_NAMES for part in path.parts)
    support_filename = path.stem.lower().startswith(SUPPORT_FILE_PREFIXES)
    if support_directory or support_filename:
        return "support_verifier_installer"

    if path.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}:
        return "config_contract"
    if any(exact_defs.values()):
        return "runtime_definition"
    return "reference"


# Re-export the original implementation without allowing it to overwrite the
# fixed classifier or this wrapper's main entry point.
for _name in dir(_original):
    if _name.startswith("__") or _name in {"classify_kind", "main"}:
        continue
    globals()[_name] = getattr(_original, _name)

# analyze_file() resolves classify_kind from the original module globals, so
# both bindings must point to the fixed function.
_original.classify_kind = _fixed_classify_kind
classify_kind = _fixed_classify_kind


def main() -> int:
    return _original.main()


if __name__ == "__main__":
    raise SystemExit(main())
