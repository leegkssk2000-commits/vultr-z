#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
GEN="$ROOT/gen0"
DUR=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1
CANON=/opt/zel/forward-expansion-v1/source
PY=/home/z/z/.venv/bin/python
CONTRACT_VERSION=VWAP_CLOSED_LOOP_V1_2_RESUME_W3_CANON_GUARDS
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASE_RUNNER="$SCRIPT_DIR/zel-structural-premium-vwap-closed-loop-v1.sh"
test -s "$BASE_RUNNER"

for p in \
  "$DUR/work/engine/replay_v1.py" \
  "$DUR/work/engine/replay_v2.py" \
  "$DUR/work/engine/lane_checkpoint_v2.py" \
  "$BASE/work/engine/replay_v1_no_trend.py" \
  "$BASE/work/engine/replay_v2_no_trend.py" \
  "$BASE/work/engine/lane_checkpoint_v2.py" \
  "$BASE/work/replay/trades.jsonl.gz" \
  "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" \
  "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json"; do
  test -s "$p"
done

canonical_fingerprint() {
  {
    find "$CANON/backend/strategies" -type f \
      ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | sort -z | xargs -0 sha256sum
    sha256sum \
      "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" \
      "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json"
  } | sha256sum | awk '{print $1}'
}

CANON_BEFORE=$(canonical_fingerprint)
verify_canonical_on_exit() {
  local rc=$?
  local after
  after=$(canonical_fingerprint)
  if [ "$after" != "$CANON_BEFORE" ]; then
    echo "CRITICAL_CANONICAL_MUTATION before=$CANON_BEFORE after=$after" >&2
    exit 97
  fi
  echo "PASS_CANONICAL_TREE_UNCHANGED $after"
  return "$rc"
}
trap verify_canonical_on_exit EXIT

mkdir -p "$GEN/result"
CURRENT_FP=$(
  {
    printf '%s\n' "$CONTRACT_VERSION"
    sha256sum "$BASE_RUNNER" \
      "$DUR/work/engine/replay_v1.py" \
      "$DUR/work/engine/replay_v2.py" \
      "$DUR/work/engine/lane_checkpoint_v2.py" \
      "$BASE/work/engine/replay_v1_no_trend.py" \
      "$BASE/work/engine/replay_v2_no_trend.py" \
      "$BASE/work/engine/lane_checkpoint_v2.py" \
      "$BASE/work/replay/trades.jsonl.gz"
  } | sha256sum | awk '{print $1}'
)
FP_FILE="$GEN/result/runner_contract_fingerprint.sha256"
OLD_FP=$(cat "$FP_FILE" 2>/dev/null || true)

# Unknown provenance is not resumable. This catches Gen0 caches produced before v1.2.
if [ -z "$OLD_FP" ] && [ -d "$GEN/runs" ] && find "$GEN/runs" -type f -print -quit 2>/dev/null | grep -q .; then
  rm -rf "$GEN/runs" "$GEN/merged_A" "$GEN/merged_B" "$GEN/merged_C"
  rm -f "$GEN/result/w12_selection.json" "$GEN/result/terminal_receipt.json" "$GEN/result/research_incumbent.json"
  echo "INVALIDATE_UNPROVENANCED_GEN0_CACHE"
fi

# Engine/data/runner changes invalidate all candidate replay caches.
if [ -n "$OLD_FP" ] && [ "$OLD_FP" != "$CURRENT_FP" ]; then
  rm -rf "$GEN/runs" "$GEN/merged_A" "$GEN/merged_B" "$GEN/merged_C"
  rm -f "$GEN/result/w12_selection.json" "$GEN/result/terminal_receipt.json" "$GEN/result/research_incumbent.json"
  echo "INVALIDATE_STALE_GEN0_CACHE old=$OLD_FP new=$CURRENT_FP"
fi
printf '%s\n' "$CURRENT_FP" > "$FP_FILE.tmp"
mv -f "$FP_FILE.tmp" "$FP_FILE"
echo "PASS_RUNNER_CONTRACT_FINGERPRINT $CURRENT_FP"

