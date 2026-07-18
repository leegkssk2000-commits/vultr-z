#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

ERROR_RE = re.compile(r"Traceback|\bERROR\b|Exception|NameError|TypeError|AttributeError|SyntaxError", re.I)
FORBIDDEN = ("_r73b4u3_", "_R73B4U3_", "CanonicalizeTelegram")
COMMANDS = ("/pos", "/pnl", "/view")


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True)


def command_count(text: str) -> int:
    return sum(text.count(repr(item)) + text.count(json.dumps(item)) for item in COMMANDS)


def select_clean_backup(pattern: str) -> Path:
    candidates = sorted((Path(p) for p in glob.glob(pattern)), key=lambda p: p.stat().st_mtime_ns)
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        if any(marker in text for marker in FORBIDDEN):
            continue
        if command_count(text) < len(COMMANDS):
            continue
        compile(text, str(path), "exec")
        return path
    raise RuntimeError("CLEAN_PRE_AST_BACKUP_NOT_FOUND")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py"))
    parser.add_argument("--backup-glob", default="/home/z/z/runtime/exact25_edge_v1/display_adapter/rollback/r73b4u3u4/telegram.*.py")
    parser.add_argument("--unit", default="zel-q4r3-telegram-pos-adapter-v2.service")
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    clean = select_clean_backup(args.backup_glob)
    live_backup = args.status.parent / "rollback" / "telegram_live_before_restore.py"
    live_backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.source, live_backup)
    mode = args.source.stat().st_mode & 0o777

    try:
        original = clean.read_text(encoding="utf-8", errors="strict")
        before_commands = command_count(original)
        stop = run(["systemctl", "stop", args.unit])
        if stop.returncode != 0:
            raise RuntimeError("STOP_FAILED:" + stop.stderr[-300:])
        shutil.copy2(clean, args.source)
        args.source.chmod(mode or 0o755)
        compile_result = run(["python3", "-m", "py_compile", str(args.source)])
        if compile_result.returncode != 0:
            raise RuntimeError("COMPILE_FAILED:" + compile_result.stderr[-300:])
        restored = args.source.read_text(encoding="utf-8", errors="strict")
        after_commands = command_count(restored)
        if after_commands != before_commands or after_commands < len(COMMANDS):
            raise RuntimeError(f"COMMANDS_NOT_PRESERVED:{before_commands}->{after_commands}")
        started_at = int(time.time())
        start = run(["systemctl", "start", args.unit])
        if start.returncode != 0:
            raise RuntimeError("START_FAILED:" + start.stderr[-300:])
        time.sleep(3)
        active = run(["systemctl", "is-active", args.unit]).stdout.strip()
        if active != "active":
            raise RuntimeError("UNIT_NOT_ACTIVE:" + active)
        journal = run(["journalctl", "-u", args.unit, "--since", f"@{started_at}", "--no-pager", "-o", "cat"]).stdout
        errors = [line for line in journal.splitlines() if ERROR_RE.search(line)]
        if errors:
            raise RuntimeError("STARTUP_ERRORS:" + " | ".join(errors[-5:]))
        payload = {
            "state": "PASS",
            "blockers": [],
            "blocker_count": 0,
            "mutation_count": 1,
            "rollback_performed": False,
            "restored_from_backup": str(clean),
            "telegram_command_count": after_commands,
            "telegram_compile_ok": True,
            "telegram_unit_active": True,
            "telegram_startup_error_count": 0,
            "next_stage": "R7.3B4U6B_POS_RENDER_SINGLE_SOURCE_PATCH"
        }
        args.status.parent.mkdir(parents=True, exist_ok=True)
        args.status.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        shutil.copy2(live_backup, args.source)
        args.source.chmod(mode or 0o755)
        run(["systemctl", "start", args.unit])
        payload = {
            "state": "HOLD",
            "blockers": [str(exc)],
            "blocker_count": 1,
            "mutation_count": 0,
            "rollback_performed": True,
            "next_stage": "R7.3B4U6_RESTORE_DIAGNOSE"
        }
        args.status.parent.mkdir(parents=True, exist_ok=True)
        args.status.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
