#!/usr/bin/env bash
set -euo pipefail

DUR=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1
ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
GEN="$ROOT/gen0"
PY=/home/z/z/.venv/bin/python
CANON=/opt/zel/forward-expansion-v1/source

for p in \
  "$DUR/work/engine/replay_v1.py" \
  "$DUR/work/engine/replay_v2.py" \
  "$DUR/work/engine/lane_checkpoint_v2.py" \
  "$BASE/work/engine/replay_v1_no_trend.py" \
  "$BASE/work/engine/replay_v2_no_trend.py" \
  "$BASE/work/engine/lane_checkpoint_v2.py" \
  "$BASE/work/replay/report.json" \
  "$BASE/work/replay/trades.jsonl.gz"; do
  test -s "$p"
done
for s in vwap_revert support_resistance liquidity_sweep; do
  test -d "$BASE/work/replay/lane_checkpoints/$s"
done

mkdir -p "$GEN/candidates" "$GEN/runs" "$GEN/result" "$ROOT/advisory"

# Protected canonical fingerprints. Research loop must never mutate these files.
CANON_SR=$(sha256sum "$CANON/backend/strategies/sr_levels.py" | awk '{print $1}')
CANON_VWAP=$(sha256sum "$CANON/backend/strategies/vwap_reversion.py" 2>/dev/null | awk '{print $1}' || true)
CANON_TR=$(sha256sum "$CANON/backend/strategies/trend_rider.py" | awk '{print $1}')
CANON_MAN=$(sha256sum "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" | awk '{print $1}')
CANON_BIND=$(sha256sum "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json" | awk '{print $1}')

# Baseline is recomputed from the raw no-trend replay, LONG side only, matching the
# previously diagnosed 885-trade vwap loss surface. W3 remains sealed from selection.
"$PY" - "$DUR/work/engine/replay_v1.py" "$BASE/work/replay/trades.jsonl.gz" "$GEN/result/baseline_long.json" <<'PYBASE'
import gzip, importlib.util, json, sys
from pathlib import Path
engine_path, trades_path, out_path = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("zel_vwap_baseline_engine", engine_path)
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
assert spec.loader is not None
spec.loader.exec_module(engine)
rows = []
with gzip.open(trades_path, "rt", encoding="utf-8") as handle:
    for line in handle:
        row = json.loads(line)
        if row.get("strategy_id") == "vwap_revert" and row.get("side") == "long":
            rows.append(row)
by_window = {w: engine.metrics([r for r in rows if r.get("window_id") == w]) for w in sorted({str(r.get("window_id")) for r in rows})}
payload = {
    "schema_version": "zel.structural_premium.vwap_closed_loop.baseline.v1",
    "scope": "vwap_revert.long",
    "selection_windows": ["1m_w1", "1m_w2"],
    "sealed_confirmation_window": "1m_w3",
    "overall": engine.metrics(rows),
    "by_window": by_window,
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "action": "hold",
}
out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
print(json.dumps({"state":"PASS_BASELINE_LONG","overall":payload["overall"],"by_window":by_window}, sort_keys=True))
PYBASE

# Gen0 candidates came from the linked AI debate (Sol judge + Gemini context + Grok critic).
"$PY" - "$GEN/candidates" <<'PYCANDS'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
def stable_sha(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
rows = {
  "A": dict(stop_distance_mult=0.85,target_distance_mult=1.20,min_confidence=None,cooldown_min=30.0,min_risk_distance_pct=0.25,max_hold_min=90.0),
  "B": dict(stop_distance_mult=0.95,target_distance_mult=1.35,min_confidence=0.65,cooldown_min=60.0,min_risk_distance_pct=0.40,max_hold_min=120.0),
  "C": dict(stop_distance_mult=1.10,target_distance_mult=1.10,min_confidence=0.75,cooldown_min=90.0,min_risk_distance_pct=0.60,max_hold_min=60.0),
}
for cid, params in rows.items():
    payload = {
      "schema_version":"zel.structural_premium.overlay.v1",
      "candidate_id":f"VWAP_GEN0_{cid}",
      "generation":0,
      "axis":"SIX_AXIS_VWAP_LONG",
      "closed_loop_axes":["FREQUENCY","COST_EXECUTION","RISK_EXPOSURE","INTERACTION","PORTFOLIO","ROBUSTNESS"],
      "parameters":{**params,"enabled_entry_owners":["vwap_revert"]},
      "research_only":True,"selection_authority":False,"promotion_authority":False,
      "execution_authority":"NONE","order_authority":"BLOCKED",
    }
    payload["overlay_sha256"] = stable_sha(payload)
    (root/f"{cid}.json").write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+"\n")
