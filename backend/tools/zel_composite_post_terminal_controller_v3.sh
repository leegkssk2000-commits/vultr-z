#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID required}"
: "${VPS_HOST:?VPS_HOST required}"
: "${VPS_USER:?VPS_USER required}"
: "${SSH_KEY_PATH:?SSH_KEY_PATH required}"
: "${RESULTS_DIR:?RESULTS_DIR required}"

ROOT="$GITHUB_WORKSPACE"
OUT="$ROOT/out"
RESULTS="$RESULTS_DIR"
if [ ! -s "$SSH_KEY_PATH" ] && [ -s "$HOME/.ssh/vps_key" ]; then
  SSH_KEY_PATH="$HOME/.ssh/vps_key"
fi
test -s "$SSH_KEY_PATH"
SSH=(ssh -i "$SSH_KEY_PATH" -o BatchMode=yes -o ConnectTimeout=15 "$VPS_USER@$VPS_HOST")
mkdir -p "$OUT"

python - <<'PY' > "$OUT/idempotency_v3.json"
import hashlib,json
from pathlib import Path
latest=Path('results/runtime_results/zel/composite_post_terminal_v1/latest.json')
pin=Path('backend/research/zel_composite_live_source_pin_v1.json')
def stable(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
complete=False
reason='NO_PRIOR_V3_RECEIPT'
if latest.is_file():
    try:
        row=json.loads(latest.read_text())
        complete=(
          row.get('state')=='PASS_COMPOSITE_POST_TERMINAL_SEQUENCE_COMPLETE_RETAIN_INCUMBENT'
          and row.get('version')=='ZEL_COMPOSITE_TERMINAL_EVALUATOR_V3'
          and row.get('source_pin_sha256')==stable(json.loads(pin.read_text()))
          and row.get('parallel_adapter_readiness_bound') is True
        )
        reason='MATCHED_COMPLETE_V3_RECEIPT' if complete else 'PRIOR_RECEIPT_NOT_CURRENT_V3'
    except Exception as exc:
        reason=f'PRIOR_RECEIPT_INVALID:{type(exc).__name__}'
print(json.dumps({'complete':complete,'reason':reason},indent=2,sort_keys=True))
PY

if [ "$(python - <<'PY'
import json
print('true' if json.load(open('out/idempotency_v3.json'))['complete'] else 'false')
PY
)" = true ]; then
  echo 'PASS_ALREADY_COMPLETED_PINNED_V3_SEQUENCE'
  exit 0
fi

bash "$ROOT/backend/tools/zel_composite_post_terminal_controller_v2.sh"

if [ ! -s "$OUT/terminal_gate.json" ]; then
  echo 'HOLD_V2_NO_TERMINAL_GATE'
  exit 0
fi
if [ "$(python - <<'PY'
import json
print('true' if json.load(open('out/terminal_gate.json')).get('ready') else 'false')
PY
)" != true ]; then
  echo 'HOLD_1M_TERMINAL_PENDING_AFTER_V2'
  exit 0
fi
if [ ! -s "$OUT/evaluation/latest.json" ] || [ ! -s "$OUT/ablation_order_plan.json" ] || [ ! -s "$OUT/trade_method_behavior.json" ]; then
  echo 'HOLD_V2_SEQUENCE_ARTIFACTS_MISSING'
  exit 0
fi

cleanup_v3_raw() {
  rm -rf "$OUT/terminal_v3" "$OUT/terminal_v3.tar.gz"
}
trap cleanup_v3_raw EXIT

"${SSH[@]}" \
  'tar -C /var/lib/zel-research/data-b-1m-v2 -czf - terminal_receipt.json report.json summary.json scoreboard.csv trades.jsonl.gz progress.json artifact_manifest.json' \
  > "$OUT/terminal_v3.tar.gz"
mkdir -p "$OUT/terminal_v3"
tar -C "$OUT/terminal_v3" -xzf "$OUT/terminal_v3.tar.gz"
test -s "$OUT/terminal_v3/trades.jsonl.gz"

"${SSH[@]}" 'cat /home/z/z/backend/contracts/ZOS_SKILL_REGISTRY_v1.json' > "$OUT/skill_registry.json"
python -m json.tool "$OUT/skill_registry.json" >/dev/null

python - <<'PY'
import json
from pathlib import Path
from backend.tools import zel_skill_counterfactual_adapter_v1 as adapter
contract=json.loads(Path('backend/research/zel_skill_counterfactual_contract_v1.json').read_text())
registry=json.loads(Path('out/skill_registry.json').read_text())
skill_ids=[]
for row in registry.get('skills') or []:
    if isinstance(row,dict) and row.get('skill_id'):
        skill_ids.append(str(row['skill_id']))
result=adapter.build(contract,skill_ids,adapter.load_trade_schema(Path('out/terminal_v3/trades.jsonl.gz')))
Path('out/skill_adapter_terminal.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
PY

set +e
python "$ROOT/backend/tools/zel_lico_historical_min_data_mapper_v1.py" \
  --trades "$OUT/terminal_v3/trades.jsonl.gz" \
  --out "$OUT/lico_mapper_terminal.json"
lico_rc=$?
python "$ROOT/backend/tools/zel_trade_method_historical_adapter_v1.py" \
  --trades "$OUT/terminal_v3/trades.jsonl.gz" \
  --behavior "$OUT/trade_method_behavior.json" \
  --out "$OUT/trade_method_adapter_terminal.json"
method_rc=$?
set -e
test "$lico_rc" -eq 0 -o "$lico_rc" -eq 1
test "$method_rc" -eq 0 -o "$method_rc" -eq 1

python "$ROOT/backend/tools/zel_composite_terminal_evaluator_v3.py" \
  --terminal-root "$OUT/terminal_v3" \
  --plan "$OUT/ablation_order_plan.json" \
  --contract "$ROOT/backend/research/zel_composite_adapter_contract_v1.json" \
  --source-root "$ROOT" \
  --method-behavior "$OUT/trade_method_behavior.json" \
  --skill-adapter "$OUT/skill_adapter_terminal.json" \
  --lico-mapper "$OUT/lico_mapper_terminal.json" \
  --trade-method-adapter "$OUT/trade_method_adapter_terminal.json" \
  --out-dir "$OUT/evaluation_v3"

python - <<'PY'
import json
row=json.load(open('out/evaluation_v3/latest.json'))
assert row['state']=='PASS_COMPOSITE_POST_TERMINAL_SEQUENCE_COMPLETE_RETAIN_INCUMBENT',row
assert row['version']=='ZEL_COMPOSITE_TERMINAL_EVALUATOR_V3',row
assert row['parallel_adapter_readiness_bound'] is True,row
assert row['economic_survivor_count']==0,row
assert row['incumbent_retained'] is True,row
assert row['execution_authority']=='NONE' and row['order_authority']=='BLOCKED',row
for name in ('skill','lico','trade_method'):
    assert name in row['parallel_adapter_readiness'],row
print({'state':row['state'],'version':row['version'],'blockers':row['parallel_adapter_blocker_counts']})
PY

cd "$RESULTS"
git config user.name 'zel-composite-terminal-bot'
git config user.email 'zel-composite-terminal-bot@users.noreply.github.com'
git pull --rebase origin zel-data-expansion-results-v1
cd "$ROOT"
dest="$RESULTS/runtime_results/zel/composite_post_terminal_v1"
mkdir -p "$dest"
cp "$OUT/evaluation_v3/latest.json" "$dest/latest.json"
cp "$OUT/evaluation_v3/latest.json" "$dest/run_${GITHUB_RUN_ID}_v3.json"
cp "$OUT/evaluation_v3/w1_ablation.json" "$dest/w1_ablation_latest.json"
cp "$OUT/evaluation_v3/w2_forward.json" "$dest/w2_forward_latest.json"
cp "$OUT/evaluation_v3/w3_durability.json" "$dest/w3_durability_latest.json"
cp "$OUT/evaluation_v3/portfolio_joint_risk.json" "$dest/portfolio_joint_risk_latest.json"
cp "$OUT/skill_adapter_terminal.json" "$dest/skill_adapter_latest.json"
cp "$OUT/lico_mapper_terminal.json" "$dest/lico_mapper_latest.json"
cp "$OUT/trade_method_adapter_terminal.json" "$dest/trade_method_adapter_latest.json"
cd "$RESULTS"
git add runtime_results/zel/composite_post_terminal_v1
git commit -m "result(zel): Composite post-terminal adapter lineage ${GITHUB_RUN_ID}" || true
git push origin HEAD:zel-data-expansion-results-v1

echo 'PASS_COMPOSITE_POST_TERMINAL_CONTROLLER_V3'
