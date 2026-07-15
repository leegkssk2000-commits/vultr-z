#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
OBSERVER_UNIT=q4r3-exact25-skill-trigger-lineage-observer
REPAIR_UNIT=q4r3-exact25-lineage-cadence-repair-guard
INTERVAL_SEC=10

LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
EVENTS="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/skill_events.jsonl"
PRE100_STATUS="$ROOT/runtime/exact25_edge_v1/pre100_integrity_audit/status_latest.json"
OBSERVER_STATUS="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/status_latest.json"
OUT="$ROOT/runtime/exact25_edge_v1/lineage_cadence_repair"
ACTIVATION="$OUT/activation_v1.json"
STATUS="$OUT/status_latest.json"
VIOLATIONS="$OUT/violations_latest.json"
JOB_STATUS="$ROOT/runtime/q4r3_exact25_lineage_cadence_repair_job_latest.json"
ACTIVE_SCRIPT="$ROOT/tools/q4r3_exact25_observers/q4r3_exact25_lineage_cadence_repair_guard.py"
SOURCE_SCRIPT="$WT/tools/q4r3_exact25_lineage_cadence_repair_guard.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_lineage_cadence_repair_guard.py"
OBSERVER_TIMER="/etc/systemd/system/$OBSERVER_UNIT.timer"
REPAIR_SERVICE="/etc/systemd/system/$REPAIR_UNIT.service"
REPAIR_TIMER="/etc/systemd/system/$REPAIR_UNIT.timer"
BACKUP="$ROOT/runtime/q4r3_exact25_lineage_cadence_repair_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)"
LEDGER_PREFIX="$(mktemp /tmp/q4r3_lineage_repair_ledger_prefix.XXXXXX)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
INSTALLED=false

cleanup() { rm -f "$LEDGER_PREFIX"; }
trap cleanup EXIT

write_job_status() {
  local state="$1" reason="$2"
  mkdir -p "$(dirname "$JOB_STATUS")"
  "$PY" - "$JOB_STATUS" "$state" "$reason" "$STARTED_AT" "$STATUS" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
path=Path(sys.argv[1])
payload={
  "job":"q4r3_exact25_lineage_cadence_repair",
  "state":sys.argv[2],
  "reason":sys.argv[3],
  "started_at":sys.argv[4],
  "updated_at":datetime.now(timezone.utc).isoformat(),
  "repair_status_path":sys.argv[5],
  "root_cause":"MISSED_OPEN_WINDOW_NO_OBSERVER_TICK",
  "observer_interval_sec":10,
  "historical_backfill_performed":False,
  "producer_modified":False,
  "writer_modified":False,
  "formal_ledger_modified":False,
  "strategy_modified":False,
  "trade_method_modified":False,
  "skill_registry_modified":False,
  "paper_enabled":False,
  "live_enabled":False,
  "order_enabled":False,
  "order_authority":"blocked",
  "execution_authority":"none",
  "action":"hold",
}
tmp=path.with_suffix(path.suffix+".tmp")
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
os.replace(tmp,path)
PY
}

rollback() {
  set +e
  systemctl stop "$REPAIR_UNIT.timer" "$REPAIR_UNIT.service" 2>/dev/null
  if [[ -f "$BACKUP/$OBSERVER_UNIT.timer" ]]; then
    cp -f "$BACKUP/$OBSERVER_UNIT.timer" "$OBSERVER_TIMER"
  fi
  if [[ -f "$BACKUP/$REPAIR_UNIT.service" ]]; then cp -f "$BACKUP/$REPAIR_UNIT.service" "$REPAIR_SERVICE"; else rm -f "$REPAIR_SERVICE"; fi
  if [[ -f "$BACKUP/$REPAIR_UNIT.timer" ]]; then cp -f "$BACKUP/$REPAIR_UNIT.timer" "$REPAIR_TIMER"; else rm -f "$REPAIR_TIMER"; fi
  if [[ -f "$BACKUP/active_guard.py" ]]; then cp -f "$BACKUP/active_guard.py" "$ACTIVE_SCRIPT"; else rm -f "$ACTIVE_SCRIPT"; fi
  if [[ -f "$BACKUP/$OBSERVER_UNIT.timer" ]]; then
    systemctl daemon-reload
    systemctl restart "$OBSERVER_UNIT.timer"
  fi
  set -e
}

