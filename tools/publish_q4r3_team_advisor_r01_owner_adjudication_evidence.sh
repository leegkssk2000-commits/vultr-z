#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r01-owner-adjudication-v1}"
SOURCE="$ROOT/runtime/exact25_edge_v1/team_advisor_r01_owner_adjudication"
JSON_PATH="evidence/q4r3_team_advisor_r01_owner_adjudication_latest.json"
MD_PATH="evidence/q4r3_team_advisor_r01_owner_adjudication_latest.md"

[[ -f "$SOURCE/status_latest.json" ]] || { echo R01_JSON_MISSING; exit 1; }
[[ -f "$SOURCE/owner_adjudication_latest.md" ]] || { echo R01_MD_MISSING; exit 1; }

mkdir -p "$WT/evidence"
install -m 0644 "$SOURCE/status_latest.json" "$WT/$JSON_PATH"
install -m 0644 "$SOURCE/owner_adjudication_latest.md" "$WT/$MD_PATH"

git -C "$WT" add "$JSON_PATH" "$MD_PATH"
if git -C "$WT" diff --cached --quiet; then
  echo R01_EVIDENCE_UNCHANGED
  exit 0
fi

git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" \
  commit -m "Record R0.1 owner adjudication evidence"
git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"

echo "R01_EVIDENCE_PUBLISHED=$JSON_PATH"
