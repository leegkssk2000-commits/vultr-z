#!/usr/bin/env bash
set -euo pipefail

C=/home/z/z/_ai_council
OUT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1/advisory
RUNNER=/tmp/zel-vwap-gen1-review.sh
mkdir -p "$OUT"
test -s "$RUNNER"
set -a
. "$C/.env"
set +a
BASE=${REQUESTY_BASE_URL:-https://router.requesty.ai/v1}
test -n "${REQUESTY_API_KEY:-}"

python3 - "$RUNNER" /tmp/gemini_review_body.json <<'PY'
import json,sys
from pathlib import Path
code=Path(sys.argv[1]).read_text()
q=("Review this ZEL research-only Gen1 VWAP LONG closed-loop runner for concrete correctness bugs. "
   "Requirements: Gen0 A/B/C all failed; Gen1 candidates are B60/B75 changing only B max_hold and C120 changing only C target; "
   "all candidates run W1 first, only W1 survivors may run W2, exactly one W12 winner may open W3; "
   "support_resistance/liquidity_sweep stable 30 lanes are reused only after W3 PASS; trend_rider excluded; canonical/paper/live/order/promotion mutation forbidden. "
   "Check window leakage, checkpoint contamination, candidate fingerprint/resume, scoring gates, W3 seal, canonical guard, aggregation, shell/Python errors. "
   "Return first line VERDICT=GO or VERDICT=BLOCK, then CRITICAL/MAJOR/MINOR findings and exact minimal fixes. CODE:\n"+code)
Path(sys.argv[2]).write_text(json.dumps({'model':'google/gemini-3.1-pro-preview','messages':[{'role':'user','content':q}],'temperature':0.0,'max_tokens':1800},ensure_ascii=False))
PY
GCODE=$(curl -sS -m 240 -o "$OUT/gen1_gemini_review.json" -w '%{http_code}' -H "Authorization: Bearer $REQUESTY_API_KEY" -H 'Content-Type: application/json' --data-binary @/tmp/gemini_review_body.json "$BASE/chat/completions" || true)
echo GEMINI_HTTP_CODE=$GCODE
test "$GCODE" = 200

python3 - "$RUNNER" "$OUT/gen1_gemini_review.json" /tmp/sol_review_body.json <<'PY'
import json,sys
from pathlib import Path
code=Path(sys.argv[1]).read_text(); r=json.loads(Path(sys.argv[2]).read_text())
g=((r.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
q=("You are final code-review judge for a research-only ZEL Gen1 VWAP runner. No live/order/promotion authority. "
   "Independently inspect the code and Gemini review. Return first line VERDICT=GO only if there is no CRITICAL correctness/safety bug; otherwise VERDICT=BLOCK. "
   "Focus on window leakage, stale checkpoint reuse across changed candidate engines, W3 leakage, canonical mutation, aggregation mismatch, shell/Python runtime errors. "
   "CODE:\n"+code+"\nGEMINI_REVIEW:\n"+g)
Path(sys.argv[3]).write_text(json.dumps({'model':'openai/gpt-5.6-sol','messages':[{'role':'user','content':q}],'temperature':0.0,'max_tokens':1800},ensure_ascii=False))
PY
SCODE=$(curl -sS -m 300 -o "$OUT/gen1_sol_review.json" -w '%{http_code}' -H "Authorization: Bearer $REQUESTY_API_KEY" -H 'Content-Type: application/json' --data-binary @/tmp/sol_review_body.json "$BASE/chat/completions" || true)
echo SOL_HTTP_CODE=$SCODE
test "$SCODE" = 200

python3 - "$OUT/gen1_gemini_review.json" "$OUT/gen1_sol_review.json" <<'PY'
import json,sys
from pathlib import Path
for path in map(Path,sys.argv[1:]):
    d=json.loads(path.read_text()); text=((d.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
    print('===',path.stem,'==='); print(text)
PY
