#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
DUR=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1
SRC=$ROOT/gen2/runs/C120_FASTSALVAGE
RUN=$ROOT/gen3/neutral_entry_only_v1
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
cp "$SRC/engine/replay_v1_candidate.py" "$RUN/engine/replay_v1_neutral.py"
cp "$SRC/engine/replay_v2_candidate.py" "$RUN/engine/replay_v2_neutral.py"

# Important: historical row['regime'] is EXIT-time htf_bias. Gen3 must never use it as
# an entry filter. This patch computes the exact producer htf_bias from CURRENT ENTRY frame.
"$PY" - "$RUN/engine/replay_v1_neutral.py" <<'PYPATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1]); t=p.read_text()
marker='# ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V1'
if marker in t:
    raise SystemExit('ALREADY_PATCHED_UNEXPECTED')
insert_anchor='def _zel_disabled_strategy(current, state=None, risk_action="hold"):'
if t.count(insert_anchor)!=1:
    raise SystemExit(f'INSERT_ANCHOR_COUNT:{t.count(insert_anchor)}')
helper='''# ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V1\ndef _zel_entry_htf_bias(current):\n    try:\n        recent = current.tail(240).copy()\n        close = recent["close"].astype(float)\n        if len(close) < 180:\n            return "unknown"\n        fast = close.ewm(span=60, adjust=False).mean()\n        slow = close.ewm(span=180, adjust=False).mean()\n        f1 = float(fast.iloc[-1]); f4 = float(fast.iloc[-4]); s1 = float(slow.iloc[-1])\n        if f1 > s1 and f1 >= f4:\n            return "long"\n        if f1 < s1 and f1 <= f4:\n            return "short"\n        return "neutral"\n    except Exception:\n        return "unknown"\n\n'''
t=t.replace(insert_anchor,helper+insert_anchor,1)
old='''        if not _zel_is_long(result):\n            return result\n'''
new='''        if not _zel_is_long(result):\n            return result\n        # Entry-only causal gate: same current frame as make_position(). Never use exit regime.\n        if state is None:\n            entry_bias = _zel_entry_htf_bias(current)\n            if entry_bias != "neutral":\n                return _zel_hold(result, f"ENTRY_HTF_BIAS_{entry_bias.upper()}_BLOCKED_NEUTRAL_ONLY")\n'''
if t.count(old)!=1:
    raise SystemExit(f'WRAP_ANCHOR_COUNT:{t.count(old)}')
t=t.replace(old,new,1)
p.write_text(t)
print('PASS_NEUTRAL_ENTRY_PATCH')
PYPATCH
"$PY" -m py_compile "$RUN/engine/replay_v1_neutral.py" "$RUN/engine/replay_v2_neutral.py"
grep -q 'ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V1' "$RUN/engine/replay_v1_neutral.py"
grep -q 'entry_bias != "neutral"' "$RUN/engine/replay_v1_neutral.py"

