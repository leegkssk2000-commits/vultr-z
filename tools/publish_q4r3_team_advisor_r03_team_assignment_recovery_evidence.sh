#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r03-team-assignment-recovery-v1}"
OUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r03_team_assignment_recovery"
STATUS="$OUT/status_latest.json"
REPORT="$OUT/team_assignment_recovery_latest.md"
EVIDENCE_JSON="$WT/evidence/q4r3_team_advisor_r03_team_assignment_recovery_latest.json"
EVIDENCE_MD="$WT/evidence/q4r3_team_advisor_r03_team_assignment_recovery_latest.md"

for required in "$STATUS" "$REPORT"; do
  [[ -f "$required" ]] || { echo "REQUIRED_EVIDENCE_MISSING=$required"; exit 1; }
done

mkdir -p "$WT/evidence"
cp -f "$STATUS" "$EVIDENCE_JSON"
cp -f "$REPORT" "$EVIDENCE_MD"

git -C "$WT" add \
  evidence/q4r3_team_advisor_r03_team_assignment_recovery_latest.json \
  evidence/q4r3_team_advisor_r03_team_assignment_recovery_latest.md

if git -C "$WT" diff --cached --quiet; then
  echo R03_EVIDENCE_UNCHANGED
  exit 0
fi

git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" \
  commit -m "Record R0.3 Team assignment recovery evidence"
git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"

echo R03_TEAM_ASSIGNMENT_RECOVERY_EVIDENCE_PUBLISHED
