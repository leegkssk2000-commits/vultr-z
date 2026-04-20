# engine/fvg_tuner.py
import os, math, sqlite3, time, json, itertools, random
DB="/home/z/z/db/z.sqlite"; PHASE=os.getenv("FVG_TUNE_PHASE","0-90")
ARMS=list(itertools.product(
  [int(x) for x in os.getenv("FVG_ARMS_PCT","3,4,5,6,7").split(",")],
  os.getenv("FVG_ARMS_TF","1h,4h").split(","),
  os.getenv("FVG_ARMS_HALF","on,off").split(",")
))
def _db():
  c=sqlite3.connect(DB); c.execute("""CREATE TABLE IF NOT EXISTS fvg_trials(
    ts INTEGER, arm TEXT, trades INT, pf REAL, wr REAL, dd REAL, cost REAL, score REAL)"""); return c
def reward(pf,wr,dd,cost):
  Ri=max(cost,1e-6); Vi=max(0.0,min(pf,3.0)); Fi=max(0.0,min(wr,1.0)); Ni=max(0.3, 1.0-(dd/0.02))
  return (Vi*Fi*Ni)/Ri
def choose_arm():
  c=_db(); t=int(time.time())
  rows=c.execute("SELECT arm, AVG(score), COUNT(*) FROM fvg_trials GROUP BY arm").fetchall()
  if not rows: return random.choice(ARMS)
  n_total=sum(r[2] for r in rows)
  def ucb(mean, n): return mean + math.sqrt(2*math.log(n_total+1)/(n+1))
  by={r[0]:ucb(r[1],r[2]) for r in rows}
  for a in ARMS:
    if str(a) not in by: return a # 미시도 우선
  return max(by.items(), key=lambda x:x[1])[0]
def log_trial(arm, trades, pf, wr, dd, cost):
  sc=reward(pf,wr,dd,cost); c=_db()
  c.execute("INSERT INTO fvg_trials VALUES (?,?,?,?,?,?,?,?)",
            (int(time.time()), str(arm), trades, pf, wr, dd, cost, sc)); c.commit()
def current_params(days_since_start):
  if os.getenv("FVG_AUTOTUNE","on")!="on": return (int(os.getenv("FVG_BASE_PCT","5")),"4h","on")
  if days_since_start >= int(os.getenv("FVG_LOCK_AFTER_D","90")):
    c=_db(); r=c.execute("SELECT arm, AVG(score) s FROM fvg_trials GROUP BY arm ORDER BY s DESC LIMIT 1").fetchone()
    return eval(r[0]) if r else (int(os.getenv("FVG_BASE_PCT","5")),"4h","on")
  return choose_arm()
