import os, time, re
def _ok(rule:str, ctx:dict):
    # rule: "WR>=0.53&PF>=1.15&DD_day<=0.03"
    for expr in rule.split("&"):
        k,op,v=re.split(r'(>=|<=|>|<|==)', expr); x=float(ctx.get(k.strip(), 0))
        y=float(v); 
        if op==">=" and not (x>=y): return False
        elif op=="<=" and not (x<=y): return False
        elif op==">" and not (x> y): return False
        elif op=="<" and not (x< y): return False
        elif op=="==" and not (x==y): return False
    return True
def phase_gate(day:int, metrics:dict)->bool:
    if day<7: return True
    if day<90: return _ok(os.getenv("PHASE_KPI_7D","WR>=0.5&PF>=1.05"), metrics)
    return _ok(os.getenv("PHASE_KPI_90D","WR>=0.53&PF>=1.15&DD_day<=0.03"), metrics)