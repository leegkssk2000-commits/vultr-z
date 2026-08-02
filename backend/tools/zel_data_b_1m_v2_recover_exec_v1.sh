#!/usr/bin/env bash
set -euo pipefail

ACTIONS_JSON=${1:?actions json required}
DIAG_OUT=${2:?diagnostic output required}
RECOVERY_OUT=${3:?recovery output required}

ENGINE_ROOT=/opt/zel/research-runtime/data-b-v2
OUTPUT_ROOT=/var/lib/zel-research/data-b-1m-v2
LOG_ROOT=/var/log/zel-research
UNIT=zel-data-b-1m-v2.service
LOCK=/var/lock/zel-data-b-1m-single-owner-v1.lock

legacy_started_at=$(python3 - "$ACTIONS_JSON" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1]))
rows=[r for r in rows if r.get('name')=='ZEL Data B 1m Single Owner Repair V1']
rows.sort(key=lambda r:r.get('startedAt') or r.get('createdAt') or '',reverse=True)
print((rows[0].get('startedAt') or rows[0].get('createdAt') or '2026-08-01T18:00:00Z') if rows else '2026-08-01T18:00:00Z')
PY
)

legacy_count=$(pgrep -af '[z]el_historical_oos_exact25_replay_v1.py.*--interval 1m' | wc -l || true)
v2_count=$(pgrep -af '[z]el_historical_oos_exact25_replay_v2.py.*--interval 1m' | wc -l || true)
terminal_count=0
for name in report.json summary.json scoreboard.csv trades.jsonl.gz; do
  [ -s "/tmp/zel_historical_oos_exact25_replay_v1_1m/$name" ] && terminal_count=$((terminal_count+1))
done
oom_count=$(journalctl -k --since "$legacy_started_at" --no-pager 2>/dev/null | grep -Eic 'out of memory|oom-kill|killed process' || true)
boot_epoch=$(awk '/^btime /{print $2}' /proc/stat)
start_epoch=$(python3 - "$legacy_started_at" <<'PY'
from datetime import datetime
import sys
print(int(datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).timestamp()))
PY
)
host_reboot=false
if [ "$boot_epoch" -gt "$start_epoch" ]; then host_reboot=true; fi
free_kb=$(df -Pk /var/lib | awk 'NR==2{print $4}')
mem_available_kb=$(awk '/MemAvailable:/{print $2}' /proc/meminfo)

LEGACY_COUNT="$legacy_count" V2_COUNT="$v2_count" TERMINAL_COUNT="$terminal_count" OOM_COUNT="$oom_count" HOST_REBOOT="$host_reboot" FREE_KB="$free_kb" MEM_AVAILABLE_KB="$mem_available_kb" LEGACY_STARTED_AT="$legacy_started_at" python3 - "$DIAG_OUT" <<'PY'
import json,os,sys
from datetime import datetime,timezone
out={
 'schema_version':'zel.data_b.1m.remote_diagnostic.v1',
 'generated_at':datetime.now(timezone.utc).isoformat(),
 'legacy_started_at':os.environ['LEGACY_STARTED_AT'],
 'legacy_process_count':int(os.environ['LEGACY_COUNT']),
 'v2_process_count':int(os.environ['V2_COUNT']),
 'terminal_artifact_count':int(os.environ['TERMINAL_COUNT']),
 'kernel_oom_detected':int(os.environ['OOM_COUNT'])>0,
 'kernel_oom_line_count':int(os.environ['OOM_COUNT']),
 'host_reboot_detected':os.environ['HOST_REBOOT']=='true',
 'disk_free_kb':int(os.environ['FREE_KB']),
 'mem_available_kb':int(os.environ['MEM_AVAILABLE_KB']),
 'read_only_diagnostic':True,
 'execution_authority':'NONE',
 'order_authority':'BLOCKED',
 'action':'hold',
}
open(sys.argv[1],'w').write(json.dumps(out,indent=2,sort_keys=True)+'\n')
PY

if [ "$legacy_count" -ne 0 ]; then
  echo 'LEGACY_1M_PROCESS_STILL_PRESENT' >&2
  exit 75
fi

install -d -m 0755 "$ENGINE_ROOT" "$LOG_ROOT"
install -d -m 0750 "$OUTPUT_ROOT"
install -m 0644 /tmp/zel_historical_oos_exact25_replay_v1.py "$ENGINE_ROOT/zel_historical_oos_exact25_replay_v1.py"
install -m 0644 /tmp/zel_historical_oos_exact25_replay_v2.py "$ENGINE_ROOT/zel_historical_oos_exact25_replay_v2.py"

