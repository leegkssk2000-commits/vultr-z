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

  # 1) Resolve the current deterministic Explore state first. Existing verified
  # families always have priority; terminal/source-unbound families cannot be
  # queued and no AI proposal is allowed to override them.
  "${PYTHON_BIN}" -m backend.production.zel_production_economic_edge_router_v1 --tick

  # 2) Only when the deterministic catalog is exhausted, ask the proposal-only
  # AI layer for at most two causal economic hypotheses. The AI receives no raw
  # trades/private code/account data/credentials and has zero selection,
  # promotion, execution, LIVE, order or source-code-mutation authority.
  # Identical Explore contexts reuse the durable proposal receipt; failed API
  # calls are cooldown-HOLD and do not stop the PAPER daemon.
  "${PYTHON_BIN}" -m backend.production.zel_production_ai_proposal_layer_v1 --tick

  # 3) Re-run the O(1) deterministic router in the same cycle so a newly written
  # AI proposal is source-gated immediately instead of waiting for the next
  # daemon interval. Only source-ready proposals may enter a bounded admission
  # queue; source-unbound proposals remain HOLD.
  "${PYTHON_BIN}" -m backend.production.zel_production_economic_edge_router_v1 --tick

  # 4) Refresh the active-alpha signal before building PAPER input.
  # Missing/non-executable authority is an O(1) HOLD: no BingX call and no
  # signal-file mutation. Only an already executable nonterminal authority is
  # allowed to reach a strict production signal producer.
  "${PYTHON_BIN}" -m backend.production.zel_production_alpha_signal_runner_v1

  # 5) Refresh authoritative PAPER input. Missing/non-executable alpha emits
  # NO_VALIDATED_ALPHA without touching BingX or inventing price/qty.
  # Active alpha uses strict BingX-native freshness + canonical Risk/Sizing.
  "${PYTHON_BIN}" -m backend.production.zel_production_paper_source_adapter_v1

  # 6) Execute exactly one bounded PAPER cycle under the existing single-flight,
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

  # 7) Advance cumulative Exploit improvement after the cycle receipt is durable.
  # With no incumbent/evidence this is an O(1) HOLD. With valid evidence it may
  # atomically promote/rollback CONFIG_ONLY PAPER authority. It never edits
  # source code and never submits an exchange order.
  "${PYTHON_BIN}" -m backend.production.zel_production_improvement_controller_v1 --tick

  # 8) Rebuild the distinct-family survivor portfolio after any improvement
  # state transition. The pool never creates a survivor and never grants trade
  # authority: it only ranks already verified family survivors into Top3 ACTIVE
  # + Top2 RESERVE and writes a change receipt for notification/rotation logic.
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_pool_v1

  sleep "${INTERVAL_S}"
done
