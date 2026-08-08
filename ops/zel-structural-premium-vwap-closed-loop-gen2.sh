#!/usr/bin/env bash
set -euo pipefail

DUR=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1
ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
G="$ROOT/gen2"
PY=/home/z/z/.venv/bin/python
CANON=/opt/zel/forward-expansion-v1/source
AI_CONTRACT="$G/advisory/gen2_ai_contract.json"
SELF=$(readlink -f "${BASH_SOURCE[0]}")

for p in "$DUR/work/engine/replay_v1.py" "$DUR/work/engine/replay_v2.py" "$DUR/work/engine/lane_checkpoint_v2.py" "$BASE/work/replay/trades.jsonl.gz" "$BASE/work/source/backend/strategies/vwap_revert.py"; do test -s "$p"; done

# The workflow may start while the AI-design job is still finishing. Wait, do not race it.
for i in $(seq 1 120); do
  [ -s "$AI_CONTRACT" ] && break
  sleep 5
done
test -s "$AI_CONTRACT" || { echo FAIL_AI_CONTRACT_TIMEOUT >&2; exit 91; }

mapfile -t CIDS < <("$PY" - "$AI_CONTRACT" <<'PYIDS'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text()); ids=d.get('candidate_ids') or []
if len(ids)!=3: raise SystemExit('AI_CONTRACT_EXPECTS_3')
for x in ids: print(str(x))
PYIDS
)
[ "${#CIDS[@]}" -eq 3 ]
for cid in "${CIDS[@]}"; do test -s "$G/candidates/$cid.json"; done

echo "GEN2_AI_CANDIDATES=${CIDS[*]}"

# Reap only orphan Gen2 workers from prior cancelled attempts.
PIDS=$(pgrep -f "$ROOT/gen2/runs/.*/engine/lane_.*\.py" || true)
if [ -n "$PIDS" ]; then kill -TERM $PIDS 2>/dev/null || true; sleep 2; fi
PIDS=$(pgrep -f "$ROOT/gen2/runs/.*/engine/lane_.*\.py" || true)
if [ -n "$PIDS" ]; then kill -KILL $PIDS 2>/dev/null || true; sleep 1; fi
if pgrep -f "$ROOT/gen2/runs/.*/engine/lane_.*\.py" >/dev/null; then echo FAIL_ORPHAN_GEN2_WORKERS >&2; exit 96; fi

canonical_fingerprint() {
  {
    find "$CANON/backend/strategies" -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | sort -z | xargs -0 sha256sum
    sha256sum "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json"
  } | sha256sum | awk '{print $1}'
}
CANON_BEFORE=$(canonical_fingerprint)
verify_canonical_on_exit() {
  rc=$?; after=$(canonical_fingerprint)
  if [ "$after" != "$CANON_BEFORE" ]; then echo "CRITICAL_CANONICAL_MUTATION before=$CANON_BEFORE after=$after" >&2; exit 97; fi
  echo "PASS_CANONICAL_TREE_UNCHANGED $after"; return "$rc"
}
trap verify_canonical_on_exit EXIT

mkdir -p "$G/runs" "$G/result"

DATASET_ID=$(sha256sum "$BASE/work/replay/trades.jsonl.gz" | awk '{print $1}')
BASE_CONTRACT=$(
  {
    printf '%s\n' 'VWAP_GEN2_AI_W2_FIRST_V1' "$DATASET_ID"
    sha256sum "$SELF" "$AI_CONTRACT" "$DUR/work/engine/replay_v1.py" "$DUR/work/engine/replay_v2.py" "$DUR/work/engine/lane_checkpoint_v2.py" "$BASE/work/source/backend/strategies/vwap_revert.py"
  } | sha256sum | awk '{print $1}'
)
echo "GEN2_BASE_CONTRACT=$BASE_CONTRACT"

# Baselines only for W2/W1. W3 remains unopened until a W12 winner exists.
"$PY" - "$DUR/work/engine/replay_v1.py" "$BASE/work/replay/trades.jsonl.gz" "$G/result/baseline_w12.json" <<'PYBASE'
import gzip,importlib.util,json,sys
from pathlib import Path
eng,trades,out=map(Path,sys.argv[1:]); spec=importlib.util.spec_from_file_location('g2base',eng); e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e; spec.loader.exec_module(e)
rows={'1m_w1':[],'1m_w2':[]}
with gzip.open(trades,'rt',encoding='utf-8') as h:
  for line in h:
    r=json.loads(line); w=str(r.get('window_id'))
    if w in rows and r.get('strategy_id')=='vwap_revert' and r.get('side')=='long': rows[w].append(r)
