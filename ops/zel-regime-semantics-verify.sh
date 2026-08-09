#!/usr/bin/env bash
set -euo pipefail
PY=/home/z/z/.venv/bin/python
P=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/source/tools/q4r3_exact25_dedicated_shadow_producer.py
E=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2/work/engine/replay_v1.py
T=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/replay/trades.jsonl.gz
C=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1/gen2/runs/C120_FASTSALVAGE/replay_w2/lane_checkpoints/vwap_revert

echo '===REGIME_SEMANTICS==='
grep -n -A70 '^def close_position' "$P" | grep -E 'def close_position|exit_features|"regime"|entry_features|exit_features' || true

echo '===ENTRY_BIAS_COHORTS==='
"$PY" - "$E" "$T" "$C" <<'PY'
import gzip,importlib.util,json,sys
from collections import defaultdict
from pathlib import Path
engp,tradesp,croot=Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3])
spec=importlib.util.spec_from_file_location('entrybias',engp)
e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e
assert spec.loader is not None; spec.loader.exec_module(e)
def entry_bias(r):
    ef=r.get('entry_features') or {}
    return str(ef.get('htf_bias') or 'unknown') if isinstance(ef,dict) else 'unknown'
def group(rows,label):
    buckets=defaultdict(list)
    for r in rows:buckets[entry_bias(r)].append(r)
    print(label,'OVERALL',json.dumps(e.metrics(rows),sort_keys=True))
    for k in sorted(buckets):
        print(label,'ENTRY_BIAS',k,json.dumps(e.metrics(buckets[k]),sort_keys=True))
    exits=defaultdict(list)
    for r in rows:exits[str(r.get('regime') or 'unknown')].append(r)
    for k in sorted(exits):
        print(label,'EXIT_BIAS',k,json.dumps(e.metrics(exits[k]),sort_keys=True))
base=[]
with gzip.open(tradesp,'rt',encoding='utf-8') as h:
    for line in h:
        r=json.loads(line)
        if r.get('strategy_id')=='vwap_revert' and r.get('side')=='long' and str(r.get('window_id'))=='1m_w2':base.append(r)
cand=[]
for p in sorted(croot.glob('*.json.gz')):
    with gzip.open(p,'rt',encoding='utf-8') as h:d=json.load(h)
    cand += [r for r in (d.get('result') or {}).get('closed_rows') or [] if r.get('side')=='long']
if len(base)!=48 or len(cand)!=48: raise SystemExit(f'ROW_COUNT:{len(base)}:{len(cand)}')
group(base,'BASE')
group(cand,'C120')
PY
