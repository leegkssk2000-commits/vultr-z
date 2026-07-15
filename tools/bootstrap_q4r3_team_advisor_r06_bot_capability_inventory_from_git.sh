#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${Q4R3_ROOT:-/home/z/z}"
SHA="${Q4R3_R06_SHA:?Q4R3_R06_SHA_REQUIRED}"
BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r06-bot-source-consolidation-audit-v1}"
WT="/tmp/q4r3_team_advisor_r06_${SHA:0:12}"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
PREFIX="$(mktemp /tmp/q4r3_r06_ledger_prefix.XXXXXX)"

cleanup() {
  local code="$?"
  rm -f "$PREFIX"
  if [[ "$code" -eq 0 ]]; then
    git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  else
    echo "WORKTREE_PRESERVED_FOR_DIAGNOSIS=$WT"
  fi
}
trap cleanup EXIT

[[ -f "$LEDGER" ]] || { echo "LEDGER_MISSING=$LEDGER"; exit 1; }
cp --reflink=auto "$LEDGER" "$PREFIX"
LEDGER_SIZE="$(stat -c %s "$PREFIX")"
ZICO_PID_BEFORE="$(systemctl show zico-ceo-canonical-adapter.service -p MainPID --value)"
PRODUCER_PID_BEFORE="$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value)"

if [[ -e "$WT" ]]; then
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi
git -C "$ROOT" -c safe.directory="$ROOT" fetch --no-tags origin "$SHA"
git -C "$ROOT" -c safe.directory="$ROOT" worktree add --detach "$WT" "$SHA"

Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" \
  bash "$WT/tools/run_q4r3_team_advisor_r06_bot_capability_inventory.sh"

[[ "$(systemctl show zico-ceo-canonical-adapter.service -p MainPID --value)" == "$ZICO_PID_BEFORE" ]] || { echo ZICO_PID_CHANGED; exit 1; }
[[ "$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value)" == "$PRODUCER_PID_BEFORE" ]] || { echo PRODUCER_PID_CHANGED; exit 1; }
[[ "$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value)" == "$WRITER_PID_BEFORE" ]] || { echo WRITER_PID_CHANGED; exit 1; }
cmp -n "$LEDGER_SIZE" "$PREFIX" "$LEDGER"

Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" Q4R3_TARGET_BRANCH="$BRANCH" \
  bash "$WT/tools/publish_q4r3_team_advisor_r06_bot_capability_inventory_evidence.sh"

echo Q4R3_TEAM_ADVISOR_R06_BOOTSTRAP_PASS
echo "ZICO_PID=$ZICO_PID_BEFORE"
echo "PRODUCER_PID=$PRODUCER_PID_BEFORE"
echo "WRITER_PID=$WRITER_PID_BEFORE"