p={'schema_version':'zel.structural_premium.vwap.gen2_baseline.v1','by_window':{w:e.metrics(v) for w,v in rows.items()},'w3_metrics_present':False,'research_only':True,'action':'hold'}
out.write_text(json.dumps(p,indent=2,sort_keys=True,allow_nan=False)+'\n'); print(json.dumps({'state':'PASS_GEN2_BASELINE_W12','by_window':p['by_window']},sort_keys=True))
PYBASE

prepare_candidate() {
  cid="$1"; cjson="$G/candidates/$cid.json"; run="$G/runs/$cid"
  contract=$( { printf '%s\n' "$BASE_CONTRACT"; sha256sum "$cjson"; } | sha256sum | awk '{print $1}')
  valid=0
  if [ -s "$run/contract.sha256" ] && [ "$(cat "$run/contract.sha256")" = "$contract" ] && [ -s "$run/engine/replay_v1_candidate.py" ] && [ -s "$run/engine/replay_v2_candidate.py" ]; then
    "$PY" -m py_compile "$run/engine/replay_v1_candidate.py" "$run/engine/replay_v2_candidate.py" >/dev/null 2>&1 && valid=1 || true
  fi
  if [ "$valid" = 1 ]; then echo "RESUME_GEN2_VALIDATED $cid"; return; fi
  rm -rf "$run"; mkdir -p "$run/engine" "$run/result" "$run/logs"
  cp "$DUR/work/engine/replay_v1.py" "$run/engine/replay_v1_candidate.py"
  cp "$DUR/work/engine/replay_v2.py" "$run/engine/replay_v2_candidate.py"
  "$PY" - "$run/engine/replay_v1_candidate.py" "$run/engine/replay_v2_candidate.py" "$cjson" <<'PYPATCH'
import json,re,sys
from pathlib import Path
p1,p2,cpath=map(Path,sys.argv[1:]); c=json.loads(cpath.read_text()); q=c['parameters']
for k,lo,hi in [('stop_distance_mult',.70,1.25),('target_distance_mult',.80,1.50),('cooldown_min',0,120),('min_risk_distance_pct',0,2),('max_hold_min',15,240)]:
    v=float(q[k]);
    if not lo<=v<=hi: raise SystemExit(f'RANGE:{k}:{v}')
mc=q.get('min_confidence')
if mc is not None and not 0<=float(mc)<=.90: raise SystemExit(f'RANGE:min_confidence:{mc}')
if q.get('enabled_entry_owners')!=['vwap_revert']: raise SystemExit('VWAP_ONLY_REQUIRED')
t=p1.read_text()
if t.count('EXPECTED_STRATEGY_COUNT = 4')!=1: raise SystemExit('V1_COUNT_ANCHOR')
t=t.replace('EXPECTED_STRATEGY_COUNT = 4','EXPECTED_STRATEGY_COUNT = 1',1)
t,n=re.subn(r'^MAX_HOLD_MIN = [0-9.]+$',f"MAX_HOLD_MIN = {float(q['max_hold_min'])!r}",t,count=1,flags=re.M)
if n!=1: raise SystemExit('MAX_HOLD_ANCHOR')
enc=json.dumps(c,sort_keys=True,separators=(',',':'),allow_nan=False)
t,n=re.subn(r'^_ZEL_OVERLAY = json\.loads\(.*\)$',f'_ZEL_OVERLAY = json.loads({enc!r})',t,count=1,flags=re.M)
if n!=1: raise SystemExit('OVERLAY_ANCHOR')
anchor='if __name__ == "__main__":'
if t.count(anchor)!=1: raise SystemExit('MAIN_ANCHOR')
override='''\n# ZEL_GEN2_VWAP_TARGET_ONLY\n_ZEL_GEN2_PREV_RESTORE = _restore_structural_premium_registry\ndef _restore_structural_premium_registry(source_root, raw_registry):\n    restored = dict(_ZEL_GEN2_PREV_RESTORE(source_root, raw_registry))\n    if "vwap_revert" not in restored:\n        raise RuntimeError(f"VWAP_TARGET_OWNER_MISSING:{sorted(restored)}")\n    return {"vwap_revert": restored["vwap_revert"]}\n\n'''
p1.write_text(t.replace(anchor,override+anchor,1))
t=p2.read_text()
if t.count('EXPECTED_STRATEGY_COUNT = 4')!=1: raise SystemExit('V2_COUNT_ANCHOR')
p2.write_text(t.replace('EXPECTED_STRATEGY_COUNT = 4','EXPECTED_STRATEGY_COUNT = 1',1))
print(json.dumps({'state':'PASS_GEN2_ENGINE_PATCH','candidate_id':c['candidate_id'],'changed_axes':c.get('changed_axes')},sort_keys=True))
PYPATCH
  "$PY" -m py_compile "$run/engine/replay_v1_candidate.py" "$run/engine/replay_v2_candidate.py"
  printf '%s\n' "$contract" > "$run/contract.sha256.tmp"; mv -f "$run/contract.sha256.tmp" "$run/contract.sha256"
}

