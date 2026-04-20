# app.py — Z AutoEvo-Lite v1.1 (축소 자가진화형)
# 최소 의존성: flask, flask-cors, apscheduler, pandas, numpy, python-dotenv
# 포트: 8000 (nginx는 127.0.0.1:8000 프록시)

import os, json, time, random, math, hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from engine.core_loop import start as start_core
start_core()

import strategies
import numpy as np
import pandas as pd
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
SCHED = BackgroundScheduler()

con = sqlite3.connect("/home/z/z/db/z.sqlite")
cur = con.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT,
    strategy TEXT,
    side TEXT,
    pnl REAL
)
""")
con.commit()
con.close()

# ──────────────────────────────────────────────────────────────────────────────
# 0) 경로·환경
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

VERSION = "Z-AutoEvo-Lite v1.1"
Z_HOME = os.environ.get("Z_HOME", os.path.expanduser("~/z/z")).rstrip("/")
PORT = int(os.environ.get("PORT", "8000"))
FLASK_ENV="production"

DIRS = {
    "engine": f"{Z_HOME}/engine",
    "strategies": f"{Z_HOME}/strategies",
    "logs": f"{Z_HOME}/logs",
    "config": f"{Z_HOME}/config",
    "db": f"{Z_HOME}/db",
}

for d in DIRS.values():
    os.makedirs(d, exist_ok=True)

SETTINGS_F = f"{DIRS['db']}/settings.json"
METRICS_F = f"{DIRS['db']}/metrics.json"

def _read_json(fp: str, default: Any) -> Any:
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(fp: str, obj: Any) -> None:
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fp)

def load_setting(key: str, default: Any=None) -> Any:
    st = _read_json(SETTINGS_F, {})
    return st.get(key, default)

def save_setting(key: str, val: Any) -> None:
    st = _read_json(SETTINGS_F, {})
    st[key] = val
    _write_json(SETTINGS_F, st)

def metrics_inc(key: str, by: float=1.0) -> None:
    m = _read_json(METRICS_F, {})
    m[key] = m.get(key, 0) + by
    _write_json(METRICS_F, m)

def metrics_get() -> Dict[str, Any]:
    return _read_json(METRICS_F, {})

# 초기 설정 시드
if not os.path.exists(SETTINGS_F):
    _write_json(SETTINGS_F, {
        "created_at": datetime.utcnow().isoformat(),
        "start_date": datetime.utcnow().date().isoformat(),
        "tier": "A", # 게이팅 시작 티어
        "params": {}, # 운영 파라미터
        "pop": None, # 진화 개체군
        "notes": {"version": VERSION}
    })

# ──────────────────────────────────────────────────────────────────────────────
# 1) 620일 루틴 · 티어 (A~S)
# ──────────────────────────────────────────────────────────────────────────────
# 날짜 기반 티어 전환. 축소형: 범위만 간단화
TIERS = [
    ("A", 0), # 더미·시뮬 관찰
    ("B", 15),
    ("C", 30),
    ("D", 60),
    ("E", 90),
    ("F", 120),
    ("G", 150),
    ("H", 180),
    ("I", 210),
    ("J", 240),
    ("K", 300),
    ("L", 360),
    ("M", 420),
    ("N", 480),
    ("O", 540),
    ("P", 600),
    ("Q", 620), # 실거래 전환 검토
    ("R", 660),
    ("S", 720),
]

# 티어별 허용 전략 묶음(상관도 낮은 3축 고정)
TIER_STRATS = {
    # 초반은 breakoutLite 단독/관찰
    "A": ["breakoutLite"],
    "B": ["breakoutLite", "trendX"],
    "C": ["breakoutLite", "trendX", "alpha1"],
}
# 이후 전 구간 동일 3축(리스크는 사이즈로 조절)
for code, _ in TIERS:
    if code not in TIER_STRATS:
        TIER_STRATS[code] = ["breakoutLite", "trendX", "alpha1"]

def days_since_start() -> int:
    s = load_setting("start_date", datetime.utcnow().date().isoformat())
    d0 = datetime.fromisoformat(s).date()
    return (datetime.utcnow().date() - d0).days

def current_tier() -> Tuple[str, List[str]]:
    d = days_since_start()
    tier = "A"
    for code, day_cut in TIERS:
        if d >= day_cut:
            tier = code
        else:
            break
    # 수동 오버라이드 지원(.env TIER_OVERRIDE)
    ov = os.getenv("TIER_OVERRIDE")
    if ov:
        tier = ov
    return tier, TIER_STRATS[tier]

# ──────────────────────────────────────────────────────────────────────────────
# 2) 데이터 더미/유틸
# ──────────────────────────────────────────────────────────────────────────────
def make_dummy_ohlcv(n: int=500, seed: int=None) -> pd.DataFrame:
    if seed is None:
        seed = random.randint(1, 10_000)
    rng = np.random.default_rng(seed)
    # 간단한 AR(1) 경로 + 볼클러스터링
    ret = rng.normal(0, 0.003, size=n)
    for i in range(1, n):
        ret[i] = 0.2*ret[i-1] + ret[i]
    px = 100*np.exp(np.cumsum(ret))
    high = px*(1 + rng.normal(0.0008, 0.001, size=n))
    low = px*(1 - rng.normal(0.0008, 0.001, size=n))
    open_ = np.roll(px, 1); open_[0] = px[0]
    vol = rng.integers(10_000, 50_000, size=n)
    ts = pd.date_range(end=datetime.utcnow(), periods=n, freq="1min")
    df = pd.DataFrame({"open":open_, "high":high, "low":low, "close":px, "volume":vol}, index=ts)
    return df

# ──────────────────────────────────────────────────────────────────────────────
# 3) 전략들(간소 3축)
# ──────────────────────────────────────────────────────────────────────────────
def _safe(df: pd.DataFrame, need: int) -> bool:
    return (df is not None) and (len(df) >= need)

def run_breakoutLite(df: pd.DataFrame, params: Dict[str,int]) -> Dict[str, Any]:
    n = int(params.get("bo_window", 60))
    if not _safe(df, n+1): return {"name":"breakoutLite","edge":0,"dir":0,"size":0}
    hh = df["high"].rolling(n).max()
    ll = df["low"].rolling(n).min()
    price = df["close"].iloc[-1]
    up = price > hh.iloc[-2]
    dn = price < ll.iloc[-2]
    direction = 1 if up else (-1 if dn else 0)
    atr = (df["high"]-df["low"]).rolling(14).mean().iloc[-1]
    edge = float((price - ll.iloc[-2])/(hh.iloc[-2]-ll.iloc[-2]+1e-9)) if direction==1 else \
           float((hh.iloc[-2]-price)/(hh.iloc[-2]-ll.iloc[-2]+1e-9)) if direction==-1 else 0.0
    size = min(1.0, max(0.0, edge)) # 0~1
    return {"name":"breakoutLite","edge":edge, "dir":direction, "size":size, "atr":float(atr)}

def run_trendX(df: pd.DataFrame, params: Dict[str,int]) -> Dict[str, Any]:
    f = int(params.get("ma_fast", 20)); s = int(params.get("ma_slow", 80))
    if s <= f: s = f*3
    if not _safe(df, s+1): return {"name":"trendX","edge":0,"dir":0,"size":0}
    ma_f = df["close"].rolling(f).mean()
    ma_s = df["close"].rolling(s).mean()
    dir_ = 1 if ma_f.iloc[-1] > ma_s.iloc[-1] else (-1 if ma_f.iloc[-1] < ma_s.iloc[-1] else 0)
    # 기울기 기반 신뢰도
    slope = (ma_f.iloc[-1] - ma_f.iloc[-5])/(ma_f.iloc[-5]+1e-9)
    edge = float(abs(slope))
    size = min(1.0, max(0.0, edge*5))
    return {"name":"trendX","edge":edge, "dir":dir_, "size":size}

def run_alpha1(df: pd.DataFrame, params: Dict[str,int]) -> Dict[str, Any]:
    n = int(params.get("rsi_len", 14))
    if not _safe(df, n+5): return {"name":"alpha1","edge":0,"dir":0,"size":0}
    delta = df["close"].diff()
    up = delta.clip(lower=0).rolling(n).mean()
    dn = -delta.clip(upper=0).rolling(n).mean() + 1e-9
    rs = up/dn
    rsi = 100 - (100/(1+rs))
    r = rsi.iloc[-1]
    dir_ = 1 if r < 30 else (-1 if r > 70 else 0) # 역추세
    edge = float(abs(50 - r)/50.0) # 0~1
    size = min(1.0, max(0.0, edge*0.8))
    return {"name":"alpha1","edge":edge, "dir":dir_, "size":size}

STRAT_FUNCS = {
    "breakoutLite": run_breakoutLite,
    "trendX": run_trendX,
    "alpha1": run_alpha1,
}

# ──────────────────────────────────────────────────────────────────────────────
# 4) 리스크·집계(간소)
# ──────────────────────────────────────────────────────────────────────────────
def kelly_size(edge: float, p: float=0.55) -> float:
    # 간략 Kelly 비율
    b = 1.0
    f = (b*p - (1-p))/b
    f = max(0.0, f) * edge
    return float(np.clip(f, 0, 1))

def ensemble_decision(df: pd.DataFrame, tier_code: str) -> Dict[str, Any]:
    allowed = TIER_STRATS[tier_code]
    params = load_setting("params", {})
    votes = []
    for name in allowed:
        fn = STRAT_FUNCS[name]
        res = fn(df, params)
        votes.append(res)

    # 방향 투표(가중: edge*size)
    w_sum_pos = sum(v["edge"]*v["size"] for v in votes if v["dir"]>0)
    w_sum_neg = sum(v["edge"]*v["size"] for v in votes if v["dir"]<0)
    if w_sum_pos==0 and w_sum_neg==0:
        direction = 0
        edge = 0.0
    else:
        direction = 1 if w_sum_pos >= w_sum_neg else -1
        edge = float(abs(w_sum_pos - w_sum_neg) / (w_sum_pos + w_sum_neg + 1e-9))

    base_size = kelly_size(edge, p=0.55)
    # 티어별 레버 제한
    tier_cap = {
        "A": 0.00, "B": 0.10, "C": 0.15, "D": 0.20, "E": 0.25, "F": 0.30,
        "G": 0.35, "H": 0.40, "I": 0.45, "J": 0.50, "K": 0.55, "L": 0.60,
        "M": 0.65, "N": 0.70, "O": 0.75, "P": 0.80, "Q": 0.85, "R": 0.90, "S": 0.95
    }.get(tier_code, 0.3)
    size = float(np.clip(base_size, 0, tier_cap))
    return {"tier": tier_code, "edge": edge, "dir": direction, "size": size, "votes": votes}

# ──────────────────────────────────────────────────────────────────────────────
# 5) 축소 자가진화(개체군 기반)
# ──────────────────────────────────────────────────────────────────────────────
PARAM_BOUNDS = {
    "bo_window": (30, 120),
    "ma_fast": (10, 40),
    "ma_slow": (60, 160),
    "rsi_len": (8, 28),
}

EVO_ON = int(os.getenv("EVO_ON", "1"))
EVO_POP = int(os.getenv("EVO_POP", "8"))
ELITES = int(os.getenv("EVO_ELITES", "2"))
CV_SEG = int(os.getenv("EVO_CV_SEG", "5"))

def _sample_params() -> Dict[str,int]:
    out = {}
    for k,(lo,hi) in PARAM_BOUNDS.items():
        out[k] = random.randint(lo, hi)
    return out

def _score_params(p: Dict[str,int]) -> float:
    # 더미 CV: 서로 다른 시드로 세그먼트 평가
    scores = []
    for k in range(CV_SEG):
        df = make_dummy_ohlcv(500, seed=1234+k)
        save_setting("params", p)
        tier, _ = current_tier()
        res = ensemble_decision(df, tier)
        scores.append(res["edge"] * (res["size"]+1e-9))
    return float(np.mean(scores))

def evo_step():
    if int(os.getenv("EVO_ON","1")) == 0:
        return
    pop = load_setting("pop", None)
    if not pop:
        pop = [{"p": _sample_params(), "s": None} for _ in range(EVO_POP)]

    # 점수 갱신
    for c in pop:
        c["s"] = _score_params(c["p"])

    pop.sort(key=lambda x: x["s"], reverse=True)
    elites = pop[:ELITES]

    # 변이+교배
    new_pop = elites[:]
    while len(new_pop) < EVO_POP:
        a,b = random.sample(elites, 2) if len(elites) >= 2 else (elites[0], elites[0])
        child = {}
        for k in PARAM_BOUNDS.keys():
            lo,hi = PARAM_BOUNDS[k]
            v = random.choice([a["p"][k], b["p"][k]])
            step = max(1, int((hi-lo)*0.05))
            v = int(np.clip(v + random.randint(-step, step), lo, hi))
            child[k] = v
        new_pop.append({"p": child, "s": None})

    best = elites[0]["p"]
    save_setting("params", best)
    save_setting("pop", new_pop)
    metrics_inc("evo_ticks", 1)

# ──────────────────────────────────────────────────────────────────────────────
# 6) 서비스·스케줄러
# ──────────────────────────────────────────────────────────────────────────────
def create_app():
    app = Flask(__name__)
    CORS(app)
    from frontend.dashboard import bp as dashboard_bp

def _init_once():
    pass
    
    app.register_blueprint(dashboard_bp, url_prefix="/")
    return app

def boot():
    if not SCHED.running:
        SCHED.start()

def heartbeat():
    metrics_inc("heartbeat", 1)

def heartbeat():
    print("heartbeat tick")


def rotate_logs():
    metrics_inc("log_rot", 1)

# 10분 하트비트, 6시간 진화, 1일 로그회전
SCHED.add_job(heartbeat, "interval", minutes=10, id="heartbeat")
SCHED.add_job(evo_step, "interval", hours=6, id="evo_step")
SCHED.add_job(rotate_logs, "cron", hour=3, minute=10, id="logrotate")
SCHED.add_job(lambda: __import__("engine.runner").engine.runner.select_exec(),
              "interval", minutes=10, id="promote_check", replace_existing=True)

# ──────────────────────────────────────────────────────────────────────────────
# 7) API
# ──────────────────────────────────────────────────────────────────────────────

from os import getenv
PHASE_DONE = int(getenv("PHASE_DONE","620"))
MONTHLY_DAY = getenv("MONTHLY_EVO_DAY","1")
MONTHLY_HR = getenv("MONTHLY_EVO_HOUR","3")

def phase_watcher():
    d = days_since_start()
    if d >= PHASE_DONE:
        os.environ["EVO_ON"] = "0"
        try: SCHED.remove_job("evo_step")
        except: pass
        SCHED.add_job(evo_step, "cron", day=MONTHLY_DAY, hour=MONTHLY_HR,
                      minute=5, id="evo_monthly", replace_existing=True)
    else:
        ids = {j.id for j in SCHED.get_jobs()}
        if "evo_step" not in ids:
            SCHED.add_job(evo_step, "interval", hours=6,
                          id="evo_step", replace_existing=True)

SCHED.add_job(phase_watcher, "cron", hour=0, minute=5,
              id="phase_watcher", replace_existing=True)
# ──────────────────────────────────────────────────────────────────────────────
# 8) 메인
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 최초 파라미터 부재 시 샘플 세팅
    if not load_setting("params", None):
        save_setting("params", {
            "bo_window": 60,
            "ma_fast": 20,
            "ma_slow": 80,
            "rsi_len": 14
        })
    app.run(host="0.0.0.0", port=8000, debug=False)