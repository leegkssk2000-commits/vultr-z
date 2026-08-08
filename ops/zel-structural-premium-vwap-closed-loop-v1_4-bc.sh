#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
GEN="$ROOT/gen0"
CANON=/opt/zel/forward-expansion-v1/source
PY=/home/z/z/.venv/bin/python
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASE_RUNNER="$SCRIPT_DIR/zel-structural-premium-vwap-closed-loop-v1.sh"
PATCHED_RUNNER=/tmp/zel-structural-premium-vwap-closed-loop-bc-runtime.sh

test -s "$BASE_RUNNER"
test -x "$PY"

# Superseded GitHub runs can leave ProcessPool children on the VPS. Reap only this
# isolated research lane before continuing from B/C.
PIDS=$(pgrep -f "$ROOT/gen0/runs/.*/engine/lane_w(12|3)\.py" || true)
if [ -n "$PIDS" ]; then
  echo "REAP_SUPERSEDED_VWAP_WORKERS term=$PIDS"
  kill -TERM $PIDS 2>/dev/null || true
  sleep 2
fi
PIDS=$(pgrep -f "$ROOT/gen0/runs/.*/engine/lane_w(12|3)\.py" || true)
if [ -n "$PIDS" ]; then
  echo "REAP_SUPERSEDED_VWAP_WORKERS kill=$PIDS"
  kill -KILL $PIDS 2>/dev/null || true
  sleep 1
fi
if pgrep -f "$ROOT/gen0/runs/.*/engine/lane_w(12|3)\.py" >/dev/null; then
  echo "FAIL_ORPHAN_VWAP_WORKERS_REMAIN" >&2
  exit 96
fi

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
"$PY" - "$GEN/result/skipped_A.json" <<'PYSKIP'
import json,sys
from pathlib import Path
p={
  "schema_version":"zel.structural_premium.vwap_closed_loop.skip.v1",
  "candidate_id":"A",
  "state":"SKIPPED_USER_DIRECTED_AFTER_WORSE_PARTIAL",
  "reason":"A partial paired result worsened net_R, drawdown and win_rate; continue identical contract with B/C",
  "selection_eligible":False,
  "w3_eligible":False,
  "research_only":True,
  "selection_authority":False,
  "promotion_authority":False,
  "execution_authority":"NONE",
  "order_authority":"BLOCKED",
  "action":"hold"
}
Path(sys.argv[1]).write_text(json.dumps(p,indent=2,sort_keys=True)+"\n")
print(json.dumps(p,sort_keys=True))
PYSKIP

# Patch only the execution/selection candidate set in an ephemeral runtime copy.
# The repository base runner and canonical strategy source are not edited here.
cp "$BASE_RUNNER" "$PATCHED_RUNNER"
"$PY" - "$PATCHED_RUNNER" <<'PYPATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1]); t=p.read_text()
old_loop='for cid in A B C; do'
old_select="for cid in ('A','B','C'):"
if t.count(old_loop) != 1:
    raise SystemExit(f'BC_PATCH_LOOP_ANCHOR_COUNT:{t.count(old_loop)}')
if t.count(old_select) != 1:
    raise SystemExit(f'BC_PATCH_SELECTOR_ANCHOR_COUNT:{t.count(old_select)}')
t=t.replace(old_loop,'for cid in B C; do',1)
t=t.replace(old_select,"for cid in ('B','C'):",1)
t=t.replace('# W1/W2 only for all Gen0 candidates. W3 is deliberately not touched here.',
            '# W1/W2 only for B/C. A is explicitly skipped after worse paired partial result; W3 remains sealed.',1)
p.write_text(t)
print('PASS_EPHEMERAL_BC_PATCH')
PYPATCH
bash -n "$PATCHED_RUNNER"

echo "START_IDENTICAL_CONTRACT_BC_ONLY"
bash "$PATCHED_RUNNER"

# Fail closed: A must not participate in selection or W3; B/C must have finite W12 scores.
"$PY" - "$GEN" <<'PYPOST'
import json,math,sys
from pathlib import Path
g=Path(sys.argv[1])
sel=json.loads((g/'result/w12_selection.json').read_text())
rank_ids=[str(x.get('candidate_id')) for x in sel.get('ranking',[])]
if 'A' in rank_ids:
    raise SystemExit('A_LEAKED_INTO_SELECTION')
if any(x not in {'B','C'} for x in rank_ids):
    raise SystemExit(f'UNEXPECTED_SELECTION_IDS:{rank_ids}')
for cid in ('B','C'):
    p=g/'runs'/cid/'result/w12_score.json'
    if not p.exists():
        raise SystemExit(f'MISSING_W12_SCORE:{cid}')
    d=json.loads(p.read_text())
    if not math.isfinite(float(d.get('diagnostic_score'))):
        raise SystemExit(f'NONFINITE_SCORE:{cid}')
    if int(d.get('lane_file_count',0)) != 10:
        raise SystemExit(f'BAD_W12_LANE_COUNT:{cid}:{d.get("lane_file_count")}')
for p in (g/'runs/A/replay_w3/lane_checkpoints/vwap_revert').glob('*.json.gz') if (g/'runs/A/replay_w3/lane_checkpoints/vwap_revert').exists() else []:
    raise SystemExit(f'A_W3_LEAK:{p}')
term=json.loads((g/'result/terminal_receipt.json').read_text())
if term.get('research_only') is not True: raise SystemExit('TERMINAL_NOT_RESEARCH_ONLY')
if term.get('promotion_authority') is not False: raise SystemExit('PROMOTION_AUTHORITY_NOT_FALSE')
if term.get('execution_authority') != 'NONE': raise SystemExit('EXECUTION_AUTHORITY_NOT_NONE')
if term.get('order_authority') != 'BLOCKED': raise SystemExit('ORDER_AUTHORITY_NOT_BLOCKED')
print(json.dumps({
  'state':'PASS_BC_IDENTICAL_CONTRACT_POST_GUARDS',
  'skipped':['A'],
  'evaluated':['B','C'],
  'winner':sel.get('winner'),
  'ranking':sel.get('ranking'),
  'research_only':True
},sort_keys=True))
PYPOST