run_window() {
  cid="$1"; phase="$2"; window="$3"; run="$G/runs/$cid"; lane="$run/engine/lane_${phase}.py"; out="$run/replay_${phase}"
  if [ ! -s "$lane" ]; then
    cp "$DUR/work/engine/lane_checkpoint_v2.py" "$lane"
    "$PY" - "$lane" "$window" <<'PYLANE'
from pathlib import Path
import sys
p=Path(sys.argv[1]); w=sys.argv[2]; t=p.read_text(); a='files = sorted(files, key=lambda row: (str(row["window_id"]), str(row["symbol"])))'
if t.count(a)!=1: raise SystemExit('LANE_SORT_ANCHOR')
t=t.replace(a,a+f'\n    files = [row for row in files if str(row["window_id"]) == {w!r}]',1); p.write_text(t)
PYLANE
    "$PY" -m py_compile "$lane"
  fi
  mkdir -p "$out"
  "$PY" "$lane" --engine-v1 "$run/engine/replay_v1_candidate.py" --engine-v2 "$run/engine/replay_v2_candidate.py" --source-root "$BASE/work/source" --data-root "$DUR/work/data" --interval 1m --output-dir "$out" --workers 4 2>&1 | tee "$run/logs/${phase}.log"
  test "$(find "$out/lane_checkpoints/vwap_revert" -type f -name '*.json.gz' 2>/dev/null | wc -l)" -eq 5
}

