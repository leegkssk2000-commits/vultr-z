#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
C=/home/z/z/_ai_council
ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
G2="$ROOT/gen2"
ADV="$G2/advisory"
SNAP="$ADV/gen1_failure_snapshot.json"
GEM="$ADV/gemini_gen2.json"
SOL_MODEL=openai/gpt-5.6-sol
FALLBACK_MODEL=openai/gpt-5.4
mkdir -p "$G2/candidates" "$ADV"
test -s "$SNAP"; test -s "$GEM"

set -a
. "$C/.env"
set +a
BASE_URL=${REQUESTY_BASE_URL:-https://router.requesty.ai/v1}
test -n "${REQUESTY_API_KEY:-}"

"$PY" - "$SNAP" "$GEM" /tmp/zel_gen2_judge_body.json "$SOL_MODEL" <<'PYBODY'
import json,sys
from pathlib import Path
snap=json.loads(Path(sys.argv[1]).read_text()); raw=json.loads(Path(sys.argv[2]).read_text()); model=sys.argv[4]
gmsg=((raw.get('choices') or [{}])[0].get('message') or {})
gtext=gmsg.get('content') or gmsg.get('reasoning_content') or ''
if not gtext: raise SystemExit('GEMINI_CONTENT_EMPTY')
prompt=(
"Return one JSON object only, no markdown. You are the final research judge for ZEL vwap_revert LONG Gen2. "
"Gen1 has zero W12 survivors. B60/B75 passed W1 but both W2 net/PF/DD worsened; C120 failed W1 PF. "
"Use the exact snapshot and Gemini proposal. Produce exactly 3 distinct candidates, each changing at most 2 axes from its named seed. "
"Goal is W2 structural repair first while preserving W1. W3 remains sealed. No trend_rider/canonical/paper/live/order/promotion. "
"Required JSON keys: decision, diagnosis, candidates, screening. candidates item keys: id, seed, changed_axes, parameters, why. "
"parameters must contain stop_distance_mult,target_distance_mult,min_confidence,cooldown_min,min_risk_distance_pct,max_hold_min. "
"Ranges: stop .70-1.25,target .80-1.50,confidence null or 0-.90,cooldown 0-120,min_risk 0-2,max_hold 15-240. "
"screening must specify first_window='1m_w2', next_window='1m_w1', w3_rule='only_after_W2_and_W1_pass'. "
"SNAPSHOT="+json.dumps(snap,ensure_ascii=False,separators=(',',':'))+" GEMINI="+gtext
)
Path(sys.argv[3]).write_text(json.dumps({'model':model,'messages':[{'role':'user','content':prompt}],'temperature':0.0,'max_tokens':2200},ensure_ascii=False))
PYBODY

call_model() {
  local model="$1" out="$2"
  "$PY" - /tmp/zel_gen2_judge_body.json "$model" /tmp/zel_gen2_judge_body_model.json <<'PYSWAP'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); d=json.loads(p.read_text()); d['model']=sys.argv[2]; Path(sys.argv[3]).write_text(json.dumps(d,ensure_ascii=False))
PYSWAP
  curl -sS -m 300 -o "$out" -w '%{http_code}' -H "Authorization: Bearer $REQUESTY_API_KEY" -H 'Content-Type: application/json' --data-binary @/tmp/zel_gen2_judge_body_model.json "$BASE_URL/chat/completions" || true
}

CODE=$(call_model "$SOL_MODEL" "$ADV/sol_gen2_retry.json")
echo "PRIMARY_MODEL=$SOL_MODEL HTTP=$CODE"
test "$CODE" = 200

