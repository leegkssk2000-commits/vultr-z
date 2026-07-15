#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-exact25-lineage-postrepair-root-cause-v2}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

AUDIT="$WT/tools/q4r3_exact25_lineage_postrepair_root_cause_v2.py"
TEST="$WT/tests/test_q4r3_exact25_lineage_postrepair_root_cause_v2.py"
ACTIVATION="$ROOT/runtime/exact25_edge_v1/lineage_cadence_repair/activation_v1.json"
REPAIR_STATUS="$ROOT/runtime/exact25_edge_v1/lineage_cadence_repair/status_latest.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
EVENTS="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/skill_events.jsonl"
RUNTIME_ROOT="$ROOT/runtime"
OBSERVER_UNIT=q4r3-exact25-skill-trigger-lineage-observer.service
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
EVIDENCE_REL="evidence/q4r3_exact25_lineage_postrepair_root_cause_v2_latest.json"
EVIDENCE="$WT/$EVIDENCE_REL"
RAW_JOURNAL="$(mktemp /tmp/q4r3_postrepair_journal_raw.XXXXXX.jsonl)"
JOURNAL="$(mktemp /tmp/q4r3_postrepair_journal_normalized.XXXXXX.jsonl)"
PREFIX="$(mktemp /tmp/q4r3_postrepair_ledger_prefix.XXXXXX)"

cleanup() { rm -f "$RAW_JOURNAL" "$JOURNAL" "$PREFIX"; }
trap cleanup EXIT

for required in "$AUDIT" "$TEST" "$ACTIVATION" "$REPAIR_STATUS" "$LEDGER" "$EVENTS"; do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
[[ "$WRITER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
cp --reflink=auto "$LEDGER" "$PREFIX"
PREFIX_SIZE="$(stat -c %s "$PREFIX")"

"$PY" -m py_compile "$AUDIT"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"

# journalctl does not consistently accept RFC3339 strings containing T,
# fractional seconds and an explicit +00:00 offset. Convert the activation
# boundary to journalctl's documented calendar format in UTC and subtract one
# second so the boundary invocation cannot be lost to second-level rounding.
JOURNAL_SINCE="$($PY - "$ACTIVATION" <<'PY'
import json,sys
from datetime import datetime,timezone,timedelta
payload=json.load(open(sys.argv[1],encoding='utf-8'))
raw=str(payload['activated_at']).strip()
dt=datetime.fromisoformat(raw.replace('Z','+00:00'))
if dt.tzinfo is None:
    dt=dt.replace(tzinfo=timezone.utc)
dt=dt.astimezone(timezone.utc)-timedelta(seconds=1)
print(dt.strftime('%Y-%m-%d %H:%M:%S UTC'))
PY
)"
[[ "$JOURNAL_SINCE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}\ UTC$ ]]
echo "JOURNAL_SINCE=$JOURNAL_SINCE"

journalctl -u "$OBSERVER_UNIT" --since "$JOURNAL_SINCE" --no-pager -o json > "$RAW_JOURNAL"
[[ -s "$RAW_JOURNAL" ]] || { echo OBSERVER_JOURNAL_EMPTY_AFTER_ACTIVATION; exit 1; }

# journalctl emits __REALTIME_TIMESTAMP in microseconds. Normalize to Unix seconds
# before the audit so timestamp units are explicit and deterministic.
"$PY" - "$RAW_JOURNAL" "$JOURNAL" <<'PY'
import json,sys
src,dst=sys.argv[1:]
out=[]
for line in open(src,encoding='utf-8',errors='replace'):
    if not line.strip():
        continue
    row=json.loads(line)
    raw=row.get('__REALTIME_TIMESTAMP')
    try:
        row['__REALTIME_TIMESTAMP']=float(raw)/1_000_000.0
    except Exception:
        pass
    out.append({k:row.get(k) for k in ('_SYSTEMD_INVOCATION_ID','__REALTIME_TIMESTAMP','MESSAGE','PRIORITY','_SYSTEMD_UNIT')})
with open(dst,'w',encoding='utf-8') as f:
    for row in out:
        f.write(json.dumps(row,ensure_ascii=False)+'\n')
PY
[[ -s "$JOURNAL" ]] || { echo NORMALIZED_OBSERVER_JOURNAL_EMPTY; exit 1; }

mkdir -p "$(dirname "$EVIDENCE")"
"$PY" "$AUDIT" \
  --activation "$ACTIVATION" \
  --repair-status "$REPAIR_STATUS" \
  --formal-ledger "$LEDGER" \
  --skill-events "$EVENTS" \
  --observer-journal-jsonl "$JOURNAL" \
  --runtime-root "$RUNTIME_ROOT" \
  --output "$EVIDENCE"

PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
[[ "$(stat -c %s "$LEDGER")" -ge "$PREFIX_SIZE" ]]
cmp -n "$PREFIX_SIZE" "$PREFIX" "$LEDGER"

"$PY" - "$EVIDENCE" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding='utf-8'))
assert p.get('schema')=='q4r3_exact25_lineage_postrepair_root_cause_v2', p
assert p.get('automatic_patch_allowed') is False, p
assert p.get('historical_backfill_performed') is False, p
assert p.get('producer_modified') is False, p
assert p.get('writer_modified') is False, p
assert p.get('formal_ledger_modified') is False, p
assert p.get('paper_enabled') is False, p
assert p.get('live_enabled') is False, p
assert p.get('order_enabled') is False, p
assert p.get('order_authority')=='blocked', p
assert p.get('execution_authority')=='none', p
print('POSTREPAIR_ROOT_CAUSE_EVIDENCE_GATE=PASS')
PY

git -C "$WT" add "$EVIDENCE_REL"
if ! git -C "$WT" diff --cached --quiet; then
  git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" \
    commit -m "Record post-repair lineage root-cause evidence"
  git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"
else
  echo EVIDENCE_UNCHANGED
fi

echo Q4R3_EXACT25_POSTREPAIR_ROOT_CAUSE_AUDIT_AND_PUBLISH_PASS
echo "EVIDENCE=$EVIDENCE_REL"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
