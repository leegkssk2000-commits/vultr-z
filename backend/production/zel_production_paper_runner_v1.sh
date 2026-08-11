#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
INTERVAL_S="${ZEL_PRODUCTION_PAPER_INTERVAL_S:-5}"
MAX_FAILURES="${ZEL_PRODUCTION_PAPER_MAX_CONSECUTIVE_FAILURES:-3}"

while true; do
  # Refresh the canonical producer-owned input first. Missing/non-executable
  # alpha emits a stable NO_VALIDATED_ALPHA payload with no price or qty.
  # An executable alpha without bound market/risk/sizing authority fails here.
  "${PYTHON_BIN}" -m backend.production.zel_production_paper_source_adapter_v1

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

  sleep "${INTERVAL_S}"
done
