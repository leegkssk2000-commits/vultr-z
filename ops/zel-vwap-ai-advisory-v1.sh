#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
C=/home/z/z/_ai_council
ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
G="$ROOT/gen0"
ADV="$ROOT/advisory"
ENG=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2/work/engine/replay_v1.py
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/replay/lane_checkpoints/vwap_revert
GEMINI_MODEL=google/gemini-3.1-pro-preview
mkdir -p "$ADV"

"$PY" - "$ENG" "$BASE" "$G" "$ADV/partial_snapshot_latest.json" "$GEMINI_MODEL" <<'PYSNAP'
import gzip,importlib.util,json,sys
from pathlib import Path
engp,basep,g,out=map(Path,sys.argv[1:5]); gemini_model=sys.argv[5]
spec=importlib.util.spec_from_file_location('advisory_engine',engp)
e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e
assert spec.loader is not None; spec.loader.exec_module(e)
def load(p):
    with gzip.open(p,'rt',encoding='utf-8') as h: return json.load(h)
def key(d): return (str(d.get('window_id')),str(d.get('symbol')))
base={}
for p in basep.glob('*.json.gz'):
    d=load(p); base[key(d)]=d
snapshot={
  'schema_version':'zel.structural_premium.vwap_ai_advisory.snapshot.v3',
  'scope':'vwap_revert.long',
  'generation':0,
  'advisors':['openai/gpt-5.6-sol',gemini_model],
  'excluded_advisors':['xai/grok-*'],
  'candidates':{},
  'constraints':{
    'trend_rider':'excluded',
    'candidate_A':'skipped_user_directed_after_worse_partial',
    'active_candidates':['B','C'],
    'canonical_mutation':False,
    'paper_live_order_promotion':False,
    'w3_sealed_until_w12_winner':True,
  },
}
for cid in ('A','B','C'):
    root=g/'runs'/cid/'replay_w12/lane_checkpoints/vwap_revert'
    files=sorted(root.glob('*.json.gz')) if root.exists() else []
    cand_rows=[]; matched=[]; keys=[]
    for p in files:
        d=load(p); k=key(d); keys.append(k)
        cand_rows += [r for r in (d.get('result') or {}).get('closed_rows') or [] if r.get('side')=='long']
        b=base.get(k)
        if b: matched += [r for r in (b.get('result') or {}).get('closed_rows') or [] if r.get('side')=='long']
    row={'completed_lanes':len(files),'lane_keys':keys,'selection_eligible':cid in ('B','C')}
    if files:
        cm=e.metrics(cand_rows); bm=e.metrics(matched)
        row['matched_baseline']=bm; row['candidate']=cm
        row['delta']={
          'sample':int(cm.get('sample_count') or 0)-int(bm.get('sample_count') or 0),
          'net_R':float(cm.get('net_R') or 0)-float(bm.get('net_R') or 0),
          'profit_factor':float(cm.get('profit_factor') or 0)-float(bm.get('profit_factor') or 0),
          'max_drawdown_R':float(cm.get('max_drawdown_R') or 0)-float(bm.get('max_drawdown_R') or 0),
          'win_rate_pp':float(cm.get('win_rate_pct') or 0)-float(bm.get('win_rate_pct') or 0),
        }
    score=g/'runs'/cid/'result/w12_score.json'
    if score.exists(): row['w12_score']=json.loads(score.read_text())
    snapshot['candidates'][cid]=row
