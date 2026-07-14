#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_FUNNEL_SCOPE_WORKTREE:-/tmp/q4r3-exact25-funnel-counter-scope-repair}
BRANCH=q4r3-exact25-six-layer-observer-suite
PYTHON_BIN=$ROOT/.venv/bin/python
SOURCE_CORE=$WORKTREE/tools/q4r3_exact25_six_layer_observer_core.py
SOURCE_TEST=$WORKTREE/tests/test_q4r3_exact25_six_layer_observer_suite.py
ACTIVE_CORE=$ROOT/tools/q4r3_exact25_six_layer_observer_core.py
SUITE_UNIT=q4r3-exact25-six-layer-observer-suite.service
SUITE_TIMER=q4r3-exact25-six-layer-observer-suite.timer
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
FORMAL_LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
OUTPUT_ROOT=$ROOT/runtime/exact25_edge_v1/six_layer_observer_suite
FUNNEL_REPORT=$OUTPUT_ROOT/strategy_funnel_report_latest.json
VIOLATIONS=$OUTPUT_ROOT/violations_latest.json
SUITE_STATUS=$OUTPUT_ROOT/status_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_funnel_counter_scope_repair_job_latest.json
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_funnel_counter_scope_repair
RESULT=$RESULT_DIR/q4r3_exact25_funnel_counter_scope_repair_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_funnel_counter_scope_repair_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)

if [ "$(id -u)" -ne 0 ]; then
  echo RUN_AS_ROOT >&2
  exit 1
fi

for required in "$PYTHON_BIN" "$SOURCE_CORE" "$SOURCE_TEST" "$ACTIVE_CORE" "$FORMAL_LEDGER"; do
  [ -e "$required" ] || { echo "REQUIRED_INPUT_MISSING:$required" >&2; exit 2; }
done

mkdir -p "$BACKUP_DIR" "$RESULT_DIR"
cp -a "$ACTIVE_CORE" "$BACKUP_DIR/q4r3_exact25_six_layer_observer_core.py"
PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')

"$PYTHON_BIN" - "$SOURCE_CORE" "$SOURCE_TEST" <<'PY'
from pathlib import Path
import sys

core_path = Path(sys.argv[1])
test_path = Path(sys.argv[2])
core = core_path.read_text(encoding="utf-8")
test = test_path.read_text(encoding="utf-8")

old_core = '''def funnel_layer(rows: Sequence[Mapping[str, Any]], owner_map: Mapping[str, str], status: Mapping[str, Any], state: Mapping[str, Any], opens: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    value = lambda first, second: int(num(status.get(first)) if num(status.get(first)) is not None else num(state.get(second)) or 0)
    signals, opened, closed = value("signal_count", "signal_count"), value("open_event_count", "open_count"), value("close_event_count", "close_count")
    active = int(num(status.get("open_position_count")) if num(status.get("open_position_count")) is not None else num(opens.get("open_count")) or 0)
    formal = len(rows); issues: list[dict[str, str]] = []; verdict = "HEALTHY_OR_ACCUMULATING"
    if signals == 0: verdict = "WAITING_FOR_SIGNAL"
    elif opened == 0: verdict = "SIGNAL_TO_OPEN_STALL"
    elif opened > 0 and closed == 0 and active == 0:
        verdict = "OPEN_TO_CLOSE_COUNTER_GAP"; issues.append(problem("OPEN_CLOSE_COUNTER_GAP", "M", f"opened={opened}:closed={closed}:active={active}", "funnel"))
    if closed > formal:
        verdict = "CLOSE_TO_FORMAL_LEDGER_GAP"; issues.append(problem("CLOSE_TO_FORMAL_LEDGER_GAP", "C", f"producer_closed={closed}:formal={formal}", "funnel"))
    elif formal > closed:
        issues.append(problem("FORMAL_LEDGER_EXCEEDS_PRODUCER_COUNTER", "M", f"formal={formal}:producer_closed={closed}", "funnel"))
    close_counts = Counter(str(row.get("strategy_id") or "unknown") for row in rows)
    active_counts = Counter(str(row.get("strategy_id") or "unknown") for row in opens.get("positions", []) if isinstance(row, Mapping)) if isinstance(opens.get("positions"), list) else Counter()
    return {
        "schema": "q4r3_exact25_strategy_funnel_observer_v1", "generated_at": now_iso(), "verdict": verdict,
        "observable_global_funnel": {"signal": signals, "candidate": None, "admitted": None, "opened_total": opened, "opened_active": active, "producer_closed": closed, "formal_ledger": formal},
        "unsupported_stages": ["candidate", "admitted", "per_strategy_signal", "per_strategy_open_total"],
        "unsupported_stage_policy": "UNKNOWN_NEVER_TREATED_AS_ZERO_OR_FAILURE",
        "zero_formal_close_strategies": sorted(name for name in owner_map if close_counts[name] == 0),
        "per_strategy": [{"strategy_id": name, "signal_count": None, "candidate_count": None, "admitted_count": None, "opened_active_count": active_counts[name], "formal_closed_count": close_counts[name], "dead_route_decision": "UNAVAILABLE_UNTIL_PER_STRATEGY_STAGE_COUNTERS_EXIST"} for name in sorted(owner_map)],
        "observer_only": True, "action": "hold",
    }, issues
'''

