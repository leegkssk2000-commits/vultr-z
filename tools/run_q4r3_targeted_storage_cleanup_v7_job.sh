#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
OUTDIR=$ROOT/runtime/q4r3_targeted_storage_cleanup_v7
STATUS=$ROOT/runtime/q4r3_targeted_storage_cleanup_v7_job_latest.json
REPORT=$OUTDIR/report_latest.json
DU_MAP=$OUTDIR/du_map_latest.txt
OPEN_DELETED=$OUTDIR/open_deleted_latest.txt
LOG=$ROOT/runtime/q4r3_targeted_storage_cleanup_v7_job.log

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
CAPTURE_TIMER=q4r3-exact25-preentry-method-context-capture.timer
FORMAL_LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
ACTIVE_METHOD_ROOT=$ROOT/backend/trade_methods
ACTIVE_PRODUCER=$ROOT/tools/q4r3_exact25_dedicated_shadow_producer.py

JOURNAL_MAX_SIZE=${Q4R3_JOURNAL_MAX_SIZE:-1G}

mkdir -p "$OUTDIR"
exec > >(tee -a "$LOG") 2>&1

json_status() {
  local state=$1 stage=$2 reason=$3
  "$PYTHON_BIN" - "$STATUS" "$state" "$stage" "$reason" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({
  "job":"q4r3_targeted_storage_cleanup_v7",
  "state":sys.argv[2],
  "current_stage":sys.argv[3],
  "reason":sys.argv[4],
  "updated_at":datetime.now(timezone.utc).isoformat(),
  "action":"hold",
  "mode":"targeted_regenerable_cleanup_only",
  "runtime_root_deleted":False,
  "formal_ledger_deleted":False,
  "unique_backup_deleted":False,
  "paper_enabled":False,
  "live_enabled":False,
  "order_enabled":False,
  "order_authority":"blocked",
  "execution_authority":"none"
},ensure_ascii=False,indent=2),encoding="utf-8")
PY
}

fail() {
  local stage=$1 reason=$2
  trap - ERR
  json_status FAILED "$stage" "$reason"
  echo "TARGETED_STORAGE_CLEANUP_V7_FAILED:$stage:$reason"
  exit 1
}
trap 'fail unexpected "line=$LINENO command=$BASH_COMMAND"' ERR

[ "$(id -u)" -eq 0 ] || fail preflight RUN_AS_ROOT
for required in "$PYTHON_BIN" "$FORMAL_LEDGER" "$ACTIVE_METHOD_ROOT" "$ACTIVE_PRODUCER"; do
  [ -e "$required" ] || fail preflight "REQUIRED_INPUT_MISSING:$required"
done
systemctl is-active --quiet "$PRODUCER_UNIT" || fail preflight PRODUCER_NOT_ACTIVE
systemctl is-active --quiet "$WRITER_UNIT" || fail preflight WRITER_NOT_ACTIVE
systemctl is-active --quiet "$CAPTURE_TIMER" || fail preflight PREENTRY_CAPTURE_TIMER_NOT_ACTIVE

json_status RUNNING preflight capture_immutability_baseline
PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
FORMAL_ROWS_BEFORE=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
METHOD_HASH_BEFORE=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
PRODUCER_HASH_BEFORE=$(sha256sum "$ACTIVE_PRODUCER" | awk '{print $1}')
DISK_USED_BEFORE=$(df -B1 --output=used / | tail -1 | xargs)
DISK_AVAIL_BEFORE=$(df -B1 --output=avail / | tail -1 | xargs)
DISK_PCT_BEFORE=$(df -P / | awk 'NR==2{print $5}')

json_status RUNNING inventory fast_du_map
: > "$DU_MAP"
for target in "$ROOT" /var/log /tmp /root; do
  [ -e "$target" ] || continue
  echo "===== $target =====" >> "$DU_MAP"
  timeout 300 du -x -B1 --max-depth=2 "$target" 2>/dev/null | sort -nr | head -200 >> "$DU_MAP" || true
done

json_status RUNNING open_deleted_inventory read_only
: > "$OPEN_DELETED"
lsof +L1 2>/dev/null | sort -k7 -nr | head -200 > "$OPEN_DELETED" || true