# Cached candidate engines must still match their candidate JSON and compile cleanly.
for cid in A B C; do
  run="$GEN/runs/$cid"
  cjson="$GEN/candidates/$cid.json"
  [ -d "$run" ] || continue
  valid=1
  [ -s "$cjson" ] || valid=0
  [ -s "$run/candidate.sha256" ] || valid=0
  if [ "$valid" = 1 ]; then
    csha=$(sha256sum "$cjson" | awk '{print $1}')
    [ "$(cat "$run/candidate.sha256")" = "$csha" ] || valid=0
  fi
  for f in replay_v1_candidate.py replay_v2_candidate.py lane_w12.py lane_w3.py; do
    [ -s "$run/engine/$f" ] || valid=0
  done
  if [ "$valid" = 1 ]; then
    "$PY" -m py_compile \
      "$run/engine/replay_v1_candidate.py" \
      "$run/engine/replay_v2_candidate.py" \
      "$run/engine/lane_w12.py" \
      "$run/engine/lane_w3.py" >/dev/null 2>&1 || valid=0
  fi
  if [ "$valid" = 1 ]; then
    "$PY" - "$run/engine/replay_v1_candidate.py" "$cjson" <<'PYCV' >/dev/null 2>&1 || valid=0
import ast,json,re,sys
from pathlib import Path
engine=Path(sys.argv[1]).read_text(); candidate=json.loads(Path(sys.argv[2]).read_text())
m=re.search(r'^_ZEL_OVERLAY = json\.loads\((.+)\)$',engine,re.M)
if not m: raise SystemExit(2)
encoded=ast.literal_eval(m.group(1)); embedded=json.loads(encoded)
if embedded.get('overlay_sha256') != candidate.get('overlay_sha256'): raise SystemExit(3)
if embedded.get('candidate_id') != candidate.get('candidate_id'): raise SystemExit(4)
if embedded.get('parameters') != candidate.get('parameters'): raise SystemExit(5)
PYCV
  fi
  if [ "$valid" != 1 ]; then
    rm -rf "$run"
    echo "INVALIDATE_CORRUPT_CANDIDATE_CACHE $cid"
  else
    echo "PASS_CANDIDATE_CACHE_VALID $cid"
  fi
done

# Base runner: W1/W2 selection first; W3 may execute only for that winner.
bash "$BASE_RUNNER"

# Explicit post-run W3 seal and finite-score checks. Fail closed on any leakage.
"$PY" - "$GEN" <<'PYPOST'
import json,math,sys
from pathlib import Path
g=Path(sys.argv[1]); selp=g/'result/w12_selection.json'; termp=g/'result/terminal_receipt.json'
if not selp.exists() or not termp.exists(): raise SystemExit('MISSING_SELECTION_OR_TERMINAL')
sel=json.loads(selp.read_text()); term=json.loads(termp.read_text()); winner=sel.get('winner')
for cid in ('A','B','C'):
    p=g/'runs'/cid/'result/w12_score.json'
    if not p.exists(): raise SystemExit(f'MISSING_W12_SCORE:{cid}')
    d=json.loads(p.read_text()); score=float(d['diagnostic_score'])
    if not math.isfinite(score): raise SystemExit(f'NONFINITE_W12_SCORE:{cid}')
    for w,m in d.get('metrics',{}).items():
        for k in ('net_R','max_drawdown_R'):
            v=m.get(k)
            if v is None or not math.isfinite(float(v)): raise SystemExit(f'NONFINITE_METRIC:{cid}:{w}:{k}')
        pf=m.get('profit_factor')
        if pf is None or not math.isfinite(float(pf)): raise SystemExit(f'NONFINITE_METRIC:{cid}:{w}:profit_factor')
for cid in ('A','B','C'):
    w3=list((g/'runs'/cid/'replay_w3/lane_checkpoints/vwap_revert').glob('*.json.gz')) if (g/'runs'/cid/'replay_w3/lane_checkpoints/vwap_revert').exists() else []
    if winner is None and w3: raise SystemExit(f'W3_LEAK_WITHOUT_W12_WINNER:{cid}:{len(w3)}')
    if winner is not None and cid != winner and w3: raise SystemExit(f'W3_LEAK_NONWINNER:{cid}:{len(w3)}')
if winner is not None:
    p=g/'runs'/winner/'result/w3_score.json'
    if not p.exists(): raise SystemExit(f'MISSING_WINNER_W3_SCORE:{winner}')
    d=json.loads(p.read_text()); score=float(d['diagnostic_score'])
    if not math.isfinite(score): raise SystemExit(f'NONFINITE_W3_SCORE:{winner}')
if term.get('research_only') is not True: raise SystemExit('TERMINAL_NOT_RESEARCH_ONLY')
if term.get('promotion_authority') is not False: raise SystemExit('PROMOTION_AUTHORITY_NOT_FALSE')
if term.get('execution_authority') != 'NONE': raise SystemExit('EXECUTION_AUTHORITY_NOT_NONE')
if term.get('order_authority') != 'BLOCKED': raise SystemExit('ORDER_AUTHORITY_NOT_BLOCKED')
print(json.dumps({'state':'PASS_V1_2_POST_GUARDS','winner':winner,'w3_seal':True,'finite_scores':True,'research_only':True},sort_keys=True))
PYPOST
