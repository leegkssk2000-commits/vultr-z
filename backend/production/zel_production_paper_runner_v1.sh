#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
INTERVAL_S="${ZEL_PRODUCTION_PAPER_INTERVAL_S:-5}"
MAX_FAILURES="${ZEL_PRODUCTION_PAPER_MAX_CONSECUTIVE_FAILURES:-3}"

# The trading/data path stays on the 5-second cadence.  The survivor/evidence
# chain below is control-plane work: it is deterministic for unchanged inputs,
# but several stages stamp updated_at_ms and therefore used to rewrite ledger
# state every loop.  Keep an in-memory content fingerprint so that chain runs
# on boot, on a real upstream/output change, or when an output is removed.
# Nothing is persisted: every service restart necessarily runs the chain once.
cold_source_fp=""
cold_output_fp=""

cold_pipeline_fingerprints() {
  "${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import hashlib
from pathlib import Path

SOURCE_PATHS = (
    Path("/home/z/z/ledger/production_family_paper_canary_result_v1.json"),
    Path("/home/z/z/ledger/production_incumbent_registry_v1.json"),
    Path("/home/z/z/ledger/production_family_paper_canary_runner_state_v1.json"),
    Path("/home/z/z/ledger/production_survivor_quarantine_v1.json"),
    Path("/home/z/z/ledger/production_alpha_authority_v1.json"),
)
OUTPUT_PATHS = (
    Path("/home/z/z/ledger/production_family_paper_evidence_producer_state_v1.json"),
    Path("/home/z/z/ledger/production_family_paper_evidence_v1.json"),
    Path("/home/z/z/ledger/production_family_survivor_verifier_state_v1.json"),
    Path("/home/z/z/ledger/production_verified_survivor_intake_v1.json"),
    Path("/home/z/z/ledger/production_survivor_candidates_v1.json"),
    Path("/home/z/z/ledger/production_survivor_pool_v1.json"),
    Path("/home/z/z/ledger/production_survivor_authority_activation_v1.json"),
)


def digest(paths: tuple[Path, ...]) -> str:
    h = hashlib.sha256()
    for path in paths:
        raw_path = str(path).encode("utf-8")
        h.update(len(raw_path).to_bytes(4, "big"))
        h.update(raw_path)
        if path.is_file():
            data = path.read_bytes()
            h.update(b"\x01")
            h.update(len(data).to_bytes(8, "big"))
            h.update(data)
        else:
            h.update(b"\x00")
    return h.hexdigest()


print(digest(SOURCE_PATHS), digest(OUTPUT_PATHS))
PY
}

run_cold_pipeline() {
  "${PYTHON_BIN}" -m backend.production.zel_production_family_paper_evidence_producer_v1
  "${PYTHON_BIN}" -m backend.production.zel_production_family_survivor_verifier_v1
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_catalog_v1
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_pool_v2
  "${PYTHON_BIN}" -m backend.production.zel_production_survivor_authority_activation_v2
}

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

  # Keep repair/recovery semantics hot.  This controller may restore authority
  # or queue state even when market evidence itself has not changed.
  "${PYTHON_BIN}" -m backend.production.zel_production_improvement_controller_v1 --tick

  read -r source_before output_before < <(cold_pipeline_fingerprints)
  if [[ -z "${cold_source_fp}" || -z "${cold_output_fp}" \
        || "${source_before}" != "${cold_source_fp}" \
        || "${output_before}" != "${cold_output_fp}" ]]; then
    run_cold_pipeline
    read -r source_after output_after < <(cold_pipeline_fingerprints)

    # If an upstream source changed while the chain was running, retain the
    # pre-run source fingerprint so the next 5-second iteration replays once.
    # This avoids accepting a race-stale downstream snapshot indefinitely.
    if [[ "${source_after}" == "${source_before}" ]]; then
      cold_source_fp="${source_after}"
    else
      cold_source_fp="${source_before}"
    fi
    cold_output_fp="${output_after}"
  fi

  sleep "${INTERVAL_S}"
done