sel=g/'result/w12_selection.json'
if sel.exists(): snapshot['w12_selection']=json.loads(sel.read_text())
out.write_text(json.dumps(snapshot,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps({'state':'PASS_AI_SNAPSHOT_SOL_GEMINI_LATEST','gemini_model':gemini_model,'counts':{k:v['completed_lanes'] for k,v in snapshot['candidates'].items()}},sort_keys=True))
PYSNAP

set -a
. "$C/.env"
set +a
BASE_URL=${REQUESTY_BASE_URL:-https://router.requesty.ai/v1}
test -n "${REQUESTY_API_KEY:-}"

"$PY" - "$ADV/partial_snapshot_latest.json" /tmp/zel_vwap_gemini_body.json "$GEMINI_MODEL" <<'PYBODY'
import json,sys
from pathlib import Path
snap=json.loads(Path(sys.argv[1]).read_text()); gemini_model=sys.argv[3]
question=(
"ZEL Structural Premium vwap_revert LONG closed-loop의 연구 전용 Context/Critic 역할이다. "
"A는 사용자 지시로 제외했고 B/C만 동일 계약 평가 중이다. trend_rider 제외, canonical/paper/live/order/promotion 변경 금지, W3는 W12 승자 전까지 봉인. "
"완료되지 않은 lane을 완료됐다고 가정하지 말고 B/C 실측만으로 진단해라. "
"B/C의 성능 차이, sample collapse, 과적합, 비용/노출/리스크 문제를 분석하고 Gen1로 넘어갈 때 수정할 축을 최대 3개로 제한해서 제안해라. "
"운영/실거래 변경은 제안하지 마라. SNAPSHOT="+json.dumps(snap,ensure_ascii=False,separators=(',',':'))
)
body={
  'model':gemini_model,
  'messages':[{'role':'user','content':question}],
  'temperature':0.1,
  'max_tokens':1200
}
Path(sys.argv[2]).write_text(json.dumps(body,ensure_ascii=False))
PYBODY

GCODE=$(curl -sS -m 240 -o "$ADV/gemini_context_latest.json" -w '%{http_code}' \
  -H "Authorization: Bearer $REQUESTY_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/zel_vwap_gemini_body.json \
  "$BASE_URL/chat/completions" || true)
echo "GEMINI_MODEL=$GEMINI_MODEL GEMINI_HTTP_CODE=$GCODE"
test "$GCODE" = 200

"$PY" - "$ADV/partial_snapshot_latest.json" "$ADV/gemini_context_latest.json" /tmp/zel_vwap_sol_body.json <<'PYSOL'
import json,sys
from pathlib import Path
snap=json.loads(Path(sys.argv[1]).read_text())
g=json.loads(Path(sys.argv[2]).read_text())
gtext=((g.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
question=(
"너는 ZEL 연구 closed-loop 최종 Judge다. Grok/xAI는 사용하지 않는다. "
"A는 사용자 지시로 제외, B/C만 동일 계약으로 평가한다. trend_rider 제외, canonical/paper/live/order/promotion 변경 금지, W3는 W12 승자 전까지 봉인. "
"아래 실제 스냅샷과 Gemini 분석을 대조해 B/C 판정, 다음 안전한 단계, Gen1 필요 시 최소 수정축을 결정해라. "
"미완료 데이터를 완료로 간주하지 말고 수치 없는 주장은 금지한다. 출력은 판정/조치/근거/리스크/다음 5줄. "
"SNAPSHOT="+json.dumps(snap,ensure_ascii=False,separators=(',',':'))+" GEMINI="+gtext
)
body={
  'model':'openai/gpt-5.6-sol',
  'messages':[{'role':'user','content':question}],
  'temperature':0.0,
  'max_tokens':1200
}
Path(sys.argv[3]).write_text(json.dumps(body,ensure_ascii=False))
PYSOL

SCODE=$(curl -sS -m 240 -o "$ADV/sol_judge_latest.json" -w '%{http_code}' \
  -H "Authorization: Bearer $REQUESTY_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/zel_vwap_sol_body.json \
  "$BASE_URL/chat/completions" || true)
echo "SOL_HTTP_CODE=$SCODE"
test "$SCODE" = 200

"$PY" - "$ADV/gemini_context_latest.json" "$ADV/sol_judge_latest.json" "$ADV/partial_review_latest.json" "$GEMINI_MODEL" <<'PYOUT'
import json,sys
from pathlib import Path
g=json.loads(Path(sys.argv[1]).read_text()); s=json.loads(Path(sys.argv[2]).read_text()); gemini_model=sys.argv[4]
gtext=((g.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
stext=((s.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
out={
  'schema_version':'zel.structural_premium.vwap_ai_advisory.review.v3',
  'models':{
    'context':gemini_model,
    'judge':'openai/gpt-5.6-sol',
    'grok':None,
    'groq':None
  },
  'gemini_context':gtext,
  'final':stext,
  'research_only':True,
  'execution_authority':'NONE',
  'order_authority':'BLOCKED',
  'promotion_authority':False
}
Path(sys.argv[3]).write_text(json.dumps(out,indent=2,ensure_ascii=False,sort_keys=True)+'\n')
print('MODE sol_gemini_latest')
print('MODELS',out['models'])
print('FINAL')
print(stext)
PYOUT
