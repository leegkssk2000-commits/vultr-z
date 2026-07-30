from __future__ import annotations
import json
from backend.tools.strategy11_expanded_discovery_v3 import combine_stats

def main():
    saturated=combine_stats([{"net_return_pct":1.0},{"net_return_pct":-1e-14}])
    regular=combine_stats([{"net_return_pct":1.0},{"net_return_pct":-0.5}])
    assert saturated["net_profit_factor"]==999.0
    assert saturated["payoff_ratio"]==0.0
    assert regular["net_profit_factor"]==2.0
    assert regular["payoff_ratio"]==2.0
    print(json.dumps({"state":"PASS_V3_PF_EPSILON_FIXTURE"},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