extract_json() {
  "$PY" - "$1" "$2" <<'PYEX'
import json,re,sys
from pathlib import Path
raw=json.loads(Path(sys.argv[1]).read_text()); msg=((raw.get('choices') or [{}])[0].get('message') or {})
text=msg.get('content') or msg.get('reasoning_content') or msg.get('reasoning') or ''
text=text.strip()
if text.startswith('```'):
    text=re.sub(r'^```(?:json)?\s*','',text); text=re.sub(r'\s*```$','',text)
if not text:
    raise SystemExit(3)
try: d=json.loads(text)
except Exception:
    a=text.find('{'); b=text.rfind('}')
    if a<0 or b<=a: raise SystemExit(4)
    d=json.loads(text[a:b+1])
Path(sys.argv[2]).write_text(json.dumps(d,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
print('PASS_JSON_EXTRACT')
PYEX
}

JUDGE_MODEL="$SOL_MODEL"
if ! extract_json "$ADV/sol_gen2_retry.json" "$ADV/judge_contract_raw.json"; then
  CODE=$(call_model "$FALLBACK_MODEL" "$ADV/fallback_gen2_retry.json")
  echo "FALLBACK_MODEL=$FALLBACK_MODEL HTTP=$CODE"
  test "$CODE" = 200
  extract_json "$ADV/fallback_gen2_retry.json" "$ADV/judge_contract_raw.json"
  JUDGE_MODEL="$FALLBACK_MODEL"
fi

"$PY" - "$ADV/judge_contract_raw.json" "$G2/candidates" "$ADV/gen2_ai_contract.json" "$JUDGE_MODEL" <<'PYVALID'
import json,sys,hashlib
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text()); root=Path(sys.argv[2]); out=Path(sys.argv[3]); judge=sys.argv[4]
cs=d.get('candidates')
if not isinstance(cs,list) or len(cs)!=3: raise SystemExit('CANDIDATE_COUNT_NOT_3')
limits={'stop_distance_mult':(.70,1.25),'target_distance_mult':(.80,1.50),'cooldown_min':(0,120),'min_risk_distance_pct':(0,2.0),'max_hold_min':(15,240)}
ids=set(); paramfps=set(); root.mkdir(parents=True,exist_ok=True)
for old in root.glob('*.json'): old.unlink()
for i,c in enumerate(cs,1):
    cid=str(c.get('id') or f'G2_{i}').upper().replace(' ','_').replace('/','_')
    if cid in ids: raise SystemExit(f'DUPLICATE_ID:{cid}')
    ids.add(cid)
    axes=c.get('changed_axes') or []
    if not isinstance(axes,list) or len(axes)>2: raise SystemExit(f'CHANGED_AXES:{cid}:{axes}')
    p=c.get('parameters') or {}
    for k,(lo,hi) in limits.items():
        if k not in p: raise SystemExit(f'MISSING:{cid}:{k}')
        if not lo<=float(p[k])<=hi: raise SystemExit(f'RANGE:{cid}:{k}:{p[k]}')
    mc=p.get('min_confidence')
    if mc is not None and not 0<=float(mc)<=.90: raise SystemExit(f'RANGE:{cid}:min_confidence:{mc}')
    fp=json.dumps(p,sort_keys=True,separators=(',',':'))
    if fp in paramfps: raise SystemExit(f'DUPLICATE_PARAMS:{cid}')
    paramfps.add(fp)
    payload={'schema_version':'zel.structural_premium.overlay.v1','candidate_id':cid,'generation':2,'seed':c.get('seed'),'changed_axes':axes,'parameters':{**p,'enabled_entry_owners':['vwap_revert']},'why':c.get('why',''),'ai_models':['google/gemini-3.1-pro-preview',judge],'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED'}
    payload['overlay_sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    (root/f'{cid}.json').write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n')
scr=d.get('screening') or {}
if str(scr.get('first_window'))!='1m_w2': raise SystemExit(f'FIRST_WINDOW_NOT_W2:{scr}')
contract={'schema_version':'zel.structural_premium.vwap.closed_loop.gen2_ai_contract.v2','models':['google/gemini-3.1-pro-preview',judge],'decision':d.get('decision'),'diagnosis':d.get('diagnosis'),'candidate_ids':sorted(ids),'screening':scr,'research_only':True,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED'}
out.write_text(json.dumps(contract,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps({'state':'PASS_GEN2_AI_CONTRACT','judge_model':judge,'candidate_ids':sorted(ids),'screening':scr},sort_keys=True))
PYVALID

cat "$ADV/gen2_ai_contract.json"
for f in "$G2"/candidates/*.json; do echo "=== $(basename "$f") ==="; cat "$f"; done
