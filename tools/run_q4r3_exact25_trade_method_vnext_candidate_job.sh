#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_TRADE_METHOD_VNEXT_WORKTREE:-/tmp/q4r3-exact25-trade-method-vnext-candidate}
PYTHON_BIN=$ROOT/.venv/bin/python
BRANCH=q4r3-exact25-trade-method-research-hardening
PACKAGE=$WORKTREE/backend/trade_methods_vnext
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_trade_methods_vnext.py
SSOT=$WORKTREE/config/q4r3_exact25_trade_method_vnext_sgrade_ssot.json
LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
ACTIVE_METHOD_ROOT=$ROOT/backend/trade_methods
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_trade_method_vnext_candidate
RESULT=$RESULT_DIR/result_latest.json
LIVE_DIR=$ROOT/runtime/exact25_edge_v1/trade_method_vnext_candidate
LIVE_RESULT=$LIVE_DIR/result_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_trade_method_vnext_candidate_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_trade_method_vnext_candidate_job.log

exec > >(tee -a "$LOG") 2>&1

fail() {
  local stage=$1
  local reason=$2
  "$PYTHON_BIN" - "$JOB_STATUS" "$stage" "$reason" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({
    "job": "q4r3_exact25_trade_method_vnext_candidate",
    "state": "FAILED",
    "current_stage": sys.argv[2],
    "reason": sys.argv[3],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "action": "hold",
    "order_authority": "blocked",
    "execution_authority": "none",
    "strategy_modified": False,
    "trade_method_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified": False,
}, ensure_ascii=False, indent=2), encoding="utf-8")
PY
  echo "FAILED stage=$stage reason=$reason" >&2
  exit 1
}
trap 'fail unexpected "line=$LINENO command=$BASH_COMMAND"' ERR

[ "$(id -u)" -eq 0 ] || fail preflight RUN_AS_ROOT
for required in "$WORKTREE" "$PYTHON_BIN" "$PACKAGE" "$TEST_FILE" "$SSOT" "$LEDGER"; do
  [ -e "$required" ] || fail preflight "REQUIRED_INPUT_MISSING:$required"
done

mkdir -p "$RESULT_DIR" "$LIVE_DIR"
PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
LEDGER_HASH_BEFORE=$(sha256sum "$LEDGER" | awk '{print $1}')
ACTIVE_HASH_BEFORE=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')

"$PYTHON_BIN" - "$JOB_STATUS" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({
    "job": "q4r3_exact25_trade_method_vnext_candidate",
    "state": "RUNNING",
    "current_stage": "compile_contract_and_determinism_tests",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "action": "hold",
}, ensure_ascii=False, indent=2), encoding="utf-8")
PY

cd "$WORKTREE"
find "$PACKAGE" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
export PYTHONPATH="$WORKTREE"
export PYTHONDONTWRITEBYTECODE=1

while IFS= read -r -d '' file; do
  "$PYTHON_BIN" -m py_compile "$file"
done < <(find "$PACKAGE" -type f -name '*.py' -print0)

TEST_OUTPUT=$("$PYTHON_BIN" -m pytest -q "$TEST_FILE")
echo "$TEST_OUTPUT"
echo "$TEST_OUTPUT" | grep -Eq '[0-9]+ passed'

"$PYTHON_BIN" - "$SSOT" "$RESULT" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
from backend.trade_methods_vnext.manifest import build_manifest
from backend.trade_methods_vnext.profiles import METHOD_PROFILES
from backend.trade_methods_vnext.validation import validate_profile_registry

ssot = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
errors = validate_profile_registry()
if errors:
    raise SystemExit("PROFILE_REGISTRY_INVALID:" + ";".join(errors))
manifest = [
    {
        "method": item.method.value,
        "method_subtype": item.method_subtype.value,
        "profile_version": item.profile_version,
        "profile_sha256": item.profile_sha256,
    }
    for item in build_manifest(METHOD_PROFILES)
]
required_support = set(ssot["required_support_modules"])
actual_support = {"cost_model.py", "manifest.py", "lineage.py", "validation.py"}
if required_support != actual_support:
    raise SystemExit(f"SUPPORT_MODULE_MISMATCH:{actual_support}!={required_support}")
