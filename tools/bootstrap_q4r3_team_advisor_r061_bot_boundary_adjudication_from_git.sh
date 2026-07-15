#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${Q4R3_ROOT:-/home/z/z}"
SHA="${Q4R3_R061_SHA:?Q4R3_R061_SHA_REQUIRED}"
BRANCH="q4r3-team-advisor-r061-bot-boundary-adjudication-v1"
WT="/tmp/q4r3_team_advisor_r061_${SHA:0:12}"

cleanup() {
  local code="$?"
  if [[ "$code" -eq 0 ]]; then
    git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  else
    echo "WORKTREE_PRESERVED_FOR_DIAGNOSIS=$WT"
  fi
}
trap cleanup EXIT

if [[ -e "$WT" ]]; then
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi
git -C "$ROOT" -c safe.directory="$ROOT" fetch --no-tags origin "$SHA"
git -C "$ROOT" -c safe.directory="$ROOT" worktree add --detach "$WT" "$SHA"

Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" bash "$WT/tools/run_q4r3_team_advisor_r061_bot_boundary_adjudication.sh"

STATUS="$ROOT/runtime/exact25_edge_v1/team_advisor_r061_bot_boundary_adjudication/status_latest.json"
EVIDENCE="$WT/evidence/q4r3_team_advisor_r061_bot_boundary_adjudication_latest.json"
mkdir -p "$(dirname "$EVIDENCE")"
cp -f "$STATUS" "$EVIDENCE"
git -C "$WT" add "evidence/q4r3_team_advisor_r061_bot_boundary_adjudication_latest.json"
git -C "$WT" -c user.name="ZEL Evidence" -c user.email="zel-evidence@localhost" commit -m "Record R0.6.1 Bot boundary evidence"
git -C "$WT" push origin "HEAD:refs/heads/$BRANCH"

echo Q4R3_TEAM_ADVISOR_R061_BOOTSTRAP_PASS
