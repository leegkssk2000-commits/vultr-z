#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
C=/home/z/z/_ai_council
ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
G1="$ROOT/gen1"
G2="$ROOT/gen2"
ADV="$G2/advisory"
GEMINI_MODEL=google/gemini-3.1-pro-preview
SOL_MODEL=openai/gpt-5.6-sol
mkdir -p "$G1/result" "$G2/candidates" "$ADV"

# Close Gen1 deterministically from already-completed W1/W2 measurements.
"$PY" - "$G1" <<'PYFINAL'
import json,sys
from pathlib import Path
g=Path(sys.argv[1])
rows=[]
for cid in ('B60','B75'):
    w1=json.loads((g/'runs'/cid/'result/w1_score.json').read_text())
    w2=json.loads((g/'runs'/cid/'result/w2_score.json').read_text())
    rows.append((cid,w1,w2))
# C120 failed W1 and must not have W2/W3 access.
c=json.loads((g/'runs/C120/result/w1_score.json').read_text())
if c.get('phase_pass') is not False:
    raise SystemExit('C120_EXPECTED_W1_FAIL')
for cid,w1,w2 in rows:
    if w1.get('phase_pass') is not True:
        raise SystemExit(f'{cid}_EXPECTED_W1_PASS')
    if w2.get('phase_pass') is not False:
        raise SystemExit(f'{cid}_EXPECTED_W2_FAIL')
for cid in ('B60','B75','C120'):
    p=g/'runs'/cid/'replay_w3/lane_checkpoints/vwap_revert'
    if p.exists() and any(p.glob('*.json.gz')):
        raise SystemExit(f'W3_LEAK:{cid}')
rank=sorted(rows,key=lambda r:(-(float(r[1]['diagnostic_score'])+float(r[2]['diagnostic_score'])),r[0]))
sel={
 'schema_version':'zel.structural_premium.vwap_closed_loop.gen1_w12_selection.v3',
 'winner':None,
 'survivors':[],
 'ranking':[{'candidate_id':r[0],'w1_pass':True,'w2_pass':False,'diagnostic_score':float(r[1]['diagnostic_score'])+float(r[2]['diagnostic_score'])} for r in rank],
 'c120_w1_pass':False,
 'w3_accessed':False,
 'research_only':True,'selection_authority':False,'promotion_authority':False,
 'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'
}
(g/'result/w12_selection.json').write_text(json.dumps(sel,indent=2,sort_keys=True)+'\n')
term={
 'schema_version':'zel.structural_premium.vwap_closed_loop.gen1_terminal.v3',
 'state':'HOLD_GEN1_NO_W12_SURVIVOR',
 'next':'SOL_GEMINI_REVIEW_AND_GEN2',
 'w2_accessed':True,'w3_accessed':False,'canonical_mutations':0,
 'research_only':True,'selection_authority':False,'promotion_authority':False,
 'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'
}
(g/'result/terminal_receipt.json').write_text(json.dumps(term,indent=2,sort_keys=True)+'\n')
print(json.dumps({'state':'PASS_GEN1_FINALIZED_NO_SURVIVOR','ranking':sel['ranking'],'w3_accessed':False},sort_keys=True))
PYFINAL

# Build exact evidence snapshot for advisors. No prose-only inputs.
"$PY" - "$G1" "$ADV/gen1_failure_snapshot.json" <<'PYSNAP'
import json,sys
from pathlib import Path
g=Path(sys.argv[1]); out=Path(sys.argv[2])
base=json.loads((g/'result/baseline_w12.json').read_text())
s={'schema_version':'zel.structural_premium.vwap.closed_loop.gen1_failure_snapshot.v1','scope':'vwap_revert.long','baseline':base['by_window'],'candidates':{},'constraints':{
 'trend_rider':'excluded','canonical_mutation':False,'paper_live_order_promotion':False,
 'w3_sealed':True,'allowed':{'stop_distance_mult':[0.70,1.25],'target_distance_mult':[0.80,1.50],'min_confidence':[None,0.90],'cooldown_min':[0,120],'min_risk_distance_pct':[0,2.0],'max_hold_min':[15,240]},
 'gen2_design':'W2-first structural repair; max 2 changed axes per candidate; no random grid'
}}
for cid in ('B60','B75','C120'):
    row={}
    for phase in ('w1','w2'):
        p=g/'runs'/cid/'result'/f'{phase}_score.json'
        if p.exists(): row[phase]=json.loads(p.read_text())
    s['candidates'][cid]=row
