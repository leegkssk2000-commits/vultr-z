cat > "$ROOT/engine/utils/state.py" <<'PY'
import os, sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] # /home/z/z
DB = os.getenv("DB_PATH", str(BASE / "db" / "z.sqlite"))

def _now(): return datetime.now(timezone.utc)

def _q1(sql, p=()):
    con = sqlite3.connect(DB); cur = con.cursor()
    cur.execute(sql, p); r = cur.fetchone()
    con.close(); return (r[0] if r else None)

def load_state():
    # returns (mode, started_at: datetime)
    m = _q1("SELECT mode FROM app_state WHERE id=1")
    t = _q1("SELECT started_at FROM app_state WHERE id=1")
    if not m: return "paper", _now()
    try:
        started = datetime.fromisoformat((t or "").replace("Z","+00:00"))
    except Exception:
        started = _now()
    return m, started

def update_mode(mode:str):
    con = sqlite3.connect(DB); cur = con.cursor()
    cur.execute("UPDATE app_state SET mode=? WHERE id=1", (mode,))
    con.commit(); con.close()

def ok_performance(min_trades:int=50, min_pnl:float=0.0):
    trades = int(_q1("SELECT COUNT(1) FROM trades") or 0)
    pnl = float(_q1("SELECT COALESCE(SUM(pnl),0) FROM trades") or 0.0)
    return trades >= min_trades and pnl >= min_pnl
PY

# shim (기존 import 대비)
cat > "$ROOT/engine/util/state.py" <<'PY'
from engine.utils.state import * # shim for legacy import path
PY