new_core = '''def funnel_layer(rows: Sequence[Mapping[str, Any]], owner_map: Mapping[str, str], status: Mapping[str, Any], state: Mapping[str, Any], opens: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    value = lambda first, second: int(num(status.get(first)) if num(status.get(first)) is not None else num(state.get(second)) or 0)
    signals = value("signal_count", "signal_count")
    opened = value("open_event_count", "open_count")
    producer_closed_lifetime = value("close_event_count", "close_count")
    active = int(num(status.get("open_position_count")) if num(status.get("open_position_count")) is not None else num(opens.get("open_count")) or 0)
    formal = len(rows)
    issues: list[dict[str, str]] = []
    verdict = "HEALTHY_OR_ACCUMULATING"
    if signals == 0:
        verdict = "WAITING_FOR_SIGNAL"
    elif opened == 0:
        verdict = "SIGNAL_TO_OPEN_STALL"
    elif opened > 0 and producer_closed_lifetime == 0 and active == 0:
        verdict = "OPEN_TO_CLOSE_COUNTER_GAP"
        issues.append(problem("OPEN_CLOSE_COUNTER_GAP", "M", f"opened={opened}:closed={producer_closed_lifetime}:active={active}", "funnel"))
    close_counts = Counter(str(row.get("strategy_id") or "unknown") for row in rows)
    active_counts = Counter(str(row.get("strategy_id") or "unknown") for row in opens.get("positions", []) if isinstance(row, Mapping)) if isinstance(opens.get("positions"), list) else Counter()
    return {
        "schema": "q4r3_exact25_strategy_funnel_observer_v1",
        "generated_at": now_iso(),
        "verdict": verdict,
        "observable_global_funnel": {
            "signal": signals,
            "candidate": None,
            "admitted": None,
            "opened_total": opened,
            "opened_active": active,
            "producer_closed_lifetime": producer_closed_lifetime,
            "formal_ledger": formal,
        },
        "counter_scopes": {
            "producer_signal_open_close": "PRODUCER_LIFETIME",
            "formal_ledger": "FORWARD_MEASUREMENT_EPOCH",
            "cross_scope_comparison": "DISABLED_NO_COMMON_BASELINE",
        },
        "cross_scope_gap_decision": "UNAVAILABLE_NO_COMMON_BASELINE",
        "unsupported_stages": ["candidate", "admitted", "per_strategy_signal", "per_strategy_open_total", "producer_to_formal_counter_gap"],
        "unsupported_stage_policy": "UNKNOWN_NEVER_TREATED_AS_ZERO_OR_FAILURE",
        "zero_formal_close_strategies": sorted(name for name in owner_map if close_counts[name] == 0),
        "per_strategy": [{"strategy_id": name, "signal_count": None, "candidate_count": None, "admitted_count": None, "opened_active_count": active_counts[name], "formal_closed_count": close_counts[name], "dead_route_decision": "UNAVAILABLE_UNTIL_PER_STRATEGY_STAGE_COUNTERS_EXIST"} for name in sorted(owner_map)],
        "observer_only": True,
        "action": "hold",
    }, issues
'''

old_test = '''def test_funnel_gap_and_duplicate_are_reported_hold(tmp_path: Path) -> None:
    owner = "a" * 64
    start = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    duplicate = row("dup:close", "alpha", owner, "ETHUSDT", "long", start, 0.4, "take_profit")
    args, _ledger = make_args(tmp_path, [duplicate, dict(duplicate)], producer_closed=3)
    assert suite.run(args) == 0
    violations = json.loads(args.violations.read_text(encoding="utf-8"))
    codes = {item["code"] for item in violations["violations"]}
    assert "DUPLICATE_EVENT_ID" in codes
    assert "CLOSE_TO_FORMAL_LEDGER_GAP" in codes
    assert violations["action"] == "hold"
'''

new_test = '''def test_funnel_cross_scope_counter_is_not_misclassified_as_gap(tmp_path: Path) -> None:
    owner = "a" * 64
    start = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    duplicate = row("dup:close", "alpha", owner, "ETHUSDT", "long", start, 0.4, "take_profit")
    args, _ledger = make_args(tmp_path, [duplicate, dict(duplicate)], producer_closed=3)
    assert suite.run(args) == 0
    violations = json.loads(args.violations.read_text(encoding="utf-8"))
    codes = {item["code"] for item in violations["violations"]}
    assert "DUPLICATE_EVENT_ID" in codes
    assert "CLOSE_TO_FORMAL_LEDGER_GAP" not in codes
    assert "FORMAL_LEDGER_EXCEEDS_PRODUCER_COUNTER" not in codes
    assert violations["action"] == "hold"
    funnel = json.loads(args.funnel_report.read_text(encoding="utf-8"))
    assert funnel["counter_scopes"]["cross_scope_comparison"] == "DISABLED_NO_COMMON_BASELINE"
    assert funnel["cross_scope_gap_decision"] == "UNAVAILABLE_NO_COMMON_BASELINE"
    assert funnel["observable_global_funnel"]["producer_closed_lifetime"] == 3
    assert funnel["observable_global_funnel"]["formal_ledger"] == 2
'''