json_status RUNNING failed_worktree_cleanup exact_known_paths_only
FAILED_WORKTREE_REMOVED_COUNT=0
FAILED_WORKTREE_REMOVED_BYTES=0
for stale in \
  "$ROOT/.worktrees/q4r3-deep-storage-hygiene-hotfix-v3" \
  "$ROOT/.worktrees/q4r3-deep-storage-hygiene-v4" \
  "$ROOT/.worktrees/q4r3-deep-storage-hygiene-v5" \
  "$ROOT/.worktrees/q4r3-deep-storage-hygiene-v6" \
  /tmp/q4r3-deep-storage-hygiene \
  /tmp/q4r3-deep-storage-hygiene-hotfix \
  /tmp/q4r3-deep-storage-hygiene-hotfix-v3
 do
  [ -e "$stale" ] || continue
  if pgrep -af -- "$stale" >/dev/null 2>&1; then
    echo "PRESERVE_RUNNING_PATH=$stale"
    continue
  fi
  size=$(du -sx -B1 "$stale" 2>/dev/null | awk '{print $1}' || echo 0)
  rm -rf --one-file-system -- "$stale"
  FAILED_WORKTREE_REMOVED_COUNT=$((FAILED_WORKTREE_REMOVED_COUNT + 1))
  FAILED_WORKTREE_REMOVED_BYTES=$((FAILED_WORKTREE_REMOVED_BYTES + size))
done

json_status RUNNING regenerable_cache_cleanup caches_only
CACHE_REMOVED_COUNT=0
CACHE_REMOVED_BYTES=0
while IFS= read -r -d '' cache; do
  [ -e "$cache" ] || continue
  size=$(du -sx -B1 "$cache" 2>/dev/null | awk '{print $1}' || echo 0)
  rm -rf --one-file-system -- "$cache"
  CACHE_REMOVED_COUNT=$((CACHE_REMOVED_COUNT + 1))
  CACHE_REMOVED_BYTES=$((CACHE_REMOVED_BYTES + size))
done < <(
  find "$ROOT" -xdev \
    \( -path "$ROOT/.git" -o -path "$ROOT/.venv" \) -prune -o \
    -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) \
    -print0 2>/dev/null
)

if [ -d /root/.cache/pip ]; then
  size=$(du -sx -B1 /root/.cache/pip 2>/dev/null | awk '{print $1}' || echo 0)
  rm -rf --one-file-system /root/.cache/pip
  CACHE_REMOVED_COUNT=$((CACHE_REMOVED_COUNT + 1))
  CACHE_REMOVED_BYTES=$((CACHE_REMOVED_BYTES + size))
fi

json_status RUNNING package_cache_cleanup apt_archives_only
APT_BYTES_BEFORE=$(du -sx -B1 /var/cache/apt/archives 2>/dev/null | awk '{print $1}' || echo 0)
apt-get clean
APT_BYTES_AFTER=$(du -sx -B1 /var/cache/apt/archives 2>/dev/null | awk '{print $1}' || echo 0)
APT_REMOVED_BYTES=$((APT_BYTES_BEFORE - APT_BYTES_AFTER))

json_status RUNNING journal_retention archived_journals_only
JOURNAL_BEFORE=$(du -sx -B1 /var/log/journal 2>/dev/null | awk '{print $1}' || echo 0)
journalctl --rotate >/dev/null 2>&1 || true
journalctl --vacuum-size="$JOURNAL_MAX_SIZE" >/dev/null 2>&1 || true
JOURNAL_AFTER=$(du -sx -B1 /var/log/journal 2>/dev/null | awk '{print $1}' || echo 0)
JOURNAL_REMOVED_BYTES=$((JOURNAL_BEFORE - JOURNAL_AFTER))

json_status RUNNING postcheck verify_immutability
PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_AFTER=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
FORMAL_ROWS_AFTER=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
METHOD_HASH_AFTER=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
PRODUCER_HASH_AFTER=$(sha256sum "$ACTIVE_PRODUCER" | awk '{print $1}')
DISK_USED_AFTER=$(df -B1 --output=used / | tail -1 | xargs)
DISK_AVAIL_AFTER=$(df -B1 --output=avail / | tail -1 | xargs)
DISK_PCT_AFTER=$(df -P / | awk 'NR==2{print $5}')

[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ] || fail postcheck PRODUCER_PID_CHANGED
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ] || fail postcheck WRITER_PID_CHANGED
[ "$METHOD_HASH_BEFORE" = "$METHOD_HASH_AFTER" ] || fail postcheck ACTIVE_TRADE_METHOD_CHANGED
[ "$PRODUCER_HASH_BEFORE" = "$PRODUCER_HASH_AFTER" ] || fail postcheck ACTIVE_PRODUCER_CHANGED
[ "$FORMAL_ROWS_AFTER" -ge "$FORMAL_ROWS_BEFORE" ] || fail postcheck FORMAL_LEDGER_ROWS_DECREASED

