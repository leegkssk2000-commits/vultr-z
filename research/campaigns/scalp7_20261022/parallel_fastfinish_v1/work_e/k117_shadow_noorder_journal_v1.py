"""Tiny fail-closed K117 development-observation journal.

One writer lock belongs to the caller. This module performs ZERO exchange calls.
Its receipts are explicitly NOT formal PREAUTO/G4/G5 or actual broker fills.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "k117.price_only.noorder_checkpoint.v1"


def hash_body(body: dict[str, Any]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def next_open_eligibility(
    *, expected_open_ms: int, decision_ts_ms: int, price_received_at_ms: int | None
) -> str:
    """Never treat a late quote as the *historical* exact next open."""
    if price_received_at_ms is None:
        return "HOLD_NO_ASOF_QUOTE"
    if decision_ts_ms > expected_open_ms or price_received_at_ms > expected_open_ms:
        return "HOLD_LATE_NEXT_OPEN_NO_RETRO_FILL"
    if price_received_at_ms < expected_open_ms:
        return "HOLD_PREOPEN_PRICE_NOT_OPEN_FILL"
    return "TIMING_POTENTIALLY_ELIGIBLE_REQUIRES_QUOTE_AND_COST_PROOF"


def read_checkpoint(path: Path, contract_sha: str, observer_sha: str) -> dict[str, Any]:
    data = json.loads((path / "STATE.json").read_bytes())
    claimed = data.pop("state_sha256", None)
    if not claimed or claimed != hash_body(data):
        raise ValueError("CHECKPOINT_SHA256_MISMATCH")
    if (
        data.get("schema") != SCHEMA
        or data.get("contract_sha256") != contract_sha
        or data.get("observer_source_sha256") != observer_sha
        or data.get("status", {}).get("formal_shadow_active") is not False
        or data.get("status", {}).get("formal_fresh_credit") is not False
        or data.get("status", {}).get("order_calls") != 0
        or data.get("status", {}).get("virtual_fills") != 0
        or data.get("adapter", {}).get("order_calls") != 0
        or data.get("adapter", {}).get("formal_fresh_credit") is not False
        or data.get("adapter", {}).get("trades")
        or data.get("adapter", {}).get("positions")
    ):
        raise ValueError("SHADOW_NO_ORDER_OR_CODE_BINDING_MISMATCH")
    return data


def commit_checkpoint(
    path: Path,
    status: dict[str, Any],
    adapter_state: dict[str, Any],
    contract_sha: str,
    observer_sha: str,
) -> str:
    # This observer never fabricates fills. A native pending signal remains
    # UNKNOWN until a legitimate next-open trade event is witnessed.
    if (
        status.get("order_calls") != 0
        or status.get("formal_shadow_active") is not False
        or status.get("formal_fresh_credit") is not False
        or status.get("virtual_fills") != 0
        or adapter_state.get("order_calls") != 0
        or adapter_state.get("formal_fresh_credit") is not False
        or adapter_state.get("positions")
        or adapter_state.get("trades")
    ):
        raise ValueError("FORBIDDEN_FORMAL_OR_UNPROVEN_VIRTUAL_FILL")
    body = {
        "schema": SCHEMA,
        "contract_sha256": contract_sha,
        "observer_source_sha256": observer_sha,
        "status": status,
        "adapter": adapter_state,
    }
    prior = path / "STATE.json"
    if prior.exists():
        old = read_checkpoint(path, contract_sha, observer_sha)
        a, b = old["status"], status
        if (
            old["adapter"]["events"]
            != adapter_state["events"][: len(old["adapter"]["events"])]
            or a["decisions"] != b["decisions"][: len(a["decisions"])]
            or a["signals"] != b["signals"][: len(a["signals"])]
            or a["started_at_ms"] != b["started_at_ms"]
            or b["next_expected_complete_close_ms"]
            < a["next_expected_complete_close_ms"]
        ):
            raise ValueError("OBSERVATION_LEDGER_REWRITTEN_OR_CLOCK_BACKWARDS")
    digest = hash_body(body)
    temporary = path / "STATE.tmp"
    temporary.write_text(
        json.dumps({**body, "state_sha256": digest}, sort_keys=True, allow_nan=False)
        + "\n"
    )
    os.replace(temporary, prior)
    return digest
