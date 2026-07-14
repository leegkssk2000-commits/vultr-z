#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_SIX_LAYER_WORKTREE:-/tmp/q4r3-exact25-six-layer-observer-suite}
BRANCH=q4r3-exact25-six-layer-observer-suite
PYTHON_BIN=$ROOT/.venv/bin/python
SOURCE_COLLECTOR=$WORKTREE/tools/q4r3_exact25_market_context_collector.py
SOURCE_CORE=$WORKTREE/tools/q4r3_exact25_six_layer_observer_core.py
SOURCE_ANALYTICS=$WORKTREE/tools/q4r3_exact25_six_layer_analytics.py
SOURCE_SUITE=$WORKTREE/tools/q4r3_exact25_six_layer_observer_suite.py
SOURCE_SSOT=$WORKTREE/backend/config/q4r3_exact25_six_layer_observer_ssot_v1.json
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_six_layer_observer_suite.py
ACTIVE_COLLECTOR=$ROOT/tools/q4r3_exact25_market_context_collector.py
ACTIVE_CORE=$ROOT/tools/q4r3_exact25_six_layer_observer_core.py
ACTIVE_ANALYTICS=$ROOT/tools/q4r3_exact25_six_layer_analytics.py
ACTIVE_SUITE=$ROOT/tools/q4r3_exact25_six_layer_observer_suite.py
ACTIVE_SSOT=$ROOT/backend/config/q4r3_exact25_six_layer_observer_ssot_v1.json

MANIFEST=$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json
PRODUCER_ROOT=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer
PRODUCER_STATUS=$PRODUCER_ROOT/status_latest.json
PRODUCER_STATE=$PRODUCER_ROOT/state.json
OPEN_POSITIONS=$PRODUCER_ROOT/open_positions_latest.json
FORMAL_ROOT=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement
FORMAL_LEDGER=$FORMAL_ROOT/forward_r_ledger.jsonl
WRITER_STATUS=$FORMAL_ROOT/status_latest.json
PRODUCER_UNIT_NAME=q4r3-exact25-shadow-producer.service
WRITER_UNIT_NAME=q4r3-exact25-persistent-single-event-writer.service

OUTPUT_ROOT=$ROOT/runtime/exact25_edge_v1/six_layer_observer_suite
CONTEXT_LEDGER=$OUTPUT_ROOT/market_context_snapshots.jsonl
CONTEXT_STATUS=$OUTPUT_ROOT/market_context_collector_status_latest.json
PROJECTION=$OUTPUT_ROOT/outcome_contract_projection_v1.jsonl
OUTCOME_REPORT=$OUTPUT_ROOT/outcome_contract_report_latest.json
FUNNEL_REPORT=$OUTPUT_ROOT/strategy_funnel_report_latest.json
COST_EXIT_REPORT=$OUTPUT_ROOT/cost_exit_efficiency_latest.json
MARKET_REPORT=$OUTPUT_ROOT/market_context_regime_latest.json
PORTFOLIO_REPORT=$OUTPUT_ROOT/portfolio_interaction_latest.json
REPLAY_REPORT=$OUTPUT_ROOT/replay_ablation_lab_latest.json
SUITE_STATUS=$OUTPUT_ROOT/status_latest.json
VIOLATIONS=$OUTPUT_ROOT/violations_latest.json

COLLECTOR_UNIT_NAME=q4r3-exact25-market-context-collector.service
COLLECTOR_TIMER_NAME=q4r3-exact25-market-context-collector.timer
SUITE_UNIT_NAME=q4r3-exact25-six-layer-observer-suite.service
SUITE_TIMER_NAME=q4r3-exact25-six-layer-observer-suite.timer
COLLECTOR_UNIT=/etc/systemd/system/$COLLECTOR_UNIT_NAME
COLLECTOR_TIMER=/etc/systemd/system/$COLLECTOR_TIMER_NAME
SUITE_UNIT=/etc/systemd/system/$SUITE_UNIT_NAME
SUITE_TIMER=/etc/systemd/system/$SUITE_TIMER_NAME

JOB_STATUS=$ROOT/runtime/q4r3_exact25_six_layer_observer_suite_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_six_layer_observer_suite_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_six_layer_observer_suite
RESULT=$RESULT_DIR/q4r3_exact25_six_layer_observer_suite_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_six_layer_observer_suite_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap
MUTATION_STARTED=false
ROLLBACK_DONE=false

mkdir -p "$ROOT/runtime" "$RESULT_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