cat > "$ENGINE_ROOT/run_1m_v2.sh" <<'RUNNER'
#!/usr/bin/env bash
set -euo pipefail
exec 9>/var/lock/zel-data-b-1m-single-owner-v1.lock
flock -n 9 || exit 75
OUTPUT_ROOT=/var/lib/zel-research/data-b-1m-v2
if [ -s "$OUTPUT_ROOT/terminal_receipt.json" ]; then
  if python3 - "$OUTPUT_ROOT/terminal_receipt.json" <<'PY'
import json,sys
raise SystemExit(0 if json.load(open(sys.argv[1])).get('state')=='PASS' else 1)
PY
  then
    exit 0
  fi
fi
exec /home/z/z/.venv/bin/python \
  /opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v2.py \
  --engine-v1 /opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py \
  --source-root /opt/zel/forward-expansion-v1/source \
  --data-root /opt/zel/historical-oos-v1 \
  --interval 1m \
  --output-dir "$OUTPUT_ROOT" \
  --workers 4
RUNNER
chmod 0755 "$ENGINE_ROOT/run_1m_v2.sh"

cat > "/etc/systemd/system/$UNIT" <<'UNITFILE'
[Unit]
Description=ZEL Data B Exact25 1m Replay V2 (research only)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/zel/research-runtime/data-b-v2/run_1m_v2.sh
WorkingDirectory=/opt/zel
Nice=10
CPUWeight=30
IOWeight=30
Restart=on-abnormal
RestartSec=30
TimeoutStartSec=infinity
TimeoutStopSec=60
KillMode=control-group
StandardOutput=append:/var/log/zel-research/data-b-1m-v2.log
StandardError=append:/var/log/zel-research/data-b-1m-v2.log

[Install]
WantedBy=multi-user.target
UNITFILE

systemctl daemon-reload
terminal_complete=false
if [ -s "$OUTPUT_ROOT/terminal_receipt.json" ]; then
  terminal_complete=$(python3 - "$OUTPUT_ROOT/terminal_receipt.json" <<'PY'
import json,sys
print('true' if json.load(open(sys.argv[1])).get('state')=='PASS' else 'false')
PY
)
fi
if [ "$terminal_complete" != true ]; then
  systemctl enable "$UNIT" >/dev/null
  if ! systemctl is-active --quiet "$UNIT"; then
    systemctl start "$UNIT"
  fi
fi
sleep 10
service_active=false
systemctl is-active --quiet "$UNIT" && service_active=true || true
service_enabled=false
systemctl is-enabled --quiet "$UNIT" && service_enabled=true || true
main_pid=$(systemctl show -p MainPID --value "$UNIT" 2>/dev/null || echo 0)
checkpoint_count=$(find "$OUTPUT_ROOT/checkpoints" -maxdepth 1 -type f -name '*.json.gz' 2>/dev/null | wc -l || true)
progress_exists=false
[ -s "$OUTPUT_ROOT/progress.json" ] && progress_exists=true
log_tail_sha256=$(tail -n 80 "$LOG_ROOT/data-b-1m-v2.log" 2>/dev/null | sha256sum | awk '{print $1}')

SERVICE_ACTIVE="$service_active" SERVICE_ENABLED="$service_enabled" MAIN_PID="$main_pid" CHECKPOINT_COUNT="$checkpoint_count" PROGRESS_EXISTS="$progress_exists" TERMINAL_COMPLETE="$terminal_complete" LOG_TAIL_SHA256="$log_tail_sha256" python3 - "$RECOVERY_OUT" <<'PY'
import json,os,sys
from datetime import datetime,timezone
out={
 'schema_version':'zel.data_b.1m.v2_recovery.status.v1',
 'generated_at':datetime.now(timezone.utc).isoformat(),
 'v2_service_active':os.environ['SERVICE_ACTIVE']=='true',
 'v2_service_enabled':os.environ['SERVICE_ENABLED']=='true',
 'v2_main_pid':int(os.environ['MAIN_PID'] or 0),
 'checkpoint_count':int(os.environ['CHECKPOINT_COUNT']),
 'progress_exists':os.environ['PROGRESS_EXISTS']=='true',
 'terminal_complete':os.environ['TERMINAL_COMPLETE']=='true',
 'output_root_sha256':__import__('hashlib').sha256(b'/var/lib/zel-research/data-b-1m-v2').hexdigest(),
 'log_tail_sha256':os.environ['LOG_TAIL_SHA256'],
 'detached_from_github_actions':True,
 'persistent_systemd_owner':True,
 'resume_enabled':True,
 'execution_authority':'NONE',
 'order_authority':'BLOCKED',
 'action':'hold',
}
open(sys.argv[1],'w').write(json.dumps(out,indent=2,sort_keys=True)+'\n')
PY

if [ "$service_active" != true ] && [ "$terminal_complete" != true ]; then
  journalctl -u "$UNIT" -n 80 --no-pager >&2 || true
  exit 1
fi
