from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def patched(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    patcher = load(root / "tools/r7a4d2_entry_chain_minimal_patch.py", "a4d2_patcher")
    source = (root / "tools/r7a4d_historical_simulation_3600.py").read_text()
    result = patcher.apply_patch(source)
    compile(result, "patched_runner.py", "exec")
    path = tmp_path / "patched_runner.py"
    path.write_text(result)
    return load(path, "a4d2_runner")


def frame() -> pd.DataFrame:
    rows = []
    for i in range(8):
        p = 100.0 + i
        rows.append({"timestamp": 1_700_000_000 + i * 300, "open": p, "high": p + .4,
                     "low": p - .4, "close": p + .1, "volume": 10.0,
                     "symbol": "BTCUSDT", "timeframe": "5m",
                     "__timestamp": 1_700_000_000 + i * 300})
    return pd.DataFrame(rows)


CONTRACT = {"minimum_call_bars": 1, "maximum_position_qty": 1.0,
            "allowed_intents": ["hold", "enter_long", "exit_long", "reduce", "block"]}
COST = {"fee_bps_per_side": 0.0, "slippage_bps_per_side": 0.0,
        "latency_bars": 0, "funding_bps_per_8h": 0.0}
PERTURB = {"additional_entry_delay_bars": 0, "additional_exit_delay_bars": 0}
SCENARIO = {"scenario_id": "test", "strategy_id": "break_and_continue",
            "segment_id": "segment", "regime": "trend_up", "fold": 0,
            "cost_profile": "cost_profile_0", "perturbation": "perturbation_0"}


def decision(action: str, why: str, size: float = .2):
    legacy = {"side": "long", "action": action, "size": size, "entry": 103.0,
              "sl": 90.0, "tp": 120.0, "why": why}
    return {"ok": True, "intent": "enter_long", "target_qty": size,
            "reason": why, "payload": {"legacy_signal": legacy}}


class EnterThenAdd:
    def decide(self, ctx):
        p = ctx.signal.payload
        if not p["position_side"]:
            return decision("enter", "bnc_long", .25)
        if int(p["add_count"]) == 0:
            return decision("add", "bnc_long_add", .15)
        return {"ok": True, "intent": "hold", "payload": {}}


class AddOnly:
    def decide(self, ctx):
        return decision("add", "bnc_long_add", .15)


def test_preroll_window(tmp_path: Path) -> None:
    mod = patched(tmp_path)
    sample = mod.select_segment_with_preroll(frame(), 2, 8, 6, 2)
    assert len(sample) == 8
    assert sample.attrs == {"evaluation_start_index": 2, "indicator_preroll_bars": 2,
                            "evaluation_bars": 6}


def test_valid_entry_lineage_allows_add(tmp_path: Path) -> None:
    mod = patched(tmp_path)
    sample = mod.select_segment_with_preroll(frame(), 2, 8, 6, 2)
    row = mod.simulate_scenario(SCENARIO, sample, EnterThenAdd, "decide", COST, PERTURB, CONTRACT)
    assert (row["bars"], row["context_bars"], row["trade_count"]) == (6, 8, 1)
    assert (row["enter_signal_count"], row["add_signal_count"], row["orphan_add_block_count"]) == (1, 1, 0)
    assert row["trade_sample"][0]["entry_event"] == "bnc_long"


def test_orphan_add_fails_closed(tmp_path: Path) -> None:
    mod = patched(tmp_path)
    sample = mod.select_segment_with_preroll(frame(), 2, 8, 6, 2)
    row = mod.simulate_scenario(SCENARIO, sample, AddOnly, "decide", COST, PERTURB, CONTRACT)
    assert row["trade_count"] == 0
    assert row["orphan_add_block_count"] > 0


def test_foreign_lineage_rejected(tmp_path: Path) -> None:
    mod = patched(tmp_path)
    assert mod.lineage_allows_add("rbreaker_like", {"entry_strategy_id": "rbreaker_like",
                                                     "entry_event": "rbr_reversal_long"})
    assert not mod.lineage_allows_add("rbreaker_like", {"entry_strategy_id": "other",
                                                         "entry_event": "rbr_reversal_long"})