write_job_status() {
  local state=$1 reason=$2 report_commit=${3:-}
  "$PYTHON_BIN" - "$JOB_STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$report_commit" "$RESULT" "$CURRENT_STAGE" "$LOG" "$BACKUP_DIR" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1]); result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_six_layer_observer_suite",
    "state": sys.argv[2], "reason": sys.argv[3], "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(), "branch": sys.argv[5],
    "report_commit": sys.argv[6] or None, "result_path": str(result_path),
    "result_exists": result_path.exists() and result_path.stat().st_size > 0,
    "current_stage": sys.argv[8], "log_path": sys.argv[9], "backup_dir": sys.argv[10],
    "action": "hold", "order_authority": "blocked", "execution_authority": "none",
    "real_order_enabled": False, "paper_request_written": False, "live_execution_allowed": False,
    "strategy_modified": False, "producer_modified": False, "writer_modified": False,
    "formal_ledger_modified_by_job": False, "historical_backfill_allowed": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in ("status", "verdict", "next_action", "layer_count", "installed_layers",
                    "formal_ledger_row_count", "context_snapshot_count", "violation_count",
                    "violation_severity", "collector_timer_active", "suite_timer_active",
                    "writer_pid_unchanged", "producer_pid_unchanged", "formal_ledger_hash_unchanged"):
            payload[key] = result.get(key)
    except Exception as exc:
        payload["result_read_error"] = f"{type(exc).__name__}:{exc}"
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
PY
}

set_stage() { CURRENT_STAGE=$1; write_job_status RUNNING "stage=$CURRENT_STAGE"; echo "=== STAGE: $CURRENT_STAGE ==="; }

backup_path() {
  local source=$1 key=$2
  mkdir -p "$BACKUP_DIR/items"
  if [ -e "$source" ]; then cp -a "$source" "$BACKUP_DIR/items/$key"; echo true > "$BACKUP_DIR/$key.existed";
  else echo false > "$BACKUP_DIR/$key.existed"; fi
}

restore_path() {
  local target=$1 key=$2
  rm -rf "$target"
  if [ "$(cat "$BACKUP_DIR/$key.existed" 2>/dev/null || echo false)" = true ]; then
    mkdir -p "$(dirname "$target")"; cp -a "$BACKUP_DIR/items/$key" "$target"
  fi
}

rollback() {
  [ "$ROLLBACK_DONE" = true ] && return 0
  ROLLBACK_DONE=true; trap - ERR
  [ "$MUTATION_STARTED" = true ] || return 0
  systemctl stop "$SUITE_TIMER_NAME" "$COLLECTOR_TIMER_NAME" 2>/dev/null || true
  systemctl stop "$SUITE_UNIT_NAME" "$COLLECTOR_UNIT_NAME" 2>/dev/null || true
  restore_path "$ACTIVE_COLLECTOR" active_collector
  restore_path "$ACTIVE_CORE" active_core
  restore_path "$ACTIVE_ANALYTICS" active_analytics
  restore_path "$ACTIVE_SUITE" active_suite
  restore_path "$ACTIVE_SSOT" active_ssot
  restore_path "$COLLECTOR_UNIT" collector_unit
  restore_path "$COLLECTOR_TIMER" collector_timer
  restore_path "$SUITE_UNIT" suite_unit
  restore_path "$SUITE_TIMER" suite_timer
  restore_path "$OUTPUT_ROOT" output_root
  systemctl daemon-reload || true
  [ "$(cat "$BACKUP_DIR/collector_timer_active" 2>/dev/null || echo false)" = true ] && systemctl start "$COLLECTOR_TIMER_NAME" 2>/dev/null || true
  [ "$(cat "$BACKUP_DIR/suite_timer_active" 2>/dev/null || echo false)" = true ] && systemctl start "$SUITE_TIMER_NAME" 2>/dev/null || true
}

