from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

ANATOMY_SCHEMA_VERSION = 1
REQUIRED_TRADE_FIELDS = (
    "symbol",
    "side",
    "entry_bar",
    "exit_bar",
    "hold_bars",
    "gross_return_pct",
    "round_trip_cost_pct",
    "net_return_pct",
    "mfe_pct",
    "mae_pct",
    "giveback_from_mfe_pct",
    "exit_reason",
    "entry_context",
)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else float(default)


def _profit_factor(values: Iterable[float]) -> float | None:
    materialized = [float(value) for value in values]
    gains = sum(value for value in materialized if value > 0)
    losses = abs(sum(value for value in materialized if value < 0))
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _group_stats(trades: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    gross = [_number(trade.get("gross_return_pct")) for trade in trades]
    net = [_number(trade.get("net_return_pct")) for trade in trades]
    costs = [_number(trade.get("round_trip_cost_pct")) for trade in trades]
    mfe = [_number(trade.get("mfe_pct")) for trade in trades]
    mae = [_number(trade.get("mae_pct")) for trade in trades]
    holds = [_number(trade.get("hold_bars")) for trade in trades]
    wins = sum(value > 0 for value in net)
    gross_sum = sum(gross)
    cost_sum = sum(costs)
    return {
        "trade_count": len(trades),
        "win_count": wins,
        "win_rate_pct": wins / len(trades) * 100.0 if trades else None,
        "gross_return_pct_sum": gross_sum,
        "round_trip_cost_pct_sum": cost_sum,
        "net_return_pct_sum": sum(net),
        "gross_profit_factor": _profit_factor(gross),
        "net_profit_factor": _profit_factor(net),
        "mean_gross_return_pct": _mean(gross),
        "mean_net_return_pct": _mean(net),
        "mean_mfe_pct": _mean(mfe),
        "mean_mae_pct": _mean(mae),
        "mean_hold_bars": _mean(holds),
        "cost_to_gross_edge_ratio": cost_sum / gross_sum if gross_sum > 0 else None,
    }


def _group(
    trades: Sequence[Mapping[str, Any]],
    key_name: str,
    resolver,
) -> List[Dict[str, Any]]:
    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        buckets[str(resolver(trade))].append(trade)
    rows = [{key_name: key, **_group_stats(items)} for key, items in buckets.items()]
    return sorted(rows, key=lambda row: (row["net_return_pct_sum"], -row["trade_count"], row[key_name]))


def _entry_context(trade: Mapping[str, Any]) -> Mapping[str, Any]:
    value = trade.get("entry_context")
    return value if isinstance(value, Mapping) else {}


def _validate_trade(trade: Mapping[str, Any], source: Path, index: int) -> None:
    missing = [field for field in REQUIRED_TRADE_FIELDS if field not in trade]
    if missing:
        raise ValueError(f"TRADE_ANATOMY_MISSING:{source.name}:{index}:{','.join(missing)}")
    if not isinstance(trade.get("entry_context"), Mapping):
        raise ValueError(f"ENTRY_CONTEXT_INVALID:{source.name}:{index}")
    if int(_number(trade.get("hold_bars"), -1)) < 1:
        raise ValueError(f"HOLD_BARS_INVALID:{source.name}:{index}")
    for field in (
        "gross_return_pct",
        "round_trip_cost_pct",
        "net_return_pct",
        "mfe_pct",
        "mae_pct",
        "giveback_from_mfe_pct",
    ):
        if not _finite(trade.get(field)):
            raise ValueError(f"TRADE_NUMBER_INVALID:{source.name}:{index}:{field}")
    expected_net = _number(trade["gross_return_pct"]) - _number(trade["round_trip_cost_pct"])
    if abs(expected_net - _number(trade["net_return_pct"])) > 1e-10:
        raise ValueError(f"NET_IDENTITY_MISMATCH:{source.name}:{index}")


def _load_replays(root: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    replay_files = sorted(path for path in root.glob("*_replay.json") if path.is_file())
    if not replay_files:
        raise FileNotFoundError(f"NO_REPLAY_JSON:{root}")
    replays: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []
    for path in replay_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("anatomy_schema_version", 0)) != ANATOMY_SCHEMA_VERSION:
            raise ValueError(f"ANATOMY_SCHEMA_MISSING:{path.name}")
        rows = payload.get("trades")
        if not isinstance(rows, list):
            raise ValueError(f"TRADES_NOT_LIST:{path.name}")
        if int(payload.get("trade_count", -1)) != len(rows):
            raise ValueError(f"TRADE_COUNT_MISMATCH:{path.name}")
        for index, trade in enumerate(rows):
            if not isinstance(trade, dict):
                raise ValueError(f"TRADE_NOT_OBJECT:{path.name}:{index}")
            _validate_trade(trade, path, index)
            trades.append(dict(trade))
        replays.append(payload)
    return replays, trades


def _baseline_invariants(root: Path, trades: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    summary_path = root / "summary_v1.json"
    if not summary_path.is_file():
        return {"status": "UNAVAILABLE", "reason": "SUMMARY_V1_NOT_FOUND"}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    aggregate = summary.get("aggregate") if isinstance(summary.get("aggregate"), Mapping) else {}
    actual = _group_stats(trades)
    checks = {
        "trade_count": {
            "expected": aggregate.get("trade_count"),
            "actual": actual["trade_count"],
            "match": int(aggregate.get("trade_count", -1)) == int(actual["trade_count"]),
        },
        "net_return_pct_sum": {
            "expected": aggregate.get("net_return_pct_sum"),
            "actual": actual["net_return_pct_sum"],
            "match": _finite(aggregate.get("net_return_pct_sum"))
            and abs(float(aggregate["net_return_pct_sum"]) - float(actual["net_return_pct_sum"])) <= 1e-9,
        },
        "net_profit_factor": {
            "expected": aggregate.get("net_profit_factor"),
            "actual": actual["net_profit_factor"],
            "match": (
                aggregate.get("net_profit_factor") is None
                and actual["net_profit_factor"] is None
            )
            or (
                _finite(aggregate.get("net_profit_factor"))
                and _finite(actual["net_profit_factor"])
                and abs(float(aggregate["net_profit_factor"]) - float(actual["net_profit_factor"])) <= 1e-9
            ),
        },
    }
    return {
        "status": "PASS" if all(bool(value["match"]) for value in checks.values()) else "FAIL",
        "checks": checks,
    }


def analyze(root: Path) -> Dict[str, Any]:
    replays, trades = _load_replays(root)
    overall = _group_stats(trades)

    gross_positive_net_negative = [
        trade for trade in trades
        if _number(trade["gross_return_pct"]) > 0 and _number(trade["net_return_pct"]) <= 0
    ]
    cost_exceeds_positive_gross = [
        trade for trade in trades
        if _number(trade["gross_return_pct"]) > 0
        and _number(trade["gross_return_pct"]) <= _number(trade["round_trip_cost_pct"])
    ]
    immediate_fail = [
        trade for trade in trades
        if int(_number(trade["hold_bars"])) <= 2 and _number(trade["net_return_pct"]) < 0
    ]
    same_bar_stop = [
        trade for trade in trades
        if int(_number(trade["hold_bars"])) == 1
        and str(trade["exit_reason"]) == "SUPERTREND_TRAILING_STOP"
    ]
    mfe_available_but_net_negative = [
        trade for trade in trades
        if _number(trade["mfe_pct"]) >= _number(trade["round_trip_cost_pct"])
        and _number(trade["net_return_pct"]) < 0
    ]
    invalid_initial_stop = [trade for trade in trades if trade.get("invalid_initial_stop") is True]

    cluster_buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        context = _entry_context(trade)
        key = "|".join(
            (
                str(trade.get("symbol", "UNKNOWN")),
                str(trade.get("side", "UNKNOWN")),
                str(context.get("trigger_signature", "UNRESOLVED")),
                str(context.get("confluence_signature", "UNRESOLVED")),
                str(trade.get("exit_reason", "UNKNOWN")),
            )
        )
        cluster_buckets[key].append(trade)
    loss_clusters = [
        {"cluster": key, **_group_stats(items)}
        for key, items in cluster_buckets.items()
    ]
    loss_clusters.sort(key=lambda row: (row["net_return_pct_sum"], -row["trade_count"], row["cluster"]))

    invariants = _baseline_invariants(root, trades)
    blockers: List[str] = []
    if invariants.get("status") == "FAIL":
        blockers.append("BASELINE_METRIC_INVARIANT_FAILED")
    if len({str(replay.get("symbol")) for replay in replays}) != len(replays):
        blockers.append("DUPLICATE_REPLAY_SYMBOL")

    state = (
        "PASS_R7A4D_INTEGRATED_SUPERTREND_TRADE_ANATOMY"
        if not blockers and trades
        else "HOLD_R7A4D_INTEGRATED_SUPERTREND_TRADE_ANATOMY"
    )
    return {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "anatomy_schema_version": ANATOMY_SCHEMA_VERSION,
        "source_directory": str(root),
        "replay_count": len(replays),
        "symbols": sorted(str(replay.get("symbol")) for replay in replays),
        "overall": overall,
        "failure_classes": {
            "gross_positive_net_negative": _group_stats(gross_positive_net_negative),
            "cost_exceeds_positive_gross": _group_stats(cost_exceeds_positive_gross),
            "immediate_fail_hold_le_2_bars": _group_stats(immediate_fail),
            "same_bar_supertrend_stop": _group_stats(same_bar_stop),
            "mfe_ge_roundtrip_cost_but_net_negative": _group_stats(mfe_available_but_net_negative),
            "invalid_initial_stop": _group_stats(invalid_initial_stop),
        },
        "decomposition": {
            "by_symbol": _group(trades, "symbol", lambda trade: trade.get("symbol", "UNKNOWN")),
            "by_side": _group(trades, "side", lambda trade: trade.get("side", "UNKNOWN")),
            "by_exit_reason": _group(trades, "exit_reason", lambda trade: trade.get("exit_reason", "UNKNOWN")),
            "by_trigger_signature": _group(
                trades,
                "trigger_signature",
                lambda trade: _entry_context(trade).get("trigger_signature", "UNRESOLVED"),
            ),
            "by_confirmation_signature": _group(
                trades,
                "confirmation_signature",
                lambda trade: _entry_context(trade).get("confirmation_signature", "UNRESOLVED"),
            ),
            "by_confluence_signature": _group(
                trades,
                "confluence_signature",
                lambda trade: _entry_context(trade).get("confluence_signature", "UNRESOLVED"),
            ),
        },
        "top_loss_clusters": loss_clusters[:15],
        "baseline_metric_invariants": invariants,
        "blockers": blockers,
        "performance_claim_allowed": False,
        "promotion_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": "SELECT_SINGLE_CAUSAL_REPAIR_FROM_TRADE_ANATOMY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only trade-level anatomy for integrated Supertrend pullback OOS")
    parser.add_argument(
        "--input-dir",
        default="/home/z/z/runtime/r7a4d_integrated_supertrend_bingx_real_oos_v1",
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(args.input_dir).resolve()
    result = analyze(root)
    output = Path(args.output).resolve() if args.output else root / "trade_anatomy_v1.json"
    _atomic_json(output, result)
    overall = result["overall"]
    failure = result["failure_classes"]
    top_cluster = result["top_loss_clusters"][0] if result["top_loss_clusters"] else None
    print(
        "\n".join(
            (
                f"STATE={result['state']}",
                f"REPLAY_COUNT={result['replay_count']}",
                f"TRADE_COUNT={overall['trade_count']}",
                f"GROSS_RETURN_PCT_SUM={overall['gross_return_pct_sum']:.9f}",
                f"ROUND_TRIP_COST_PCT_SUM={overall['round_trip_cost_pct_sum']:.9f}",
                f"NET_RETURN_PCT_SUM={overall['net_return_pct_sum']:.9f}",
                f"GROSS_PF={overall['gross_profit_factor']}",
                f"NET_PF={overall['net_profit_factor']}",
                f"COST_TO_GROSS_EDGE_RATIO={overall['cost_to_gross_edge_ratio']}",
                f"GROSS_POSITIVE_NET_NEGATIVE_COUNT={failure['gross_positive_net_negative']['trade_count']}",
                f"IMMEDIATE_FAIL_COUNT={failure['immediate_fail_hold_le_2_bars']['trade_count']}",
                f"SAME_BAR_STOP_COUNT={failure['same_bar_supertrend_stop']['trade_count']}",
                f"MFE_AVAILABLE_BUT_NET_NEGATIVE_COUNT={failure['mfe_ge_roundtrip_cost_but_net_negative']['trade_count']}",
                f"INVALID_INITIAL_STOP_COUNT={failure['invalid_initial_stop']['trade_count']}",
                f"TOP_LOSS_CLUSTER={json.dumps(top_cluster, ensure_ascii=False, sort_keys=True)}",
                f"BASELINE_INVARIANT_STATUS={result['baseline_metric_invariants'].get('status')}",
                f"OUTPUT={output}",
                f"BLOCKERS={json.dumps(result['blockers'])}",
                f"NEXT_STAGE={result['next_stage']}",
                f"RC={0 if result['state'].startswith('PASS') else 2}",
            )
        )
    )
    return 0 if result["state"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
