#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
PROJECTION_TIMER=q4r3-exact25-six-profile-projection-observer.timer
PAIR_TIMER=q4r3-exact25-future-pair-join-observer.timer
RISK_TIMER=q4r3-exact25-risk-scenario-grid-observer.timer
UNIT=q4r3-exact25-method-scoreboard-observer

PROJECTION_ROOT="$ROOT/runtime/exact25_edge_v1/six_profile_projection_observer"
PROJECTION_STATUS="$PROJECTION_ROOT/status_latest.json"
PROJECTION="$PROJECTION_ROOT/projection_latest.json"
PAIR_STATUS="$ROOT/runtime/exact25_edge_v1/future_pair_join_observer/status_latest.json"
RISK_ROOT="$ROOT/runtime/exact25_edge_v1/risk_scenario_grid_observer"
RISK_STATUS="$RISK_ROOT/status_latest.json"
RISK_GRID="$RISK_ROOT/grid_latest.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
STORAGE_STATUS="$ROOT/runtime/q4r3_storage_regrowth_guard/status_latest.json"

INSTALL_DIR="$ROOT/tools/q4r3_exact25_observers"
ACTIVE_SCRIPT="$INSTALL_DIR/q4r3_exact25_method_scoreboard_observer.py"
OUTDIR="$ROOT/runtime/exact25_edge_v1/method_scoreboard_observer"
OUTPUT="$OUTDIR/scoreboard_latest.json"
STATUS="$OUTDIR/status_latest.json"
VIOLATIONS="$OUTDIR/violations_latest.json"
JOB="$ROOT/runtime/q4r3_exact25_method_scoreboard_observer_job_latest.json"

SOURCE_SCRIPT="$WT/tools/q4r3_exact25_method_scoreboard_observer.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_method_scoreboard_observer.py"

for required in "$SOURCE_SCRIPT" "$TEST_FILE" "$PROJECTION_STATUS" "$PROJECTION" "$PAIR_STATUS" "$RISK_STATUS" "$RISK_GRID" "$LEDGER" "$STORAGE_STATUS"; do
  [[ -s "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
systemctl is-active --quiet "$PROJECTION_TIMER"
systemctl is-active --quiet "$PAIR_TIMER"
systemctl is-active --quiet "$RISK_TIMER"

"$PY" - "$PROJECTION_STATUS" "$PAIR_STATUS" "$RISK_STATUS" "$STORAGE_STATUS" <<'PY'
import json, sys
projection = json.load(open(sys.argv[1], encoding="utf-8"))
pair = json.load(open(sys.argv[2], encoding="utf-8"))
risk = json.load(open(sys.argv[3], encoding="utf-8"))
storage = json.load(open(sys.argv[4], encoding="utf-8"))
assert projection.get("state") == "PASS", projection
assert projection.get("profile_count") == 6, projection
assert projection.get("observer_only") is True, projection
assert pair.get("state") == "PASS", pair
assert pair.get("observer_only") is True, pair
assert risk.get("state") == "PASS", risk
assert risk.get("scenario_count") == 12, risk
assert risk.get("observer_only") is True, risk
assert storage.get("state") == "PASS", storage
assert storage.get("verdict") == "STORAGE_REGROWTH_GUARD_HEALTHY", storage
print("PREFLIGHT_CONTRACT=PASS")
PY

PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_HASH_BEFORE="$(sha256sum "$LEDGER" | awk '{print $1}')"

PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST_FILE"
PYTHONPATH="$WT" "$PY" -m py_compile "$SOURCE_SCRIPT"

mkdir -p "$INSTALL_DIR" "$OUTDIR"
install -m 0555 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"

cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Q4R3 Exact25 Read-Only Method Scoreboard Observer
After=$PROJECTION_TIMER $PAIR_TIMER $RISK_TIMER
Requires=$PROJECTION_TIMER $PAIR_TIMER $RISK_TIMER

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PY $ACTIVE_SCRIPT --projection-status $PROJECTION_STATUS --projection $PROJECTION --risk-status $RISK_STATUS --risk-grid $RISK_GRID --pair-status $PAIR_STATUS --output $OUTPUT --status $STATUS --violations $VIOLATIONS
User=root
Group=root
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
Description=Q4R3 Exact25 Method Scoreboard Timer

[Timer]
OnBootSec=135s
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

test "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER"
test "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER"
test "$LEDGER_HASH_BEFORE" = "$LEDGER_HASH_AFTER"
systemctl is-active --quiet "$UNIT.timer"

"$PY" - "$STATUS" "$VIOLATIONS" "$JOB" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
status = json.load(open(sys.argv[1], encoding="utf-8"))
violations = json.load(open(sys.argv[2], encoding="utf-8"))
assert status.get("state") == "PASS", status
assert status.get("method_count") == 6, status
assert status.get("observer_only") is True, status
assert status.get("ranking_enabled") is False, status
assert status.get("comparison_decision_enabled") is False, status
assert status.get("formal_ledger_modified") is False, status
assert violations.get("count") == 0, violations
payload = {
    "job": "q4r3_exact25_method_scoreboard_observer",
    "state": "PASS",
    "current_stage": "complete",
    "status": "PASS_Q4R3_EXACT25_METHOD_SCOREBOARD_OBSERVER",
    "verdict": status.get("verdict"),
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "method_count": status.get("method_count"),
    "methods_with_trigger": status.get("methods_with_trigger"),
    "methods_with_outcome": status.get("methods_with_outcome"),
    "methods_risk_ready": status.get("methods_risk_ready"),
    "observer_only": True,
    "ranking_enabled": False,
    "comparison_decision_enabled": False,
    "promotion_enabled": False,
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

echo Q4R3_EXACT25_METHOD_SCOREBOARD_OBSERVER_INSTALLED
echo "STATUS=$STATUS"
echo "SCOREBOARD=$OUTPUT"
echo "VIOLATIONS=$VIOLATIONS"
echo "JOB=$JOB"
