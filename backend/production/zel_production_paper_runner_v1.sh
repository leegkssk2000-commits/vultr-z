#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
INTERVAL_S="${ZEL_PRODUCTION_PAPER_INTERVAL_S:-5}"
MAX_FAILURES="${ZEL_PRODUCTION_PAPER_MAX_CONSECUTIVE_FAILURES:-3}"

while true; do
  # 1) Refresh the active-alpha signal before building PAPER input.
  # Missing/non-executable authority is an O(1) HOLD: no BingX call and no
  # signal-file mutation. Only an already executable Trend/Momentum authority
  # is allowed to reach the strict BingX producer in v1.
  "${PYTHON_BIN}" -m backend.production.zel_production_alpha_signal_runner_v1

  # 2) Refresh authoritative PAPER input. Missing/non-executable alpha emits
  # NO_VALIDATED_ALPHA without touching BingX or inventing price/qty.
  # Active alpha uses strict BingX-native freshness + canonical Risk/Sizing.
  "${PYTHON_BIN}" -m backend.production.zel_production_paper_source_adapter_v1

  # 3) Execute exactly one bounded PAPER cycle under the existing single-flight,
  # idempotence, retry-budget and circuit-breaker supervisor.
  set +e
  "${PYTHON_BIN}" -m backend.production.zel_production_paper_loop_v1 \
    --once \
    --interval-s 0 \
    --max-consecutive-failures "${MAX_FAILURES}"
  rc=$?
  set -e

  # PAPER loop exit 2 means its bounded circuit is intentionally open.
  # Preserve that status so systemd RestartPreventExitStatus=2 remains valid.
  if [[ "${rc}" -eq 2 ]]; then
    exit 2
  fi
  if [[ "${rc}" -ne 0 ]]; then
    exit "${rc}"
  fi

  # 4) Advance cumulative improvement after the cycle receipt is durable.
  # With no incumbent/evidence this is an O(1) HOLD. With valid evidence it may
  # atomically seed/promote/rollback CONFIG_ONLY PAPER authority. It never edits
  # source code and never submits an exchange order.
  "${PYTHON_BIN}" -m backend.production.zel_production_improvement_controller_v1 --tick

  sleep "${INTERVAL_S}"
done