on_error() {
  local code=$? failed_stage=$CURRENT_STAGE
  rollback || true; CURRENT_STAGE=$failed_stage
  write_job_status FAILED "stage=$failed_stage exit_code=$code rollback=true" || true
  echo "Q4R3_EXACT25_SIX_LAYER_OBSERVER_SUITE_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

for required in "$PYTHON_BIN" "$SOURCE_COLLECTOR" "$SOURCE_CORE" "$SOURCE_ANALYTICS" "$SOURCE_SUITE" "$SOURCE_SSOT" "$TEST_FILE" \
                "$MANIFEST" "$PRODUCER_STATUS" "$PRODUCER_STATE" "$OPEN_POSITIONS" "$FORMAL_LEDGER" "$WRITER_STATUS"; do
  [ -e "$required" ] || { CURRENT_STAGE=required_input_check; echo "REQUIRED_INPUT_MISSING:$required" >&2; exit 2; }
done

set_stage preflight_compile_and_tests
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$SOURCE_COLLECTOR" "$SOURCE_CORE" "$SOURCE_ANALYTICS" "$SOURCE_SUITE"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage active_source_safety_gate
systemctl is-active --quiet "$PRODUCER_UNIT_NAME"
systemctl is-active --quiet "$WRITER_UNIT_NAME"
PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT_NAME" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT_NAME" -p MainPID --value)
[ "$PRODUCER_PID_BEFORE" != 0 ] && [ "$WRITER_PID_BEFORE" != 0 ]
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
"$PYTHON_BIN" - "$PRODUCER_STATUS" "$WRITER_STATUS" <<'PY'
import json, sys
from pathlib import Path
producer=json.loads(Path(sys.argv[1]).read_text()); writer=json.loads(Path(sys.argv[2]).read_text())
if producer.get("state") != "RUNNING": raise SystemExit(f"PRODUCER_NOT_RUNNING:{producer.get('state')}")
if producer.get("feature_filter_enabled") not in (False, None): raise SystemExit("FEATURE_FILTER_ENABLED")
if producer.get("cycle_errors") not in ({}, None): raise SystemExit(f"PRODUCER_CYCLE_ERRORS:{producer.get('cycle_errors')}")
if writer.get("state") != "RUNNING": raise SystemExit(f"WRITER_NOT_RUNNING:{writer.get('state')}")
for payload, name in ((producer,"producer"),(writer,"writer")):
    for key in ("paper_enabled","live_enabled","order_enabled"):
        if payload.get(key) not in (False, None): raise SystemExit(f"UNSAFE_{name.upper()}_FLAG:{key}")
PY

set_stage backup_observer_surfaces
mkdir -p "$BACKUP_DIR"
if systemctl is-active --quiet "$COLLECTOR_TIMER_NAME"; then echo true > "$BACKUP_DIR/collector_timer_active"; else echo false > "$BACKUP_DIR/collector_timer_active"; fi
if systemctl is-active --quiet "$SUITE_TIMER_NAME"; then echo true > "$BACKUP_DIR/suite_timer_active"; else echo false > "$BACKUP_DIR/suite_timer_active"; fi
backup_path "$ACTIVE_COLLECTOR" active_collector
backup_path "$ACTIVE_CORE" active_core
backup_path "$ACTIVE_ANALYTICS" active_analytics
backup_path "$ACTIVE_SUITE" active_suite
backup_path "$ACTIVE_SSOT" active_ssot
backup_path "$COLLECTOR_UNIT" collector_unit
backup_path "$COLLECTOR_TIMER" collector_timer
backup_path "$SUITE_UNIT" suite_unit
backup_path "$SUITE_TIMER" suite_timer
backup_path "$OUTPUT_ROOT" output_root
MUTATION_STARTED=true

set_stage install_readonly_six_layer_suite
systemctl stop "$SUITE_TIMER_NAME" "$COLLECTOR_TIMER_NAME" 2>/dev/null || true
systemctl stop "$SUITE_UNIT_NAME" "$COLLECTOR_UNIT_NAME" 2>/dev/null || true
install -m 0755 "$SOURCE_COLLECTOR" "$ACTIVE_COLLECTOR.tmp"; mv -f "$ACTIVE_COLLECTOR.tmp" "$ACTIVE_COLLECTOR"
install -m 0644 "$SOURCE_CORE" "$ACTIVE_CORE.tmp"; mv -f "$ACTIVE_CORE.tmp" "$ACTIVE_CORE"
install -m 0644 "$SOURCE_ANALYTICS" "$ACTIVE_ANALYTICS.tmp"; mv -f "$ACTIVE_ANALYTICS.tmp" "$ACTIVE_ANALYTICS"
install -m 0755 "$SOURCE_SUITE" "$ACTIVE_SUITE.tmp"; mv -f "$ACTIVE_SUITE.tmp" "$ACTIVE_SUITE"
install -m 0644 "$SOURCE_SSOT" "$ACTIVE_SSOT.tmp"; mv -f "$ACTIVE_SSOT.tmp" "$ACTIVE_SSOT"
mkdir -p "$OUTPUT_ROOT"; chmod 0750 "$OUTPUT_ROOT"

