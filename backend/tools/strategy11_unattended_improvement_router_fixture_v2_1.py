from __future__ import annotations

import json
import tempfile
from pathlib import Path

from backend.tools import strategy11_unattended_improvement_fixture_v2 as fixture
from backend.tools import strategy11_unattended_improvement_router_v2_1 as router
from backend.tools import strategy11_unattended_improvement_v2 as v2


def authority() -> dict:
    return {
        "strategy_id": "alpha_combo",
        "route": "ALPHA_W1_MULTIOBJECTIVE_CONFIRMATION",
        "source_pr": 249,
        "source_head_sha": "7" * 40,
        "source_run_id": 30345463070,
        "source_artifact_id": 8683273561,
        "same_dataset_generation_budget_exhausted": True,
        "active_candidate_queue": ["TIME54", "TIME60"],
        "payoff_reference": "STOP065_PROFIT_CONTROL",
        "controls": {
            "TIME54": {
                "candidate_config_sha256": "a" * 64,
                "trade_count": 40,
                "win_rate_pct": 57.5,
                "net_return_pct_sum": 21.0965578658,
                "net_profit_factor": 4.4221375568,
                "payoff_ratio": 3.2685364550,
                "max_drawdown_pct": 1.5011034128,
                "positive_fresh_windows_pct": 100.0,
                "exit": {
                    "exit_id": "RR150_STOP065_TIME54_MULTIOBJ",
                    "stop_mult": 0.65,
                    "target_mult": 1.5,
                    "breakeven_r": None,
                    "partial_r": None,
                    "partial_fraction": 0.0,
                    "runner_target_r": None,
                    "trail_activate_r": None,
                    "trail_atr_mult": None,
                    "time_stop_bars": 54,
                },
            },
            "TIME60": {"candidate_config_sha256": "b" * 64},
            "STOP065_PROFIT_CONTROL": {"candidate_config_sha256": "c" * 64},
        },
        **v2.SAFETY,
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        policy = fixture.policy()
        catalog = fixture.catalog()
        controls = []
        for strategy_id in v2.STRATEGIES:
            trades = 30 if strategy_id == "alpha_combo" else 6
            controls.append({"strategy_id": strategy_id, "variants": [fixture.control(strategy_id, trades)]})
        for name, value in (
            ("policy.json", policy),
            ("catalog.json", catalog),
            ("baseline.json", {"rows": controls}),
            ("authority.json", authority()),
        ):
            (root / name).write_text(json.dumps(value), encoding="utf-8")
        args = type("Args", (), {
            "policy": str(root / "policy.json"),
            "catalog": str(root / "catalog.json"),
            "baseline_final": str(root / "baseline.json"),
            "alpha_authority": str(root / "authority.json"),
            "previous_ledger": None,
            "now_utc": "2026-07-30T12:00:00Z",
            "out": str(root / "out"),
        })()
        assert router.main.__module__
        router.validate_authority(authority())
        delegate = type("Delegate", (), {
            "policy": args.policy,
            "catalog": args.catalog,
            "baseline_final": args.baseline_final,
            "previous_ledger": None,
            "now_utc": args.now_utc,
            "out": args.out,
        })()
        assert v2.build_plan(delegate) == 0
        router.route_alpha(root / "out", authority())
        plan = json.loads((root / "out/plan.json").read_text())
        ledger = json.loads((root / "out/search_ledger.json").read_text())
        assert "alpha_combo" not in plan["active_strategy_ids"]
        assert all(row["strategy_id"] != "alpha_combo" for row in plan["rows"])
        assert plan["special_routes"][0]["route"] == "ALPHA_W1_MULTIOBJECTIVE_CONFIRMATION"
        alpha = next(row for row in ledger["rows"] if row["strategy_id"] == "alpha_combo")
        assert alpha["incumbent_snapshot"]["trade_count"] == 40
        assert alpha["incumbent_snapshot"]["candidate_config"]["exit"]["time_stop_bars"] == 54
        assert alpha["same_dataset_generation_budget_exhausted"] is True
        assert alpha["requires_w1_fresh_non_overlap"] is True
        assert alpha["requires_new_sealed_holdback"] is True
        assert plan["promotion_authority"] is False
        assert plan["execution_allowed"] is False
        assert plan["order_authority"] == "BLOCKED"
    print(json.dumps({"state": "PASS_ALPHA_AUTHORITY_ROUTE_V2_1"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
