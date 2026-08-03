from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import zel_exact25_selected_indicator_screen_v1 as screen

VERSION = "ZEL_EXACT25_COST_FLOOR_SCREEN_V1"
SCHEMA = "zel.exact25.cost_floor_screen.receipt.v1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


class RiskDistanceOwner:
    def __init__(
        self,
        base: Any,
        producer: Any,
        strategy_id: str,
        symbol: str,
        interval: str,
        axis_id: str,
        config: Mapping[str, Any],
    ) -> None:
        self.base = base
        self.producer = producer
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.interval = interval
        self.axis_id = axis_id
        self.config = dict(config)
        self.owner_sha256 = stable_sha(
            {
                "base_owner_sha256": str(getattr(base, "owner_sha256", "")),
                "axis_id": axis_id,
                "config": self.config,
                "version": VERSION,
            }
        )
        self.valid_entry_count = 0
        self.blocked_entry_count = 0
        self.unknown_side_count = 0
        self.minimum_observed_risk_distance_pct: float | None = None
        self.maximum_observed_risk_distance_pct: float | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def strategy(
        self, current: Any, state: Any = None, risk_action: str = "hold"
    ) -> dict[str, Any]:
        result = self.base.strategy(
            current, state=state, risk_action=risk_action
        )
        if not isinstance(result, dict) or state is not None:
            return result
        current_price = float(current["close"].iloc[-1])
        if self.producer.valid_entry(result, current_price) is None:
            return result
        self.valid_entry_count += 1
        try:
            position = self.producer.make_position(
                self.strategy_id,
                str(getattr(self.base, "owner_sha256", "")),
                self.symbol,
                self.interval,
                result,
                current,
                1.0,
                0.0005,
                1.0,
            )
        except Exception:
            position = None
        if not isinstance(position, Mapping):
            self.unknown_side_count += 1
            return result
        entry_price = finite(position.get("entry_price"))
        qty = finite(position.get("original_qty")) or finite(position.get("qty"))
        risk = finite(position.get("initial_risk_usdt"))
        if entry_price is None or qty is None or risk is None or entry_price * qty <= 0:
            self.unknown_side_count += 1
            return result
        risk_distance_pct = risk / (entry_price * qty) * 100.0
        self.minimum_observed_risk_distance_pct = (
            risk_distance_pct
            if self.minimum_observed_risk_distance_pct is None
            else min(self.minimum_observed_risk_distance_pct, risk_distance_pct)
        )
        self.maximum_observed_risk_distance_pct = (
            risk_distance_pct
            if self.maximum_observed_risk_distance_pct is None
            else max(self.maximum_observed_risk_distance_pct, risk_distance_pct)
        )
        if risk_distance_pct >= float(self.config["minimum_risk_distance_pct"]):
            return result
        self.blocked_entry_count += 1
        return {
            "action": "hold",
            "reason": "research_cost_floor_min_risk_distance",
            "research_only": True,
        }


