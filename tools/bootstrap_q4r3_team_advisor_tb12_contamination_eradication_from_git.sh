#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
SHA="${Q4R3_TB12_SHA:?Q4R3_TB12_SHA_REQUIRED}"
WT="/tmp/q4r3_team_advisor_tb12_${SHA:0:12}"

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
  bash "$WT/tools/run_q4r3_team_advisor_tb12_contamination_eradication_audit.sh"

echo Q4R3_TEAM_ADVISOR_TB12_BOOTSTRAP_PASS
