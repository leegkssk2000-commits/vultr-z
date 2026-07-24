from __future__ import annotations

import argparse
import json
import math
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_entry_origin_anatomy as anatomy
import r7a4d_integrated_supertrend_linkusdt_single_loss_cluster_oos as survivor_filter
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as shared
import r7a4d_integrated_supertrend_survivor_dema_gate_and_loss_surgery_audit as surgery

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_survivor_dema_second_nonoverlap_oos_v1"
FIRST_SUMMARY_DIRNAME = surgery.OUTPUT_DIRNAME
FIRST_BASELINE_DIRNAME = surgery.BASELINE_DIRNAME
SECOND_FOLD_SURVIVOR = "BINGX_REAL_OOS_PRECEDING_WINDOW_FROZEN_SURVIVOR"
SECOND_FOLD_CANDIDATE = "BINGX_REAL_OOS_PRECEDING_WINDOW_FROZEN_SURVIVOR_DEMA_GATE"


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON_NOT_FOUND:{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return value


def _parsed_timestamp_ms(series: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(series, utc=True, errors="raise")
    return timestamps.map(
        lambda value: int(pd.Timestamp(value).value // 1_000_000)
    ).astype("int64")


def _window_contract(path: Path) -> Dict[str, int]:
    if not path.is_file():
        raise FileNotFoundError(f"FIRST_WINDOW_CSV_NOT_FOUND:{path}")
    header = pd.read_csv(path, nrows=0)
    usecols = [column for column in ("timestamp_ms", "timestamp") if column in header.columns]
    if not usecols:
        raise ValueError(f"FIRST_WINDOW_TIMESTAMP_COLUMN_MISSING:{path}")
    frame = pd.read_csv(path, usecols=usecols)
    if frame.empty:
        raise ValueError(f"FIRST_WINDOW_EMPTY:{path}")

    if "timestamp_ms" in frame.columns:
        values = pd.to_numeric(frame["timestamp_ms"], errors="raise").astype("int64")
    else:
        values = _parsed_timestamp_ms(frame["timestamp"])

    if values.duplicated().any():
        duplicate = int(values[values.duplicated()].iloc[0])
        raise ValueError(f"FIRST_WINDOW_DUPLICATE_TIMESTAMP:{path}:{duplicate}")
    deltas = values.diff().dropna().astype("int64")
    bad = deltas[deltas != source.INTERVAL_MS]
    if not bad.empty:
        index = int(bad.index[0])
        raise ValueError(
            "FIRST_WINDOW_GAP_OR_WRONG_INTERVAL:"
            f"{path}:row={index}:prev_ms={int(values.iloc[index - 1])}:"
            f"current_ms={int(values.iloc[index])}:delta_ms={int(bad.iloc[0])}:"
            f"expected_ms={source.INTERVAL_MS}"
        )
    if "timestamp_ms" in frame.columns and "timestamp" in frame.columns:
        parsed = _parsed_timestamp_ms(frame["timestamp"])
        mismatch = parsed != values
        if mismatch.any():
            index = int(mismatch[mismatch].index[0])
            raise ValueError(
                "FIRST_WINDOW_TIMESTAMP_PARITY_MISMATCH:"
                f"{path}:row={index}:timestamp_ms={int(values.iloc[index])}:"
                f"parsed_timestamp_ms={int(parsed.iloc[index])}"
            )

    rows = int(len(values))
    start_ms = int(values.iloc[0])
    end_ms = int(values.iloc[-1])
    calculated_rows = ((end_ms - start_ms) // source.INTERVAL_MS) + 1
    if calculated_rows != rows:
        raise ValueError(f"FIRST_WINDOW_ROW_CONTRACT:{path}:{calculated_rows}!={rows}")
    print(
        "FIRST_WINDOW_CONTRACT_PASS"
        f"|symbol_file={path.name}|rows={rows}|start_ms={start_ms}|"
        f"end_ms={end_ms}|interval_ms={source.INTERVAL_MS}"
    )
    return {"rows": rows, "start_ms": start_ms, "end_ms": end_ms}


def _payload_rows(payload: Mapping[str, Any]) -> List[Any]:
    data: Any = payload.get("data")
    if isinstance(data, dict):
        data = next(
            (
                data[key]
                for key in ("data", "rows", "klines", "list")
                if isinstance(data.get(key), list)
            ),
            [],
        )
    return data if isinstance(data, list) else []


def _fetch_exact_window(
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
    expected_rows: int,
) -> Tuple[pd.DataFrame, str, int]:
    if end_ms < start_ms:
        raise ValueError("WINDOW_REVERSED")
    calculated_rows = ((end_ms - start_ms) // source.INTERVAL_MS) + 1
    if calculated_rows != expected_rows:
        raise ValueError(f"WINDOW_ROW_CONTRACT:{calculated_rows}!={expected_rows}")

    request_start = start_ms - source.INTERVAL_MS
    request_end = end_ms + source.INTERVAL_MS
    max_requests = max(
        8,
        math.ceil((expected_rows + 2) / max(source.REQUEST_LIMIT - 1, 1)) + 4,
    )
    errors: List[str] = []

    for endpoint in source.ENDPOINTS:
        try:
            found: Dict[int, Tuple[int, float, float, float, float, float]] = {}
            cursor = request_start
            request_count = 0
            while cursor <= request_end and request_count < max_requests:
                window_end = min(
                    request_end,
                    cursor + (source.REQUEST_LIMIT - 1) * source.INTERVAL_MS,
                )
                query = urllib.parse.urlencode(
                    {
                        "symbol": symbol[:-4] + "-USDT",
                        "interval": source.INTERVAL,
                        "limit": source.REQUEST_LIMIT,
                        "startTime": cursor,
                        "endTime": window_end,
                    }
                )
                payload = source.request_json(endpoint + "?" + query)
                if payload.get("code") not in (None, 0, "0"):
                    raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
                page = [
                    item
                    for item in (source.parse_row(row) for row in _payload_rows(payload))
                    if item is not None
                ]
                request_count += 1
                if not page:
                    raise ValueError(f"EMPTY_PAGE:{cursor}:{window_end}")
                for item in page:
                    if start_ms <= item[0] <= end_ms:
                        found[item[0]] = item
                if (
                    len(found) >= expected_rows
                    and min(found) == start_ms
                    and max(found) == end_ms
                ):
                    break
                max_seen = max(item[0] for item in page)
                next_cursor = max_seen + source.INTERVAL_MS
                if next_cursor <= cursor:
                    raise ValueError(f"PAGINATION_STALLED:{cursor}:{max_seen}")
                cursor = next_cursor

            frame = pd.DataFrame(
                [found[key] for key in sorted(found)],
                columns=("timestamp_ms", "open", "high", "low", "close", "volume"),
            )
            source.validate(frame, expected_rows)
            if int(frame["timestamp_ms"].iloc[0]) != start_ms:
                raise ValueError("WINDOW_START_MISMATCH")
            if int(frame["timestamp_ms"].iloc[-1]) != end_ms:
                raise ValueError("WINDOW_END_MISMATCH")
            frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
            return frame, endpoint, request_count
        except Exception as exc:
            errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("BINGX_EXACT_WINDOW_FAILED:" + "|".join(errors))


def _trade_stats(replays: List[Mapping[str, Any]]) -> Dict[str, Any]:
    trades = [
        trade
        for replay in replays
        for trade in replay.get("trades", [])
        if isinstance(trade, Mapping)
    ]
    return anatomy._stats(trades)


def _metric_delta(candidate: Any, survivor: Any) -> Optional[float]:
    if not _finite(candidate) or not _finite(survivor):
        return None
    return float(candidate) - float(survivor)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the LINKUSDT survivor plus the side-adjusted DEMA/ATR 0.50-1.00 gate, "
            "then validate the exact same single gate on the immediately preceding fully "
            "non-overlapping BingX public 15m window."
        )
    )
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--warmup-bars", type=int, default=400)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()

    if args.warmup_bars < 250:
        raise ValueError("WARMUP_BARS_INVALID")
    if args.cost_bps_per_side < 0.0:
        raise ValueError("COST_BPS_INVALID")

    root = Path(args.root).resolve()
    first_baseline_dir = root / "runtime" / FIRST_BASELINE_DIRNAME
    first_summary_dir = root / "runtime" / FIRST_SUMMARY_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(
        dict.fromkeys(source.norm_symbol(item) for item in args.symbols.split(",") if item.strip())
    )

    blockers: List[str] = []
    results: List[Dict[str, Any]] = []
    survivor_replays: List[Dict[str, Any]] = []
    candidate_replays: List[Dict[str, Any]] = []
    total_dema_blocked = 0
    total_survivor_blocked = 0
    first_summary: Dict[str, Any] = {}

    try:
        first_summary = _load_json(first_summary_dir / "summary_v1.json")
        if not bool(first_summary.get("economic_survivor")):
            raise RuntimeError("FIRST_WINDOW_DEMA_GATE_NOT_ECONOMIC_SURVIVOR")
        if str(first_summary.get("single_new_entry_gate_policy_id")) != surgery.POLICY_ID:
            raise RuntimeError("FIRST_WINDOW_DEMA_POLICY_ID_MISMATCH")
        if str(first_summary.get("frozen_survivor_policy_id")) != survivor_filter.POLICY_ID:
            raise RuntimeError("FIRST_WINDOW_SURVIVOR_POLICY_ID_MISMATCH")
        if int(first_summary.get("canonical_strategy_count", 0)) != 1:
            raise RuntimeError("FIRST_WINDOW_CANONICAL_STRATEGY_COUNT_INVALID")
        if not bool(first_summary.get("payoff_preserved_within_5pct")):
            raise RuntimeError("FIRST_WINDOW_PAYOFF_NOT_PRESERVED")
    except Exception as exc:
        blockers.append(f"FIRST_WINDOW_SUMMARY:{type(exc).__name__}:{exc}")

    for symbol in symbols:
        try:
            first_window = _window_contract(first_baseline_dir / f"{symbol.lower()}_15m.csv")
            second_end_ms = first_window["start_ms"] - source.INTERVAL_MS
            second_start_ms = second_end_ms - (first_window["rows"] - 1) * source.INTERVAL_MS
            non_overlap = second_end_ms < first_window["start_ms"]
            if not non_overlap:
                raise RuntimeError("WINDOW_OVERLAP_DETECTED")

            raw, endpoint, request_count = _fetch_exact_window(
                symbol,
                start_ms=second_start_ms,
                end_ms=second_end_ms,
                expected_rows=first_window["rows"],
            )
            enriched = source.geometry(raw, args.warmup_bars)
            prefix_checks = source.prefix_check(raw, args.warmup_bars)
            csv_path = output_dir / f"{symbol.lower()}_15m.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            enriched.to_csv(csv_path, index=False)

            direct_survivor = survivor_filter._run_filtered_replay(
                enriched,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id=SECOND_FOLD_SURVIVOR + "_DIRECT_PARITY",
                cost_bps_per_side=args.cost_bps_per_side,
            )
            survivor = surgery._run_replay(
                enriched,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id=SECOND_FOLD_SURVIVOR,
                cost_bps_per_side=args.cost_bps_per_side,
                dema_gate_enabled=False,
            )
            parity = surgery._parity(direct_survivor, survivor)
            if parity.get("status") != "PASS":
                raise RuntimeError(f"SECOND_WINDOW_SURVIVOR_PARITY_FAILED:{symbol}:{parity.get('checks')}")

            candidate = surgery._run_replay(
                enriched,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id=SECOND_FOLD_CANDIDATE,
                cost_bps_per_side=args.cost_bps_per_side,
                dema_gate_enabled=True,
            )
            total_dema_blocked += int(candidate.get("dema_gate_blocked_entry_signal_count", 0))
            total_survivor_blocked += int(candidate.get("frozen_survivor_blocked_entry_signal_count", 0))
            survivor_replays.append(survivor)
            candidate_replays.append(candidate)
            source.atomic_json(output_dir / f"{symbol.lower()}_survivor_replay.json", survivor)
            source.atomic_json(output_dir / f"{symbol.lower()}_candidate_replay.json", candidate)
            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "endpoint": endpoint,
                    "request_count": request_count,
                    "prefix_checks": prefix_checks,
                    "rows": len(enriched),
                    "first_window_start_ms": first_window["start_ms"],
                    "first_window_end_ms": first_window["end_ms"],
                    "second_window_start_ms": second_start_ms,
                    "second_window_end_ms": second_end_ms,
                    "non_overlap": non_overlap,
                    "survivor_parity": parity,
                    "dema_gate_blocked_entry_signal_count": candidate.get("dema_gate_blocked_entry_signal_count"),
                    "survivor_trade_count": survivor.get("trade_count"),
                    "candidate_trade_count": candidate.get("trade_count"),
                    "survivor_net_return_pct": survivor.get("net_return_pct"),
                    "candidate_net_return_pct": candidate.get("net_return_pct"),
                    "survivor_net_profit_factor": survivor.get("net_profit_factor"),
                    "candidate_net_profit_factor": candidate.get("net_profit_factor"),
                    "csv": str(csv_path),
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    survivor_metrics = shared._summary_metrics(survivor_replays)
    candidate_metrics = shared._summary_metrics(candidate_replays)
    survivor_stats = _trade_stats(survivor_replays)
    candidate_stats = _trade_stats(candidate_replays)
    survivor_payoff = survivor_stats.get("payoff_ratio_pct")
    candidate_payoff = candidate_stats.get("payoff_ratio_pct")
    data_pass = len(candidate_replays) == len(symbols) and not blockers
    all_nonoverlap = bool(data_pass and all(bool(result.get("non_overlap")) for result in results))
    payoff_preserved = bool(
        _finite(survivor_payoff)
        and _finite(candidate_payoff)
        and float(candidate_payoff) >= 0.95 * float(survivor_payoff)
    )
    causal_improvement = bool(
        data_pass
        and all_nonoverlap
        and total_dema_blocked > 0
        and candidate_metrics["trade_count"] <= survivor_metrics["trade_count"]
        and candidate_metrics["net_return_pct_sum"] > survivor_metrics["net_return_pct_sum"]
        and _finite(candidate_metrics.get("net_profit_factor"))
        and _finite(survivor_metrics.get("net_profit_factor"))
        and float(candidate_metrics["net_profit_factor"]) > float(survivor_metrics["net_profit_factor"])
        and float(candidate_stats.get("win_rate_pct") or 0.0) > float(survivor_stats.get("win_rate_pct") or 0.0)
        and payoff_preserved
    )
    second_economic_survivor = bool(
        causal_improvement
        and candidate_metrics["net_return_pct_sum"] > 0.0
        and float(candidate_metrics["net_profit_factor"]) > 1.0
        and candidate_metrics["positive_symbol_count"] >= 3
    )
    two_window_confirmed = bool(
        bool(first_summary.get("economic_survivor")) and second_economic_survivor
    )

    if not data_pass:
        state = "HOLD_R7A4D_SURVIVOR_DEMA_SECOND_OOS_DATA_OR_PARITY_FAIL"
        next_stage = "REPAIR_SECOND_WINDOW_DATA_OR_PARITY_ONLY"
    elif two_window_confirmed:
        state = "PASS_R7A4D_SURVIVOR_DEMA_GATE_TWO_WINDOW_CONFIRMED"
        next_stage = "DESIGN_ONE_CAUSAL_0_25R_PROFIT_LOCK_REPLAY"
    elif causal_improvement:
        state = "HOLD_R7A4D_SURVIVOR_DEMA_SECOND_OOS_IMPROVED_NOT_ECONOMIC"
        next_stage = "KEEP_RESEARCH_ONLY_AUDIT_SECOND_WINDOW_SYMBOL_CONCENTRATION"
    else:
        state = "HOLD_R7A4D_SURVIVOR_DEMA_GATE_FAILED_SECOND_NONOVERLAP_OOS"
        next_stage = "ROLLBACK_DEMA_GATE_CANDIDACY_KEEP_FROZEN_SURVIVOR"

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "strategy_id": "integrated_supertrend_pullback_v1",
        "canonical_strategy_count": 1,
        "target_sha": args.target_sha,
        "source": "BingX public 15m immediately preceding fully non-overlapping fixed window",
        "interval": source.INTERVAL,
        "symbols": symbols,
        "warmup_bars": args.warmup_bars,
        "cost_bps_per_side": args.cost_bps_per_side,
        "frozen_survivor_policy_id": survivor_filter.POLICY_ID,
        "frozen_dema_gate_policy_id": surgery.POLICY_ID,
        "frozen_dema_gate_definition": {
            "field": "side_adjusted_dema_distance_atr",
            "lower_exclusive": surgery.DEMA_ATR_LOWER_EXCLUSIVE,
            "upper_inclusive": surgery.DEMA_ATR_UPPER_INCLUSIVE,
            "future_data_used": False,
        },
        "first_window_summary": {
            "state": first_summary.get("state"),
            "economic_survivor": first_summary.get("economic_survivor"),
            "candidate": first_summary.get("candidate"),
            "candidate_payoff_ratio_pct": first_summary.get("candidate_payoff_ratio_pct"),
        },
        "results": results,
        "second_window_survivor": survivor_metrics,
        "second_window_candidate": candidate_metrics,
        "second_window_survivor_trade_stats": survivor_stats,
        "second_window_candidate_trade_stats": candidate_stats,
        "second_window_survivor_payoff_ratio_pct": survivor_payoff,
        "second_window_candidate_payoff_ratio_pct": candidate_payoff,
        "payoff_preserved_within_5pct": payoff_preserved,
        "delta_candidate_vs_survivor": {
            "trade_count": candidate_metrics["trade_count"] - survivor_metrics["trade_count"],
            "win_count": int(candidate_stats.get("win_count", 0)) - int(survivor_stats.get("win_count", 0)),
            "win_rate_pct_point": _metric_delta(candidate_stats.get("win_rate_pct"), survivor_stats.get("win_rate_pct")),
            "net_return_pct_sum": candidate_metrics["net_return_pct_sum"] - survivor_metrics["net_return_pct_sum"],
            "net_profit_factor": _metric_delta(candidate_metrics.get("net_profit_factor"), survivor_metrics.get("net_profit_factor")),
            "payoff_ratio_pct": _metric_delta(candidate_payoff, survivor_payoff),
            "positive_symbol_count": candidate_metrics["positive_symbol_count"] - survivor_metrics["positive_symbol_count"],
        },
        "dema_gate_blocked_entry_signal_count": total_dema_blocked,
        "survivor_blocked_entry_signal_count": total_survivor_blocked,
        "all_windows_nonoverlapping": all_nonoverlap,
        "causal_improvement": causal_improvement,
        "second_oos_economic_survivor": second_economic_survivor,
        "two_window_confirmed": two_window_confirmed,
        "blockers": blockers,
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "shadow_started": False,
        "paper_live_order_allowed": False,
        "performance_claim_allowed": False,
        "promotion_allowed": False,
        "next_stage": next_stage,
    }
    source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={len(candidate_replays)}/{len(symbols)}")
    print(f"ALL_WINDOWS_NONOVERLAPPING={str(all_nonoverlap).lower()}")
    print(f"DEMA_GATE_BLOCKED_ENTRY_SIGNALS={total_dema_blocked}")
    print(f"SURVIVOR_TRADES={survivor_metrics['trade_count']}")
    print(f"CANDIDATE_TRADES={candidate_metrics['trade_count']}")
    print(f"SURVIVOR_WINS={survivor_stats['win_count']}")
    print(f"CANDIDATE_WINS={candidate_stats['win_count']}")
    print(f"SURVIVOR_WIN_RATE_PCT={survivor_stats['win_rate_pct']}")
    print(f"CANDIDATE_WIN_RATE_PCT={candidate_stats['win_rate_pct']}")
    print(f"SURVIVOR_NET_RETURN_PCT_SUM={survivor_metrics['net_return_pct_sum']:.6f}")
    print(f"CANDIDATE_NET_RETURN_PCT_SUM={candidate_metrics['net_return_pct_sum']:.6f}")
    print(f"SURVIVOR_NET_PF={survivor_metrics['net_profit_factor']}")
    print(f"CANDIDATE_NET_PF={candidate_metrics['net_profit_factor']}")
    print(f"SURVIVOR_PAYOFF_RATIO_PCT={survivor_payoff}")
    print(f"CANDIDATE_PAYOFF_RATIO_PCT={candidate_payoff}")
    print(f"PAYOFF_PRESERVED_WITHIN_5PCT={str(payoff_preserved).lower()}")
    print(f"POSITIVE_SYMBOLS={candidate_metrics['positive_symbol_count']}/{len(symbols)}")
    print(f"CAUSAL_IMPROVEMENT={str(causal_improvement).lower()}")
    print(f"SECOND_OOS_ECONOMIC_SURVIVOR={str(second_economic_survivor).lower()}")
    print(f"TWO_WINDOW_CONFIRMED={str(two_window_confirmed).lower()}")
    print(f"SUMMARY_JSON={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