FORMAL_EXTERNAL_APPEND=false
if [ "$FORMAL_HASH_BEFORE" != "$FORMAL_HASH_AFTER" ]; then
  [ "$FORMAL_ROWS_AFTER" -gt "$FORMAL_ROWS_BEFORE" ] || fail postcheck FORMAL_LEDGER_CHANGED_WITHOUT_APPEND
  FORMAL_EXTERNAL_APPEND=true
fi

systemctl is-active --quiet "$PRODUCER_UNIT" || fail postcheck PRODUCER_NOT_ACTIVE
systemctl is-active --quiet "$WRITER_UNIT" || fail postcheck WRITER_NOT_ACTIVE
systemctl is-active --quiet "$CAPTURE_TIMER" || fail postcheck PREENTRY_CAPTURE_TIMER_NOT_ACTIVE

FREE_BYTES_DELTA=$((DISK_AVAIL_AFTER - DISK_AVAIL_BEFORE))
DECLARED_REMOVED_BYTES=$((FAILED_WORKTREE_REMOVED_BYTES + CACHE_REMOVED_BYTES + APT_REMOVED_BYTES + JOURNAL_REMOVED_BYTES))

"$PYTHON_BIN" - \
  "$REPORT" "$STATUS" \
  "$DISK_USED_BEFORE" "$DISK_AVAIL_BEFORE" "$DISK_PCT_BEFORE" \
  "$DISK_USED_AFTER" "$DISK_AVAIL_AFTER" "$DISK_PCT_AFTER" \
  "$FREE_BYTES_DELTA" "$DECLARED_REMOVED_BYTES" \
  "$FAILED_WORKTREE_REMOVED_COUNT" "$FAILED_WORKTREE_REMOVED_BYTES" \
  "$CACHE_REMOVED_COUNT" "$CACHE_REMOVED_BYTES" \
  "$APT_REMOVED_BYTES" "$JOURNAL_REMOVED_BYTES" \
  "$FORMAL_ROWS_BEFORE" "$FORMAL_ROWS_AFTER" "$FORMAL_EXTERNAL_APPEND" \
  "$DU_MAP" "$OPEN_DELETED" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
(
 report,status,used_b,avail_b,pct_b,used_a,avail_a,pct_a,free_delta,declared,
 wt_count,wt_bytes,cache_count,cache_bytes,apt_bytes,journal_bytes,
 rows_b,rows_a,external_append,du_map,open_deleted
)=sys.argv[1:]
payload={
 "job":"q4r3_targeted_storage_cleanup_v7",
 "state":"PASS",
 "current_stage":"complete",
 "status":"PASS_Q4R3_TARGETED_STORAGE_CLEANUP_V7",
 "verdict":"FAST_REGENERABLE_TARGETED_CLEANUP_COMPLETE",
 "updated_at":datetime.now(timezone.utc).isoformat(),
 "action":"hold",
 "disk_before":{"used_bytes":int(used_b),"avail_bytes":int(avail_b),"use_pct":pct_b},
 "disk_after":{"used_bytes":int(used_a),"avail_bytes":int(avail_a),"use_pct":pct_a},
 "free_bytes_delta":int(free_delta),
 "declared_removed_bytes":int(declared),
 "failed_worktree_removed_count":int(wt_count),
 "failed_worktree_removed_bytes":int(wt_bytes),
 "cache_removed_count":int(cache_count),
 "cache_removed_bytes":int(cache_bytes),
 "apt_removed_bytes":int(apt_bytes),
 "journal_removed_bytes":int(journal_bytes),
 "formal_ledger_rows_before":int(rows_b),
 "formal_ledger_rows_after":int(rows_a),
 "formal_ledger_external_append_detected":external_append.lower()=="true",
 "runtime_root_deleted":False,
 "formal_ledger_deleted":False,
 "unique_backup_deleted":False,
 "producer_pid_unchanged":True,
 "writer_pid_unchanged":True,
 "active_trade_method_hash_unchanged":True,
 "active_producer_hash_unchanged":True,
 "paper_enabled":False,
 "live_enabled":False,
 "order_enabled":False,
 "order_authority":"blocked",
 "execution_authority":"none",
 "du_map_path":du_map,
 "open_deleted_path":open_deleted,
 "next_action":"RUN_SKILL_ACTIVE_LINEAGE_AUDIT_IF_DISK_USE_IS_STABLE_OTHERWISE_REVIEW_DU_MAP_TOP_ROWS"
}
Path(report).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
Path(status).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
print("Q4R3_TARGETED_STORAGE_CLEANUP_V7_PASS")
PY

trap - ERR
echo Q4R3_TARGETED_STORAGE_CLEANUP_V7_INSTALL_PASS
