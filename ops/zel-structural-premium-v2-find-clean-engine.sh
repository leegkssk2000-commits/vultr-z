#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/zel/research-runtime/jobs/structural-premium-v2
ADV=$ROOT/advisory
SMOKE=$ROOT/smoke_next_open_v3

echo '===GEMINI_REVIEW==='
cat "$ADV/gemini_replay_contract_review.txt" 2>/dev/null || true
echo
echo '===OPENAI_REVIEW==='
cat "$ADV/openai_replay_contract_review.txt" 2>/dev/null || true
echo
echo '===MACHINE_GATE==='
cat "$ADV/deterministic_contract_gate.json" 2>/dev/null || true
echo
echo '===SMOKE_RECEIPT==='
cat "$ADV/smoke_receipt.json" 2>/dev/null || true
echo
echo '===READINESS==='
cat "$ADV/v2_replay_readiness.json" 2>/dev/null || true
echo
echo '===SMOKE_CHECKPOINTS==='
find "$SMOKE/lane_checkpoints" -type f -name '*.json.gz' -printf '%p %s\n' 2>/dev/null | sort || true
echo 'COUNT='
find "$SMOKE/lane_checkpoints" -type f -name '*.json.gz' 2>/dev/null | wc -l || true
echo '===ACTIVE_PROCESSES==='
pgrep -af 'replay_v1_v2|lane_smoke_v2|smoke_next_open_v3' || true
echo '===SMOKE_LOG_TAIL==='
tail -80 "$ROOT/engine/smoke.log" 2>/dev/null || true
