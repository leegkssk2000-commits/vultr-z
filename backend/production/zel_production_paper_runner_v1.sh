#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
INTERVAL_S="${ZEL_PRODUCTION_PAPER_INTERVAL_S:-5}"
MAX_FAILURES="${ZEL_PRODUCTION_PAPER_MAX_CONSECUTIVE_FAILURES:-3}"

while true; do
  # Performance/bootstrap and deterministic Explore routing stay O(1) and
  # network-free inside the 5-second PAPER loop.
  "${PYTHON_BIN}" -m backend.production.zel_production_performance_bootstrap_v1 --tick
  "${PYTHON_BIN}" -m backend.production.zel_production_economic_edge_router_v1 --tick

  # Consume only durable proposal receipts produced asynchronously outside this
  # daemon. Source acquisition is deterministic and may release a previously
  # blocked proposal once its verified native source becomes available.
  "${PYTHON_BIN}" -m backend.production.zel_production_source_acquisition_v1
  "${PYTHON_BIN}" -m backend.production.zel_production_economic_edge_router_v1 --tick

  "${PYTHON_BIN}" -m backend.production.zel_production_alpha_signal_runner_v1
  "${PYTHON_BIN}" -m backend.production.zel_production_paper_source_adapter_v1

  set +e
  "${PYTHON_BIN}" -m backend.production.zel_production_paper_loop_v1 \
    --once \
    --interval-s 0 \
    --max-consecutive-failures "${MAX_FAILURES}"
  rc=$?
  set -e
  if [[ "${rc}" -eq 2 ]]; then
    exit 2
  fi
  if [[ "${rc}" -ne 0 ]]; then
    exit "${rc}"
  fi

  "${PYTHON_BIN}" -m backend.production.zel_production_improvement_controller_v1 --tick
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_pool_v1
  sleep "${INTERVAL_S}"
done