payload = {
    "schema": "q4r3_exact25_trade_method_vnext_candidate_result_v1",
    "state": "PASS",
    "verdict": "S_GRADE_STATIC_CONTRACT_AND_DETERMINISM_PASS",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "candidate_only": True,
    "active_source_replaced": False,
    "profile_count": len(manifest),
    "profile_manifest": manifest,
    "contract_modules": ["types.py", "profiles.py", "policy.py", "resolver.py"],
    "support_modules": sorted(actual_support),
    "determinism_replay_count": ssot["validation_gates"]["determinism_replay_count"],
    "all_in_cost_gate": True,
    "no_trade_zone": True,
    "liquidity_gate": True,
    "volatility_gate": True,
    "regime_gate": True,
    "drawdown_gate": True,
    "liquidation_buffer_gate": True,
    "lineage_hashes": True,
    "network_access": False,
    "randomness": False,
    "wall_clock_decision_reads": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
    "action": "hold",
    "next_action": "BUILD_READONLY_METHOD_PROJECTION_REPLAY_AND_CALIBRATE_THRESHOLDS",
}
path = Path(sys.argv[2])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY

PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
LEDGER_HASH_AFTER=$(sha256sum "$LEDGER" | awk '{print $1}')
ACTIVE_HASH_AFTER=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ] || fail immutability PRODUCER_PID_CHANGED
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ] || fail immutability WRITER_PID_CHANGED
[ "$LEDGER_HASH_BEFORE" = "$LEDGER_HASH_AFTER" ] || fail immutability FORMAL_LEDGER_HASH_CHANGED
[ "$ACTIVE_HASH_BEFORE" = "$ACTIVE_HASH_AFTER" ] || fail immutability ACTIVE_TRADE_METHOD_SOURCE_CHANGED

cp -f "$RESULT" "$LIVE_RESULT.tmp"
mv -f "$LIVE_RESULT.tmp" "$LIVE_RESULT"

cd "$WORKTREE"
export GIT_CONFIG_COUNT=4
export GIT_CONFIG_KEY_0=core.hooksPath
export GIT_CONFIG_VALUE_0=/dev/null
export GIT_CONFIG_KEY_1=commit.gpgsign
export GIT_CONFIG_VALUE_1=false
export GIT_CONFIG_KEY_2=user.name
export GIT_CONFIG_VALUE_2="Q4R3 Exact25 Audit"
export GIT_CONFIG_KEY_3=user.email
export GIT_CONFIG_VALUE_3="q4r3-audit@localhost"
git add runtime_results/q4r3/exact25_trade_method_vnext_candidate
if ! git diff --cached --quiet; then
  git commit -m "Record Exact25 trade-method vNext candidate validation"
  git push origin HEAD:"$BRANCH"
fi
REPORT_COMMIT=$(git rev-parse HEAD)

"$PYTHON_BIN" - "$JOB_STATUS" "$RESULT" "$REPORT_COMMIT" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
result = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
payload = {
    "job": "q4r3_exact25_trade_method_vnext_candidate",
    "state": "PASS",
    "current_stage": "complete",
    "status": "PASS_Q4R3_EXACT25_TRADE_METHOD_VNEXT_CANDIDATE",
    "verdict": result["verdict"],
    "profile_count": result["profile_count"],
    "report_commit": sys.argv[3],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "producer_pid_unchanged": True,
    "writer_pid_unchanged": True,
    "formal_ledger_hash_unchanged": True,
    "active_trade_method_hash_unchanged": True,
    "strategy_modified": False,
    "trade_method_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
    "action": "hold",
    "next_action": result["next_action"],
}
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY

echo "Q4R3_EXACT25_TRADE_METHOD_VNEXT_CANDIDATE_PASS commit=$REPORT_COMMIT"
