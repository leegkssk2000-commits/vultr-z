import os, sqlite3
from datetime import datetime, timezone
from engine.router import route
from engine.exec_live import exec_live
from engine.exec_shadow import exec_shadow
from config.settings import (LIVE_MIN_TRADES, LIVE_MIN_DAYS,
    TRACKING_ERR_MAX, SLIPPAGE_P95_MAX, MISSED_FILL_RATE_MAX,
    DATA_STALE_SEC, ON_STALE)
from engine.util.state import load_state, save_state, update_mode
from engine.gate import precheck
# ...
gate = precheck(kwargs.get("df"), kwargs.get("data_stale_sec"))
if gate: return {n: gate for n in names

def _utcnow(): return datetime.now(timezone.utc)
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "db", "z.sqlite"))


def run_and_trade(names, symbol, qty=1.0, **kwargs):
    results = {}
    for n in names:
        try:
            # 전략 호출
            sig = route(n, **kwargs)
            results[n] = sig
            # 주문 실행
            EXEC.place({ "symbol": symbol, "signal": sig, "qty": qty })
        except Exception as e:
            results[n] = {"error": str(e)}
    return results

def _q1(sql, params=()):
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None

def load_state():
    row = _q1("SELECT mode FROM app_state WHERE id=1")
    if not row:
        return "paper", _utcnow()
    mode = row
    ts = _q1("SELECT started_at FROM app_state WHERE id=1")
    started_at = datetime.fromisoformat(ts.replace("Z","+"+"00:00")) if ts else _utcnow()
    return mode, started_at

def update_mode(mode:str):
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("UPDATE app_state SET mode=? WHERE id=1", (mode,))
        con.commit()
    finally:
        con.close()

def get_metric(key, default=None):
    r = _q1("select value from metrics where key=? order by ts desc limit 1", (key,))
    return (r and float(r["value"])) if r else default

def stats():
    # 없으면 0으로 처리
    trades = _q1("SELECT COUNT(1) FROM trades") or 0
    pnl = _q1("SELECT COALESCE(SUM(pnl),0) FROM trades") or 0.0
    return int(trades), float(pnl)

def ok_auto_promote():
    trades = int((get_metric("trades_cnt", 0) or 0))
    days = (_utcnow() - load_state()[1]).days if load_state() else 0
    te = float(get_metric("tracking_err_p95", 0) or 0)
    slp = float(get_metric("slippage_p95", 0) or 0)
    mfr = float(get_metric("missed_fill_rate", 0) or 0)
    return (trades >= LIVE_MIN_TRADES and days >= LIVE_MIN_DAYS
            and te <= TRACKING_ERR_MAX and slp <= SLIPPAGE_P95_MAX
            and mfr <= MISSED_FILL_RATE_MAX)

def ok_performance():
    t, p = stats()
    return (t >= PROMOTE_MIN_TRADES) and (p >= PROMOTE_MIN_PNL)

def select_exec():
    force = os.getenv("FORCE_MODE", "").lower()
    if force == "live": return exec_live
    if force == "paper": return exec_shadow
    mode, started_at = load_state()
    days = (_utcnow() - started_at).days if started_at else 0
    if mode == "paper" and ok_auto_promote():
        update_mode("live")
        return exec_live
    return exec_shadow if mode != "live" else exec_live

EXEC = select_exec()