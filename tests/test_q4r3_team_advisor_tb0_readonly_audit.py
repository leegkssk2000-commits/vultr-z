from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "q4r3_team_advisor_tb0_readonly_audit.sh"


def test_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_required_read_only_sections_present() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    required = [
        "CORE UNIT STATE / PID / EXEC",
        "EXACT25 STATUS CHAIN",
        "FORMAL LEDGER SNAPSHOT",
        "TEAM / ADVISOR / ALIMI UNIT INVENTORY",
        "PROCESS / TIMER / CRON / LISTENER EVIDENCE",
        "STATIC CANONICAL FILE INVENTORY",
        "CALLER / CONTRACT / AUTHORITY EVIDENCE",
        "ALIMI SOURCE / CARD BINDING EVIDENCE",
        "KNOWN MASKED UNIT DETAIL",
        "COMPACT MACHINE SUMMARY",
        "READ_ONLY_AUDIT_V2_DONE",
    ]
    for marker in required:
        assert marker in text


def test_no_mutating_shell_commands() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = re.compile(
        r"^\s*(?:sudo\s+)?(?:"
        r"systemctl\s+(?:restart|stop|start|enable|disable|mask|unmask|reset-failed)"
        r"|git\s+(?:reset|clean|checkout|switch|merge|rebase|stash)"
        r"|rm\b|mv\b|cp\b|install\b|chmod\b|chown\b"
        r"|sed\s+-i\b"
        r")",
        re.IGNORECASE,
    )
    violations = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("echo "):
            continue
        if forbidden.search(line):
            violations.append((number, line))
    assert not violations, violations


def test_scan_is_bounded_and_redacted() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--follow" not in text
    assert "--max-filesize 5M" in text
    assert "find /home/z/z/runtime" in text
    assert "-maxdepth 5" in text
    assert "[REDACTED]" in text
    assert "redact()" in text


def test_no_python_import_probe_of_project_modules() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "importlib.import_module" not in text
    assert "PYTHONPATH=" not in text
    assert "pytest" not in text
