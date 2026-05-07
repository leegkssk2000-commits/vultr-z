from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from config.settings import DB_PATH, LOG_DIR
from engine.runner import gate_status


def check_health() -> dict[str, object]:
    log_dir = Path(LOG_DIR)
    db_path = Path(DB_PATH)
    db_ok = False
    if db_path.is_file():
        try:
            sqlite3.connect(db_path).close()
            db_ok = True
        except sqlite3.Error:
            db_ok = False

    gate = gate_status()
    return {
        "ok": bool(log_dir.is_dir() and db_ok and gate["ok"]),
        "ts": time.time(),
        "log_dir": log_dir.is_dir(),
        "db": db_ok,
        "execution_allowed": False,
        "live_execution_enabled": False,
        "p0_p2_gate": gate,
    }


if __name__ == "__main__":
    print(json.dumps(check_health(), sort_keys=True))
