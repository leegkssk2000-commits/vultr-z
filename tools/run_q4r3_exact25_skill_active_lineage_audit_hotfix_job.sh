#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
BRANCH="q4r3-exact25-skill-active-lineage-audit"
WT="/tmp/q4r3-exact25-skill-active-lineage-audit-hotfix"
PYTHON_BIN="${Q4R3_PYTHON_BIN:-$ROOT/venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" && -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi
RUNTIME_DIR="$ROOT/runtime/exact25_edge_v1/skill_active_lineage_audit"
JOB_STATUS="$ROOT/runtime/q4r3_exact25_skill_active_lineage_audit_job_latest.json"
RESULT="$RUNTIME_DIR/q4r3_exact25_skill_active_lineage_audit_latest.json"
MATRIX="$RUNTIME_DIR/q4r3_exact25_skill_compatibility_matrix_latest.csv"
PRODUCER_UNIT="q4r3-exact25-shadow-producer.service"
WRITER_UNIT="q4r3-exact25-persistent-single-event-writer.service"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
CURRENT_STAGE="preflight"

write_job_status() {
  local state="$1"
  local reason="$2"
  local tmp="${JOB_STATUS}.tmp"
  mkdir -p "$(dirname "$JOB_STATUS")"
  cat >"$tmp" <<JSON
{
  "job": "q4r3_exact25_skill_active_lineage_audit",
  "state": "$state",
  "current_stage": "$CURRENT_STAGE",
  "reason": $("$PYTHON_BIN" -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$reason"),
  "started_at": "$STARTED_AT",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "branch": "$BRANCH",
  "result_path": "$RESULT",
  "matrix_path": "$MATRIX",
  "action": "hold",
  "order_authority": "blocked",
  "execution_authority": "none",
  "paper_enabled": false,
  "live_enabled": false,
  "order_enabled": false,
  "strategy_modified": false,
  "trade_method_modified": false,
  "producer_modified": false,
  "writer_modified": false,
  "formal_ledger_modified": false,
  "historical_backfill_allowed": false
}
JSON
  mv -f "$tmp" "$JOB_STATUS"
}

on_error() {
  local line="$1"
  local command="$2"
  local code="$3"
  write_job_status "FAILED" "line=${line} exit=${code} command=${command}"
  exit "$code"
}
trap 'on_error "$LINENO" "$BASH_COMMAND" "$?"' ERR

[[ "$(id -u)" -eq 0 ]] || { echo "RUN_AS_ROOT"; exit 1; }
[[ -d "$ROOT/.git" ]] || { echo "ROOT_REPOSITORY_MISSING=$ROOT"; exit 1; }
[[ -x "$PYTHON_BIN" ]] || { echo "PYTHON_MISSING=$PYTHON_BIN"; exit 1; }

CURRENT_STAGE="active_source_safety_gate"
systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
PRODUCER_PID_BEFORE="$(systemctl show -p MainPID --value "$PRODUCER_UNIT")"
WRITER_PID_BEFORE="$(systemctl show -p MainPID --value "$WRITER_UNIT")"
[[ "$PRODUCER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]
[[ "$WRITER_PID_BEFORE" =~ ^[1-9][0-9]*$ ]]

AVAILABLE_KB="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
[[ "$AVAILABLE_KB" =~ ^[0-9]+$ ]]
if (( AVAILABLE_KB < 4194304 )); then
  echo "INSUFFICIENT_FREE_SPACE_KB=$AVAILABLE_KB"
  exit 1
fi

PROTECTED=(
  "$ROOT/backend/contracts/ZOS_SKILL_REGISTRY_v1.json"
  "$ROOT/backend/engine/skill_resolver.py"
  "$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
  "$ROOT/backend/trade_methods/policy.py"
  "$ROOT/backend/trade_methods/profiles.py"
  "$ROOT/tools/q4r3_exact25_dedicated_shadow_producer.py"
  "$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
)
for path in "${PROTECTED[@]}"; do
  [[ -f "$path" ]] || { echo "PROTECTED_INPUT_MISSING=$path"; exit 1; }
done
HASH_BEFORE="$(sha256sum "${PROTECTED[@]}")"

CURRENT_STAGE="prepare_pinned_worktree"
cd "$ROOT"
git -c safe.directory="$ROOT" fetch origin "$BRANCH"
EXPECTED_HEAD="$(git -c safe.directory="$ROOT" rev-parse "origin/$BRANCH")"
git -c safe.directory="$ROOT" worktree remove --force "$WT" 2>/dev/null || true
rm -rf "$WT"
git -c safe.directory="$ROOT" worktree add --detach "$WT" "origin/$BRANCH"
ACTUAL_HEAD="$(git -c safe.directory="$WT" -C "$WT" rev-parse HEAD)"
[[ "$ACTUAL_HEAD" == "$EXPECTED_HEAD" ]] || { echo "BRANCH_HEAD_MISMATCH"; exit 1; }

CURRENT_STAGE="compile_and_contract_tests"
cd "$WT"
PYTHONPATH="$WT" "$PYTHON_BIN" -m py_compile \
  backend/engine/skill_resolver_v2_candidate.py \
  tools/q4r3_exact25_skill_active_lineage_audit.py \
  tools/q4r3_exact25_skill_active_lineage_audit_hotfix.py
PYTHONPATH="$WT" "$PYTHON_BIN" -m pytest -q \
  tests/test_q4r3_exact25_skill_registry_v2.py \
  tests/test_q4r3_exact25_skill_active_lineage_audit.py

CURRENT_STAGE="execute_readonly_active_lineage_audit"
mkdir -p "$RUNTIME_DIR"
PYTHONPATH="$WT:$ROOT" "$PYTHON_BIN" \
  "$WT/tools/q4r3_exact25_skill_active_lineage_audit_hotfix.py" \
  --active-root "$ROOT" \
  --candidate-root "$WT" \
  --output "$RESULT" \
  --matrix-output "$MATRIX"

CURRENT_STAGE="post_audit_immutability_gate"
PRODUCER_PID_AFTER="$(systemctl show -p MainPID --value "$PRODUCER_UNIT")"
WRITER_PID_AFTER="$(systemctl show -p MainPID --value "$WRITER_UNIT")"
[[ "$PRODUCER_PID_AFTER" == "$PRODUCER_PID_BEFORE" ]] || { echo "PRODUCER_PID_CHANGED"; exit 1; }
[[ "$WRITER_PID_AFTER" == "$WRITER_PID_BEFORE" ]] || { echo "WRITER_PID_CHANGED"; exit 1; }
HASH_AFTER="$(sha256sum "${PROTECTED[@]}")"
[[ "$HASH_AFTER" == "$HASH_BEFORE" ]] || { echo "PROTECTED_HASH_CHANGED"; exit 1; }

RESULT_STATE="$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["state"])' "$RESULT")"
RESULT_VERDICT="$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["verdict"])' "$RESULT")"
[[ "$RESULT_STATE" == "PASS" ]] || { echo "AUDIT_HOLD=$RESULT_VERDICT"; exit 2; }

CURRENT_STAGE="publish_sanitized_result"
DEST="$WT/runtime_results/q4r3/exact25_skill_active_lineage_audit"
mkdir -p "$DEST"
cp -f "$RESULT" "$DEST/q4r3_exact25_skill_active_lineage_audit_latest.json"
cp -f "$MATRIX" "$DEST/q4r3_exact25_skill_compatibility_matrix_latest.csv"
cd "$WT"
git config user.name "Q4R3 Exact25 Audit"
git config user.email "q4r3-audit@localhost"
git add runtime_results/q4r3/exact25_skill_active_lineage_audit/
if ! git diff --cached --quiet; then
  git commit -m "Record Exact25 skill active lineage audit result"
  git push origin "HEAD:$BRANCH"
fi

CURRENT_STAGE="complete"
write_job_status "PASS" "$RESULT_VERDICT"
echo "Q4R3_EXACT25_SKILL_ACTIVE_LINEAGE_AUDIT_PASS"
echo "RESULT=$RESULT"
echo "MATRIX=$MATRIX"
