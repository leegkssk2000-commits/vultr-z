#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
ROOT=/opt/zel/research-runtime/jobs/structural-premium-v2
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1
DUR=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2
ENG=$ROOT/engine/replay_v1_v2.py
READINESS=$ROOT/advisory/v2_replay_readiness.json
OUT=$ROOT/baseline_next_open_v1
LANE=$ROOT/engine/lane_baseline_v2.py
REPORT=$OUT/strategy_edge_report.json
CANON=/opt/zel/forward-expansion-v1/source

for p in "$ENG" "$READINESS" "$BASE/work/engine/lane_checkpoint_v2.py" "$DUR/work/data"; do
  test -e "$p"
done

"$PY" - "$READINESS" <<'PYREADY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
if p.get('state')!='PASS_V2_REPLAY_ENGINE_READY_FOR_AXIS_WORK': raise SystemExit('V2_REPLAY_NOT_READY')
if p.get('machine_gate')!='PASS' or p.get('smoke')!='PASS': raise SystemExit('V2_REPLAY_GATES_NOT_PASS')
if p.get('research_only') is not True or p.get('execution_authority')!='NONE' or p.get('order_authority')!='BLOCKED': raise SystemExit('V2_RESEARCH_AUTHORITY_MISMATCH')
print('PASS_V2_READINESS_PRECONDITION')
PYREADY

canon_hash() {
  { find "$CANON/backend/strategies" -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | sort -z | xargs -0 sha256sum; sha256sum "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json"; } | sha256sum | awk '{print $1}'
}
BEFORE=$(canon_hash)
verify_canonical() {
  rc=$?
  trap - EXIT
  AFTER=$(canon_hash)
  if [ "$AFTER" != "$BEFORE" ]; then
    echo "CRITICAL_CANONICAL_MUTATION before=$BEFORE after=$AFTER" >&2
    exit 97
  fi
  echo "PASS_CANONICAL_UNCHANGED $AFTER"
  exit "$rc"
}
trap verify_canonical EXIT

mkdir -p "$OUT" "$ROOT/engine"
cp "$BASE/work/engine/lane_checkpoint_v2.py" "$LANE"
"$PY" -m py_compile "$LANE" "$ENG"

# Resumable 3 strategies x 3 windows x 5 symbols = 45 lane units.
"$PY" "$LANE" \
  --engine-v1 "$ENG" \
  --engine-v2 "$BASE/work/engine/replay_v2_no_trend.py" \
  --source-root "$BASE/work/source" \
  --data-root "$DUR/work/data" \
  --interval 1m \
  --output-dir "$OUT" \
  --workers 4 2>&1 | tee "$OUT/baseline.log"

COUNT=$(find "$OUT/lane_checkpoints" -type f -name '*.json.gz' | wc -l)
test "$COUNT" -eq 45 || { echo "BASELINE_LANE_COUNT:$COUNT" >&2; exit 10; }

"$PY" - "$ENG" "$OUT/lane_checkpoints" "$REPORT" <<'PYREPORT'
import gzip,importlib.util,json,sys
from collections import defaultdict
from pathlib import Path
engp,root,out=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('spv2_baseline_metrics',engp)
e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e; assert spec.loader is not None; spec.loader.exec_module(e)
strategies=('vwap_revert','support_resistance','liquidity_sweep')
windows=('1m_w1','1m_w2','1m_w3')
by={s:defaultdict(list) for s in strategies}; errors={s:0 for s in strategies}; opens={s:0 for s in strategies}; files={s:0 for s in strategies}
all_rows=[]
for p in sorted(root.rglob('*.json.gz')):
    with gzip.open(p,'rt',encoding='utf-8') as h:d=json.load(h)
    r=d.get('result') or {}; s=str(r.get('strategy_id') or d.get('strategy_id') or ''); w=str(r.get('window_id') or d.get('window_id') or '')
    if s not in by: raise SystemExit(f'UNEXPECTED_STRATEGY:{s}:{p}')
    if w not in windows: raise SystemExit(f'UNEXPECTED_WINDOW:{w}:{p}')
    files[s]+=1; errors[s]+=int(r.get('error_count') or 0); opens[s]+=int(r.get('open_count') or 0)
    rows=list(r.get('closed_rows') or []); by[s][w].extend(rows); all_rows.extend(rows)
for s in strategies:
    if files[s]!=15: raise SystemExit(f'STRATEGY_LANE_COUNT:{s}:{files[s]}')
    if errors[s]!=0: raise SystemExit(f'STRATEGY_ERRORS:{s}:{errors[s]}')

def pack(rows):
    m=e.metrics(rows)
    return {**m,'long':e.metrics([x for x in rows if x.get('side')=='long']),'short':e.metrics([x for x in rows if x.get('side')=='short'])}
strategy_report={}
for s in strategies:
    rows=[x for w in windows for x in by[s][w]]
    strategy_report[s]={
      'lane_files':files[s],'open_count':opens[s],'overall':pack(rows),
      'by_window':{w:pack(by[s][w]) for w in windows},
    }
combined=pack(all_rows)
rank=sorted(strategies,key=lambda s:(-float(strategy_report[s]['overall'].get('net_R') or 0),-float(strategy_report[s]['overall'].get('win_rate_pct') or 0)))
payload={
 'schema_version':'zel.structural_premium.v2.next_open.baseline.v1',
 'state':'PASS_V2_NEXT_OPEN_BASELINE_45_OF_45',
 'execution_model':'NEXT_BAR_OPEN_PRESERVE_ABS_RISK_REWARD_DISTANCE',
 'lane_files_total':45,
 'selection_windows_consumed':['1m_w1','1m_w2','1m_w3'],
 'fresh_final_oos_required':True,
 'combined':combined,
 'strategies':strategy_report,
 'rank_by_net_then_wr':rank,
 'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold',
}
out.write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n')
print('STATE',payload['state'])
print('COMBINED',json.dumps(combined,sort_keys=True))
for s in strategies: print('STRATEGY',s,json.dumps(strategy_report[s]['overall'],sort_keys=True))
print('RANK',rank)
PYREPORT

cat "$REPORT"
