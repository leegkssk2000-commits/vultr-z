from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from backend.tools import strategy11_unattended_improvement_replay_v2 as replay


def snapshot(strategy_id: str, trades: int) -> dict:
    config = {
        "strategy_id": strategy_id,
        "candidate_id": "NO_CHANGE_CONTROL",
        "axis": "NO_CHANGE",
        "kind": "CONTROL",
        "gate": {"gate_id": "BASE", "family": "fixture", "required": [], "forbidden": [], "description": ""},
        "exit": {"exit_id": "ORIG", "stop_mult": 1.0, "target_mult": 1.0},
        "surgery": None,
        "symbols": ["BTCUSDT", "ETHUSDT"],
    }
    return {
        "trade_count": trades,
        "win_rate_pct": 50.0,
        "net_return_pct_sum": float(trades) / 10.0,
        "net_profit_factor": 1.2,
        "payoff_ratio": 1.1,
        "max_drawdown_pct": 0.5,
        "positive_fresh_windows_pct": 66.6666667,
        "candidate_config_sha256": f"sha-{strategy_id}",
        "candidate_config": config,
    }


def main() -> int:
    ids = [f"strategy_{index:02d}" for index in range(25)]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "input/plan").mkdir(parents=True)
        (root / "out/base").mkdir(parents=True)
        ledger = {
            "rows": [
                {"strategy_id": strategy_id, "incumbent_snapshot": snapshot(strategy_id, index + 1)}
                for index, strategy_id in enumerate(ids)
            ]
        }
        active = ids[:3]
        final = {
            "rows": [
                {
                    "strategy_id": strategy_id,
                    "state": "PASS_REPLAY",
                    "variants": [{"variant_id": "NO_CHANGE_CONTROL", **snapshot(strategy_id, index + 1)}],
                }
                for index, strategy_id in enumerate(active)
            ]
        }
        (root / "input/plan/search_ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
        (root / "out/base/final.json").write_text(json.dumps(final), encoding="utf-8")
        previous = Path.cwd()
        os.chdir(root)
        try:
            replay.carry_all_controls(["--mode", "aggregate", "--out", "out/base"])
        finally:
            os.chdir(previous)
        carried = json.loads((root / "out/base/final.json").read_text(encoding="utf-8"))
        assert carried["strategy_count"] == 25
        assert carried["active_replayed_strategy_count"] == 3
        assert carried["carried_inactive_control_count"] == 22
        assert {row["strategy_id"] for row in carried["rows"]} == set(ids)
        assert sum(row.get("state") == "CARRIED_INACTIVE_CONTROL" for row in carried["rows"]) == 22
    print(json.dumps({"state": "PASS_UNATTENDED_V2_CARRY_ALL_25_CONTROLS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
