#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
RUN=$ROOT/gen3/neutral_entry_only_v1
ENG=$RUN/engine/replay_v1_neutral.py
SRC=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/source/tools/q4r3_exact25_dedicated_shadow_producer.py
BASEENG=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2/work/engine/replay_v1.py
PY=/home/z/z/.venv/bin/python

test -s "$ENG"
test -s "$SRC"
test -s "$BASEENG"

echo '===PATCH_REGION==='
grep -n -A120 -B40 'ZEL_GEN3_ENTRY_NEUTRAL_ONLY_V1' "$ENG" | head -220

echo '===WRAPPER_REGION==='
grep -n -A180 -B40 '^def _zel_wrap_strategy' "$ENG" | head -260 || true

echo '===RESTORE_REGION==='
grep -n -A220 -B40 '^def _restore_structural_premium_registry' "$ENG" | head -300 || true

echo '===STRATEGY_CALLS==='
grep -n -E 'strategy\(|owner\.strategy|strategy_fn' "$ENG" | head -120 || true

echo '===FEATURE_SNAPSHOT_DEF==='
grep -n -A180 -B20 '^def feature_snapshot' "$SRC" | head -240

echo '===HTF_BIAS_REFERENCES==='
grep -RIn --exclude='*.pyc' --exclude-dir='__pycache__' -E 'htf_bias|ema60|ema180|EMA_60|EMA_180' "$SRC" "$BASEENG" | head -200 || true

echo '===W2_LANE_META_SAMPLE==='
"$PY" - "$RUN/replay_w2/lane_checkpoints/vwap_revert" <<'PY'
import gzip,json,sys
from pathlib import Path
root=Path(sys.argv[1])
for p in sorted(root.glob('*.json.gz'))[:2]:
    with gzip.open(p,'rt',encoding='utf-8') as h:d=json.load(h)
    r=d.get('result') or {}
    print('LANE',p.name,'TOP_KEYS',sorted(d.keys()))
    print('RESULT_KEYS',sorted(r.keys()))
    rows=[x for x in (r.get('closed_rows') or []) if x.get('side')=='long']
    print('CLOSED_LONG',len(rows))
    for x in rows[:5]:
        print(json.dumps({k:x.get(k) for k in ('symbol','entry_ts','exit_ts','regime','entry_features','exit_features','close_reason','realized_R')},sort_keys=True))
PY

echo '===DONE==='
