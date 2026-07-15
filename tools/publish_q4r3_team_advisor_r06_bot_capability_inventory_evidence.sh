#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r06-bot-source-consolidation-audit-v1}"
STATUS="$ROOT/runtime/exact25_edge_v1/team_advisor_r06_bot_capability_inventory/status_latest.json"
EVIDENCE="evidence/q4r3_team_advisor_r06_bot_capability_inventory_latest.json"
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
  commit -m "Record R0.6 bot capability inventory evidence"
git -C "$WT" push origin "HEAD:refs/heads/$BRANCH"
echo "R06_EVIDENCE_PUBLISHED=$EVIDENCE"
