#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1
GEN="$ROOT/gen0"
DUR=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1
CONTRACT_VERSION=VWAP_CLOSED_LOOP_V1_1_CACHE_FINGERPRINT

for p in \
  "$DUR/work/engine/replay_v1.py" \
  "$DUR/work/engine/replay_v2.py" \
  "$DUR/work/engine/lane_checkpoint_v2.py" \
  "$BASE/work/engine/replay_v1_no_trend.py" \
  "$BASE/work/engine/replay_v2_no_trend.py" \
  "$BASE/work/engine/lane_checkpoint_v2.py" \
  "$BASE/work/replay/trades.jsonl.gz"; do
  test -s "$p"
done

mkdir -p "$GEN/result"
CURRENT_FP=$(
  {
    printf '%s\n' "$CONTRACT_VERSION"
    sha256sum \
      "$DUR/work/engine/replay_v1.py" \
      "$DUR/work/engine/replay_v2.py" \
      "$DUR/work/engine/lane_checkpoint_v2.py" \
      "$BASE/work/engine/replay_v1_no_trend.py" \
      "$BASE/work/engine/replay_v2_no_trend.py" \
      "$BASE/work/engine/lane_checkpoint_v2.py" \
      "$BASE/work/replay/trades.jsonl.gz"
  } | sha256sum | awk '{print $1}'
)
FP_FILE="$GEN/result/runner_contract_fingerprint.sha256"
OLD_FP=$(cat "$FP_FILE" 2>/dev/null || true)

# A cache created under a different engine/data/runner contract must never be resumed.
if [ -n "$OLD_FP" ] && [ "$OLD_FP" != "$CURRENT_FP" ]; then
  rm -rf "$GEN/runs" "$GEN/merged_A" "$GEN/merged_B" "$GEN/merged_C"
  rm -f "$GEN/result/w12_selection.json" "$GEN/result/terminal_receipt.json" "$GEN/result/research_incumbent.json"
  echo "INVALIDATE_STALE_GEN0_CACHE old=$OLD_FP new=$CURRENT_FP"
fi
printf '%s\n' "$CURRENT_FP" > "$FP_FILE.tmp"
mv -f "$FP_FILE.tmp" "$FP_FILE"

echo "PASS_RUNNER_CONTRACT_FINGERPRINT $CURRENT_FP"

# The base runner still performs per-candidate SHA validation. This wrapper adds
# engine/data/contract invalidation so candidate-only hashes cannot resume stale lanes.
exec bash ops/zel-structural-premium-vwap-closed-loop-v1.sh
