from __future__ import annotations
import json
from backend.tools.strategy11_expanded_discovery_v3 import annotate_observer_trades
from backend.tools.strategy11_long_short_observer_v3 import chronological, stats

def main():
    raw=[
      {"side":"long","entry_ts":"2026-01-02T00:00:00+00:00","exit_ts":"2026-01-02T00:15:00+00:00","net_return_pct":-1.0},
      {"side":"long","entry_ts":"2026-01-01T00:00:00+00:00","exit_ts":"2026-01-01T00:15:00+00:00","net_return_pct":2.0},
    ]
    a=annotate_observer_trades([raw[0]],window_id="A02",symbol="ETHUSDT")
    b=annotate_observer_trades([raw[1]],window_id="A01",symbol="BTCUSDT")
    ordered=chronological(a+b)
    assert [row["window_id"] for row in ordered]==["A01","A02"]
    assert all("symbol" in row for row in ordered)
    metric=stats(ordered)
    assert metric["trade_count"]==2 and metric["max_drawdown_pct"]==1.0
    epsilon=stats([{"window_id":"A01","symbol":"BTCUSDT","entry_ts":"1","exit_ts":"2","side":"long","net_return_pct":1.0},{"window_id":"A01","symbol":"BTCUSDT","entry_ts":"3","exit_ts":"4","side":"long","net_return_pct":-1e-14}])
    assert epsilon["net_profit_factor"]==999.0
    print(json.dumps({"state":"PASS_V3_OBSERVER_INTEGRITY_FIXTURE"},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
