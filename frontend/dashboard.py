# frontend/dashboard.py
from flask import Blueprint, render_template, jsonify
bp = Blueprint('dashboard_bp', __name__,
               template_folder='../templates', static_folder='../static')
import sqlite3, json, os
from pathlib import Path
from datetime import datetime

BASE = Path("/home/z/z")
DB_PATH = BASE / "db" / "logs.db"
TASKS_JSON = BASE / "620_tasks.json"

def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def _safe_exec(sql, params=()):
    if not DB_PATH.exists():
        return []
    try:
        with _conn() as con:
            cur = con.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []

@bp.route("/")
def index():
    return render_template("index.html")

@bp.route("/api/summary")
def summary():
    tcnt = _safe_exec("select count(*) n from trades")
    wins = _safe_exec("select avg(case when pnl>0 then 1 else 0 end) win from trades")
    pnl = _safe_exec("select sum(pnl) pnl from trades")
    return jsonify({
        "trades": (tcnt[0]["n"] if tcnt else 0),
        "win_rate": (round((wins[0]["win"] or 0)*100,2) if wins else 0),
        "pnl_sum": (round(pnl[0]["pnl"],2) if pnl and pnl[0]["pnl"] is not None else 0),
    })

@bp.route("/api/winrates/by_symbol")
def win_by_symbol():
    sql = """
    select symbol,
           round(avg(case when pnl>0 then 1.0 else 0 end)*100,2) as win_rate,
           count(*) as trades
    from trades
    group by symbol
    having trades>=5
    order by trades desc
    limit 50
    """
    return jsonify(_safe_exec(sql))

@bp.route("/api/winrates/by_strategy")
def win_by_strategy():
    sql = """
    select coalesce(strategy,'unknown') as strategy,
           round(avg(case when pnl>0 then 1.0 else 0 end)*100,2) as win_rate,
           count(*) as trades
    from trades
    group by strategy
    having trades>=5
    order by trades desc
    """
    return jsonify(_safe_exec(sql))

@bp.route("/api/winrates/long_short")
def win_long_short():
    sql = """
    select upper(side) as side,
           round(avg(case when pnl>0 then 1.0 else 0 end)*100,2) as win_rate,
           count(*) trades
    from trades
    group by upper(side)
    """
    return jsonify(_safe_exec(sql))

@bp.route("/api/pnl/monthly")
def pnl_monthly():
    sql = """
    select strftime('%Y-%m', ts) as ym,
           round(sum(pnl),2) as pnl
    from trades
    group by ym
    order by ym
    """
    return jsonify(_safe_exec(sql))

@bp.route("/api/scanner/alts")
def scanner_alts():
    # 기대 스키마: market_snapshots(symbol TEXT, change24 REAL, vol24 REAL, ts DATETIME)
    sql = """
    select symbol, round(change24,2) as change24, round(vol24,2) as vol24
    from market_snapshots
    where ts >= datetime('now','-1 day')
    order by change24 desc
    limit 50
    """
    return jsonify(_safe_exec(sql))

@bp.route("/api/routine/status")
def routine_status():
    out = {"phase":"unknown","progress":0,"next":"n/a"}
    try:
        if TASKS_JSON.exists():
            data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
            out["phase"] = data.get("phase","unknown")
            out["progress"] = data.get("progress",0)
            out["next"] = data.get("next","n/a")
    except Exception:
        pass
    return jsonify(out)

# 선택: 최소 스키마 자동 생성(없을 때)
@bp.before_app_request
def ensure_schema():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with conn() as con:
        con.execute("""
        create table if not exists trades(
            id integer primary key,
            ts text not null,
            symbol text,
            side text,
            strategy text,
            pnl real
        )
        """)
        con.commit()

@bp.route("/api/metrics2")
def metrics2():
    import sqlite3, os
    DB=os.path.abspath(os.path.join(os.path.dirname(__file__),"..","db","z.sqlite"))
    with sqlite3.connect(DB) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute("select ts,key,value from metrics order by ts desc limit 50").fetchall()
    return jsonify([dict(r) for r in rows])

@bp.route("/")
def index():
    return "Dashboard running"

@bp.route("/health")
def health():
    return jsonify(status="ok"), 200

@bp.route("/healthz")
def healthz():
    return jsonify(ok=True)
