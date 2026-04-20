# 주문 라우터: 전략 신호 -> 실행기(place) 호출
from datetime import datetime, timezone
from config.settings import PROMOTE_MIN_TRADES, PROMOTE_MIN_PNL, PAPER_DAYS, FORCE_MODE
from engine import exec_shadow # 모의 실행기(이미 있음)
# TODO: 실거래 실행기 준비되면 아래 import 교체
# from engine.exec_binance import exec_live
exec_live = None

import os, sqlite3
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "db", "z.sqlite"))

def _q1(sql, p=()):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute(sql, p); r = cur.fetchone()
    con.close(); return (r[0] if r else None)

def _now(): return datetime.now(timezone.utc)

def _load_mode():
    m = _q1("SELECT mode FROM app_state WHERE id=1")
    t = _q1("SELECT started_at FROM app_state WHERE id=1")
    if not m: return "paper", _now()
    try: started = datetime.fromisoformat(t.replace("Z","+00:00")) if t else _now()
    except: started = _now()
    return m, started

def _update_mode(m):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE app_state SET mode=? WHERE id=1", (m,)); con.commit(); con.close()

def _ok_perf():
    trades = int(_q1("SELECT COUNT(1) FROM trades") or 0)
    pnl = float(_q1("SELECT COALESCE(SUM(pnl),0) FROM trades") or 0.0)
    return trades >= PROMOTE_MIN_TRADES and pnl >= PROMOTE_MIN_PNL

def _select_exec():
    if FORCE_MODE == "paper": return exec_shadow
    if FORCE_MODE == "live": return exec_live or exec_shadow
    mode, started = _load_mode()
    days = (_now() - started).days
    if mode == "paper" and days >= PAPER_DAYS and _ok_perf() and exec_live:
        _update_mode("live"); return exec_live
    return exec_shadow if (mode == "paper" or not exec_live) else exec_live

def handle_signal(symbol: str, sig: dict, base_qty: float = 1.0):
    """전략 신호(dict) -> 주문 실행기 호출. 없으면 스킵."""
    if not sig or sig.get("side") not in ("buy", "sell"):
        return {"status": "skip"}

    conf = float(sig.get("confidence", 0.0))
    qty = max(0.0, min(1.0, conf)) * float(base_qty) # 신뢰도로 사이즈 스케일
    ex = _select_exec()
    # 실행기의 인터페이스: place(symbol, side, qty, price=None, meta=None)
    return ex.place(symbol=symbol, side=sig["side"], qty=qty,
                    meta={"source": sig.get("source"), "ttl": sig.get("ttl")})