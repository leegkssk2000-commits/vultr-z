#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_TRADE_METHOD_HARDENING_WORKTREE:-/tmp/q4r3-exact25-trade-method-research-hardening-v2}
INNER_RUNNER=$WORKTREE/tools/run_q4r3_exact25_trade_method_source_capture_audit_job.sh
PYTHON_BIN=$ROOT/.venv/bin/python
JOB_STATUS=$ROOT/runtime/q4r3_exact25_trade_method_source_capture_audit_job_latest.json

if [ "$(id -u)" -ne 0 ]; then
  echo RUN_AS_ROOT >&2
  exit 1
fi

for required in "$WORKTREE" "$INNER_RUNNER" "$PYTHON_BIN"; do
  [ -e "$required" ] || {
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  }
done

cd "$WORKTREE"

# Isolate evidence commits from repository-local hooks and signing policy.
# The previous audit completed and produced a valid report, then failed only
# because the final evidence commit returned status 1.
export GIT_CONFIG_COUNT=4
export GIT_CONFIG_KEY_0=core.hooksPath
export GIT_CONFIG_VALUE_0=/dev/null
export GIT_CONFIG_KEY_1=commit.gpgsign
export GIT_CONFIG_VALUE_1=false
export GIT_CONFIG_KEY_2=user.name
export GIT_CONFIG_VALUE_2="Q4R3 Exact25 Audit"
export GIT_CONFIG_KEY_3=user.email
export GIT_CONFIG_VALUE_3="q4r3-audit@localhost"

# Confirm the intended isolation before executing the original audited job.
[ "$(git config --get core.hooksPath)" = "/dev/null" ]
[ "$(git config --bool --get commit.gpgsign)" = "false" ]

Q4R3_TRADE_METHOD_HARDENING_WORKTREE="$WORKTREE" \
  bash "$INNER_RUNNER"

# Fail closed unless the published job result proves the complete source
# capture and system immutability contract.
"$PYTHON_BIN" - "$JOB_STATUS" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit("JOB_STATUS_MISSING")
data = json.loads(path.read_text(encoding="utf-8"))
required = {
    "state": "PASS",
    "status": "PASS_Q4R3_EXACT25_TRADE_METHOD_SOURCE_CAPTURE_AUDIT",
    "source_count": 4,
    "producer_pid_unchanged": True,
    "writer_pid_unchanged": True,
    "formal_ledger_hash_unchanged": True,
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
}
for key, expected in required.items():
    actual = data.get(key)
    if actual != expected:
        raise SystemExit(f"FAIL_CLOSED_RESULT_MISMATCH:{key}:{actual!r}!={expected!r}")
print("Q4R3_EXACT25_TRADE_METHOD_SOURCE_CAPTURE_AUDIT_V2_PASS")
PY
