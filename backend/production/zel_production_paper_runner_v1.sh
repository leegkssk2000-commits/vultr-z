#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
INTERVAL_S="${ZEL_PRODUCTION_PAPER_INTERVAL_S:-5}"
MAX_FAILURES="${ZEL_PRODUCTION_PAPER_MAX_CONSECUTIVE_FAILURES:-3}"

while true; do
  "${PYTHON_BIN}" -m backend.production.zel_production_performance_bootstrap_v1 --tick
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_pool_refill_bridge_v1

  # Resolve deterministic Explore state only. AI proposal generation and source
  # acquisition are intentionally outside this 5-second PAPER daemon and run in
  # bounded asynchronous GitHub Actions. The refill bridge can only turn a
  # verified 3+2 pool deficit into the existing bounded route-change demand; it
  # grants no selection/promotion/execution/LIVE/order authority.
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
  "${PYTHON_BIN}" -m backend.production.zel_production_family_paper_evidence_producer_v1
  "${PYTHON_BIN}" -m backend.production.zel_production_family_survivor_verifier_v1
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_catalog_v1
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_pool_v2
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_authority_activation_v2
  sleep "${INTERVAL_S}"
done
