from __future__ import annotations

import json
import tempfile
from pathlib import Path
import pandas as pd
from backend.tools.strategy11_expanded_discovery_v3 import load_archive_cache, materiality_evidence

class Exact:
    def __init__(self): self.calls=0
    def compute_feature_frame(self,frame): self.calls+=1; return frame.assign(feature=1.0)

def main():
    policy={"classification":{"materiality":{"net_return_pct_points_min":0.25,"profit_factor_min":0.05,"payoff_ratio_min":0.05,"drawdown_pct_points_min":0.10,"material_metrics_min":2}}}
    control={"net_return_pct_sum":10.0,"net_profit_factor":1.5,"payoff_ratio":2.0,"max_drawdown_pct":3.0}
    tiny={"net_return_pct_sum":10.12,"net_profit_factor":1.51,"payoff_ratio":2.01,"max_drawdown_pct":3.0}
    meaningful={"net_return_pct_sum":10.40,"net_profit_factor":1.56,"payoff_ratio":2.01,"max_drawdown_pct":2.85}
    saturated_control={**control,"net_profit_factor":999.0}; saturated_candidate={**meaningful,"net_profit_factor":1e14}
    assert materiality_evidence(tiny,control,policy)["improved_count"]==0
    evidence=materiality_evidence(meaningful,control,policy)
    assert evidence["flags"]["net"] and evidence["flags"]["pf"] and evidence["flags"]["dd"]
    assert materiality_evidence(saturated_candidate,saturated_control,policy)["flags"]["pf"] is False
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); frame=pd.DataFrame({"timestamp_ms":[1,2],"open":[1,1],"high":[1,1],"low":[1,1],"close":[1,1],"volume":[1,1]}); rows=[]
        for window in ("A01","A02"):
            p=root/f"{window}-BTCUSDT.csv"; frame.to_csv(p,index=False); rows.append({"window_id":window,"symbol":"BTCUSDT","path":p.name})
        exact=Exact(); cache=load_archive_cache(root,{"rows":rows},exact)
        assert len(cache)==2 and exact.calls==2 and "feature" in cache[("A01","BTCUSDT")][1].columns
    print(json.dumps({"state":"PASS_V3_MATERIALITY_CACHE_FIXTURE"},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