def payoff_metrics(engine: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = dict(engine.metrics(rows, "realized_R_including_funding_estimate"))
    values = [
        float(value)
        for row in rows
        if (value := finite(row.get("realized_R_including_funding_estimate")))
        is not None
    ]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss_abs = abs(sum(losses) / len(losses)) if losses else 0.0
    result.update(
        {
            "average_win_R": average_win,
            "average_loss_abs_R": average_loss_abs,
            "payoff_ratio": (
                average_win / average_loss_abs
                if average_loss_abs
                else (999.0 if average_win else 0.0)
            ),
        }
    )
    return result


def by_window(engine: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for window in ("1m_w1", "1m_w2", "1m_w3"):
        result[window] = payoff_metrics(
            engine, [row for row in rows if str(row.get("window_id")) == window]
        )
    result["all"] = payoff_metrics(engine, rows)
    return result


def gate(
    candidate: Mapping[str, Any],
    baseline_count: int,
    minimum_count: int,
    policy: Mapping[str, Any],
) -> tuple[bool, list[str], float]:
    count = int(candidate.get("sample_count") or 0)
    retention = count / baseline_count * 100.0 if baseline_count else 0.0
    blockers: list[str] = []
    if count < minimum_count:
        blockers.append("SAMPLE_BELOW_MIN")
    if retention < float(policy["minimum_retention_pct"]):
        blockers.append("RETENTION_BELOW_MIN")
    if float(candidate.get("net_R") or 0.0) <= float(policy["net_R_gt"]):
        blockers.append("NET_R_NOT_POSITIVE")
    if float(candidate.get("profit_factor") or 0.0) < float(
        policy["profit_factor_gte"]
    ):
        blockers.append("PF_BELOW_ONE")
    if float(candidate.get("expectancy_R") or 0.0) <= float(
        policy["expectancy_R_gt"]
    ):
        blockers.append("EXPECTANCY_NOT_POSITIVE")
    if float(candidate.get("payoff_ratio") or 0.0) < float(
        policy["payoff_ratio_gte"]
    ):
        blockers.append("PAYOFF_BELOW_ONE")
    return not blockers, blockers, retention


def run(
    policy: Mapping[str, Any],
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_root: Path,
) -> dict[str, Any]:
    strategy_id = str(policy["strategy_id"])
    engine = screen.load_module(
        engine_path, f"zel_cost_floor_engine_{os.getpid()}"
    )
    baseline_card, baseline_rows, baseline_meta = screen.run_replay(
        engine_path, source_root, data_root, strategy_id
    )
    immutable_rows = screen.read_terminal_rows(
        terminal_root / "trades.jsonl.gz", strategy_id
    )
    report = read_json(terminal_root / "report.json")
    terminal_card = next(
        row
        for row in report.get("scorecards", [])
        if isinstance(row, Mapping) and row.get("strategy_id") == strategy_id
    )
    baseline_metrics = baseline_card[
        "closed_metrics_including_funding_estimate"
    ]
    terminal_metrics = terminal_card[
        "closed_metrics_including_funding_estimate"
    ]
    parity = {
        "trade_count": len(baseline_rows) == len(immutable_rows),
        "economic_digest": screen.economic_digest(baseline_rows)
        == screen.economic_digest(immutable_rows),
        "net_R": abs(
            float(baseline_metrics.get("net_R") or 0.0)
            - float(terminal_metrics.get("net_R") or 0.0)
        )
        <= 1e-9,
        "profit_factor": abs(
            float(baseline_metrics.get("profit_factor") or 0.0)
            - float(terminal_metrics.get("profit_factor") or 0.0)
        )
        <= 1e-9,
        "max_drawdown_R": abs(
            float(baseline_metrics.get("max_drawdown_R") or 0.0)
            - float(terminal_metrics.get("max_drawdown_R") or 0.0)
        )
        <= 1e-9,
        "errors_zero": baseline_meta["error_count"] == 0,
        "censored_zero": baseline_meta["censored_open_count"] == 0,
    }
    baseline_windows = by_window(engine, baseline_rows)
    original_wrapper = screen.FilteredOwner
    screen.FilteredOwner = RiskDistanceOwner
    candidates = []
    try:
        for config in policy["candidate_configs"]:
            _, rows, meta = screen.run_replay(
                engine_path,
                source_root,
                data_root,
                strategy_id,
                str(policy["axis_id"]),
                config,
            )
            windows = by_window(engine, rows)
            w1_ok, w1_blockers, w1_retention = gate(
                windows["1m_w1"],
                int(baseline_windows["1m_w1"]["sample_count"] or 0),
                int(policy["positive_gate"]["minimum_w1_trade_count"]),
                policy["positive_gate"],
            )
            operational_ok = (
                meta["error_count"]
                <= int(policy["positive_gate"]["error_count_max"])
                and meta["censored_open_count"]
                <= int(policy["positive_gate"]["censored_open_count_max"])
                and meta["blocked_entry_count"] > 0
                and meta["unknown_side_count"] == 0
            )
            candidates.append(
                {
                    "config": dict(config),
                    "config_sha256": stable_sha(config),
                    "metrics": windows,
                    "counters": meta,
                    "economic_digest_sha256": screen.economic_digest(rows),
                    "w1_pass": w1_ok and operational_ok,
                    "w1_blockers": w1_blockers,
                    "w1_retention_pct": w1_retention,
                }
            )
    finally:
        screen.FilteredOwner = original_wrapper

    eligible = [row for row in candidates if row["w1_pass"]]
    selected = max(
        eligible,
        key=lambda row: (
            float(row["metrics"]["1m_w1"].get("net_R") or 0.0),
            float(row["metrics"]["1m_w1"].get("profit_factor") or 0.0),
            float(row["metrics"]["1m_w1"].get("payoff_ratio") or 0.0),
        ),
        default=None,
    )
    confirmation: dict[str, Any] = {}
    survivor = False
    if selected is not None:
        all_pass = True
        for window in ("1m_w2", "1m_w3"):
            passed, blockers, retention = gate(
                selected["metrics"][window],
                int(baseline_windows[window]["sample_count"] or 0),
                int(policy["positive_gate"]["minimum_confirmation_trade_count"]),
                policy["positive_gate"],
            )
            confirmation[window] = {
                "pass": passed,
                "blockers": blockers,
                "retention_pct": retention,
                "baseline": baseline_windows[window],
                "candidate": selected["metrics"][window],
            }
            all_pass = all_pass and passed
        overall_pass, overall_blockers, overall_retention = gate(
            selected["metrics"]["all"],
            int(baseline_windows["all"]["sample_count"] or 0),
            int(policy["positive_gate"]["minimum_confirmation_trade_count"]),
            policy["positive_gate"],
        )
        confirmation["all"] = {
            "pass": overall_pass,
            "blockers": overall_blockers,
            "retention_pct": overall_retention,
            "baseline": baseline_windows["all"],
            "candidate": selected["metrics"]["all"],
        }
        all_pass = all_pass and overall_pass
        survivor = all(parity.values()) and all_pass

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_COST_FLOOR_SCREEN_COMPLETE",
        "strategy_id": strategy_id,
        "axis_id": policy["axis_id"],
        "parent_route": policy["parent_route"],
        "baseline_parity": parity,
        "baseline": baseline_windows,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_config": selected["config"] if selected else None,
        "selected_config_sha256": (
            selected["config_sha256"] if selected else None
        ),
        "confirmation": confirmation,
        "survivor": survivor,
        "survivor_state": (
            "PASS_POSITIVE_W1_W2_W3_COST_FLOOR_SURVIVOR"
            if survivor
            else "HOLD_NO_POSITIVE_COST_FLOOR_SURVIVOR"
        ),
        "entry_time_information_only": True,
        "future_MFE_MAE_used": False,
        "raw_trade_rows_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "SEAL_RESEARCH_HOLDBACK_AND_INTERACTION_TEST"
            if survivor
            else "ADVANCE_NEXT_COST_GEOMETRY_AXIS_OR_STRATEGY"
        ),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    assert stable_sha({"a": 1}) == stable_sha({"a": 1})
    sample = {
        "sample_count": 30,
        "net_R": 3.0,
        "profit_factor": 1.2,
        "expectancy_R": 0.1,
        "payoff_ratio": 1.1,
    }
    passed, blockers, retention = gate(
        sample,
        40,
        20,
        {
            "minimum_retention_pct": 60.0,
            "net_R_gt": 0.0,
            "profit_factor_gte": 1.0,
            "expectancy_R_gt": 0.0,
            "payoff_ratio_gte": 1.0,
        },
    )
    assert passed and not blockers and retention == 75.0
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.policy,
        args.engine,
        args.source_root,
        args.data_root,
        args.terminal_root,
    )
    if any(value is None for value in required):
        parser.error("policy, engine, source-root, data-root and terminal-root required")
    receipt = run(
        read_json(args.policy),
        args.engine.resolve(),
        args.source_root.resolve(),
        args.data_root.resolve(),
        args.terminal_root.resolve(),
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