print(json.dumps({"state":"PASS_GEN0_CANDIDATES_WRITTEN","candidate_ids":sorted(rows)},sort_keys=True))
PYCANDS

prepare_candidate() {
  local cid="$1"
  local cjson="$GEN/candidates/$cid.json"
  local run="$GEN/runs/$cid"
  local csha
  csha=$(sha256sum "$cjson" | awk '{print $1}')
  if [ -s "$run/candidate.sha256" ] && [ "$(cat "$run/candidate.sha256")" = "$csha" ]; then
    echo "RESUME_CANDIDATE $cid $csha"
  else
    rm -rf "$run"
    mkdir -p "$run/engine" "$run/replay_w12" "$run/result" "$run/logs"
    cp "$DUR/work/engine/replay_v1.py" "$run/engine/replay_v1_candidate.py"
    cp "$DUR/work/engine/replay_v2.py" "$run/engine/replay_v2_candidate.py"
    cp "$DUR/work/engine/lane_checkpoint_v2.py" "$run/engine/lane_w12.py"
    cp "$DUR/work/engine/lane_checkpoint_v2.py" "$run/engine/lane_w3.py"
    printf '%s\n' "$csha" > "$run/candidate.sha256"

    "$PY" - "$run/engine/replay_v1_candidate.py" "$run/engine/replay_v2_candidate.py" "$run/engine/lane_w12.py" "$run/engine/lane_w3.py" "$cjson" <<'PYPATCH'
import json,re,sys
from pathlib import Path
p1,p2,l12,l3,cpath = map(Path,sys.argv[1:])
c=json.loads(cpath.read_text())
params=c["parameters"]
for key,lo,hi in (("stop_distance_mult",0.70,1.25),("target_distance_mult",0.80,1.50),("cooldown_min",0,120),("min_risk_distance_pct",0,2),("max_hold_min",15,240)):
    v=float(params[key]);
    if not lo <= v <= hi: raise SystemExit(f"RANGE:{key}:{v}")
mc=params.get("min_confidence")
if mc is not None and not 0 <= float(mc) <= 0.90: raise SystemExit(f"RANGE:min_confidence:{mc}")
if params.get("enabled_entry_owners") != ["vwap_revert"]: raise SystemExit("VWAP_ONLY_OWNER_REQUIRED")

t=p1.read_text()
if t.count("EXPECTED_STRATEGY_COUNT = 4") != 1: raise SystemExit("V1_EXPECTED_COUNT_ANCHOR")
t=t.replace("EXPECTED_STRATEGY_COUNT = 4","EXPECTED_STRATEGY_COUNT = 1",1)
t,n=re.subn(r"^MAX_HOLD_MIN = [0-9.]+$",f"MAX_HOLD_MIN = {float(params['max_hold_min'])!r}",t,count=1,flags=re.M)
if n != 1: raise SystemExit(f"MAX_HOLD_PATCH_COUNT:{n}")
encoded=json.dumps(c,sort_keys=True,separators=(",",":"),allow_nan=False)
line=f"_ZEL_OVERLAY = json.loads({encoded!r})"
t,n=re.subn(r"^_ZEL_OVERLAY = json\.loads\(.*\)$",line,t,count=1,flags=re.M)
if n != 1: raise SystemExit(f"OVERLAY_PATCH_COUNT:{n}")
anchor='if __name__ == "__main__":'
if t.count(anchor) != 1: raise SystemExit("MAIN_GUARD_ANCHOR")
override='''\n# ZEL_VWAP_TARGET_ONLY_V1\n_ZEL_VWAP_TARGET_BASE_RESTORE = _restore_structural_premium_registry\ndef _restore_structural_premium_registry(source_root, raw_registry):\n    restored = dict(_ZEL_VWAP_TARGET_BASE_RESTORE(source_root, raw_registry))\n    if "vwap_revert" not in restored:\n        raise RuntimeError(f"VWAP_TARGET_OWNER_MISSING:{sorted(restored)}")\n    return {"vwap_revert": restored["vwap_revert"]}\n\n'''
t=t.replace(anchor,override+anchor,1)
p1.write_text(t)

t=p2.read_text()
if t.count("EXPECTED_STRATEGY_COUNT = 4") != 1: raise SystemExit("V2_EXPECTED_COUNT_ANCHOR")
p2.write_text(t.replace("EXPECTED_STRATEGY_COUNT = 4","EXPECTED_STRATEGY_COUNT = 1",1))

sort_anchor='files = sorted(files, key=lambda row: (str(row["window_id"]), str(row["symbol"])))'
for path,allowed in ((l12,["1m_w1","1m_w2"]),(l3,["1m_w3"])):
    tx=path.read_text()
    if tx.count(sort_anchor) != 1: raise SystemExit(f"LANE_SORT_ANCHOR:{path}")
    filt=f'files = [row for row in files if str(row["window_id"]) in {set(allowed)!r}]'
    tx=tx.replace(sort_anchor,sort_anchor+"\n    "+filt,1)
    path.write_text(tx)
print(json.dumps({"state":"PASS_CANDIDATE_ENGINE_PATCHED","candidate_id":c["candidate_id"],"w12_only":True,"w3_sealed":True},sort_keys=True))
PYPATCH
    "$PY" -m py_compile "$run/engine/replay_v1_candidate.py" "$run/engine/replay_v2_candidate.py" "$run/engine/lane_w12.py" "$run/engine/lane_w3.py"
  fi
}

