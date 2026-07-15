#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r04-canonical-team-contract-v1}"
STATUS="$ROOT/runtime/exact25_edge_v1/team_advisor_r04_canonical_team_contract/status_latest.json"
EVIDENCE="evidence/q4r3_team_advisor_r04_canonical_team_contract_latest.json"
OUT="$WT/$EVIDENCE"

[[ -f "$STATUS" ]] || { echo "STATUS_MISSING=$STATUS"; exit 1; }
mkdir -p "$(dirname "$OUT")"
cp -f "$STATUS" "$OUT"

git -C "$WT" add "$EVIDENCE"
if git -C "$WT" diff --cached --quiet; then
  echo EVIDENCE_UNCHANGED
  exit 0
fi

git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" \
  commit -m "Record R0.4 canonical Team contract evidence"
git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"

echo "R04_EVIDENCE_PUBLISHED=$EVIDENCE"