on_error() {
  local line="$1" command="$2" code="$3"
  if [[ "$INSTALLED" == true ]]; then rollback; fi
  write_job_status FAILED "line=${line} exit=${code} command=${command} rollback=${INSTALLED}"
  exit "$code"
}
trap 'on_error "$LINENO" "$BASH_COMMAND" "$?"' ERR

[[ "$(id -u)" -eq 0 ]] || { echo RUN_AS_ROOT; exit 1; }
for required in "$SOURCE_SCRIPT" "$TEST_FILE" "$LEDGER" "$EVENTS" "$PRE100_STATUS" "$OBSERVER_STATUS" "$OBSERVER_TIMER"; do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
systemctl is-active --quiet "$OBSERVER_UNIT.timer"
PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
[[ "$WRITER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]

"$PY" - "$PRE100_STATUS" "$OBSERVER_STATUS" <<'PY'
import json,sys
pre=json.load(open(sys.argv[1],encoding="utf-8"))
obs=json.load(open(sys.argv[2],encoding="utf-8"))
assert pre.get("state")=="HOLD", pre
assert int(pre.get("uncovered_close_count") or 0)>0, pre
assert pre.get("integrity_gate_locked") is True, pre
assert obs.get("observer_only") is True, obs
assert obs.get("paper_enabled") is False, obs
assert obs.get("live_enabled") is False, obs
assert obs.get("order_enabled") is False, obs
assert obs.get("order_authority")=="blocked", obs
assert obs.get("execution_authority")=="none", obs
print("ROOT_CAUSE_PREFLIGHT=PASS")
PY

PYTHONPATH="$WT" "$PY" -m py_compile "$SOURCE_SCRIPT"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST_FILE"
bash -n "$0"

mkdir -p "$BACKUP" "$OUT" "$(dirname "$ACTIVE_SCRIPT")"
cp -f "$OBSERVER_TIMER" "$BACKUP/$OBSERVER_UNIT.timer"
[[ -f "$REPAIR_SERVICE" ]] && cp -f "$REPAIR_SERVICE" "$BACKUP/$REPAIR_UNIT.service" || true
[[ -f "$REPAIR_TIMER" ]] && cp -f "$REPAIR_TIMER" "$BACKUP/$REPAIR_UNIT.timer" || true
[[ -f "$ACTIVE_SCRIPT" ]] && cp -f "$ACTIVE_SCRIPT" "$BACKUP/active_guard.py" || true
cp --reflink=auto "$LEDGER" "$LEDGER_PREFIX"
LEDGER_SIZE_BEFORE="$(stat -c %s "$LEDGER_PREFIX")"

install -m 0555 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"

if [[ ! -f "$ACTIVATION" ]]; then
  "$PY" - "$LEDGER" "$EVENTS" "$PRE100_STATUS" "$ACTIVATION" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
ledger,events,pre,out=map(Path,sys.argv[1:])
def rows(path):
    return sum(1 for line in path.read_text(encoding="utf-8",errors="replace").splitlines() if line.strip())
status=json.load(open(pre,encoding="utf-8"))
payload={
  "schema":"q4r3_exact25_lineage_cadence_repair_activation_v1",
  "activated_at":datetime.now(timezone.utc).isoformat(),
  "baseline_formal_ledger_rows":rows(ledger),
  "baseline_skill_event_rows":rows(events),
  "known_prior_gap_count":int(status.get("uncovered_close_count") or 0),
  "known_prior_gap_position_ids":list(status.get("uncovered_position_ids") or [])[:100],
  "root_cause":"MISSED_OPEN_WINDOW_NO_OBSERVER_TICK",
  "observer_interval_sec":10,
  "historical_backfill_allowed":False,
  "known_prior_gaps_used_for_skill_performance":False,
  "action":"hold",
}
tmp=out.with_suffix(out.suffix+".tmp")
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
os.replace(tmp,out)
PY
fi

cat > "$OBSERVER_TIMER" <<EOF
[Unit]
Description=Q4R3 Exact25 Skill Trigger Lineage Observer Timer — Cadence Repair

[Timer]
OnBootSec=10s
OnUnitInactiveSec=${INTERVAL_SEC}s
AccuracySec=1s
Persistent=true
Unit=$OBSERVER_UNIT.service

[Install]
WantedBy=timers.target
EOF

cat > "$REPAIR_SERVICE" <<EOF
[Unit]
Description=Q4R3 Exact25 Lineage Cadence Repair Forward-Only Guard
After=$OBSERVER_UNIT.service
Requires=$OBSERVER_UNIT.timer

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PY $ACTIVE_SCRIPT --activation $ACTIVATION --formal-ledger $LEDGER --skill-events $EVENTS --status $STATUS --violations $VIOLATIONS
User=root
Group=root
Nice=15
IOSchedulingClass=idle
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$ROOT
ReadWritePaths=$OUT
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
RestrictSUIDSGID=true
RestrictRealtime=true
EOF

cat > "$REPAIR_TIMER" <<EOF
[Unit]
Description=Q4R3 Exact25 Lineage Cadence Repair Guard Timer

[Timer]
OnBootSec=30s
OnUnitInactiveSec=60s
AccuracySec=5s
Persistent=true
Unit=$REPAIR_UNIT.service

[Install]
WantedBy=timers.target
EOF

INSTALLED=true
systemctl daemon-reload
systemctl restart "$OBSERVER_UNIT.timer"
systemctl enable --now "$REPAIR_UNIT.timer"
systemctl start "$OBSERVER_UNIT.service" || true
systemctl start "$REPAIR_UNIT.service" || {
  code="$?"
  [[ "$code" -eq 2 && -f "$STATUS" ]] || exit "$code"
}

systemctl is-active --quiet "$OBSERVER_UNIT.timer"
systemctl is-active --quiet "$REPAIR_UNIT.timer"
PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
LEDGER_SIZE_AFTER="$(stat -c %s "$LEDGER")"
[[ "$LEDGER_SIZE_AFTER" -ge "$LEDGER_SIZE_BEFORE" ]]
cmp -n "$LEDGER_SIZE_BEFORE" "$LEDGER_PREFIX" "$LEDGER"

"$PY" - "$STATUS" "$ACTIVATION" <<'PY'
import json,sys
status=json.load(open(sys.argv[1],encoding="utf-8"))
activation=json.load(open(sys.argv[2],encoding="utf-8"))
assert status.get("state")=="PASS", status
assert status.get("root_cause")=="MISSED_OPEN_WINDOW_NO_OBSERVER_TICK", status
assert status.get("post_repair_uncovered_count")==0, status
assert status.get("historical_backfill_performed") is False, status
assert activation.get("observer_interval_sec")==10, activation
print("LINEAGE_CADENCE_REPAIR_INITIAL_GATE=PASS")
PY

write_job_status PASS "LINEAGE_CADENCE_REPAIR_INSTALLED_FORWARD_CANARY_ARMED"
echo Q4R3_EXACT25_LINEAGE_CADENCE_REPAIR_INSTALLED
echo "ACTIVATION=$ACTIVATION"
echo "STATUS=$STATUS"
echo "VIOLATIONS=$VIOLATIONS"
echo "PRODUCER_PID=$PRODUCER_PID_AFTER"
echo "WRITER_PID=$WRITER_PID_AFTER"
