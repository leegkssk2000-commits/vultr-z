#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
DUR=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1
SRC=$ROOT/gen2/runs/C120_FASTSALVAGE
RUN=$ROOT/gen3/neutral_entry_only_v2
CANON=/opt/zel/forward-expansion-v1/source
ADV=$RUN/advisory
mkdir -p "$RUN/engine" "$RUN/result" "$RUN/logs" "$ADV"

for p in \
  "$SRC/engine/replay_v1_candidate.py" \
  "$SRC/engine/replay_v2_candidate.py" \
  "$SRC/result/w2_score.json" \
  "$ROOT/gen3/c120_pnlwr_validation/w1_pnlwr_score.json" \
  "$ROOT/gen3/c120_pnlwr_validation/w3_pnlwr_score.json" \
  "$DUR/work/engine/lane_checkpoint_v2.py"; do
  test -s "$p"
done

canon_hash() {
  {
    find "$CANON/backend/strategies" -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | sort -z | xargs -0 sha256sum
    sha256sum "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json"
  } | sha256sum | awk '{print $1}'
}
BEFORE=$(canon_hash)
verify_canon() {
  rc=$?
  AFTER=$(canon_hash)
  if [ "$AFTER" != "$BEFORE" ]; then
    echo "CRITICAL_CANONICAL_MUTATION before=$BEFORE after=$AFTER" >&2
    exit 97
  fi
  echo "PASS_CANONICAL_UNCHANGED $AFTER"
  return "$rc"
}
trap verify_canon EXIT

rm -rf "$RUN/replay_w2" "$RUN/replay_w1" "$RUN/replay_w3"
cp "$SRC/engine/replay_v1_candidate.py" "$RUN/engine/replay_v1_neutral_v2.py"
cp "$SRC/engine/replay_v2_candidate.py" "$RUN/engine/replay_v2_neutral_v2.py"

# V2 correction:
# - historical trade row regime is EXIT-time and forbidden for entry selection;
# - state is not a reliable flat/entry discriminator in replay;
# - gate the actual ENTRY ACTION itself;
# - call producer.feature_snapshot(current) for exact htf_bias parity.
"$PY" - "$RUN/engine/replay_v1_neutral_v2.py" <<'PYPATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1]); t=p.read_text()
marker='# ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V2'
if marker in t:
    raise SystemExit('ALREADY_PATCHED_UNEXPECTED')
anchor='def _zel_disabled_strategy(current, state=None, risk_action="hold"):'
if t.count(anchor)!=1:
    raise SystemExit(f'INSERT_ANCHOR_COUNT:{t.count(anchor)}')
helper='''# ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V2\ndef _zel_entry_htf_bias(current):\n    try:\n        producer = globals().get("_WORKER_PRODUCER")\n        if producer is None or not callable(getattr(producer, "feature_snapshot", None)):\n            return "unknown"\n        features = producer.feature_snapshot(current)\n        return str((features or {}).get("htf_bias") or "unknown").lower()\n    except Exception:\n        return "unknown"\n\ndef _zel_is_entry_action(result):\n    if not isinstance(result, dict):\n        return False\n    action = str(result.get("action") or "").lower()\n    side = str(result.get("side") or "").lower()\n    return action in {"enter", "entry", "open", "buy", "sell"} and side == "long"\n\n'''
t=t.replace(anchor,helper+anchor,1)
old='''        if not _zel_is_long(result):\n            return result\n'''
new='''        if not _zel_is_long(result):\n            return result\n        # Gate only actual LONG entry actions; never gate position management/exits.\n        if _zel_is_entry_action(result):\n            entry_bias = _zel_entry_htf_bias(current)\n            if entry_bias != "neutral":\n                return _zel_hold(result, f"ENTRY_HTF_BIAS_{entry_bias.upper()}_BLOCKED_NEUTRAL_ONLY_V2")\n'''
if t.count(old)!=1:
    raise SystemExit(f'WRAP_ANCHOR_COUNT:{t.count(old)}')
t=t.replace(old,new,1)
p.write_text(t)
print('PASS_NEUTRAL_ENTRY_V2_PATCH')
PYPATCH
"$PY" -m py_compile "$RUN/engine/replay_v1_neutral_v2.py" "$RUN/engine/replay_v2_neutral_v2.py"
grep -q 'ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V2' "$RUN/engine/replay_v1_neutral_v2.py"
grep -q '_zel_is_entry_action(result)' "$RUN/engine/replay_v1_neutral_v2.py"
grep -q 'producer.feature_snapshot(current)' "$RUN/engine/replay_v1_neutral_v2.py"

