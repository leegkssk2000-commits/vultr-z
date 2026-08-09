#!/usr/bin/env bash
set -euo pipefail
P=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/source/tools/q4r3_exact25_dedicated_shadow_producer.py
E=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2/work/engine/replay_v1.py
T=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/replay/trades.jsonl.gz

echo '===CLOSE_POSITION_DEF==='
grep -n -A140 -B20 '^def close_position' "$P" | head -190

echo '===MAKE_POSITION_DEF==='
grep -n -A130 -B20 '^def make_position' "$P" | head -180

echo '===REGIME_ASSIGNMENTS==='
grep -RIn --exclude='*.pyc' --exclude-dir='__pycache__' -E '"regime"|regime=' "$P" "$E" | head -120 || true

echo '===TRADE_REGIME_SAMPLE==='
/home/z/z/.venv/bin/python - "$T" <<'PY'
import gzip,json,sys
p=sys.argv[1]
n=0
with gzip.open(p,'rt',encoding='utf-8') as h:
    for line in h:
        r=json.loads(line)
        if r.get('strategy_id')=='vwap_revert' and r.get('side')=='long' and r.get('window_id')=='1m_w2':
            print(json.dumps({k:r.get(k) for k in ('entry_ts','exit_ts','opened_at','closed_at','regime','entry_regime','htf_bias','entry_features','exit_features','captured_at') if k in r},sort_keys=True))
            n+=1
            if n>=5:
                break
PY
