#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
ROOT=/opt/zel/research-runtime/jobs/structural-premium-v2
ENG=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2/work/engine/replay_v1.py
SRC=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/source
OUT=$ROOT/replay_contract_v1
mkdir -p "$OUT"
test -s "$ENG"

"$PY" - "$ENG" "$SRC" "$OUT/report.json" <<'PY'
import ast
import json
import re
import sys
from pathlib import Path

eng = Path(sys.argv[1])
src = Path(sys.argv[2])
out = Path(sys.argv[3])
text = eng.read_text()

feature_files = []
for p in src.rglob('*.py'):
    try:
        t = p.read_text()
    except Exception:
        continue
    if 'def feature_snapshot' in t:
        feature_files.append(p)

feature_reports = []
producer_contracts = []
for p in feature_files:
    t = p.read_text()
    negative_shift = bool(re.search(r'\.shift\(\s*-', t))
    centered_rolling = bool(re.search(r'rolling\([^\n]*center\s*=\s*True', t))
    future_iloc = bool(re.search(r'iloc\[[^\]]*\+\s*1', t))
    future_slice = bool(re.search(r'\[[^\]]*:\s*[^\]]*\+\s*[12]\]', t))
    feature_reports.append({
        'path': str(p),
        'negative_shift': negative_shift,
        'centered_rolling': centered_rolling,
        'future_iloc_pattern': future_iloc,
        'future_slice_pattern': future_slice,
        'static_causality_red_flag': negative_shift or centered_rolling or future_iloc,
    })
    tree = ast.parse(t)
    linesp = t.splitlines()
    funcs={}
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'feature_snapshot','valid_entry','make_position','apply_add','close_position','bar_exit'}:
            start=node.lineno-1; end=getattr(node,'end_lineno',node.lineno)
            funcs[node.name]='\n'.join(f'{i+1}: {linesp[i]}' for i in range(start,min(end,len(linesp))))
    producer_contracts.append({'path':str(p),'functions':funcs})

causal_slice = bool(re.search(r'frame\.iloc\[max\(0,\s*index\s*-\s*FRAME_LIMIT\s*\+\s*1\)\s*:\s*index\s*\+\s*1\]', text))
uses_same_bar_close = 'current_price = float(last["close"])' in text or "current_price = float(last['close'])" in text
valid_entry_open_contract = 'producer.valid_entry(result, current_price)' in text and 'producer.make_position(' in text
stateful_branch = 'if isinstance(position, dict):' in text
apply_add_contract = 'producer.apply_add(position, result, current_price' in text
exit_contract = 'action in {"exit", "close", "stop"}' in text
management_contract = stateful_branch and apply_add_contract and exit_contract

blockers=[]
if not causal_slice:
    blockers.append('REPLAY_FRAME_CAUSAL_SLICE_UNPROVEN')
if any(x['static_causality_red_flag'] for x in feature_reports):
    blockers.append('FEATURE_SNAPSHOT_STATIC_CAUSALITY_RED_FLAG')
if not valid_entry_open_contract:
    blockers.append('VALID_ENTRY_OPEN_CONTRACT_MISSING')
if not management_contract:
    blockers.append('STATEFUL_MANAGEMENT_CONTRACT_UNPROVEN')
if uses_same_bar_close:
    blockers.append('SAME_BAR_SIGNAL_AND_EXECUTION_SEMANTICS_REQUIRE_LOCK')
if not feature_reports:
    blockers.append('FEATURE_SNAPSHOT_IMPLEMENTATION_NOT_FOUND')

report={
    'schema_version':'zel.structural_premium.v2.replay_contract.audit.v3',
    'state':'HARD_PAUSE_V2_AXIS_PATCHING' if blockers else 'PASS_REPLAY_CONTRACT_READY',
    'engine_path':str(eng),
    'frame_causal_slice_detected':causal_slice,
    'same_bar_close_execution_detected':uses_same_bar_close,
    'valid_entry_open_contract_detected':valid_entry_open_contract,
    'stateful_management_contract_detected':management_contract,
    'feature_snapshot_files':feature_reports,
    'producer_contracts':producer_contracts,
    'blockers':blockers,
    'next':[
        'USE_PRODUCER_VALID_ENTRY_AS_ONLY_NEW_ENTRY_PREDICATE',
        'PASS_THROUGH_ALL_RESULTS_WHEN_POSITION_IS_OPEN',
        'PRESERVE_SIGNAL_BAR_ENTRY_FEATURES',
        'EXECUTE_NEW_ENTRY_AT_NEXT_BAR_OPEN',
        'THEN_ENABLE_V2_FREQUENCY_AND_PORTFOLIO_AXES',
    ],
    'research_only':True,
    'execution_authority':'NONE',
    'order_authority':'BLOCKED',
    'promotion_authority':False,
    'action':'hold',
}
out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
print('STATE',report['state'])
print('CAUSAL_SLICE',causal_slice)
print('SAME_BAR_CLOSE',uses_same_bar_close)
print('VALID_ENTRY_OPEN_CONTRACT',valid_entry_open_contract)
print('STATEFUL_MANAGEMENT_CONTRACT',management_contract)
print('FEATURE_FILES',len(feature_reports))
print('BLOCKERS',json.dumps(blockers))
for node in feature_reports:
    print('FEATURE',json.dumps(node,sort_keys=True))
print('===PRODUCER_CONTRACTS===')
for node in producer_contracts:
    print('PRODUCER_PATH',node.get('path'))
    for name,body in (node.get('functions') or {}).items():
        print(f'---{name}---')
        print(body)
PY

echo '===EXACT_REPLAY_LOOP_450_570==='
sed -n '450,570p' "$ENG"
echo '===REPORT==='
cat "$OUT/report.json"
