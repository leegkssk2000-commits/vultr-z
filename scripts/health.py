import sqlite3, os, time
from config.settings import DB_PATH, LOG_DIR
ok = os.path.isdir(LOG_DIR) and os.path.isfile(DB_PATH)
try:
    sqlite3.connect(DB_PATH).close()
    db_ok = True
except Exception:
    db_ok = False
print({"ok": ok and db_ok, "ts": time.time()})
# emit metrics: loop_lag_p95, queue_depth; if over N times -> write 'halt' flag