score_window() {
  cid="$1"; phase="$2"; window="$3"; run="$G/runs/$cid"; out="$run/result/${phase}_score.json"; lane_root="$run/replay_${phase}/lane_checkpoints"; engine="$run/engine/replay_v1_candidate.py"; basep="$G/result/baseline_w12.json"
  [ "$phase" = w3 ] && basep="$G/result/baseline_w3.json"
  "$PY" - "$engine" "$lane_root" "$basep" "$out" "$phase" "$window" "$cid" <<'PYSCORE'
import gzip,importlib.util,json,math,sys
from pathlib import Path
engine,lane_root,basep,outp=map(Path,sys.argv[1:5]); phase,window,cid=sys.argv[5:8]
spec=importlib.util.spec_from_file_location('g2score_'+cid+'_'+phase,engine); e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e; spec.loader.exec_module(e)
rows=[]; files=sorted((lane_root/'vwap_revert').glob('*.json.gz'))
if len(files)!=5: raise SystemExit(f'LANE_COUNT:{cid}:{phase}:{len(files)}')
for p in files:
  with gzip.open(p,'rt',encoding='utf-8') as h: d=json.load(h)
  if str(d.get('window_id'))!=window: raise SystemExit(f'WINDOW_LEAK:{p}')
  rows += [r for r in (d.get('result') or {}).get('closed_rows') or [] if r.get('side')=='long']
base=json.loads(basep.read_text())['by_window'][window]; m=e.metrics(rows); min_samples=max(30,math.ceil(float(base['sample_count'])*.50))
g={'sample_min':min_samples,'sample_ok':int(m['sample_count'])>=min_samples,'pf_improved':float(m.get('profit_factor') or 0)>float(base.get('profit_factor') or 0),'net_improved':float(m.get('net_R') or 0)>float(base.get('net_R') or 0),'dd_nonworse':float(m.get('max_drawdown_R') or 0)<=float(base.get('max_drawdown_R') or 0)}; g['pass']=all(v for k,v in g.items() if k not in ('sample_min','pass'))
score=(float(m.get('net_R') or 0)-float(base.get('net_R') or 0))/max(abs(float(base.get('net_R') or 0)),1)+(float(m.get('profit_factor') or 0)-float(base.get('profit_factor') or 0))+(float(base.get('max_drawdown_R') or 0)-float(m.get('max_drawdown_R') or 0))/max(float(base.get('max_drawdown_R') or 0),1)
if not math.isfinite(score): raise SystemExit('NONFINITE_SCORE')
p={'schema_version':'zel.structural_premium.vwap.closed_loop.gen2_window_score.v1','candidate_id':cid,'phase':phase,'window':window,'metrics':m,'gate':g,'phase_pass':g['pass'],'diagnostic_score':score,'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
outp.write_text(json.dumps(p,indent=2,sort_keys=True,allow_nan=False)+'\n'); print(json.dumps({'state':'PASS_GEN2_WINDOW_SCORED','candidate_id':cid,'phase':phase,'phase_pass':g['pass'],'score':score,'metrics':m,'gate':g},sort_keys=True))
PYSCORE
}

# Gen2 deliberately screens the failure regime first: W2 -> W1 -> W3.
for cid in "${CIDS[@]}"; do prepare_candidate "$cid"; run_window "$cid" w2 1m_w2; score_window "$cid" w2 1m_w2; done
mapfile -t W2_SURV < <("$PY" - "$G" "${CIDS[@]}" <<'PYSEL2'
import json,sys
from pathlib import Path
g=Path(sys.argv[1]); ids=sys.argv[2:]; rows=[]
for cid in ids:
 d=json.loads((g/'runs'/cid/'result/w2_score.json').read_text()); rows.append(d)
s=[r['candidate_id'] for r in rows if r['phase_pass']]
out={'schema_version':'zel.structural_premium.vwap.gen2_w2_selection.v1','survivors':s,'ranking':sorted([{'candidate_id':r['candidate_id'],'pass':r['phase_pass'],'score':r['diagnostic_score']} for r in rows],key=lambda x:(-x['score'],x['candidate_id'])),'first_window':'1m_w2','w1_accessed':False,'w3_accessed':False,'research_only':True,'action':'hold'}
(g/'result/w2_selection.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
for x in s: print(x)
PYSEL2
)
echo "GEN2_W2_SURVIVORS=${W2_SURV[*]:-NONE}"
if [ "${#W2_SURV[@]}" -eq 0 ]; then
  "$PY" - "$G/result/terminal_receipt.json" <<'PYT'
import json,sys
from pathlib import Path
p={'schema_version':'zel.structural_premium.vwap.gen2_terminal.v1','state':'HOLD_GEN2_NO_W2_SURVIVOR','next':'SOL_GEMINI_REVIEW_AND_GEN3','w1_accessed':False,'w2_accessed':True,'w3_accessed':False,'canonical_mutations':0,'research_only':True,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}; Path(sys.argv[1]).write_text(json.dumps(p,indent=2,sort_keys=True)+'\n'); print(json.dumps(p,sort_keys=True))
PYT
  exit 0
fi

for cid in "${W2_SURV[@]}"; do run_window "$cid" w1 1m_w1; score_window "$cid" w1 1m_w1; done
WINNER=$("$PY" - "$G" "${W2_SURV[@]}" <<'PYSEL12'
import json,sys
from pathlib import Path
g=Path(sys.argv[1]); rows=[]
for cid in sys.argv[2:]:
 w2=json.loads((g/'runs'/cid/'result/w2_score.json').read_text()); w1=json.loads((g/'runs'/cid/'result/w1_score.json').read_text()); rows.append((cid,w2,w1))
passing=[r for r in rows if r[1]['phase_pass'] and r[2]['phase_pass']]
rank=sorted(rows,key=lambda r:(-(float(r[1]['diagnostic_score'])+float(r[2]['diagnostic_score'])),r[0]))
winner=rank[0][0] if rank and rank[0] in passing else (sorted(passing,key=lambda r:(-(float(r[1]['diagnostic_score'])+float(r[2]['diagnostic_score'])),r[0]))[0][0] if passing else None)
out={'schema_version':'zel.structural_premium.vwap.gen2_w12_selection.v1','winner':winner,'survivors':[r[0] for r in passing],'ranking':[{'candidate_id':r[0],'w2_pass':r[1]['phase_pass'],'w1_pass':r[2]['phase_pass'],'score':float(r[1]['diagnostic_score'])+float(r[2]['diagnostic_score'])} for r in rank],'w3_accessed':False,'research_only':True,'action':'hold'}; (g/'result/w12_selection.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(winner or '')
PYSEL12
)
echo "GEN2_W12_WINNER=${WINNER:-NONE}"
if [ -z "$WINNER" ]; then
  "$PY" - "$G/result/terminal_receipt.json" <<'PYT12'
import json,sys
from pathlib import Path
p={'schema_version':'zel.structural_premium.vwap.gen2_terminal.v1','state':'HOLD_GEN2_NO_W12_SURVIVOR','next':'SOL_GEMINI_REVIEW_AND_GEN3','w1_accessed':True,'w2_accessed':True,'w3_accessed':False,'canonical_mutations':0,'research_only':True,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}; Path(sys.argv[1]).write_text(json.dumps(p,indent=2,sort_keys=True)+'\n'); print(json.dumps(p,sort_keys=True))
PYT12
  exit 0
fi

# Only now is W3 baseline opened and only the W12 winner may touch W3.
"$PY" - "$DUR/work/engine/replay_v1.py" "$BASE/work/replay/trades.jsonl.gz" "$G/result/baseline_w3.json" <<'PYW3'
import gzip,importlib.util,json,sys
from pathlib import Path
eng,trades,out=map(Path,sys.argv[1:]); spec=importlib.util.spec_from_file_location('g2w3base',eng); e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e; spec.loader.exec_module(e); rows=[]
with gzip.open(trades,'rt',encoding='utf-8') as h:
  for line in h:
    r=json.loads(line)
    if str(r.get('window_id'))=='1m_w3' and r.get('strategy_id')=='vwap_revert' and r.get('side')=='long': rows.append(r)
p={'schema_version':'zel.structural_premium.vwap.gen2_w3_baseline.v1','by_window':{'1m_w3':e.metrics(rows)},'created_after_w12_winner':True,'research_only':True,'action':'hold'}; out.write_text(json.dumps(p,indent=2,sort_keys=True,allow_nan=False)+'\n')
PYW3
run_window "$WINNER" w3 1m_w3
score_window "$WINNER" w3 1m_w3
W3PASS=$("$PY" -c "import json; print('1' if json.load(open('$G/runs/$WINNER/result/w3_score.json'))['phase_pass'] else '0')")
if [ "$W3PASS" != 1 ]; then
  "$PY" - "$G/result/terminal_receipt.json" "$WINNER" <<'PYTW3'
import json,sys
from pathlib import Path
p={'schema_version':'zel.structural_premium.vwap.gen2_terminal.v1','state':'HOLD_GEN2_W3_REJECT','winner_w12':sys.argv[2],'next':'SOL_GEMINI_REVIEW_AND_GEN3','w1_accessed':True,'w2_accessed':True,'w3_accessed':True,'canonical_mutations':0,'research_only':True,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}; Path(sys.argv[1]).write_text(json.dumps(p,indent=2,sort_keys=True)+'\n'); print(json.dumps(p,sort_keys=True))
PYTW3
  exit 0
fi
"$PY" - "$G/result/terminal_receipt.json" "$WINNER" <<'PYPASS'
import json,sys
from pathlib import Path
p={'schema_version':'zel.structural_premium.vwap.gen2_terminal.v1','state':'PASS_GEN2_W3_SURVIVOR','winner':sys.argv[2],'next':'TARGETED_45_LANE_AGGREGATE','w1_accessed':True,'w2_accessed':True,'w3_accessed':True,'canonical_mutations':0,'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}; Path(sys.argv[1]).write_text(json.dumps(p,indent=2,sort_keys=True)+'\n'); print(json.dumps(p,sort_keys=True))
PYPASS
