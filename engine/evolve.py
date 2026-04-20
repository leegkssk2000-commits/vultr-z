import os, json, random, sqlite3, time, itertools, math
CONF="/home/z/z/config/evolve.json"; DB="/home/z/z/db/z.sqlite"
def cfg():
    with open(CONF,"r",encoding="utf-8") as f: return json.load(f)
def arms(space):
    keys=list(space.keys())
    vals=[space[k] for k in keys]
    for comb in itertools.product(*vals):
        yield dict(zip(keys, comb))
def score(row):
    # PF, WR, DD_day, Cost_bps → 목표함수 J
    PF=max(0.0, min(float(row["pf"]), 3.0))
    WR=max(0.0, min(float(row["wr"]), 1.0))
    DD=max(0.0, float(row["dd_day"]))
    C =max(1e-6, float(row["cost_bps"])/10000.0)
    Ni=max(0.3, 1.0 - min(0.02, DD)/0.02)
    return (PF*WR*Ni)/C
def db():
    c=sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS evo_trials(
      ts INTEGER, gen INT, id TEXT, params TEXT, pf REAL, wr REAL, dd_day REAL, cost_bps REAL, j REAL, tag TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS evo_champion(
      ts INTEGER, params TEXT, j REAL)""")
    return c
def select_parents(rows, k=4):
    rows=sorted(rows, key=lambda r:r["j"], reverse=True)
    return rows[:k]
def mutate(p, space, rate=0.25):
    q=p.copy()
    for k in space:
        if random.random()<rate:
            q[k]=random.choice(space[k])
    return q
def run_generation(gen:int):
    C=cfg(); S=C["param_space"]; P=C["pop"]; E=C["elitism"]
    # 후보 생성: 상위 E + 변이로 채움
    c=db()
    prev=c.execute("SELECT params,j FROM evo_trials WHERE gen=? ORDER BY j DESC", (gen-1,)).fetchall()
    seeds=[json.loads(p) for p,_ in prev[:E]] if prev else []
    pool=[]
    if seeds: pool+=seeds
    while len(pool)<P:
        if seeds: pool.append(mutate(random.choice(seeds), S))
        else: pool.append(random.choice(list(arms(S))))
    # 섀도우 실행: 외부 실행기와 연동(전략엔진에서 7d 모의 후 아래 insert 호출)
    return pool # 엔진이 받아서 실험 후 log_trial 호출
def log_trial(gen:int, pid:str, params:dict, pf:float, wr:float, dd_day:float, cost_bps:float, tag:str="shadow"):
    j=score({"pf":pf,"wr":wr,"dd_day":dd_day,"cost_bps":cost_bps})
    c=db(); c.execute("INSERT INTO evo_trials VALUES (?,?,?,?,?,?,?,?,?,?)",
        (int(time.time()), gen, pid, json.dumps(params), pf, wr, dd_day, cost_bps, j, tag)); c.commit()
def champion_if_ok(gen:int):
    C=cfg(); gate=C["live_gate"]; c=db()
    r=c.execute("SELECT params,j, pf,wr,dd_day,cost_bps FROM evo_trials WHERE gen=? ORDER BY j DESC LIMIT 1",(gen,)).fetchone()
    if not r: return None
    params=json.loads(r[0]); j=r[1]; pf,wr,dd,cb=r[2],r[3],r[4],r[5]
    if wr>=gate["WR"] and pf>=gate["PF"] and dd<=gate["DD_day"] and cb<=gate["Cost_bps"]:
        c.execute("INSERT INTO evo_champion VALUES (?,?,?)",(int(time.time()), json.dumps(params), j)); c.commit()
        return params
    return None