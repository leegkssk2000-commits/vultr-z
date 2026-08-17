from __future__ import annotations

from pathlib import Path

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as generic

ROOT = Path(__file__).resolve().parents[3]
generic.v1.LEDGER_PATH = ROOT / "backend/research/rebuild/a1_improvement_session_bias_v2_ledger.json"
generic.v1.INVENTORY_PATH = ROOT / "backend/research/rebuild/a1_improvement_session_bias_v2_inventory.json"


if __name__ == "__main__":
    generic.v1.main()