cat > "$COLLECTOR_UNIT.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Public Market Context Collector
After=network-online.target $PRODUCER_UNIT_NAME
Wants=network-online.target
Requires=$PRODUCER_UNIT_NAME

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON_BIN $ACTIVE_COLLECTOR --producer-status $PRODUCER_STATUS --ssot $ACTIVE_SSOT --ledger $CONTEXT_LEDGER --status $CONTEXT_STATUS
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadOnlyPaths=$PRODUCER_STATUS $ACTIVE_SSOT
ReadWritePaths=$OUTPUT_ROOT
EOF
install -m 0644 "$COLLECTOR_UNIT.tmp" "$COLLECTOR_UNIT"
rm -f "$COLLECTOR_UNIT.tmp"

cat > "$COLLECTOR_TIMER.tmp" <<EOF
[Unit]
Description=Run Q4R3 Exact25 Market Context Collector Every Minute
[Timer]
OnBootSec=45
OnUnitActiveSec=60
AccuracySec=5
Persistent=true
Unit=$COLLECTOR_UNIT_NAME
[Install]
WantedBy=timers.target
EOF
install -m 0644 "$COLLECTOR_TIMER.tmp" "$COLLECTOR_TIMER"; rm -f "$COLLECTOR_TIMER.tmp"

cat > "$SUITE_UNIT.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Six-Layer Read-Only Observer Suite
After=$COLLECTOR_UNIT_NAME $PRODUCER_UNIT_NAME $WRITER_UNIT_NAME
Requires=$PRODUCER_UNIT_NAME $WRITER_UNIT_NAME

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON_BIN $ACTIVE_SUITE --ledger $FORMAL_LEDGER --manifest $MANIFEST --producer-status $PRODUCER_STATUS --producer-state $PRODUCER_STATE --open-positions $OPEN_POSITIONS --context-ledger $CONTEXT_LEDGER --context-status $CONTEXT_STATUS --ssot $ACTIVE_SSOT --projection $PROJECTION --outcome-report $OUTCOME_REPORT --funnel-report $FUNNEL_REPORT --cost-exit-report $COST_EXIT_REPORT --market-report $MARKET_REPORT --portfolio-report $PORTFOLIO_REPORT --replay-report $REPLAY_REPORT --status $SUITE_STATUS --violations $VIOLATIONS
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadOnlyPaths=$FORMAL_LEDGER $MANIFEST $PRODUCER_STATUS $PRODUCER_STATE $OPEN_POSITIONS $ACTIVE_SSOT
ReadWritePaths=$OUTPUT_ROOT
EOF
install -m 0644 "$SUITE_UNIT.tmp" "$SUITE_UNIT"; rm -f "$SUITE_UNIT.tmp"

cat > "$SUITE_TIMER.tmp" <<EOF
[Unit]
Description=Run Q4R3 Exact25 Six-Layer Observer Suite Every Minute
[Timer]
OnBootSec=55
OnUnitActiveSec=60
AccuracySec=5
Persistent=true
Unit=$SUITE_UNIT_NAME
[Install]
WantedBy=timers.target
EOF
install -m 0644 "$SUITE_TIMER.tmp" "$SUITE_TIMER"; rm -f "$SUITE_TIMER.tmp"

systemctl daemon-reload
systemctl start "$COLLECTOR_UNIT_NAME"
systemctl start "$SUITE_UNIT_NAME"
systemctl enable --now "$COLLECTOR_TIMER_NAME" "$SUITE_TIMER_NAME"

set_stage verify_outputs_and_immutability
for _ in $(seq 1 20); do
  [ -s "$SUITE_STATUS" ] && [ -s "$CONTEXT_STATUS" ] && [ -s "$OUTCOME_REPORT" ] && [ -s "$FUNNEL_REPORT" ] && \
  [ -s "$COST_EXIT_REPORT" ] && [ -s "$MARKET_REPORT" ] && [ -s "$PORTFOLIO_REPORT" ] && [ -s "$REPLAY_REPORT" ] && break
  sleep 2