# Save exact reference metrics for cumulative comparison against C120, not against an older baseline.
"$PY" - "$SRC/result/w2_score.json" "$ROOT/gen3/c120_pnlwr_validation/w1_pnlwr_score.json" "$ROOT/gen3/c120_pnlwr_validation/w3_pnlwr_score.json" "$RUN/result/c120_reference.json" <<'PYREF'
import json,sys
from pathlib import Path
w2=json.loads(Path(sys.argv[1]).read_text())['metrics']
w1=json.loads(Path(sys.argv[2]).read_text())['candidate']
w3=json.loads(Path(sys.argv[3]).read_text())['candidate']
out={'schema_version':'zel.vwap.gen3.c120_reference.v1','by_window':{'1m_w1':w1,'1m_w2':w2,'1m_w3':w3},'primary':['net_R','win_rate_pct'],'research_only':True}
Path(sys.argv[4]).write_text(json.dumps(out,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps(out,sort_keys=True))
PYREF

# AI review is advisory only but mandatory before expensive replay. No Grok/Groq.
if [ -s /home/z/z/_ai_council/.env ]; then
  set -a; . /home/z/z/_ai_council/.env; set +a
  REQUESTY_BASE_URL=${REQUESTY_BASE_URL:-https://router.requesty.ai/v1}
  "$PY" - "$RUN/engine/replay_v1_neutral.py" "$ADV/review_prompt.json" <<'PYAI'
import json,sys
from pathlib import Path
text=Path(sys.argv[1]).read_text()
start=text.index('# ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V1')
end=text.index('def _restore_structural_premium_registry',start)
snippet=text[start:end]
q=("Review this research-only ZEL Gen3 entry filter for correctness and lookahead safety. Historical trade row regime is EXIT-time htf_bias, so it MUST NOT be used for entry selection. The candidate must compute the exact producer htf_bias from the current entry frame and allow only neutral LONG entries. Canonical/Paper/Live/order/promotion are forbidden. Check causal timing, EMA rule parity, state handling, hold conversion, accidental exit blocking, and sample-collapse risk. Return PASS/FAIL plus concrete issues. CODE:\n"+snippet)
Path(sys.argv[2]).write_text(json.dumps({'messages':[{'role':'user','content':q}],'temperature':0.0,'max_tokens':900},ensure_ascii=False))
PYAI
  for spec in 'GEMINI|google/gemini-3.1-pro-preview' 'OPENAI|openai/gpt-5.4'; do
    label=${spec%%|*}; model=${spec#*|}
    "$PY" - "$ADV/review_prompt.json" "$model" "/tmp/${label}_neutral_review_body.json" <<'PYBODY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text()); p['model']=sys.argv[2]
Path(sys.argv[3]).write_text(json.dumps(p,ensure_ascii=False))
PYBODY
    code=$(curl -sS -m 180 -o "$ADV/${label,,}_review.json" -w '%{http_code}' -H "Authorization: Bearer $REQUESTY_API_KEY" -H 'Content-Type: application/json' --data-binary @"/tmp/${label}_neutral_review_body.json" "$REQUESTY_BASE_URL/chat/completions" || true)
    echo "AI_REVIEW $label model=$model http=$code"
    "$PY" - "$ADV/${label,,}_review.json" "$label" <<'PYOUT'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); label=sys.argv[2]
try:d=json.loads(p.read_text())
except Exception as e: raise SystemExit(f'{label}_REVIEW_JSON:{e}')
content=((d.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
print(label+'_REVIEW_CONTENT',content[:5000])
if not content.strip(): raise SystemExit(label+'_EMPTY_REVIEW')
PYOUT
    test "$code" = 200
  done
else
  echo 'AI_COUNCIL_ENV_MISSING' >&2
  exit 95
fi

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
  "$PY" - "$RUN/engine/replay_v1_neutral.py" "$replay/lane_checkpoints/vwap_revert" "$RUN/result/c120_reference.json" "$window" "$out" <<'PYSCORE'
import gzip,importlib.util,json,sys
from pathlib import Path
eng,root,refp=map(Path,sys.argv[1:4]); window=sys.argv[4]; out=Path(sys.argv[5])
spec=importlib.util.spec_from_file_location('neutral_score',eng); e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e
assert spec.loader is not None; spec.loader.exec_module(e)
files=sorted(root.glob('*.json.gz'))
if len(files)!=5: raise SystemExit(f'LANE_COUNT:{len(files)}')
rows=[]
for p in files:
    with gzip.open(p,'rt',encoding='utf-8') as h:d=json.load(h)
    if d.get('strategy_id')!='vwap_revert' or str(d.get('window_id'))!=window: raise SystemExit(f'LANE_SCOPE:{p}')
    rows += [r for r in (d.get('result') or {}).get('closed_rows') or [] if r.get('side')=='long']
ref=json.loads(refp.read_text())['by_window'][window]; m=e.metrics(rows)
min_discovery_sample=3
gate={'net_improved':m['net_R']>ref['net_R'],'wr_improved':m['win_rate_pct']>ref['win_rate_pct'],'discovery_sample_ok':m['sample_count']>=min_discovery_sample}
gate['pass']=all(gate.values())
payload={'schema_version':'zel.vwap.gen3.neutral_entry_score.v1','window':window,'reference_c120':ref,'candidate':m,'gate':gate,'absolute_positive':m['net_R']>0,'sample_ratio_vs_c120':m['sample_count']/max(ref['sample_count'],1),'primary':['net_R','win_rate_pct'],'pf_secondary':m['profit_factor'],'dd_guard':m['max_drawdown_R'],'research_only':True,'execution_authority':'NONE','order_authority':'BLOCKED','promotion_authority':False,'action':'hold'}
out.write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n')
print('NEUTRAL_SCORE',json.dumps(payload,sort_keys=True))
PYSCORE
}

run_phase() {
  phase="$1"; window="$2"
  make_lane "$phase" "$window"
  rm -rf "$RUN/replay_${phase}"
  "$PY" "$RUN/engine/lane_${phase}.py" --engine-v1 "$RUN/engine/replay_v1_neutral.py" --engine-v2 "$RUN/engine/replay_v2_neutral.py" --source-root "$BASE/work/source" --data-root "$DUR/work/data" --interval 1m --output-dir "$RUN/replay_${phase}" --workers 4 2>&1 | tee "$RUN/logs/${phase}.log"
  score_phase "$phase" "$window"
}

# Highest-information failure window first. W3 remains sealed until W2 and W1 pass.
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
  echo 'W3_SEALED_NEUTRAL_ENTRY_NO_W12_PASS'
fi

"$PY" - "$RUN" <<'PYTERM'
import json,sys
from pathlib import Path
r=Path(sys.argv[1]); scores={}
for phase in ('w2','w1','w3'):
    p=r/'result'/f'{phase}_score.json'
    if p.exists(): scores[phase]=json.loads(p.read_text())
all_three=len(scores)==3 and all(v['gate']['pass'] for v in scores.values())
positive=[k for k,v in scores.items() if v.get('absolute_positive')]
state='PASS_NEUTRAL_ENTRY_STRUCTURE_3WINDOW' if all_three else ('HOLD_NEUTRAL_ENTRY_PARTIAL_OR_FAIL')
p={'schema_version':'zel.vwap.gen3.neutral_entry_terminal.v1','state':state,'scores':scores,'all_three_pnl_wr_pass':all_three,'absolute_positive_windows':positive,'research_only':True,'execution_authority':'NONE','order_authority':'BLOCKED','promotion_authority':False,'action':'hold'}
(r/'result/terminal.json').write_text(json.dumps(p,indent=2,sort_keys=True,allow_nan=False)+'\n')
print('TERMINAL',json.dumps({'state':state,'all_three_pnl_wr_pass':all_three,'absolute_positive_windows':positive},sort_keys=True))
PYTERM

cat "$RUN/result/terminal.json"
