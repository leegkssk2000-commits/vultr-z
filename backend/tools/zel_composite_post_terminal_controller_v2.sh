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
SSH=(ssh -i "$SSH_KEY_PATH" -o BatchMode=yes -o ConnectTimeout=15 "$VPS_USER@$VPS_HOST")
mkdir -p "$OUT"

cleanup_raw() {
  rm -rf "$OUT/terminal" "$OUT/terminal.tar.gz"
}
trap cleanup_raw EXIT

python - <<'PY' > "$OUT/idempotency.json"
import hashlib,json
from pathlib import Path
root=Path.cwd()
latest=Path('results/runtime_results/zel/composite_post_terminal_v1/latest.json')
pin=Path('backend/research/zel_composite_live_source_pin_v1.json')
def stable(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
complete=False
reason='NO_PRIOR_RECEIPT'
if latest.is_file():
    try:
        row=json.loads(latest.read_text())
        complete=(
            row.get('state')=='PASS_COMPOSITE_POST_TERMINAL_SEQUENCE_COMPLETE_RETAIN_INCUMBENT'
            and row.get('version')=='ZEL_COMPOSITE_TERMINAL_EVALUATOR_V2'
            and row.get('source_pin_sha256')==stable(json.loads(pin.read_text()))
        )
        reason='MATCHED_COMPLETE_RECEIPT' if complete else 'PRIOR_RECEIPT_NOT_CURRENT_COMPLETE'
    except Exception as exc:
        reason=f'PRIOR_RECEIPT_INVALID:{type(exc).__name__}'
print(json.dumps({'complete':complete,'reason':reason},indent=2,sort_keys=True))
PY

if [ "$(python - <<'PY'
import json
print('true' if json.load(open('out/idempotency.json'))['complete'] else 'false')
PY
)" = true ]; then
  echo 'PASS_ALREADY_COMPLETED_PINNED_SEQUENCE'
  exit 0
fi

"${SSH[@]}" 'python3 -' > "$OUT/terminal_gate.json" <<'PY'
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
root=Path('/var/lib/zel-research/data-b-1m-v2')
terminal={}; report={}; progress={}
for name,target in (('terminal_receipt.json',terminal),('report.json',report),('progress.json',progress)):
    path=root/name
    if path.is_file():
        try: target.update(json.loads(path.read_text()))
        except Exception: target.update({'state':'INVALID_JSON'})
ready=(
    terminal.get('state')=='PASS'
    and report.get('state')=='PASS'
    and report.get('interval')=='1m'
    and (report.get('replay') or {}).get('strategy_count_completed')==25
    and (report.get('replay') or {}).get('strategy_failure_count')==0
    and progress.get('state')=='PASS'
    and progress.get('completed_units')==25
)
out={
  'schema_version':'zel.composite.terminal_gate.v2',
  'generated_at':datetime.now(timezone.utc).isoformat(),
  'state':'PASS_1M_TERMINAL_READY_FOR_COMPOSITE' if ready else 'HOLD_1M_TERMINAL_PENDING',
  'ready':ready,
  'terminal_state':terminal.get('state'),
  'report_state':report.get('state'),
  'progress_state':progress.get('state'),
  'completed_units':progress.get('completed_units'),
  'total_units':progress.get('total_units'),
  'closed_trade_count':(report.get('replay') or {}).get('closed_trade_count'),
  'terminal_receipt_sha256':hashlib.sha256(json.dumps(terminal,sort_keys=True,separators=(',',':')).encode()).hexdigest() if terminal else None,
  'read_only':True,
  'active_data_b_1m_mutated':False,
  'execution_authority':'NONE',
  'order_authority':'BLOCKED',
  'action':'hold',
}
print(json.dumps(out,indent=2,sort_keys=True))
PY

if [ "$(python - <<'PY'
import json
print('true' if json.load(open('out/terminal_gate.json')).get('ready') else 'false')
PY
)" != true ]; then
  python -m json.tool "$OUT/terminal_gate.json"
  echo 'HOLD_1M_TERMINAL_PENDING'
  exit 0
fi

"${SSH[@]}" \
  'tar -C /var/lib/zel-research/data-b-1m-v2 -czf - terminal_receipt.json report.json summary.json scoreboard.csv trades.jsonl.gz progress.json artifact_manifest.json' \
  > "$OUT/terminal.tar.gz"
mkdir -p "$OUT/terminal"
tar -C "$OUT/terminal" -xzf "$OUT/terminal.tar.gz"
test -s "$OUT/terminal/trades.jsonl.gz"

set +e
"${SSH[@]}" "python3 - --root /home/z/z --inventory-stdout" \
  < "$ROOT/backend/tools/zel_composite_source_rebinding_v1.py" \
  > "$OUT/live_source_inventory_base.json"
base_rc=$?
set -e
test -s "$OUT/live_source_inventory_base.json"
"${SSH[@]}" "python3 - --root /home/z/z --stdout" \
  < "$ROOT/backend/tools/zel_composite_source_live_patch_v1.py" \
  > "$OUT/live_source_patch.json"
python "$ROOT/backend/tools/zel_composite_source_inventory_merge_v1.py" \
  --base "$OUT/live_source_inventory_base.json" \
  --live-patch "$OUT/live_source_patch.json" \
  --git-root "$ROOT" \
  --out "$OUT/live_source_inventory_current.json"
python - <<'PY'
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
pin=json.loads(Path('backend/research/zel_composite_live_source_pin_v1.json').read_text())
current=json.loads(Path('out/live_source_inventory_current.json').read_text())
expected={row['module_id']:row for row in pin['modules']}
actual=current['bindings']
mismatches=[]
for module_id in sorted(set(expected)|set(actual)):
    left=expected.get(module_id); right=actual.get(module_id)
    if not left or not right:
        mismatches.append({'module_id':module_id,'reason':'MODULE_SET_MISMATCH'})
    elif left['source_bundle_sha256']!=right['source_bundle_sha256']:
        mismatches.append({'module_id':module_id,'reason':'SOURCE_BUNDLE_SHA_DRIFT'})
    elif left['file_count']!=right['file_count']:
        mismatches.append({'module_id':module_id,'reason':'FILE_COUNT_DRIFT'})
result={
  'schema_version':'zel.composite.source_pin_runtime_parity.v2',
  'generated_at':datetime.now(timezone.utc).isoformat(),
  'state':'PASS_COMPOSITE_SOURCE_PIN_RUNTIME_PARITY' if not mismatches else 'HOLD_COMPOSITE_SOURCE_PIN_RUNTIME_DRIFT',
  'module_count':len(actual),
  'verified_module_count':len(actual)-len({row['module_id'] for row in mismatches}),
  'mismatches':mismatches,
  'pin_file_sha256':hashlib.sha256(Path('backend/research/zel_composite_live_source_pin_v1.json').read_bytes()).hexdigest(),
  'execution_authority':'NONE',
  'order_authority':'BLOCKED',
  'action':'hold',
}
Path('out/source_pin_parity.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
assert result['state']=='PASS_COMPOSITE_SOURCE_PIN_RUNTIME_PARITY',result
assert result['verified_module_count']==12,result
PY

tar -czf - \
  backend/tools/zel_bingx_private_history_fetch_v1.py \
  backend/tools/zel_bingx_execution_evidence_collector_v1.py \
  backend/tools/zel_bingx_readonly_secret_connector_v2.py \
| "${SSH[@]}" '
    set -euo pipefail
    tmp=$(mktemp -d /tmp/zel-bingx-composite.XXXXXX)
    trap "rm -rf $tmp" EXIT
    tar -xzf - -C "$tmp"
    python3 "$tmp/backend/tools/zel_bingx_readonly_secret_connector_v2.py" --root "$tmp" --lookback-days 90 --stdout
  ' > "$OUT/bingx_readonly_receipt.json"
python - <<'PY'
import json
row=json.load(open('out/bingx_readonly_receipt.json'))
assert row['state']=='PASS_BINGX_READ_ONLY_SECRET_CONNECTED',row
assert row['verified_candidate_count']==1,row
assert row['methods_allowed']==['GET'],row
assert row['credentials_persisted'] is False,row
assert row['private_history_persisted'] is False,row
assert row['raw_order_ids_persisted'] is False,row
assert row['execution_authority']=='NONE' and row['order_authority']=='BLOCKED',row
PY

python "$ROOT/backend/tools/zel_composite_pinned_registry_v1.py" \
  --registry "$ROOT/backend/research/zel_composite_module_registry_v1.json" \
  --pin "$ROOT/backend/research/zel_composite_live_source_pin_v1.json" \
  --out-registry "$OUT/pinned_registry.json" \
  --out-receipt "$OUT/pinned_registry_receipt.json"
python "$ROOT/backend/tools/zel_composite_module_factory_v3.py" \
  --registry "$OUT/pinned_registry.json" \
  --contract "$ROOT/backend/research/zel_composite_module_factory_contract_v1.json" \
  --checkpoint-ref pre-composite-factory-v1-20260802 \
  --out "$OUT/factory_v3_pinned.json"
python "$ROOT/backend/tools/zel_composite_ablation_plan_v2.py" \
  --factory "$OUT/factory_v3_pinned.json" \
  --contract "$ROOT/backend/research/zel_composite_adapter_contract_v1.json" \
  --registry "$OUT/pinned_registry.json" \
  --out "$OUT/ablation_order_plan.json"
python - <<'PY'
import json
plan=json.load(open('out/ablation_order_plan.json'))
assert plan['state']=='PASS_COMPOSITE_ABLATION_ORDER_PLAN',plan
assert plan['candidate_count']==30,plan
assert plan['w2_eligible_candidate_count']==13,plan
assert plan['terminal_required_before_execution'] is True,plan
PY

tar -czf - \
  backend/research/zel_composite_adapter_contract_v1.json \
  backend/research/strategy11_portfolio_governor_v1.py \
  backend/tools/zel_composite_adapter_contract_validator_v1.py \
| "${SSH[@]}" '
    set -euo pipefail
    tmp=$(mktemp -d /tmp/zel-composite-contract.XXXXXX)
    trap "rm -rf $tmp" EXIT
    tar -xzf - -C "$tmp"
    python3 "$tmp/backend/tools/zel_composite_adapter_contract_validator_v1.py" \
      --runtime-root /home/z/z --git-root "$tmp" \
      --contract "$tmp/backend/research/zel_composite_adapter_contract_v1.json" --stdout
  ' > "$OUT/adapter_contract_validation.json"
python - <<'PY'
import json
row=json.load(open('out/adapter_contract_validation.json'))
assert row['state']=='PASS_COMPOSITE_ADAPTER_CONTRACTS',row
assert row['adapter_pass_count']==12,row
assert row['structural_only_module_ids']==['ZICO'],row
assert row['post_score_module_ids']==['PORTFOLIO_GOVERNOR'],row
PY

"${SSH[@]}" \
  "python3 - --source-root /home/z/z --trades /var/lib/zel-research/data-b-1m-v2/trades.jsonl.gz --stdout" \
  < "$ROOT/backend/tools/zel_trade_method_runtime_behavior_v1.py" \
  > "$OUT/trade_method_behavior.json"
python - <<'PY'
import json
row=json.load(open('out/trade_method_behavior.json'))
assert row['state']=='PASS_TRADE_METHOD_DISABLED_HOLD_BEHAVIOR',row
assert row['enabled_strategy_count']==0,row
assert row['unsafe_strategy_count']==0,row
assert row['execution_authority']=='NONE' and row['order_authority']=='BLOCKED',row
PY

python "$ROOT/backend/tools/zel_composite_terminal_evaluator_v2.py" \
  --terminal-root "$OUT/terminal" \
  --plan "$OUT/ablation_order_plan.json" \
  --contract "$ROOT/backend/research/zel_composite_adapter_contract_v1.json" \
  --source-root "$ROOT" \
  --method-behavior "$OUT/trade_method_behavior.json" \
  --out-dir "$OUT/evaluation"
python - <<'PY'
import json
row=json.load(open('out/evaluation/latest.json'))
assert row['state']=='PASS_COMPOSITE_POST_TERMINAL_SEQUENCE_COMPLETE_RETAIN_INCUMBENT',row
assert row['strategy_count_completed']==25,row
assert set(row['window_trade_counts'])=={'1m_w1','1m_w2','1m_w3'},row
assert row['duplicate_event_count']==0,row
assert row['economic_survivor_count']==0,row
assert row['incumbent_retained'] is True,row
assert row['stages']['W1_ABLATION']['state']=='PASS_COMPOSITE_W1_ABLATION_PARITY_ONLY_NO_ALPHA',row
assert row['stages']['W2_FORWARD']['state']=='PASS_COMPOSITE_W2_FORWARD_PARITY_ONLY_NO_ALPHA',row
assert row['stages']['W3_DURABILITY']['state']=='PASS_COMPOSITE_W3_DURABILITY_PARITY_ONLY_NO_ALPHA',row
assert row['stages']['PORTFOLIO_JOINT_RISK']['state']=='PASS_COMPOSITE_PORTFOLIO_JOINT_RISK_RETAIN_INCUMBENT_NO_EDGE',row
assert row['execution_authority']=='NONE' and row['order_authority']=='BLOCKED',row
PY

cd "$RESULTS"
git config user.name 'zel-composite-terminal-bot'
git config user.email 'zel-composite-terminal-bot@users.noreply.github.com'
git pull --rebase origin zel-data-expansion-results-v1
cd "$ROOT"
dest="$RESULTS/runtime_results/zel/composite_post_terminal_v1"
mkdir -p "$dest"
cp "$OUT/evaluation/latest.json" "$dest/latest.json"
cp "$OUT/evaluation/latest.json" "$dest/run_${GITHUB_RUN_ID}.json"
cp "$OUT/evaluation/w1_ablation.json" "$dest/w1_ablation_latest.json"
cp "$OUT/evaluation/w2_forward.json" "$dest/w2_forward_latest.json"
cp "$OUT/evaluation/w3_durability.json" "$dest/w3_durability_latest.json"
cp "$OUT/evaluation/portfolio_joint_risk.json" "$dest/portfolio_joint_risk_latest.json"
cp "$OUT/source_pin_parity.json" "$dest/source_pin_parity_latest.json"
cp "$OUT/bingx_readonly_receipt.json" "$dest/bingx_readonly_gate_latest.json"
cp "$OUT/trade_method_behavior.json" "$dest/trade_method_behavior_latest.json"
cp "$OUT/adapter_contract_validation.json" "$dest/adapter_contract_validation_latest.json"
cp "$OUT/ablation_order_plan.json" "$dest/ablation_order_plan_latest.json"
cd "$RESULTS"
git add runtime_results/zel/composite_post_terminal_v1
git commit -m "result(zel): Composite post-terminal sequence ${GITHUB_RUN_ID}" || true
git push origin HEAD:zel-data-expansion-results-v1

echo "PASS_COMPOSITE_POST_TERMINAL_CONTROLLER_V2 base_inventory_rc=$base_rc"
