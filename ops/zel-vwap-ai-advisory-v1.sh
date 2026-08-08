#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
C=/home/z/z/_ai_council
ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
G="$ROOT/gen0"
ADV="$ROOT/advisory"
ENG=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2/work/engine/replay_v1.py
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/replay/lane_checkpoints/vwap_revert
PORTX=18790
mkdir -p "$ADV"

"$PY" - "$ENG" "$BASE" "$G" "$ADV/partial_snapshot_latest.json" <<'PYSNAP'
import gzip,importlib.util,json,sys
from pathlib import Path
engp,basep,g,out=map(Path,sys.argv[1:])
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
  'schema_version':'zel.structural_premium.vwap_ai_advisory.snapshot.v1',
  'scope':'vwap_revert.long',
  'generation':0,
  'candidates':{},
  'constraints':{
    'trend_rider':'excluded',
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
    row={'completed_lanes':len(files),'lane_keys':keys}
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
print(json.dumps({'state':'PASS_AI_SNAPSHOT','counts':{k:v['completed_lanes'] for k,v in snapshot['candidates'].items()}},sort_keys=True))
PYSNAP

cd "$C"
# Do not interfere with any persistent council service; isolated port only.
nohup env \
  PORT=$PORTX \
  MODEL_JUDGE=openai/gpt-5.6-sol \
  MODEL_GEMINI=google/gemini-2.5-flash \
  MODEL_GROK=xai/grok-4.3 \
  MAX_TOKENS_AGENT=900 \
  MAX_TOKENS_JUDGE=1300 \
  node "$C/server.js" >"/tmp/zel_vwap_ai_advisory_${PORTX}.log" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; }
trap cleanup EXIT
for i in $(seq 1 20); do
  curl -fsS -m 2 "http://127.0.0.1:$PORTX/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS -m 3 "http://127.0.0.1:$PORTX/health" > "$ADV/health_advisory_latest.json"

"$PY" - "$ADV/partial_snapshot_latest.json" /tmp/zel_vwap_ai_advisory_body.json <<'PYBODY'
import json,sys
from pathlib import Path
snap=json.loads(Path(sys.argv[1]).read_text())
question=(
"ZEL Structural Premium vwap_revert LONG closed-loop의 연구 전용 advisory다. "
"trend_rider는 제외 유지, canonical/paper/live/order/promotion 변경 금지, W3는 W1/W2 승자 전까지 봉인이다. "
"현재 Gen0 후보 A/B/C는 stop/target/confidence/cooldown/min_risk/max_hold 6축으로 탐색 중이다. "
"아래 스냅샷을 실제 근거로만 사용해라. 완료되지 않은 lane을 완료됐다고 가정하지 마라. "
"1) 현재 부분결과에서 확인 가능한 방향성/실패 원인을 진단, 2) 중간결과로 조기중단해도 되는 조건과 아직 기다려야 하는 조건 분리, "
"3) Gen0 실패 시 다음 Gen1 후보 3개를 허용범위(stop .70~1.25,target .80~1.50,confidence null~.90,cooldown 0~120m,min_risk 0~2%,max_hold 15~240m) 안에서 구체 수치로 제안, "
"4) 특히 sample collapse/과적합/W3 leakage를 막는 게이트, 5) runner 파일에 추가할 최소 안전/효율 개선을 CRITICAL/MAJOR/MINOR로 제안해라. "
"long-only 개선이라는 점을 유지하고 short는 이번 세대에 섞지 마라. SNAPSHOT="+json.dumps(snap,ensure_ascii=False,separators=(',',':'))
)
Path(sys.argv[2]).write_text(json.dumps({'question':question},ensure_ascii=False))
PYBODY

CODE=$(curl -sS -m 300 -o "$ADV/partial_review_latest.json" -w '%{http_code}' \
  -H 'Content-Type: application/json' --data-binary @/tmp/zel_vwap_ai_advisory_body.json \
  "http://127.0.0.1:$PORTX/debate" || true)
echo "HTTP_CODE=$CODE"
"$PY" - "$ADV/partial_review_latest.json" <<'PYOUT'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
print('MODE',d.get('mode'))
print('LATENCY_MS',d.get('latency_ms'))
print('ROLES',[(x.get('role'),x.get('model')) for x in d.get('round1',[])])
print('FINAL')
print(d.get('final') or d.get('judge') or d.get('error') or '')
for x in d.get('round1',[]):
    content=x.get('content') or x.get('text') or x.get('answer') or x.get('response') or ''
    if content:
        print('ROUND1',x.get('role'),content[:5000])
PYOUT
test "$CODE" = 200