done
for output in "$SUITE_STATUS" "$CONTEXT_STATUS" "$OUTCOME_REPORT" "$FUNNEL_REPORT" "$COST_EXIT_REPORT" "$MARKET_REPORT" "$PORTFOLIO_REPORT" "$REPLAY_REPORT" "$VIOLATIONS"; do [ -s "$output" ]; done
systemctl is-active --quiet "$COLLECTOR_TIMER_NAME"
systemctl is-active --quiet "$SUITE_TIMER_NAME"
[ "$(systemctl show "$COLLECTOR_UNIT_NAME" -p Result --value)" = success ]
[ "$(systemctl show "$SUITE_UNIT_NAME" -p Result --value)" = success ]
PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT_NAME" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT_NAME" -p MainPID --value)
[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ]
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ]
FORMAL_HASH_AFTER=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
[ "$FORMAL_HASH_BEFORE" = "$FORMAL_HASH_AFTER" ]
"$PYTHON_BIN" - "$SUITE_STATUS" "$CONTEXT_STATUS" <<'PY'
import json, sys
from pathlib import Path
suite=json.loads(Path(sys.argv[1]).read_text()); context=json.loads(Path(sys.argv[2]).read_text())
if suite.get("layer_count") != 6: raise SystemExit("LAYER_COUNT_NOT_SIX")
if len(suite.get("installed_layers") or []) != 6: raise SystemExit("INSTALLED_LAYER_LIST_INVALID")
for key in ("formal_ledger_mutated","strategy_modified","producer_modified","writer_modified","filter_enabled","comparison_decision_enabled","promotion_enabled","paper_enabled","live_enabled","order_enabled","historical_backfill_allowed"):
    if suite.get(key) is not False: raise SystemExit(f"UNSAFE_SUITE_FLAG:{key}={suite.get(key)}")
if suite.get("action") != "hold": raise SystemExit("SUITE_ACTION_NOT_HOLD")
if context.get("observer_only") is not True or context.get("private_credentials_used") is not False: raise SystemExit("CONTEXT_SAFETY_INVALID")
PY

set_stage publish_sanitized_result
"$PYTHON_BIN" - "$SUITE_STATUS" "$CONTEXT_STATUS" "$RESULT" "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" "$WRITER_PID_BEFORE" "$WRITER_PID_AFTER" "$FORMAL_HASH_BEFORE" "$FORMAL_HASH_AFTER" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
suite=json.loads(Path(sys.argv[1]).read_text()); context=json.loads(Path(sys.argv[2]).read_text())
result={
  "schema":"q4r3_exact25_six_layer_observer_suite_job_result_v1",
  "status":"PASS" if suite.get("state") == "HEALTHY" else "HOLD",
  "verdict":"SIX_READONLY_LAYERS_INSTALLED" if suite.get("state") == "HEALTHY" else "SIX_LAYERS_INSTALLED_WITH_OBSERVED_VIOLATIONS",
  "action":"hold", "next_action":"ACCUMULATE_AND_REVIEW_VIOLATIONS",
  "generated_at":datetime.now(timezone.utc).isoformat(),
  "layer_count":suite.get("layer_count"), "installed_layers":suite.get("installed_layers"),
  "formal_ledger_row_count":suite.get("formal_ledger_row_count"),
  "context_snapshot_count":suite.get("context_snapshot_count"),
  "violation_count":suite.get("violation_count"), "violation_severity":suite.get("violation_severity"),
  "collector_state":context.get("state"), "collector_error_count":context.get("error_count"),
  "collector_timer_active":True, "suite_timer_active":True,
  "producer_pid_unchanged":sys.argv[4] == sys.argv[5], "writer_pid_unchanged":sys.argv[6] == sys.argv[7],
  "formal_ledger_hash_unchanged":sys.argv[8] == sys.argv[9],
  "strategy_modified":False, "producer_modified":False, "writer_modified":False,
  "formal_ledger_modified_by_job":False, "paper_enabled":False, "live_enabled":False, "order_enabled":False,
  "historical_backfill_allowed":False, "order_authority":"blocked", "execution_authority":"none",
  "rollback_available":True,
}
path=Path(sys.argv[3]); path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY

set_stage commit_result
REPORT_COMMIT=""
if git -C "$WORKTREE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$WORKTREE" add "$RESULT" || true
  if ! git -C "$WORKTREE" diff --cached --quiet; then
    if git -C "$WORKTREE" commit -m "Record Exact25 six-layer observer suite install result" && git -C "$WORKTREE" push origin "HEAD:$BRANCH"; then
      REPORT_COMMIT=$(git -C "$WORKTREE" rev-parse HEAD)
    else
      echo "RESULT_PUBLISH_WARNING: installation remains active; runtime result push failed" >&2
    fi
  else
    REPORT_COMMIT=$(git -C "$WORKTREE" rev-parse HEAD)
  fi
fi

CURRENT_STAGE=complete
write_job_status COMPLETED "six read-only layers installed; action=hold" "$REPORT_COMMIT"
echo "Q4R3_EXACT25_SIX_LAYER_OBSERVER_SUITE_PASS"
