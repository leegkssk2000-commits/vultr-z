#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=2
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT

export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4C_START' \
  'MODE=READ_ONLY_HISTORICAL_SIMULATION_INPUT_LINEAGE' \
  'HISTORICAL_MARKET_DATA_READ_ALLOWED=true' \
  'SCENARIO_PLAN_GENERATION_ALLOWED=true' \
  'HISTORICAL_SIMULATION_EXECUTION_ALLOWED=false' \
  'EXECUTION_COST_APPLICATION_ALLOWED=false' \
  'HISTORICAL_REPLAY_EXECUTION_ALLOWED=false' \
  'CANONICAL_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'R7A4C_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4c.XXXXXX)" || exit 2
for path in \
  backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json \
  tools/r7a4c_historical_simulation_input_lineage.py \
  tests/test_r7a4c_historical_simulation_input_lineage.py
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'R7A4C_BOOTSTRAP_COMPLETE'
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4c_historical_simulation_input_lineage.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'R7A4C_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

if ! PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q "$TMP/tests/test_r7a4c_historical_simulation_input_lineage.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'R7A4C_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4c_historical_simulation_input_lineage.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --contract "$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json"
RC=$?

MANIFEST="$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
if [[ -f "$MANIFEST" ]]; then
  python3 - "$MANIFEST" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print("MARKET_REJECTION_DIAGNOSTIC_ERROR=" + json.dumps(f"{type(exc).__name__}:{exc}"))
else:
    rows = payload.get("rejected_market_sources", [])
    normalized = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        reason = str(row.get("reason") or "UNKNOWN")
        category = reason.split(":", 2)[1] if reason.startswith(("ValueError:", "TypeError:", "ParserError:")) and ":" in reason else reason.split(":", 1)[0]
        normalized.append({"path": str(row.get("path") or ""), "reason": reason, "category": category})
    histogram = Counter(item["category"] for item in normalized)
    print("REJECTED_MARKET_COUNT=" + str(len(normalized)))
    print("REJECTED_MARKET_REASON_HISTOGRAM=" + json.dumps(sorted(histogram.items(), key=lambda pair: (-pair[1], pair[0])), ensure_ascii=False))
    print("REJECTED_MARKET_SAMPLE=" + json.dumps(normalized[:20], ensure_ascii=False))
PY
fi

echo 'R7A4C_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
