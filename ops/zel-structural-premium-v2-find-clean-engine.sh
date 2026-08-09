#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/zel/research-runtime/jobs/structural-premium-v2
REVIEW=$ROOT/advisory/gemini_replay_contract_review.txt
ENG=$ROOT/engine/replay_v1_v2.py

echo '===GEMINI_REVIEW_FULL==='
cat "$REVIEW" 2>/dev/null || true

echo '===V2_REPRICE_HELPER==='
grep -n -A45 -B5 'def _v2_reprice_pending_entry' "$ENG" 2>/dev/null || true

echo '===V2_PENDING_EXECUTION==='
grep -n -A55 -B5 'if pending_entry is not None' "$ENG" 2>/dev/null || true
