#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_terminal_shadow(
    *,
    strategy_id: str,
    policy_path: Path,
    fresh_boundary_utc: str,
    out: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run terminal replay from a fresh boundary in temporary SSOT views only.

    Historical bars before the boundary remain available to policy warmup, but
    the evaluator no longer iterates/settles pre-boundary signals. The real
    canonical inventory and disposition ledger are byte-for-byte protected.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    real_ledger_sha_before = _sha(LEDGER)
    real_inventory_sha_before = _sha(INVENTORY)
    inventory = _read(INVENTORY)
    ledger = _read(LEDGER)
    strategy = (ledger.get("strategies") or {}).get(strategy_id)
    if not isinstance(strategy, dict):
        raise RuntimeError(f"UNKNOWN_STRATEGY:{strategy_id}")
    if strategy_id not in (inventory.get("strategies") or {}):
        raise RuntimeError(f"INVENTORY_STRATEGY_MISSING:{strategy_id}")
    original_boundary = str(strategy.get("prospective_boundary_utc") or "")
    if not original_boundary:
        raise RuntimeError("ORIGINAL_PROSPECTIVE_BOUNDARY_MISSING")

    shadow_inventory = json.loads(json.dumps(inventory))
    shadow_inventory["strategies"][strategy_id]["policy_owner"] = str(policy_path.relative_to(ROOT))
    shadow_ledger = json.loads(json.dumps(ledger))
    shadow_ledger["strategies"][strategy_id]["prospective_boundary_utc"] = fresh_boundary_utc

    with tempfile.TemporaryDirectory(prefix=f"{strategy_id}_fresh_boundary_shadow_") as td:
        td_path = Path(td)
        inv_path = td_path / "inventory.json"
        ledger_path = td_path / "ledger.json"
        inv_path.write_text(json.dumps(shadow_inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        ledger_path.write_text(json.dumps(shadow_ledger, sort_keys=True, indent=2) + "\n", encoding="utf-8")

        old_inventory = exact.v1.INVENTORY_PATH
        old_canonical = exact.CANONICAL_LEDGER_PATH
        old_argv = sys.argv[:]
        try:
            exact.v1.INVENTORY_PATH = inv_path
            exact.CANONICAL_LEDGER_PATH = ledger_path
            sys.argv = [old_argv[0], "--strategy-id", strategy_id, "--out", str(out), "--terminal-replay"]
            exact.main()
        finally:
            exact.v1.INVENTORY_PATH = old_inventory
            exact.CANONICAL_LEDGER_PATH = old_canonical
            sys.argv = old_argv

    if _sha(LEDGER) != real_ledger_sha_before:
        raise RuntimeError("REAL_CANONICAL_LEDGER_MUTATED")
    if _sha(INVENTORY) != real_inventory_sha_before:
        raise RuntimeError("REAL_CANONICAL_INVENTORY_MUTATED")
    receipt = _read(out)
    if str(receipt.get("boundary_utc") or "") != fresh_boundary_utc:
        raise RuntimeError("FRESH_BOUNDARY_NOT_APPLIED")
    replay = receipt.get("terminal_replay") if isinstance(receipt.get("terminal_replay"), dict) else {}
    if replay.get("canonical_ledger_mutated") is not False:
        raise RuntimeError("SHADOW_LEDGER_MUTATION_GUARD_FAILED")
    meta = {
        "strategy_id": strategy_id,
        "original_canonical_boundary_utc": original_boundary,
        "shadow_evaluation_boundary_utc": fresh_boundary_utc,
        "preboundary_bars_available_for_warmup": True,
        "preboundary_signals_iterated": False,
        "real_canonical_ledger_mutated": False,
        "real_canonical_inventory_mutated": False,
        "real_canonical_ledger_sha256": real_ledger_sha_before,
        "real_canonical_inventory_sha256": real_inventory_sha_before,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED"
    }
    return receipt, meta


def self_test() -> int:
    assert LEDGER.name == "a1_exact25_disposition_ledger_v1.json"
    assert INVENTORY.name == "strategy25_structural_inventory_v2.json"
    print("PASS_A1_FRESH_BOUNDARY_SHADOW_REPLAY_V1_SELF_TEST")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
