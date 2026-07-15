#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

SCRIPT="${Q4R3_DIAG_SCRIPT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/q4r3_exact25_lineage_gap_root_cause.py}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_JSON="/tmp/ZEL_EXACT25_LINEAGE_ROOT_CAUSE_${TS}.json"
OUT_TXT="/tmp/ZEL_EXACT25_LINEAGE_ROOT_CAUSE_${TS}.txt"
JOURNAL="/tmp/ZEL_EXACT25_SKILL_OBSERVER_JOURNAL_${TS}.txt"
LEDGER_SNAPSHOT="/tmp/ZEL_EXACT25_FORMAL_LEDGER_PREFIX_${TS}.jsonl"

FORMAL="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
ACTIVATION="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/activation.json"
EVENTS="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/skill_events.jsonl"
PRODUCER_LEDGER="$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/ledger.jsonl"
CHECKPOINT="$ROOT/runtime/exact25_edge_v1/checkpoint_100c_observer/status_latest.json"
INTEGRITY="$ROOT/runtime/exact25_edge_v1/pre100_integrity_audit/status_latest.json"

for f in "$SCRIPT" "$FORMAL" "$ACTIVATION" "$EVENTS" "$PRODUCER_LEDGER" "$CHECKPOINT" "$INTEGRITY"; do
  [[ -f "$f" ]] || { echo "REQUIRED_INPUT_MISSING=$f"; exit 1; }
done

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
OBSERVER_UNIT=q4r3-exact25-skill-trigger-lineage-observer.service

PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
cp --reflink=auto "$FORMAL" "$LEDGER_SNAPSHOT"
PREFIX_SIZE="$(stat -c %s "$LEDGER_SNAPSHOT")"

ACTIVATED_AT="$("$PY" - "$ACTIVATION" <<'PY'
import json,sys
print(json.load(open(sys.argv[1],encoding="utf-8"))["activated_at"])
PY
)"

journalctl -u "$OBSERVER_UNIT" --since "$ACTIVATED_AT" --no-pager -o short-iso > "$JOURNAL" 2>&1 || true

"$PY" "$SCRIPT" \
  --activation "$ACTIVATION" \
  --formal-ledger "$FORMAL" \
  --skill-events "$EVENTS" \
  --producer-ledger "$PRODUCER_LEDGER" \
  --checkpoint "$CHECKPOINT" \
  --integrity "$INTEGRITY" \
  --observer-journal "$JOURNAL" \
  --runtime-root "$ROOT/runtime" \
  --json-out "$OUT_JSON" \
  --report-out "$OUT_TXT"

PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_BEFORE" == "$PRODUCER_PID_AFTER" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_BEFORE" == "$WRITER_PID_AFTER" ]] || { echo WRITER_PID_CHANGED; exit 1; }
[[ "$(stat -c %s "$FORMAL")" -ge "$PREFIX_SIZE" ]]
cmp -n "$PREFIX_SIZE" "$LEDGER_SNAPSHOT" "$FORMAL"

echo "READ_ONLY_ROOT_CAUSE_AUDIT_DONE"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
echo "JSON=$OUT_JSON"
echo "REPORT=$OUT_TXT"
echo "JOURNAL=$JOURNAL"
