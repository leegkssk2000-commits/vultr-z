#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/zel/research-runtime/jobs
printf '===REPLAY_ENGINE_CANDIDATES===\n'
find "$ROOT" -type f \( -name 'replay_v1.py' -o -name 'replay_v1_*.py' -o -name '*replay*v1*.py' \) 2>/dev/null | sort | while read -r p; do
  test -s "$p" || continue
  if grep -qE '_ZEL_OVERLAY|ZEL_STRUCTURAL_PREMIUM_OVERLAY_PATCH' "$p"; then legacy=1; else legacy=0; fi
  if grep -q 'producer.valid_entry(result, current_price)' "$p"; then entry=1; else entry=0; fi
  if grep -q 'frame.iloc\[max(0, index - FRAME_LIMIT + 1): index + 1\]' "$p"; then causal=1; else causal=0; fi
  count=$(grep -E '^EXPECTED_STRATEGY_COUNT = ' "$p" | head -1 | sed -E 's/.*= *//' || true)
  size=$(stat -c '%s' "$p")
  sha=$(sha256sum "$p" | awk '{print $1}')
  printf '%s|legacy=%s|entry=%s|causal=%s|expected=%s|size=%s|sha=%s\n' "$p" "$legacy" "$entry" "$causal" "${count:-?}" "$size" "$sha"
done
P=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/engine/replay_v1_no_trend.py
echo '===NO_TREND_MARKERS==='
grep -nE 'ZEL_STRUCTURAL_PREMIUM_OVERLAY|_ZEL_OVERLAY|NO_TREND|EXPECTED_STRATEGY_COUNT|def _restore_structural_premium_registry|if __name__' "$P" | tail -80 || true
echo '===NO_TREND_TAIL_930_1250==='
sed -n '930,1250p' "$P"
