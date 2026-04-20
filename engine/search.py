import json, random, itertools, time
from engine.evolve import log_trial, score
from engine.exec_shadow import simulate_7d as simulate_14d # TODO: 14d 실제 모의로 교체
CONF="/home/z/z/config/evolve.json"
def cfg(): return json.loads(open(CONF,"r",encoding="utf-8").read())
def combos(pool, kmax):
    # entry 1, filter ≤1, exit ≤1, risk ≤1, 총 ≤kmax
    E=[("entry",[e]) for e in pool["entry"]]
    F=[("filter",[f]) for f in pool["filter"]]+[("filter",[])]
    X=[("exit",[x]) for x in pool["exit"]]+[("exit",[])]
    R=[("risk",[r]) for r in pool["risk"]]+[("risk",[])]
    for e in E:
      for f in F:
        for x in X:
          for r in R:
            blocks={"entry":e[1], "filter":f[1], "exit":x[1], "risk":r[1]}
            if sum(len(v) for v in blocks.values())<=kmax: yield blocks
def sample_candidates(P:int):
    C=cfg(); P=max(2,P); S=C["param_space"]; pool=C["blocks_pool"]; kmax=C.get("block_max",6)
    # 파라 샘플
    def pick(): return {k: random.choice(v) for k,v in S.items()}
    # 블록 샘플
    B=list(combos(pool, kmax)); random.shuffle(B)
    out=[]
    for i in range(P):
        out.append({"id":f"s{i+1}","params":pick(),"blocks": B[i%len(B)]})
    return out
def evolve_struct(gen:int, pop:int):
    cands=sample_candidates(pop)
    for c in cands:
        pf,wr,dd,cost = simulate_14d(c["params"]) # 구조 반영 전 스텁. 엔진 연동 시 params+blocks 모두 반영
        j=score({"pf":pf,"wr":wr,"dd_day":dd,"cost_bps":cost})
        log_trial(gen, c["id"], {**c["params"], **{"BLOCKS":c["blocks"]}}, pf, wr, dd, cost, tag="struct")
    return True