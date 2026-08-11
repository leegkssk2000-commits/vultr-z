#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
INTERVAL_S="${ZEL_PRODUCTION_PAPER_INTERVAL_S:-5}"
MAX_FAILURES="${ZEL_PRODUCTION_PAPER_MAX_CONSECUTIVE_FAILURES:-3}"

while true; do
  # 0) Resolve zero-survivor bootstrap before signal production. This is O(1)
  # and network-free: it only reads the recovered economic admission queue and
  # optional admission evidence. With no evidence it HOLDs. Only a complete
  # W1/W2/W3 seed-survivor receipt carrying explicit risk/source authority may
  # atomically register the first PAPER incumbent. No source-code mutation or
  # exchange order is possible here.
  "${PYTHON_BIN}" -m backend.production.zel_production_performance_bootstrap_v1 --tick

  # 1) If bootstrap has exhausted/rejected its bounded admission candidate,
  # route to the next already source-ready economic family. This controller is
  # O(1), network-free and authority-free: it only reads the frozen factory and
  # bootstrap state and writes an acquisition receipt. Terminal families and
  # source-unbound families cannot enter the queue.
  "${PYTHON_BIN}" -m backend.production.zel_production_economic_edge_router_v1 --tick

  # 2) Refresh the active-alpha signal before building PAPER input.
  # Missing/non-executable authority is an O(1) HOLD: no BingX call and no
  # signal-file mutation. Only an already executable nonterminal authority is
  # allowed to reach a strict production signal producer.
  "${PYTHON_BIN}" -m backend.production.zel_production_alpha_signal_runner_v1

  # 3) Refresh authoritative PAPER input. Missing/non-executable alpha emits
  # NO_VALIDATED_ALPHA without touching BingX or inventing price/qty.
  # Active alpha uses strict BingX-native freshness + canonical Risk/Sizing.
  "${PYTHON_BIN}" -m backend.production.zel_production_paper_source_adapter_v1

  # 4) Execute exactly one bounded PAPER cycle under the existing single-flight,
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

  # 5) Advance cumulative improvement after the cycle receipt is durable.
  # With no incumbent/evidence this is an O(1) HOLD. With valid evidence it may
  # atomically promote/rollback CONFIG_ONLY PAPER authority. It never edits
  # source code and never submits an exchange order.
  "${PYTHON_BIN}" -m backend.production.zel_production_improvement_controller_v1 --tick

  sleep "${INTERVAL_S}"
done
