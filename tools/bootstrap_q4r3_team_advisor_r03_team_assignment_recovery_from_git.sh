#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
SHA="${Q4R3_R03_SHA:?Q4R3_R03_SHA_REQUIRED}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r03-team-assignment-recovery-v1}"
WT="/tmp/q4r3_team_advisor_r03_${SHA:0:12}"

[[ -d "$ROOT/.git" || -f "$ROOT/.git" ]] || { echo "GIT_REPO_MISSING=$ROOT"; exit 1; }

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

Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" \
  bash "$WT/tools/run_q4r3_team_advisor_r03_team_assignment_recovery.sh"

Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" Q4R3_TARGET_BRANCH="$TARGET_BRANCH" \
  bash "$WT/tools/publish_q4r3_team_advisor_r03_team_assignment_recovery_evidence.sh"

echo Q4R3_TEAM_ADVISOR_R03_AUDIT_AND_PUBLISH_COMPLETE
