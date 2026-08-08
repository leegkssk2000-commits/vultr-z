#!/usr/bin/env bash
set -euo pipefail

SRC=${1:-/tmp/zel-structural-premium-vwap-closed-loop-gen1.sh}
DST=/tmp/zel-structural-premium-vwap-closed-loop-gen1-fixed.sh
PY=/home/z/z/.venv/bin/python

test -s "$SRC"
test -x "$PY"
cp "$SRC" "$DST"

"$PY" - "$DST" <<'PYFIX'
from pathlib import Path
import sys
p=Path(sys.argv[1])
t=p.read_text()
a='_ZEL_BASE_RESTORE=_restore_structural_premium_registry'
b='_ZEL_GEN1_PREV_RESTORE=_restore_structural_premium_registry'
c='restored=dict(_ZEL_BASE_RESTORE(source_root,raw_registry))'
d='restored=dict(_ZEL_GEN1_PREV_RESTORE(source_root,raw_registry))'
if t.count(a) != 1:
    raise SystemExit(f'RESTORE_CAPTURE_ANCHOR_COUNT:{t.count(a)}')
if t.count(c) != 1:
    raise SystemExit(f'RESTORE_CALL_ANCHOR_COUNT:{t.count(c)}')
t=t.replace(a,b,1).replace(c,d,1)
p.write_text(t)
print('PASS_GEN1_RUNTIME_RESTORE_RECURSION_FIX')
PYFIX

bash -n "$DST"
# Fail closed: the injected Gen1 wrapper must not overwrite the durable engine's
# pre-existing _ZEL_BASE_RESTORE global.
if grep -Fq '_ZEL_BASE_RESTORE=_restore_structural_premium_registry' "$DST"; then
  echo FAIL_OLD_RESTORE_CAPTURE_REMAINS >&2
  exit 95
fi
grep -Fq '_ZEL_GEN1_PREV_RESTORE=_restore_structural_premium_registry' "$DST"
grep -Fq 'restored=dict(_ZEL_GEN1_PREV_RESTORE(source_root,raw_registry))' "$DST"

exec bash "$DST"
