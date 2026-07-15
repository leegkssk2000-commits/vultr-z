#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-exact25-lineage-cadence-repair-v1}"
EVIDENCE_PATH="evidence/q4r3_exact25_lineage_cadence_repair_latest.json"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

STATUS="$ROOT/runtime/exact25_edge_v1/lineage_cadence_repair/status_latest.json"
ACTIVATION="$ROOT/runtime/exact25_edge_v1/lineage_cadence_repair/activation_v1.json"
JOB="$ROOT/runtime/q4r3_exact25_lineage_cadence_repair_job_latest.json"
PRE100="$ROOT/runtime/exact25_edge_v1/pre100_integrity_audit/status_latest.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
EVENTS="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/skill_events.jsonl"
OUT="$WT/$EVIDENCE_PATH"

for required in "$STATUS" "$ACTIVATION" "$JOB" "$PRE100" "$LEDGER" "$EVENTS"; do
  [[ -f "$required" ]] || { echo "REQUIRED_EVIDENCE_MISSING=$required"; exit 1; }
done

mkdir -p "$(dirname "$OUT")"

PRODUCER_PID="$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value 2>/dev/null || echo 0)"
WRITER_PID="$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value 2>/dev/null || echo 0)"
OBSERVER_TIMER_ACTIVE="$(systemctl is-active q4r3-exact25-skill-trigger-lineage-observer.timer 2>/dev/null || true)"
REPAIR_TIMER_ACTIVE="$(systemctl is-active q4r3-exact25-lineage-cadence-repair-guard.timer 2>/dev/null || true)"
OBSERVER_INTERVAL="$(systemctl show q4r3-exact25-skill-trigger-lineage-observer.timer -p NextElapseUSecRealtime --value 2>/dev/null || true)"

"$PY" - \
  "$STATUS" "$ACTIVATION" "$JOB" "$PRE100" "$LEDGER" "$EVENTS" "$OUT" \
  "$PRODUCER_PID" "$WRITER_PID" "$OBSERVER_TIMER_ACTIVE" "$REPAIR_TIMER_ACTIVE" "$OBSERVER_INTERVAL" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path

status_path,activation_path,job_path,pre100_path,ledger_path,events_path,out_path=map(Path,sys.argv[1:8])
producer_pid,writer_pid,observer_active,repair_active,next_elapse=sys.argv[8:13]

def load(path):
    return json.loads(path.read_text(encoding="utf-8",errors="replace"))

def lines(path):
    return sum(1 for line in path.read_text(encoding="utf-8",errors="replace").splitlines() if line.strip())

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

status=load(status_path)
activation=load(activation_path)
job=load(job_path)
pre100=load(pre100_path)

payload={
  "schema":"q4r3_exact25_lineage_cadence_repair_evidence_v1",
  "published_at":datetime.now(timezone.utc).isoformat(),
  "repair":{
    "state":status.get("state"),
    "verdict":status.get("verdict"),
    "root_cause":status.get("root_cause"),
    "observer_interval_sec":status.get("observer_interval_sec"),
    "baseline_formal_ledger_rows":status.get("baseline_formal_ledger_rows"),
    "current_formal_ledger_rows":status.get("current_formal_ledger_rows"),
    "baseline_skill_event_rows":status.get("baseline_skill_event_rows"),
    "current_skill_event_rows":status.get("current_skill_event_rows"),
    "post_repair_close_count":status.get("post_repair_close_count"),
    "post_repair_lineage_covered_count":status.get("post_repair_lineage_covered_count"),
    "post_repair_uncovered_count":status.get("post_repair_uncovered_count"),
    "post_repair_coverage_pct":status.get("post_repair_coverage_pct"),
    "canary_target_close_count":status.get("canary_target_close_count"),
    "remaining_to_canary":status.get("remaining_to_canary"),
    "known_prior_gap_count":status.get("known_prior_gap_count"),
    "known_prior_gaps_used_for_skill_performance":status.get("known_prior_gaps_used_for_skill_performance"),
    "historical_backfill_performed":status.get("historical_backfill_performed"),
    "violation_count":status.get("violation_count"),
    "violation_severity":status.get("violation_severity"),
    "action":status.get("action"),
  },
  "activation":{
    "activated_at":activation.get("activated_at"),
    "root_cause":activation.get("root_cause"),
    "observer_interval_sec":activation.get("observer_interval_sec"),
    "known_prior_gap_count":activation.get("known_prior_gap_count"),
    "historical_backfill_allowed":activation.get("historical_backfill_allowed"),
  },
  "job":{
    "state":job.get("state"),
    "reason":job.get("reason"),
    "started_at":job.get("started_at"),
    "updated_at":job.get("updated_at"),
  },
  "runtime":{
    "producer_pid":int(producer_pid or 0),
    "writer_pid":int(writer_pid or 0),
    "observer_timer_active":observer_active,
    "repair_timer_active":repair_active,
    "observer_timer_next_elapse":next_elapse,
  },
  "integrity":{
    "formal_ledger_rows":lines(ledger_path),
    "formal_ledger_sha256":sha(ledger_path),
    "skill_event_rows":lines(events_path),
    "skill_event_sha256":sha(events_path),
    "pre100_state":pre100.get("state"),
    "pre100_verdict":pre100.get("verdict"),
    "pre100_uncovered_close_count":pre100.get("uncovered_close_count"),
    "pre100_integrity_gate_locked":pre100.get("integrity_gate_locked"),
  },
  "authority":{
    "paper_enabled":False,
    "live_enabled":False,
    "order_enabled":False,
    "order_authority":"blocked",
    "execution_authority":"none",
  },
  "redaction":{
    "position_ids_included":False,
    "trade_rows_included":False,
    "credentials_included":False,
  },
}
out_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
PY

git -C "$WT" add "$EVIDENCE_PATH"
if git -C "$WT" diff --cached --quiet; then
  echo EVIDENCE_UNCHANGED
  exit 0
fi

git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" \
  commit -m "Record Exact25 lineage cadence repair runtime evidence"
git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"

echo "EVIDENCE_PUBLISHED=$EVIDENCE_PATH"
