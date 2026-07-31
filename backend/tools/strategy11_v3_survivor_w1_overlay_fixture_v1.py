from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("s11_overlay_fixture_strategy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_frame() -> pd.DataFrame:
    rows = []
    value = 100.0
    for index in range(160):
        value += 0.22 + ((index % 11) - 5) * 0.015
        open_ = value - 0.08
        rows.append({
            "timestamp_ms": 1_700_000_000_000 + index * 900_000,
            "open": open_,
            "high": value + 0.32,
            "low": open_ - 0.28,
            "close": value,
            "volume": 1000.0 + index,
        })
    return pd.DataFrame(rows)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    contract = json.loads((root / "backend/research/strategy11_v3_survivor_w1_overlay_v1.json").read_text())
    candidate = contract["candidate"]
    assert candidate["strategy_id"] == "trend_ma_macd"
    assert candidate["variant_id"] == "INT3_MAX_CHASE_DIST_ATR_RELAX"
    assert candidate["field"] == "max_chase_dist_atr"
    assert candidate["base_value"] == 1.6
    assert candidate["mutation_value"] == 1.84
    assert candidate["candidate_spec_sha256"] == "5776af1a7bc8314e798b7325b041bf0c94e68898ea131251ed5484825c35ed0e"
    safety = contract["safety"]
    assert safety == {
        "research_only": True,
        "promotion_authority": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_bound": False,
        "native_w1_chain_modified": False,
    }
    strategy_path = root / "compute/backend/strategies/trend_ma_macd.py"
    module = load_module(strategy_path)
    base = module.TrendMaMacdConfig()
    changed = dataclasses.replace(base, max_chase_dist_atr=1.84)
    assert base.max_chase_dist_atr == 1.6
    assert changed.max_chase_dist_atr == 1.84
    frame = synthetic_frame()
    state = {"position_side": "", "position_qty": 0.0, "avg_entry": 0.0, "add_count": 0, "last_add_price": 0.0}
    control_a = module.strategy(frame, state=state, risk_action="hold", config=base)
    control_b = module.strategy(frame, state=state, risk_action="hold", config=base)
    candidate_a = module.strategy(frame, state=state, risk_action="hold", config=changed)
    candidate_b = module.strategy(frame, state=state, risk_action="hold", config=changed)
    assert control_a == control_b
    assert candidate_a == candidate_b
    assert module.TrendMaMacdConfig().max_chase_dist_atr == 1.6
    assert candidate_a["indicators"].get("dist_from_fast_atr") == control_a["indicators"].get("dist_from_fast_atr")
    print("PASS_V3_SURVIVOR_OVERLAY_CONTRACT_CONFIG_AND_DETERMINISM")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