score_phase() {
  local cid="$1" phase="$2" lane_root="$3" out="$4"
  local engine="$GEN/runs/$cid/engine/replay_v1_candidate.py"
  "$PY" - "$engine" "$lane_root" "$GEN/result/baseline_long.json" "$out" "$phase" "$cid" <<'PYSCORE'
import gzip,importlib.util,json,math,sys
from pathlib import Path
engine_path,lane_root,baseline_path,out_path=map(Path,sys.argv[1:5]); phase=sys.argv[5]; cid=sys.argv[6]
spec=importlib.util.spec_from_file_location(f"zel_score_{cid}_{phase}",engine_path)
e=importlib.util.module_from_spec(spec); sys.modules[spec.name]=e; assert spec.loader is not None; spec.loader.exec_module(e)
rows=[]; lane_files=sorted((lane_root/'vwap_revert').glob('*.json.gz'))
for p in lane_files:
    with gzip.open(p,'rt',encoding='utf-8') as h: payload=json.load(h)
    result=payload.get('result') or {}
    if result.get('strategy_id')!='vwap_revert': raise SystemExit(f'BAD_LANE_STRATEGY:{p}')
    for row in result.get('closed_rows') or []:
        if row.get('side')=='long': rows.append(row)
windows=sorted({str(r.get('window_id')) for r in rows})
metrics={w:e.metrics([r for r in rows if str(r.get('window_id'))==w]) for w in windows}
base=json.loads(baseline_path.read_text())
expected=['1m_w1','1m_w2'] if phase=='W12' else ['1m_w3']
if sorted(windows)!=sorted(expected): raise SystemExit(f'WINDOW_SET:{windows}!={expected}')
gates={}
for w in expected:
    b=base['by_window'][w]; c=metrics[w]
    min_samples=max(30,math.ceil(float(b['sample_count'])*0.50))
    gates[w]={
      'sample_min':min_samples,
      'sample_ok':int(c['sample_count'])>=min_samples,
      'pf_improved':float(c.get('profit_factor') or 0)>float(b.get('profit_factor') or 0),
      'net_improved':float(c.get('net_R') or 0)>float(b.get('net_R') or 0),
      'dd_nonworse':float(c.get('max_drawdown_R') or 0)<=float(b.get('max_drawdown_R') or 0),
    }
    gates[w]['pass']=all(v for k,v in gates[w].items() if k not in ('sample_min','pass'))
score=0.0
for w in expected:
    b=base['by_window'][w]; c=metrics[w]
    score += (float(c.get('net_R') or 0)-float(b.get('net_R') or 0))/max(abs(float(b.get('net_R') or 0)),1.0)
    score += float(c.get('profit_factor') or 0)-float(b.get('profit_factor') or 0)
    score += (float(b.get('max_drawdown_R') or 0)-float(c.get('max_drawdown_R') or 0))/max(float(b.get('max_drawdown_R') or 0),1.0)
    if not gates[w]['sample_ok']: score -= 2.0
payload={'schema_version':'zel.structural_premium.vwap_closed_loop.phase_score.v1','candidate_id':cid,'phase':phase,'scope':'vwap_revert.long','lane_file_count':len(lane_files),'metrics':metrics,'gates':gates,'phase_pass':all(g['pass'] for g in gates.values()),'diagnostic_score':score,'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
out_path.parent.mkdir(parents=True,exist_ok=True); out_path.write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps({'state':'PASS_PHASE_SCORED','candidate_id':cid,'phase':phase,'phase_pass':payload['phase_pass'],'diagnostic_score':score,'metrics':metrics,'gates':gates},sort_keys=True))
PYSCORE
}

