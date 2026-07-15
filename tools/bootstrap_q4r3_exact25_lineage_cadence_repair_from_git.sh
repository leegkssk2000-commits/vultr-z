#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
SHA="${Q4R3_REPAIR_SHA:?Q4R3_REPAIR_SHA_REQUIRED}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-exact25-lineage-cadence-repair-v1}"
WT="/tmp/q4r3_lineage_cadence_repair_${SHA:0:12}"

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

git -C "$WT" -c safe.directory="$WT" merge-base --is-ancestor "$SHA" HEAD

Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" \
  bash "$WT/tools/run_q4r3_exact25_lineage_cadence_repair_job.sh"

Q4R3_ROOT="$ROOT" Q4R3_WORKTREE="$WT" Q4R3_TARGET_BRANCH="$TARGET_BRANCH" \
  bash "$WT/tools/publish_q4r3_exact25_lineage_cadence_repair_evidence.sh"

echo Q4R3_EXACT25_LINEAGE_CADENCE_REPAIR_APPLY_AND_PUBLISH_PASS
