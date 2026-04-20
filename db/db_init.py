# /home/z/z/db/db_init.py
import sqlite3, os, json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] # /home/z/z
DB = Path(os.getenv("DB_PATH") or BASE / "db" / "z.sqlite")
DB.parent.mkdir(parents=True, exist_ok=True)

ddl = [
    """
    CREATE TABLE IF NOT EXISTS metrics(
        ts TEXT, key TEXT, value REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, symbol TEXT, side TEXT,
        qty REAL, price REAL, pnl REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks(
        name TEXT PRIMARY KEY, spec TEXT, enabled INTEGER
    )
    """
]

with sqlite3.connect(DB) as c:
    cur = c.cursor()
    for q in ddl:
        cur.execute(q)

    # 옵션: 620_tasks.json 있으면만 로드
    fp = BASE / "620_tasks.json"
    if fp.exists():
        try:
            tasks = json.loads(fp.read_text())
            for t in tasks:
                cur.execute(
                    "INSERT OR IGNORE INTO tasks(name,spec,enabled) VALUES(?,?,?)",
                    (t.get("name",""), t.get("spec",""), int(t.get("enabled",1)))
                )
        except Exception:
            pass
    c.commit()

print("DB ready:", DB)