"$PY" - "$SRC/result/w2_score.json" "$ROOT/gen3/c120_pnlwr_validation/w1_pnlwr_score.json" "$ROOT/gen3/c120_pnlwr_validation/w3_pnlwr_score.json" "$RUN/result/c120_reference.json" <<'PYREF'
import json,sys
from pathlib import Path
w2=json.loads(Path(sys.argv[1]).read_text())['metrics']
w1=json.loads(Path(sys.argv[2]).read_text())['candidate']
w3=json.loads(Path(sys.argv[3]).read_text())['candidate']
out={'schema_version':'zel.vwap.gen3.c120_reference.v2','by_window':{'1m_w1':w1,'1m_w2':w2,'1m_w3':w3},'primary':['net_R','win_rate_pct'],'research_only':True}
Path(sys.argv[4]).write_text(json.dumps(out,indent=2,sort_keys=True,allow_nan=False)+'\n')
PYREF

# Mandatory linked-AI code review. FAIL text stops before replay.
set -a; . /home/z/z/_ai_council/.env; set +a
REQUESTY_BASE_URL=${REQUESTY_BASE_URL:-https://router.requesty.ai/v1}
"$PY" - "$RUN/engine/replay_v1_neutral_v2.py" "$ADV/review_prompt.json" <<'PYAI'
import json,sys
from pathlib import Path
text=Path(sys.argv[1]).read_text()
patch=text[text.index('# ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V2'):text.index('def _restore_structural_premium_registry', text.index('# ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V2'))]
replay=text[text.index('def replay_lane('):text.index('def replay_strategy', text.index('def replay_lane('))]
q=("Review this research-only ZEL Gen3 V2 entry filter. Requirements: only actual LONG ENTRY actions may pass when producer.feature_snapshot(current).htf_bias == neutral; historical closed-trade regime must never be used; current replay frame must be causal; exits/management must remain untouched; Canonical/Paper/Live/order/promotion forbidden. Verify the previous V1 state-gating leakage is fixed. Return first line exactly PASS or FAIL, then issues. CODE_PATCH:\n"+patch+"\nREPLAY_PATH:\n"+replay[:7000])
Path(sys.argv[2]).write_text(json.dumps({'messages':[{'role':'user','content':q}],'temperature':0.0,'max_tokens':1000},ensure_ascii=False))
PYAI
for spec in 'GEMINI|google/gemini-3.1-pro-preview' 'OPENAI|openai/gpt-5.4'; do
  label=${spec%%|*}; model=${spec#*|}
  "$PY" - "$ADV/review_prompt.json" "$model" "/tmp/${label}_neutral_v2_body.json" <<'PYBODY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text()); p['model']=sys.argv[2]
Path(sys.argv[3]).write_text(json.dumps(p,ensure_ascii=False))
PYBODY
  code=$(curl -sS -m 180 -o "$ADV/${label,,}_review.json" -w '%{http_code}' -H "Authorization: Bearer $REQUESTY_API_KEY" -H 'Content-Type: application/json' --data-binary @"/tmp/${label}_neutral_v2_body.json" "$REQUESTY_BASE_URL/chat/completions" || true)
  test "$code" = 200
  verdict=$("$PY" - "$ADV/${label,,}_review.json" "$label" <<'PYOUT'
import json,re,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text()); label=sys.argv[2]
content=((d.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
print(label+'_REVIEW_CONTENT',content[:5000],file=sys.stderr)
first=re.sub(r'[^A-Z]','',content.strip().splitlines()[0].upper()) if content.strip() else ''
print('PASS' if first.startswith('PASS') else 'FAIL')
PYOUT
)
  echo "AI_REVIEW_VERDICT $label $verdict"
  test "$verdict" = PASS
 done

make_lane() {
  phase="$1"; window="$2"; lane="$RUN/engine/lane_${phase}.py"
  cp "$DUR/work/engine/lane_checkpoint_v2.py" "$lane"
  "$PY" - "$lane" "$window" <<'PYLANE'
from pathlib import Path
import sys
p=Path(sys.argv[1]); w=sys.argv[2]; t=p.read_text()
a='files = sorted(files, key=lambda row: (str(row["window_id"]), str(row["symbol"])))'
if t.count(a)!=1: raise SystemExit('LANE_SORT_ANCHOR')
p.write_text(t.replace(a,a+f'\n    files = [row for row in files if str(row["window_id"]) == {w!r}]',1))
PYLANE
  "$PY" -m py_compile "$lane"
}

score_phase() {
  phase="$1"; window="$2"; replay="$RUN/replay_${phase}"; out="$RUN/result/${phase}_score.json"
  "$PY" - "$RUN/engine/replay_v1_neutral_v2.py" "$replay/lane_checkpoints/vwap_revert" "$RUN/result/c120_reference.json" "$window" "$out" <<'PYSCORE'
import gzip,importlib.util,json,sys
from pathlib import Path
eng,root,refp=map(Path,sys.argv[1:4]); window=sys.argv[4]; out=Path(sys.argv[5])
spec=importlib.util.spec_from_file_location('neutral_v2_score',eng); e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e
assert spec.loader is not None; spec.loader.exec_module(e)
files=sorted(root.glob('*.json.gz'))
if len(files)!=5: raise SystemExit(f'LANE_COUNT:{len(files)}')
rows=[]; leaks=[]
for p in files:
    with gzip.open(p,'rt',encoding='utf-8') as h:d=json.load(h)
    if d.get('strategy_id')!='vwap_revert' or str(d.get('window_id'))!=window: raise SystemExit(f'LANE_SCOPE:{p}')
    for r in (d.get('result') or {}).get('closed_rows') or []:
        if r.get('side')!='long': continue
        rows.append(r)
        entry_bias=str(((r.get('entry_features') or {}).get('htf_bias') or 'unknown')).lower()
        if entry_bias!='neutral': leaks.append({'symbol':r.get('symbol'),'entry_ts':r.get('entry_ts'),'entry_bias':entry_bias})
if leaks:
    raise SystemExit('ENTRY_BIAS_LEAK:'+json.dumps(leaks[:10],sort_keys=True))
ref=json.loads(refp.read_text())['by_window'][window]; m=e.metrics(rows)
gate={
 'absolute_positive':m['net_R']>0,
 'net_improved':m['net_R']>ref['net_R'],
 'wr_improved':m['win_rate_pct']>ref['win_rate_pct'],
 'discovery_sample_ok':m['sample_count']>=3,
 'entry_bias_clean':not leaks,
}
gate['pass']=all(gate.values())
payload={'schema_version':'zel.vwap.gen3.neutral_entry_score.v2','window':window,'reference_c120':ref,'candidate':m,'gate':gate,'entry_bias_leak_count':len(leaks),'sample_ratio_vs_c120':m['sample_count']/max(ref['sample_count'],1),'primary':['net_R','win_rate_pct'],'research_only':True,'execution_authority':'NONE','order_authority':'BLOCKED','promotion_authority':False,'action':'hold'}
out.write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n')
print('NEUTRAL_V2_SCORE',json.dumps(payload,sort_keys=True))
PYSCORE
}

run_phase() {
  phase="$1"; window="$2"
  make_lane "$phase" "$window"
  rm -rf "$RUN/replay_${phase}"
  "$PY" "$RUN/engine/lane_${phase}.py" --engine-v1 "$RUN/engine/replay_v1_neutral_v2.py" --engine-v2 "$RUN/engine/replay_v2_neutral_v2.py" --source-root "$BASE/work/source" --data-root "$DUR/work/data" --interval 1m --output-dir "$RUN/replay_${phase}" --workers 4 2>&1 | tee "$RUN/logs/${phase}.log"
  score_phase "$phase" "$window"
}

run_phase w2 1m_w2
W2PASS=$("$PY" -c "import json; print('1' if json.load(open('$RUN/result/w2_score.json'))['gate']['pass'] else '0')")
if [ "$W2PASS" = 1 ]; then
  run_phase w1 1m_w1
  W1PASS=$("$PY" -c "import json; print('1' if json.load(open('$RUN/result/w1_score.json'))['gate']['pass'] else '0')")
else
  W1PASS=0
  echo 'STOP_AFTER_W2_FAIL'
fi
if [ "$W2PASS" = 1 ] && [ "$W1PASS" = 1 ]; then
  run_phase w3 1m_w3
else
  echo 'W3_SEALED_NEUTRAL_ENTRY_V2_NO_W12_PASS'
fi

"$PY" - "$RUN" <<'PYTERM'
import json,sys
from pathlib import Path
r=Path(sys.argv[1]); scores={}
for phase in ('w2','w1','w3'):
    p=r/'result'/f'{phase}_score.json'
    if p.exists(): scores[phase]=json.loads(p.read_text())
all_three=len(scores)==3 and all(v['gate']['pass'] for v in scores.values())
total_samples=sum(int(v['candidate']['sample_count']) for v in scores.values())
state='PASS_NEUTRAL_ENTRY_V2_3WINDOW' if all_three and total_samples>=30 else 'HOLD_NEUTRAL_ENTRY_V2_PARTIAL_OR_FAIL'
p={'schema_version':'zel.vwap.gen3.neutral_entry_terminal.v2','state':state,'scores':scores,'all_three_pass':all_three,'total_samples':total_samples,'research_only':True,'execution_authority':'NONE','order_authority':'BLOCKED','promotion_authority':False,'action':'hold'}
(r/'result/terminal.json').write_text(json.dumps(p,indent=2,sort_keys=True,allow_nan=False)+'\n')
print('TERMINAL',json.dumps({'state':state,'all_three_pass':all_three,'total_samples':total_samples},sort_keys=True))
PYTERM
cat "$RUN/result/terminal.json"
