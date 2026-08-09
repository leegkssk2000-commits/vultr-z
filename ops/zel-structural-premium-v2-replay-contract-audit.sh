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

# Locate the feature_snapshot implementation referenced by the replay engine.
feature_files = []
for p in src.rglob('*.py'):
    try:
        t = p.read_text()
    except Exception:
        continue
    if 'def feature_snapshot' in t:
        feature_files.append(p)

feature_reports = []
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

# Extract snippets around strategy invocation/open/close paths to avoid inventing action semantics.
lines = text.splitlines()
def snippets(patterns, radius=4):
    hits=[]
    for i,line in enumerate(lines):
        if any(re.search(p,line) for p in patterns):
            a=max(0,i-radius); b=min(len(lines),i+radius+1)
            hits.append({'line':i+1,'text':'\n'.join(f'{j+1}: {lines[j]}' for j in range(a,b))})
    return hits[:40]

strategy_calls = snippets([r'\.strategy\(', r'strategy\('])
open_paths = snippets([r'open_position', r'valid_entry', r'entry_price', r'position\s*='])
close_paths = snippets([r'close_position', r'exit_reason', r'MAX_HOLD_MIN'])
feature_calls = snippets([r'feature_snapshot'])

# Static action literals in engine and strategy source, for actual schema discovery.
action_literals=set()
for p in [eng, *list(src.rglob('*.py'))]:
    try:t=p.read_text()
    except Exception:continue
    for m in re.finditer(r'["\'](?:action|signal|side|direction)["\']\s*:\s*["\']([^"\']+)["\']', t):
        action_literals.add(m.group(1).strip().lower())

# Replay frame causality: verify current frame ends at index + 1 and starts in the past.
causal_slice = bool(re.search(r'frame\.iloc\[max\(0,\s*index\s*-\s*FRAME_LIMIT\s*\+\s*1\)\s*:\s*index\s*\+\s*1\]', text))
uses_same_bar_close = 'current_price = float(last["close"])' in text or "current_price = float(last['close'])" in text

# Entry/management contract must be explicit in the engine before V2 structural overlays are allowed.
engine_has_entry_predicate = bool(re.search(r'def\s+.*entry.*action', text, re.I))
engine_has_position_state = 'state' in text and ('position' in text or 'open_position' in text)

blockers=[]
if not causal_slice:
    blockers.append('REPLAY_FRAME_CAUSAL_SLICE_UNPROVEN')
if any(x['static_causality_red_flag'] for x in feature_reports):
    blockers.append('FEATURE_SNAPSHOT_STATIC_CAUSALITY_RED_FLAG')
if not engine_has_entry_predicate:
    blockers.append('EXPLICIT_ENTRY_ACTION_CONTRACT_MISSING')
if uses_same_bar_close:
    blockers.append('SAME_BAR_SIGNAL_AND_EXECUTION_SEMANTICS_REQUIRE_LOCK')
if not feature_reports:
    blockers.append('FEATURE_SNAPSHOT_IMPLEMENTATION_NOT_FOUND')

report={
    'schema_version':'zel.structural_premium.v2.replay_contract.audit.v1',
    'state':'HARD_PAUSE_V2_AXIS_PATCHING' if blockers else 'PASS_REPLAY_CONTRACT_READY',
    'engine_path':str(eng),
    'frame_causal_slice_detected':causal_slice,
    'same_bar_close_execution_detected':uses_same_bar_close,
    'engine_explicit_entry_predicate_detected':engine_has_entry_predicate,
    'engine_position_state_detected':engine_has_position_state,
    'action_literals':sorted(action_literals),
    'feature_snapshot_files':feature_reports,
    'snippets':{
        'strategy_calls':strategy_calls,
        'open_paths':open_paths,
        'close_paths':close_paths,
        'feature_calls':feature_calls,
    },
    'blockers':blockers,
    'next':[
        'DEFINE_ENTRY_ACTION_FROM_ENGINE_OPEN_PATH',
        'DEFINE_MANAGEMENT_EXIT_PASSTHROUGH',
        'LOCK_FEATURE_SNAPSHOT_CAUSALITY',
        'LOCK_SIGNAL_BAR_VS_EXECUTION_BAR_SEMANTICS',
        'ONLY_THEN_ENABLE_V2_FREQUENCY_AND_PORTFOLIO_AXES',
    ],
    'research_only':True,
    'execution_authority':'NONE',
    'order_authority':'BLOCKED',
    'promotion_authority':False,
    'action':'hold',
}
out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
print('STATE',report['state'])
print('ACTION_LITERALS',sorted(action_literals))
print('CAUSAL_SLICE',causal_slice)
print('SAME_BAR_CLOSE',uses_same_bar_close)
print('ENTRY_PREDICATE',engine_has_entry_predicate)
print('FEATURE_FILES',len(feature_reports))
print('BLOCKERS',json.dumps(blockers))
for node in feature_reports:
    print('FEATURE',json.dumps(node,sort_keys=True))
print('===STRATEGY_CALL_SNIPPETS===')
for s in strategy_calls[:8]: print(s['text'])
print('===OPEN_SNIPPETS===')
for s in open_paths[:12]: print(s['text'])
print('===FEATURE_SNIPPETS===')
for s in feature_calls[:8]: print(s['text'])
PY

cat "$OUT/report.json"
