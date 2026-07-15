#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
SHA="${Q4R3_R01_SHA:?Q4R3_R01_SHA_REQUIRED}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r01-owner-adjudication-v1}"
WT="/tmp/q4r3_team_advisor_r01_${SHA:0:12}"

[[ -d "$ROOT/.git" || -f "$ROOT/.git" ]] || { echo "GIT_REPO_MISSING=$ROOT"; exit 1; }

cleanup() {
  local code="$?"
  if [[ "$code" -eq 0 ]]; then
    git -C "$ROOT" -c safe.directory="$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  else
    echo "R01_WORKTREE_PRESERVED_FOR_DIAGNOSIS=$WT"
  fi
}
trap cleanup EXIT

if [[ -e "$WT" ]]; then
  git -C "$ROOT" -c safe.directory="$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || {
    echo "EXISTING_WORKTREE_BLOCKS_RUN=$WT"
    exit 1
  }
fi

git -C "$ROOT" -c safe.directory="$ROOT" fetch --no-tags origin "$SHA"
git -C "$ROOT" -c safe.directory="$ROOT" worktree add --detach "$WT" "$SHA"
test "$(git -C "$WT" rev-parse HEAD)" = "$SHA"

Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" bash "$WT/tools/run_q4r3_team_advisor_r01_owner_adjudication.sh"
Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" Q4R3_TARGET_BRANCH="$TARGET_BRANCH" bash "$WT/tools/publish_q4r3_team_advisor_r01_owner_adjudication_evidence.sh"

echo Q4R3_TEAM_ADVISOR_R01_AUDIT_AND_PUBLISH_COMPLETE
