#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || PY=python3

MODULE="$WT/tools/q4r3_team_advisor_r03_team_assignment_recovery.py"
TEST="$WT/tests/test_q4r3_team_advisor_r03_team_assignment_recovery.py"
RANKING=/usr/local/bin/zel_alimi_teambot_ranking_p6_4.py
LANE=/usr/local/bin/zel_legendary_team_lane_w179.py
RANKING_SHA=b71bf0c88b456116ba13678c6eda6a28e9acbfefc9cece9339410fa3c7518fa2
LANE_SHA=7ade37102f4731240d7fd8033e229c58a25450b41ffeb1d96c86bf097fb1e4a7
OUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r03_team_assignment_recovery"
STATUS="$OUT/status_latest.json"
REPORT="$OUT/team_assignment_recovery_latest.md"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
LEDGER_PREFIX="$(mktemp /tmp/q4r3_r03_ledger_prefix.XXXXXX)"

cleanup() { rm -f "$LEDGER_PREFIX"; }
trap cleanup EXIT

for required in "$MODULE" "$TEST" "$RANKING" "$LANE" "$LEDGER"; do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

PRODUCER_PID_BEFORE="$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value)"
ZICO_PID_BEFORE="$(systemctl show zico-ceo-canonical-adapter.service -p MainPID --value)"
for pid in "$PRODUCER_PID_BEFORE" "$WRITER_PID_BEFORE" "$ZICO_PID_BEFORE"; do
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || { echo "INVALID_RUNTIME_PID=$pid"; exit 1; }
done

cp --reflink=auto "$LEDGER" "$LEDGER_PREFIX"
LEDGER_SIZE_BEFORE="$(stat -c %s "$LEDGER_PREFIX")"

"$PY" -m py_compile "$MODULE"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"
mkdir -p "$OUT"

"$PY" "$MODULE" \
  --ranking-source "$RANKING" \
  --ranking-sha256 "$RANKING_SHA" \
  --lane-source "$LANE" \
  --lane-sha256 "$LANE_SHA" \
  --output-json "$STATUS" \
  --output-md "$REPORT"

"$PY" - "$STATUS" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
assert p.get("schema")=="q4r3_team_advisor_r03_team_assignment_recovery_v1", p
assert p.get("source_sha_parity_count")==2, p
assert not p.get("blockers"), p
assert len(p.get("teams",{}))==4, p
assert p.get("authority",{}).get("runtime_mutation_performed") is False, p
assert p.get("authority",{}).get("systemd_mutation_performed") is False, p
assert p.get("authority",{}).get("order_authority")=="blocked", p
assert p.get("authority",{}).get("execution_authority")=="none", p
for source in p.get("sources",[]):
    assert source.get("raw_source_included") is False, source
print("R03_OUTPUT_GATE=PASS")
PY

PRODUCER_PID_AFTER="$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value)"
ZICO_PID_AFTER="$(systemctl show zico-ceo-canonical-adapter.service -p MainPID --value)"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
[[ "$ZICO_PID_AFTER" == "$ZICO_PID_BEFORE" ]] || { echo ZICO_PID_CHANGED; exit 1; }

LEDGER_SIZE_AFTER="$(stat -c %s "$LEDGER")"
[[ "$LEDGER_SIZE_AFTER" -ge "$LEDGER_SIZE_BEFORE" ]]
cmp -n "$LEDGER_SIZE_BEFORE" "$LEDGER_PREFIX" "$LEDGER"

echo Q4R3_TEAM_ADVISOR_R03_TEAM_ASSIGNMENT_RECOVERY_COMPLETE
echo "STATUS=$STATUS"
echo "REPORT=$REPORT"
echo "ZICO_PID=$ZICO_PID_AFTER"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
