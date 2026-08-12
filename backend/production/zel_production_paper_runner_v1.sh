#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
INTERVAL_S="${ZEL_PRODUCTION_PAPER_INTERVAL_S:-5}"
MAX_FAILURES="${ZEL_PRODUCTION_PAPER_MAX_CONSECUTIVE_FAILURES:-3}"
SURVIVOR_HEALTH_INTERVAL_S="${ZEL_PRODUCTION_SURVIVOR_HEALTH_INTERVAL_S:-3600}"

if ! [[ "${SURVIVOR_HEALTH_INTERVAL_S}" =~ ^[0-9]+$ ]] || [[ "${SURVIVOR_HEALTH_INTERVAL_S}" -lt 1 ]]; then
  echo "ZEL_PRODUCTION_SURVIVOR_HEALTH_INTERVAL_S must be a positive integer" >&2
  exit 64
fi

next_survivor_health_at=0

while true; do
  "${PYTHON_BIN}" -m backend.production.zel_production_performance_bootstrap_v1 --tick

  # Resolve deterministic Explore state only. AI proposal generation and source
  # acquisition are intentionally outside this 5-second PAPER daemon and run in
  # bounded asynchronous GitHub Actions. The router consumes durable receipts
  # but grants no selection/promotion/execution/LIVE/order authority to AI.
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

  # Runtime health uses the frozen 1h prospective canary contract. Do not poll it
  # on every 5-second PAPER tick. When a completed health epoch rejects the active
  # authority, rotation immediately quarantines it and moves to the next existing
  # pool survivor without metric re-ranking; the new authority is consumed on the
  # next PAPER tick. LIVE/order authority remains blocked throughout.
  now_s="$(date +%s)"
  if [[ "${now_s}" -ge "${next_survivor_health_at}" ]]; then
    "${PYTHON_BIN}" -m backend.production.zel_production_survivor_runtime_health_v1
    "${PYTHON_BIN}" -m backend.production.zel_production_survivor_rotation_v2
    next_survivor_health_at=$((now_s + SURVIVOR_HEALTH_INTERVAL_S))
  fi

  sleep "${INTERVAL_S}"
done