if old_core not in core:
    raise SystemExit("OLD_FUNNEL_BLOCK_NOT_FOUND")
if old_test not in test:
    raise SystemExit("OLD_FUNNEL_TEST_NOT_FOUND")
core_path.write_text(core.replace(old_core, new_core, 1), encoding="utf-8")
test_path.write_text(test.replace(old_test, new_test, 1), encoding="utf-8")
PY

"$PYTHON_BIN" -m py_compile "$SOURCE_CORE"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$SOURCE_TEST"
install -m 0644 "$SOURCE_CORE" "$ACTIVE_CORE.tmp"
mv -f "$ACTIVE_CORE.tmp" "$ACTIVE_CORE"
"$PYTHON_BIN" -m py_compile "$ACTIVE_CORE"

systemctl start "$SUITE_UNIT"
systemctl is-active --quiet "$SUITE_TIMER"
[ "$(systemctl show "$SUITE_UNIT" -p Result --value)" = success ]

PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_AFTER=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ]
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ]
[ "$FORMAL_HASH_BEFORE" = "$FORMAL_HASH_AFTER" ]

"$PYTHON_BIN" - "$FUNNEL_REPORT" "$VIOLATIONS" "$SUITE_STATUS" "$RESULT" "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" "$WRITER_PID_BEFORE" "$WRITER_PID_AFTER" "$FORMAL_HASH_BEFORE" "$FORMAL_HASH_AFTER" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

funnel_path = Path(sys.argv[1])
violations_path = Path(sys.argv[2])
status_path = Path(sys.argv[3])
result_path = Path(sys.argv[4])
funnel = json.loads(funnel_path.read_text(encoding="utf-8"))
violations = json.loads(violations_path.read_text(encoding="utf-8"))
status = json.loads(status_path.read_text(encoding="utf-8"))
codes = {item.get("code") for item in violations.get("violations", [])}
if "CLOSE_TO_FORMAL_LEDGER_GAP" in codes:
    raise SystemExit("FALSE_CROSS_SCOPE_GAP_STILL_PRESENT")
if "FORMAL_LEDGER_EXCEEDS_PRODUCER_COUNTER" in codes:
    raise SystemExit("REVERSE_FALSE_CROSS_SCOPE_GAP_PRESENT")
if funnel.get("counter_scopes", {}).get("cross_scope_comparison") != "DISABLED_NO_COMMON_BASELINE":
    raise SystemExit("COUNTER_SCOPE_POLICY_MISSING")
if funnel.get("cross_scope_gap_decision") != "UNAVAILABLE_NO_COMMON_BASELINE":
    raise SystemExit("CROSS_SCOPE_DECISION_INVALID")
result = {
    "schema": "q4r3_exact25_funnel_counter_scope_repair_result_v1",
    "status": "PASS",
    "verdict": "FALSE_CROSS_SCOPE_GAP_REMOVED",
    "action": "hold",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "producer_closed_lifetime": funnel.get("observable_global_funnel", {}).get("producer_closed_lifetime"),
    "formal_ledger_row_count": funnel.get("observable_global_funnel", {}).get("formal_ledger"),
    "cross_scope_comparison": funnel.get("counter_scopes", {}).get("cross_scope_comparison"),
    "cross_scope_gap_decision": funnel.get("cross_scope_gap_decision"),
    "remaining_violation_count": violations.get("count"),
    "remaining_violation_severity": violations.get("severity"),
    "suite_state": status.get("state"),
    "producer_pid_unchanged": sys.argv[5] == sys.argv[6],
    "writer_pid_unchanged": sys.argv[7] == sys.argv[8],
    "formal_ledger_hash_unchanged": sys.argv[9] == sys.argv[10],
    "strategy_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
}
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY

cd "$WORKTREE"
git add tools/q4r3_exact25_six_layer_observer_core.py tests/test_q4r3_exact25_six_layer_observer_suite.py "$RESULT"
if ! git diff --cached --quiet; then
  git -c user.name="Q4R3 Exact25 Audit" -c user.email="q4r3-audit@localhost" commit -m "Fix Exact25 funnel counter scope comparison"
  git push origin HEAD:"$BRANCH"
fi
REPORT_COMMIT=$(git rev-parse HEAD)

"$PYTHON_BIN" - "$JOB_STATUS" "$REPORT_COMMIT" "$RESULT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
result = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
payload = {
    "job": "q4r3_exact25_funnel_counter_scope_repair",
    "state": "PASS",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "report_commit": sys.argv[2],
    **result,
}
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

echo "Q4R3_EXACT25_FUNNEL_COUNTER_SCOPE_REPAIR_PASS commit=$REPORT_COMMIT"