out.write_text(json.dumps(s,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps({'state':'PASS_GEN1_FAILURE_SNAPSHOT','candidates':sorted(s['candidates'])},sort_keys=True))
PYSNAP

set -a
. "$C/.env"
set +a
BASE_URL=${REQUESTY_BASE_URL:-https://router.requesty.ai/v1}
test -n "${REQUESTY_API_KEY:-}"

# Gemini: diagnose why W1 gains reverse in W2 and propose only evidence-linked Gen2 moves.
"$PY" - "$ADV/gen1_failure_snapshot.json" /tmp/zel_gemini_gen2_body.json "$GEMINI_MODEL" <<'PYG'
import json,sys
from pathlib import Path
snap=json.loads(Path(sys.argv[1]).read_text()); model=sys.argv[3]
prompt=(
"You are the context analyst for a research-only trading-strategy optimizer. Use only the supplied measurements. "
"Gen1 has zero W12 survivors: B60 and B75 passed W1 but both failed W2 on net_R, PF, and DD; C120 failed W1 PF. "
"Diagnose the regime/parameter failure mechanism and propose exactly 3 Gen2 candidates. Each candidate may change at most TWO axes from its seed. "
"Target W2 repair first while preserving W1. No W3 access, no live/paper/order/promotion changes, no trend_rider. "
"Allowed ranges are in the snapshot. Return compact JSON only with keys diagnosis, candidates, gates. "
"Each candidate object: id, seed, rationale, parameters{stop_distance_mult,target_distance_mult,min_confidence,cooldown_min,min_risk_distance_pct,max_hold_min}. "
"SNAPSHOT="+json.dumps(snap,ensure_ascii=False,separators=(',',':'))
)
body={'model':model,'messages':[{'role':'user','content':prompt}],'temperature':0.1,'max_tokens':1800,'response_format':{'type':'json_object'}}
Path(sys.argv[2]).write_text(json.dumps(body,ensure_ascii=False))
PYG
GCODE=$(curl -sS -m 300 -o "$ADV/gemini_gen2.json" -w '%{http_code}' -H "Authorization: Bearer $REQUESTY_API_KEY" -H 'Content-Type: application/json' --data-binary @/tmp/zel_gemini_gen2_body.json "$BASE_URL/chat/completions" || true)
echo "GEMINI_MODEL=$GEMINI_MODEL HTTP=$GCODE"
test "$GCODE" = 200

# Sol: judge Gemini against exact data and emit the final machine-validated 3-candidate contract.
"$PY" - "$ADV/gen1_failure_snapshot.json" "$ADV/gemini_gen2.json" /tmp/zel_sol_gen2_body.json "$SOL_MODEL" <<'PYS'
import json,sys
from pathlib import Path
snap=json.loads(Path(sys.argv[1]).read_text()); raw=json.loads(Path(sys.argv[2]).read_text()); model=sys.argv[4]
gtext=((raw.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
prompt=(
"You are the final judge for ZEL research-only Gen2 candidate design. Verify Gemini's proposal against the exact Gen1 snapshot. "
"Hard facts: no Gen1 W12 survivor; B60/B75 W1 PASS then W2 FAIL on net/PF/DD; C120 W1 PF FAIL. "
"Select or correct exactly 3 candidates. Objective: repair W2 without sacrificing W1. At most two changed axes per candidate relative to the named seed. "
"Do not use W3, trend_rider, live/paper/order/promotion. Stay within ranges. Avoid near-duplicate candidates. "
"Return JSON only: {decision,diagnosis,candidates:[{id,seed,changed_axes:[...],parameters:{stop_distance_mult,target_distance_mult,min_confidence,cooldown_min,min_risk_distance_pct,max_hold_min},why}],screening:{first_window,pass_rules,next_window,w3_rule}}. "
"SNAPSHOT="+json.dumps(snap,ensure_ascii=False,separators=(',',':'))+" GEMINI="+gtext
)
body={'model':model,'messages':[{'role':'user','content':prompt}],'temperature':0.0,'max_tokens':2000,'response_format':{'type':'json_object'}}
Path(sys.argv[3]).write_text(json.dumps(body,ensure_ascii=False))
PYS
SCODE=$(curl -sS -m 300 -o "$ADV/sol_gen2.json" -w '%{http_code}' -H "Authorization: Bearer $REQUESTY_API_KEY" -H 'Content-Type: application/json' --data-binary @/tmp/zel_sol_gen2_body.json "$BASE_URL/chat/completions" || true)
echo "SOL_MODEL=$SOL_MODEL HTTP=$SCODE"
test "$SCODE" = 200

# Extract and validate final AI contract. Fail closed if AI output violates any hard constraint.
"$PY" - "$ADV/sol_gen2.json" "$G2/candidates" "$ADV/gen2_ai_contract.json" <<'PYVALID'
import json,sys,hashlib
from pathlib import Path
raw=json.loads(Path(sys.argv[1]).read_text()); root=Path(sys.argv[2]); outp=Path(sys.argv[3])
text=((raw.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
try: d=json.loads(text)
except Exception as e: raise SystemExit(f'SOL_JSON_INVALID:{e}')
cs=d.get('candidates')
if not isinstance(cs,list) or len(cs)!=3: raise SystemExit('CANDIDATE_COUNT_NOT_3')
limits={'stop_distance_mult':(.70,1.25),'target_distance_mult':(.80,1.50),'cooldown_min':(0,120),'min_risk_distance_pct':(0,2.0),'max_hold_min':(15,240)}
ids=set(); fps=set(); root.mkdir(parents=True,exist_ok=True)
for i,c in enumerate(cs,1):
    cid=str(c.get('id') or f'G2_{i}').upper().replace(' ','_')
    if cid in ids: raise SystemExit('DUPLICATE_ID')
    ids.add(cid)
    axes=c.get('changed_axes') or []
    if not isinstance(axes,list) or len(axes)>2: raise SystemExit(f'TOO_MANY_CHANGED_AXES:{cid}:{axes}')
    p=c.get('parameters') or {}
    for k,(lo,hi) in limits.items():
        if k not in p: raise SystemExit(f'MISSING_PARAM:{cid}:{k}')
        v=float(p[k])
        if not lo<=v<=hi: raise SystemExit(f'RANGE:{cid}:{k}:{v}')
    mc=p.get('min_confidence')
    if mc is not None and not 0<=float(mc)<=.90: raise SystemExit(f'RANGE:{cid}:min_confidence:{mc}')
    fp=json.dumps(p,sort_keys=True,separators=(',',':'))
    if fp in fps: raise SystemExit(f'DUPLICATE_PARAMETERS:{cid}')
    fps.add(fp)
    payload={'schema_version':'zel.structural_premium.overlay.v1','candidate_id':cid,'generation':2,'seed':c.get('seed'),'changed_axes':axes,'parameters':{**p,'enabled_entry_owners':['vwap_revert']},'why':c.get('why',''),'ai_models':['google/gemini-3.1-pro-preview','openai/gpt-5.6-sol'],'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED'}
    payload['overlay_sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    (root/f'{cid}.json').write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n')
contract={'schema_version':'zel.structural_premium.vwap.closed_loop.gen2_ai_contract.v1','models':['google/gemini-3.1-pro-preview','openai/gpt-5.6-sol'],'decision':d.get('decision'),'diagnosis':d.get('diagnosis'),'candidate_ids':sorted(ids),'screening':d.get('screening'),'research_only':True,'execution_authority':'NONE','order_authority':'BLOCKED','promotion_authority':False}
outp.write_text(json.dumps(contract,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps({'state':'PASS_SOL_GEMINI_GEN2_CONTRACT','candidate_ids':sorted(ids),'screening':contract['screening']},sort_keys=True))
PYVALID

cat "$ADV/gen2_ai_contract.json"
for f in "$G2"/candidates/*.json; do echo "===CANDIDATE $(basename "$f") ==="; cat "$f"; done