# W1/W2 only for all Gen0 candidates. W3 is deliberately not touched here.
for cid in A B C; do
  prepare_candidate "$cid"
  run="$GEN/runs/$cid"
  mkdir -p "$run/replay_w12"
  "$PY" "$run/engine/lane_w12.py" \
    --engine-v1 "$run/engine/replay_v1_candidate.py" \
    --engine-v2 "$run/engine/replay_v2_candidate.py" \
    --source-root "$BASE/work/source" \
    --data-root "$DUR/work/data" \
    --interval 1m \
    --output-dir "$run/replay_w12" \
    --workers 4 2>&1 | tee "$run/logs/w12.log"
  test "$(find "$run/replay_w12/lane_checkpoints/vwap_revert" -type f -name '*.json.gz' | wc -l)" -eq 10
  score_phase "$cid" W12 "$run/replay_w12/lane_checkpoints" "$run/result/w12_score.json"
done

# Deterministic W1/W2 selector. W3 cannot influence this ranking.
"$PY" - "$GEN" <<'PYSEL'
import json,sys
from pathlib import Path
g=Path(sys.argv[1]); rows=[]
for cid in ('A','B','C'):
    p=json.loads((g/'runs'/cid/'result/w12_score.json').read_text()); rows.append(p)
passing=[r for r in rows if r['phase_pass']]
ranked=sorted(rows,key=lambda r:(-float(r['diagnostic_score']),r['candidate_id']))
ranked_pass=sorted(passing,key=lambda r:(-float(r['diagnostic_score']),r['candidate_id']))
winner=ranked_pass[0]['candidate_id'] if ranked_pass else None
diagnostic=ranked[0]['candidate_id'] if ranked else None
payload={'schema_version':'zel.structural_premium.vwap_closed_loop.w12_selection.v1','state':'PASS_W12_SURVIVOR' if winner else 'HOLD_NO_W12_SURVIVOR','winner':winner,'diagnostic_winner':diagnostic,'ranking':[{'candidate_id':r['candidate_id'],'phase_pass':r['phase_pass'],'diagnostic_score':r['diagnostic_score']} for r in ranked],'sealed_w3_used_for_selection':False,'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
(g/'result/w12_selection.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n'); print(json.dumps(payload,sort_keys=True))
PYSEL

WINNER=$("$PY" -c "import json; print(json.load(open('$GEN/result/w12_selection.json')).get('winner') or '')")
if [ -z "$WINNER" ]; then
  "$PY" - "$GEN/result/terminal_receipt.json" "$GEN/result/w12_selection.json" <<'PYTERM'
import json,sys
from pathlib import Path
out=Path(sys.argv[1]); sel=json.loads(Path(sys.argv[2]).read_text())
p={'schema_version':'zel.structural_premium.vwap_closed_loop.terminal.v1','state':'HOLD_GEN0_NO_W12_SURVIVOR','next':'AI_COUNCIL_REVIEW_AND_GEN1','diagnostic_winner':sel.get('diagnostic_winner'),'w3_accessed':False,'canonical_mutations':0,'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
out.write_text(json.dumps(p,indent=2,sort_keys=True)+'\n'); print(json.dumps(p,sort_keys=True))
PYTERM
else
  run="$GEN/runs/$WINNER"
  mkdir -p "$run/replay_w3"
  "$PY" "$run/engine/lane_w3.py" \
    --engine-v1 "$run/engine/replay_v1_candidate.py" \
    --engine-v2 "$run/engine/replay_v2_candidate.py" \
    --source-root "$BASE/work/source" \
    --data-root "$DUR/work/data" \
    --interval 1m \
    --output-dir "$run/replay_w3" \
    --workers 4 2>&1 | tee "$run/logs/w3.log"
  test "$(find "$run/replay_w3/lane_checkpoints/vwap_revert" -type f -name '*.json.gz' | wc -l)" -eq 5
  score_phase "$WINNER" W3 "$run/replay_w3/lane_checkpoints" "$run/result/w3_score.json"
  W3PASS=$("$PY" -c "import json; print('1' if json.load(open('$run/result/w3_score.json'))['phase_pass'] else '0')")
  if [ "$W3PASS" != 1 ]; then
    "$PY" - "$GEN/result/terminal_receipt.json" "$WINNER" <<'PYW3H'
import json,sys
from pathlib import Path
p={'schema_version':'zel.structural_premium.vwap_closed_loop.terminal.v1','state':'HOLD_GEN0_W3_REJECT','winner_w12':sys.argv[2],'next':'AI_COUNCIL_REVIEW_AND_GEN1','w3_accessed':True,'canonical_mutations':0,'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
Path(sys.argv[1]).write_text(json.dumps(p,indent=2,sort_keys=True)+'\n'); print(json.dumps(p,sort_keys=True))
PYW3H
  else
    MERGE="$GEN/merged_$WINNER"
    rm -rf "$MERGE"; mkdir -p "$MERGE/replay/lane_checkpoints" "$MERGE/engine" "$MERGE/result" "$MERGE/logs"
    cp "$BASE/work/engine/replay_v1_no_trend.py" "$MERGE/engine/replay_v1_no_trend.py"
    cp "$BASE/work/engine/replay_v2_no_trend.py" "$MERGE/engine/replay_v2_no_trend.py"
    cp "$BASE/work/engine/lane_checkpoint_v2.py" "$MERGE/engine/lane_checkpoint_v2.py"
    for s in support_resistance liquidity_sweep; do
      mkdir -p "$MERGE/replay/lane_checkpoints/$s"
      cp "$BASE/work/replay/lane_checkpoints/$s"/*.json.gz "$MERGE/replay/lane_checkpoints/$s/"
    done
    mkdir -p "$MERGE/replay/lane_checkpoints/vwap_revert"
    cp "$run/replay_w12/lane_checkpoints/vwap_revert"/*.json.gz "$MERGE/replay/lane_checkpoints/vwap_revert/"
    cp "$run/replay_w3/lane_checkpoints/vwap_revert"/*.json.gz "$MERGE/replay/lane_checkpoints/vwap_revert/"
    test "$(find "$MERGE/replay/lane_checkpoints" -type f -name '*.json.gz' | wc -l)" -eq 45

    # Stable 30 lane bytes must remain exactly identical to the base branch.
    for s in support_resistance liquidity_sweep; do
      diff -q <(cd "$BASE/work/replay/lane_checkpoints/$s" && sha256sum *.json.gz | sort) <(cd "$MERGE/replay/lane_checkpoints/$s" && sha256sum *.json.gz | sort)
    done

    "$PY" "$MERGE/engine/lane_checkpoint_v2.py" \
      --engine-v1 "$MERGE/engine/replay_v1_no_trend.py" \
      --engine-v2 "$MERGE/engine/replay_v2_no_trend.py" \
      --source-root "$BASE/work/source" \
      --data-root "$DUR/work/data" \
      --interval 1m \
      --output-dir "$MERGE/replay" \
      --workers 1 2>&1 | tee "$MERGE/logs/finalize_lanes.log"
    grep -q '"pending_units": 0' "$MERGE/logs/finalize_lanes.log"

    "$PY" "$MERGE/engine/replay_v2_no_trend.py" \
      --engine-v1 "$MERGE/engine/replay_v1_no_trend.py" \
      --source-root "$BASE/work/source" \
      --data-root "$DUR/work/data" \
      --interval 1m \
      --output-dir "$MERGE/replay" \
      --workers 1 2>&1 | tee "$MERGE/logs/aggregate.log"
    test -s "$MERGE/replay/report.json"; test -s "$MERGE/replay/trades.jsonl.gz"

    "$PY" - "$GEN/result/research_incumbent.json" "$GEN/candidates/$WINNER.json" "$run/result/w12_score.json" "$run/result/w3_score.json" "$MERGE/replay/report.json" <<'PYINC'
import hashlib,json,sys
from pathlib import Path
out,cand,w12,w3,report=map(Path,sys.argv[1:])
p={'schema_version':'zel.structural_premium.vwap_closed_loop.research_incumbent.v1','state':'PASS_RESEARCH_INCUMBENT_GEN0','scope':'vwap_revert.long','candidate':json.loads(cand.read_text()),'w12':json.loads(w12.read_text()),'w3':json.loads(w3.read_text()),'full_report_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),'canonical_mutations':0,'research_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
out.write_text(json.dumps(p,indent=2,sort_keys=True,allow_nan=False)+'\n'); print(json.dumps({'state':p['state'],'candidate_id':p['candidate']['candidate_id'],'full_report_sha256':p['full_report_sha256']},sort_keys=True))
PYINC
    cp "$GEN/result/research_incumbent.json" "$GEN/result/terminal_receipt.json"
  fi
fi

# Final protected-state verification.
test "$(sha256sum "$CANON/backend/strategies/sr_levels.py" | awk '{print $1}')" = "$CANON_SR"
if [ -n "$CANON_VWAP" ] && [ -s "$CANON/backend/strategies/vwap_reversion.py" ]; then test "$(sha256sum "$CANON/backend/strategies/vwap_reversion.py" | awk '{print $1}')" = "$CANON_VWAP"; fi
test "$(sha256sum "$CANON/backend/strategies/trend_rider.py" | awk '{print $1}')" = "$CANON_TR"
test "$(sha256sum "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" | awk '{print $1}')" = "$CANON_MAN"
test "$(sha256sum "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json" | awk '{print $1}')" = "$CANON_BIND"

echo '===BASELINE_LONG==='; cat "$GEN/result/baseline_long.json"
echo '===W12_SELECTION==='; cat "$GEN/result/w12_selection.json"
echo '===TERMINAL==='; cat "$GEN/result/terminal_receipt.json"
