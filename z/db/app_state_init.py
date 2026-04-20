cat > "$ROOT/db/app_state_init.py" <<'PY'
import os, sqlite3
from pathlib import Path
DB = os.getenv("DB_PATH", str(Path(__file__).resolve().parents[1] / "db" / "z.sqlite"))
Path(DB).parent.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS app_state(
  id INTEGER PRIMARY KEY CHECK (id=1),
  started_at TEXT NOT NULL,
  mode TEXT NOT NULL
)""")
cur.execute("INSERT OR IGNORE INTO app_state(id, started_at, mode) VALUES (1, datetime('now'), 'paper')")
con.commit(); con.close()
print("app_state ready:", DB)
PY