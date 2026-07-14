#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
PAIR_TIMER=q4r3-exact25-future-pair-join-observer.timer
PROJECTION_TIMER=q4r3-exact25-six-profile-projection-observer.timer
UNIT=q4r3-exact25-risk-scenario-grid-observer

PAIR_ROOT="$ROOT/runtime/exact25_edge_v1/future_pair_join_observer"
PAIR_STATUS="$PAIR_ROOT/status_latest.json"
PAIR_REPORT="$PAIR_ROOT/pairs_latest.json"
PROJECTION_STATUS="$ROOT/runtime/exact25_edge_v1/six_profile_projection_observer/status_latest.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
STORAGE_STATUS="$ROOT/runtime/q4r3_storage_regrowth_guard/status_latest.json"

INSTALL_DIR="$ROOT/tools/q4r3_exact25_observers"
ACTIVE_SCRIPT="$INSTALL_DIR/q4r3_exact25_risk_scenario_grid_observer.py"
OUTDIR="$ROOT/runtime/exact25_edge_v1/risk_scenario_grid_observer"
OUTPUT="$OUTDIR/grid_latest.json"
STATUS="$OUTDIR/status_latest.json"
VIOLATIONS="$OUTDIR/violations_latest.json"
JOB="$ROOT/runtime/q4r3_exact25_risk_scenario_grid_observer_job_latest.json"

SOURCE_SCRIPT="$WT/tools/q4r3_exact25_risk_scenario_grid_observer.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_risk_scenario_grid_observer.py"

for required in "$SOURCE_SCRIPT" "$TEST_FILE" "$PAIR_STATUS" "$PAIR_REPORT" "$PROJECTION_STATUS" "$LEDGER" "$STORAGE_STATUS"; do
  [[ -s "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
systemctl is-active --quiet "$PAIR_TIMER"
systemctl is-active --quiet "$PROJECTION_TIMER"

"$PY" - "$PAIR_STATUS" "$PROJECTION_STATUS" "$STORAGE_STATUS" <<'PY'
import json, sys
pair = json.load(open(sys.argv[1], encoding="utf-8"))
projection = json.load(open(sys.argv[2], encoding="utf-8"))
storage = json.load(open(sys.argv[3], encoding="utf-8"))
assert pair.get("state") == "PASS", pair
assert pair.get("observer_only") is True, pair
assert pair.get("formal_ledger_modified") is False, pair
assert projection.get("state") == "PASS", projection
assert projection.get("profile_count") == 6, projection
assert storage.get("state") == "PASS", storage
assert storage.get("verdict") == "STORAGE_REGROWTH_GUARD_HEALTHY", storage
print("PREFLIGHT_CONTRACT=PASS")
PY

PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_HASH_BEFORE="$(sha256sum "$LEDGER" | awk '{print $1}')"
PAIR_HASH_BEFORE="$(sha256sum "$PAIR_STATUS" "$PAIR_REPORT")"
PROJECTION_HASH_BEFORE="$(sha256sum "$PROJECTION_STATUS")"

"$PY" -m pytest -q "$TEST_FILE"
"$PY" -m py_compile "$SOURCE_SCRIPT"

mkdir -p "$INSTALL_DIR" "$OUTDIR"
install -m 0755 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"

cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Q4R3 Exact25 Read-Only Risk Scenario Grid Observer
After=$PAIR_TIMER $PROJECTION_TIMER

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PY $ACTIVE_SCRIPT --pair-status $PAIR_STATUS --pair-report $PAIR_REPORT --projection-status $PROJECTION_STATUS --output $OUTPUT --status $STATUS --violations $VIOLATIONS
Nice=15
IOSchedulingClass=idle
UMask=0022
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$ROOT
ReadWritePaths=$OUTDIR
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
RestrictSUIDSGID=true
RestrictRealtime=true
EOF

cat > "/etc/systemd/system/$UNIT.timer" <<EOF
[Unit]
Description=Q4R3 Exact25 Risk Scenario Grid Timer

[Timer]
OnBootSec=120s
OnUnitActiveSec=60s
AccuracySec=5s
Persistent=true
Unit=$UNIT.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now "$UNIT.timer"
systemctl start "$UNIT.service"

PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_HASH_AFTER="$(sha256sum "$LEDGER" | awk '{print $1}')"
PAIR_HASH_AFTER="$(sha256sum "$PAIR_STATUS" "$PAIR_REPORT")"
PROJECTION_HASH_AFTER="$(sha256sum "$PROJECTION_STATUS")"

test "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER"
test "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER"
test "$LEDGER_HASH_BEFORE" = "$LEDGER_HASH_AFTER"
test "$PAIR_HASH_BEFORE" = "$PAIR_HASH_AFTER"
test "$PROJECTION_HASH_BEFORE" = "$PROJECTION_HASH_AFTER"

"$PY" - "$STATUS" "$VIOLATIONS" "$JOB" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
status = json.load(open(sys.argv[1], encoding="utf-8"))
violations = json.load(open(sys.argv[2], encoding="utf-8"))
assert status.get("state") == "PASS", status
assert status.get("scenario_count") == 12, status
assert status.get("observer_only") is True, status
assert status.get("formal_ledger_modified") is False, status
assert violations.get("count") == 0, violations
payload = {
    "job": "q4r3_exact25_risk_scenario_grid_observer",
    "state": "PASS",
    "current_stage": "complete",
    "status": "PASS_Q4R3_EXACT25_RISK_SCENARIO_GRID_OBSERVER",
    "verdict": status.get("verdict"),
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "scenario_count": status.get("scenario_count"),
    "exact_pair_count": status.get("exact_pair_count"),
    "missing_risk_fields": status.get("missing_risk_fields"),
    "observer_only": True,
    "strategy_modified": False,
    "trade_method_modified": False,
    "skill_registry_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
    "action": "hold",
}
path = Path(sys.argv[3])
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
os.replace(tmp, path)
PY

echo Q4R3_EXACT25_RISK_SCENARIO_GRID_OBSERVER_INSTALLED
echo "STATUS=$STATUS"
echo "GRID=$OUTPUT"
echo "VIOLATIONS=$VIOLATIONS"
echo "JOB=$JOB"
