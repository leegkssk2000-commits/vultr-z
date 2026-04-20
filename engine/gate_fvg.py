# engine/gate_fvg.py
from engine.fvg_tuner import current_params, log_trial
def fvg_params(ctx): # ctx.start_ts 등 사용
    days=int((time.time()-ctx.start_ts)/86400)
    return current_params(days) # (pct, tf, half)

# 백테스트/모의 결과 집계 후 주기적으로 기록
# log_trial(arm=(pct,tf,half), trades=N, pf=PF, wr=WR, dd=DD_day, cost=cost_bps/10000)