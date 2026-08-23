#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_keltner_h4_h5_hardening_v1 as kh
from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig
from backend.research.rebuild.policy_kernel_v1 import atr
from backend.tools import zel_economic_hardening_gate_v1 as hard

ROOT = Path(__file__).resolve().parents[3]
PARENT_POLICY = ROOT / "backend/research/rebuild/trend_policy_batch_v1.py"
MIN_TRADES = 25
LIQUID6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
TARGETS = {
    "supertrend_pullback_long_reclaim_good_v1": {
        "transport_strategy_id": "supertrend_pullback",
        "indicator_removal_semantics": "REMOVE_LONG_RECLAIM_GOOD_ADMISSION_RESTORE_UNCHANGED_SUPERTREND_PARENT",
    },
    "trend_ma_macd_ema_fast_up_good_v1": {
        "transport_strategy_id": "trend_ma_macd",
        "indicator_removal_semantics": "REMOVE_EMA_FAST_UP_GOOD_ADMISSION_RESTORE_UNCHANGED_TRENDMA_PARENT",
    },
}
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _first25(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(x) for x in rows),
        key=lambda x: (
            int(x.get("exit_ts") or 0), int(x.get("signal_ts") or 0),
            str(x.get("symbol") or ""), int(x.get("entry_ts") or 0),
        ),
    )
    return ordered[:MIN_TRADES]


def _one_bar_delay_net_r(
    trade: Mapping[str, Any], bars: list[dict[str, Any]], mapping: dict[int, int], cfg: TrendPolicyConfig,
) -> float:
    entry_i = mapping[int(trade["entry_ts"])]
    signal_i = entry_i - 1
    if signal_i < 0:
        raise RuntimeError("GOOD_CHILD_ONE_BAR_DELAY_SIGNAL_BAR_MISSING")
    a = atr(bars[: signal_i + 1], cfg.atr_len)
    signal_close = float(bars[signal_i]["close"])
    stop = signal_close - 1.5 * a if str(trade["side"]) == "long" else signal_close + 1.5 * a
    value = kh.simulate_stop_timeout(
        bars, entry_i, str(trade["side"]), stop, cfg.timeout_bars,
        float(trade["realized_cost_bps"]),
    )
    if value is None:
        raise RuntimeError("GOOD_CHILD_ONE_BAR_DELAY_OPEN_TRADE")
    return value / 100.0


def _parent_control(identity: str, boundary: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target = TARGETS[identity]
    with tempfile.TemporaryDirectory(prefix=f"{identity}_parent_control_") as td:
        path = Path(td) / "parent.json"
        parent, shadow = run_terminal_shadow(
            strategy_id=str(target["transport_strategy_id"]),
            policy_path=PARENT_POLICY,
            fresh_boundary_utc=boundary,
            out=path,
            symbols=LIQUID6,
        )
    defects = list(parent.get("integrity_defects") or [])
    lookahead = int(parent.get("leakage_lookahead") or 0)
    source_state = str(((parent.get("source_quality_gate") or {}).get("state") or ""))
    if defects or lookahead != 0 or source_state == "FAIL":
        raise RuntimeError(f"GOOD_CHILD_PARENT_CONTROL_INTEGRITY:{identity}:{defects}:{lookahead}:{source_state}")
    trades = _first25([dict(x) for x in (parent.get("trades") or [])])
    if len(trades) < MIN_TRADES:
        raise RuntimeError(f"GOOD_CHILD_PARENT_CONTROL_MIN_SAMPLE:{identity}:{len(trades)}")
    return trades, shadow


def run(receipt_path: Path, out: Path) -> dict[str, Any]:
    receipt = _read(receipt_path)
    identity = str(receipt.get("candidate_identity") or "")
    if identity not in TARGETS:
        raise RuntimeError(f"GOOD_CHILD_IDENTITY_MISMATCH:{identity}")
    target = TARGETS[identity]
    if str(receipt.get("transport_strategy_id") or receipt.get("strategy_id") or "") != str(target["transport_strategy_id"]):
        raise RuntimeError("GOOD_CHILD_TRANSPORT_STRATEGY_MISMATCH")
    trades = _first25([dict(x) for x in (receipt.get("trades") or [])])
    if int(receipt.get("completed_trades") or 0) != MIN_TRADES or len(trades) != MIN_TRADES:
        raise RuntimeError("GOOD_CHILD_HARDENING_EXACT25_REQUIRED")
    if receipt.get("exact_first_completed_trades") != MIN_TRADES:
        raise RuntimeError("GOOD_CHILD_FIRST25_AUTHORITY_MISSING")
    if receipt.get("parent_h4_h5_reuse_for_promotion") is not False:
        raise RuntimeError("GOOD_CHILD_PARENT_HARDENING_REUSE_FORBIDDEN")

    boundary = str(receipt.get("fresh_boundary_utc") or receipt.get("boundary_utc") or "")
    if not boundary:
        raise RuntimeError("GOOD_CHILD_BOUNDARY_MISSING")
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    cfg = TrendPolicyConfig()
    symbols = sorted({str(x["symbol"]) for x in trades})
    if not set(symbols).issubset(set(LIQUID6)):
        raise RuntimeError(f"GOOD_CHILD_NON_LIQUID6_SYMBOL:{symbols}")

    bars_by = {symbol: ev.fetch_bars(symbol, "1h", 1000) for symbol in symbols}
    maps = {symbol: kh.idx_by_ts(bars_by[symbol]) for symbol in symbols}
    latest = max(int(x["exit_ts"]) for x in trades)
    material = {
        symbol: [bar for bar in bars_by[symbol] if boundary_ms <= int(bar["ts_ms"]) <= latest + cfg.timeframe_ms]
        for symbol in symbols
    }
    source_sha = kh.stable(receipt["source"])
    data_sha = kh.stable(material)
    window_sha = kh.stable({
        "identity": identity, "boundary": boundary, "latest_exit": latest,
        "symbols": symbols, "trade_count": len(trades), "ordering": "EXIT_TIMESTAMP_BUCKET_ASC",
    })
    cost_sha = str(receipt["cost_authority_sha256"])
    config_sha = str(receipt["config_sha"])
    candidate_values = [float(x["net_bps"]) / 100.0 for x in trades]
    candidate = kh.replay_receipt(
        "candidate", candidate_values, source_sha=source_sha, data_sha=data_sha,
        config_sha=config_sha, window_sha=window_sha, cost_sha=cost_sha,
    )

    controls: dict[str, list[float]] = {}
    controls["direction_inversion"] = [
        (-float(x["gross_bps"]) - float(x["realized_cost_bps"])) / 100.0 for x in trades
    ]
    sides = [str(x["side"]) for x in trades]
    rng = random.Random(int(window_sha[:16], 16))
    shuffled = sides[:]
    rng.shuffle(shuffled)
    controls["timestamp_shuffle"] = [
        kh.net_for(shuffled[i], float(x["entry"]), float(x["exit"]), float(x["realized_cost_bps"])) / 100.0
        for i, x in enumerate(trades)
    ]
    controls["one_bar_delay"] = [
        _one_bar_delay_net_r(x, bars_by[str(x["symbol"])], maps[str(x["symbol"])], cfg)
        for x in trades
    ]

    random_values: list[float] = []
    used: set[tuple[str, int]] = set()
    for trade in trades:
        symbol = str(trade["symbol"])
        bars = bars_by[symbol]
        mapping = maps[symbol]
        duration = kh.duration_bars(trade, mapping)
        pool = [
            j for j, bar in enumerate(bars)
            if boundary_ms <= int(bar["ts_ms"]) <= latest
            and j + 1 + duration < len(bars)
            and (symbol, int(bar["ts_ms"])) not in used
        ]
        if not pool:
            raise RuntimeError("GOOD_CHILD_RANDOM_ENTRY_POOL_EXHAUSTED")
        j = pool[rng.randrange(len(pool))]
        used.add((symbol, int(bars[j]["ts_ms"])))
        entry = float(bars[j + 1]["open"])
        exit_px = float(bars[j + 1 + duration]["close"])
        random_values.append(
            kh.net_for(str(trade["side"]), entry, exit_px, float(trade["realized_cost_bps"])) / 100.0
        )
    controls["same_count_random_entry"] = random_values

    parent_trades, parent_shadow = _parent_control(identity, boundary)
    controls["indicator_removal"] = [float(x["net_bps"]) / 100.0 for x in parent_trades]

    control_receipts: dict[str, dict[str, Any]] = {}
    for name in (
        "same_count_random_entry", "one_bar_delay", "direction_inversion",
        "timestamp_shuffle", "indicator_removal",
    ):
        values = controls[name]
        ci, p_value = kh.paired_stats(
            candidate_values, values,
            int(kh.stable({"identity": identity, "window": window_sha, "control": name})[:16], 16),
        )
        control_receipts[name] = kh.replay_receipt(
            name, values, source_sha=source_sha, data_sha=data_sha,
            config_sha=kh.stable({"base": config_sha, "identity": identity, "control": name}),
            window_sha=window_sha, cost_sha=cost_sha, ci=ci, p=p_value,
        )

    policy = _read(ROOT / "backend/research/zel_economic_hardening_policy_v1.json")
    h4 = hard.h4_placebo_controls(
        {"candidate_receipt": candidate, "control_receipts": control_receipts},
        policy["h4_placebo_negative_controls"],
    )
    h5 = kh._h5(trades, bars_by, maps, window_sha, policy)

    source_quality = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), Mapping) else {}
    defects = list(receipt.get("integrity_defects") or [])
    lookahead = int(receipt.get("leakage_lookahead") or 0)
    integrity_ok = source_quality.get("state") == "PASS" and not defects and lookahead == 0
    hardening_ok = (
        h4.get("state") == "PASS_PLACEBO_NEGATIVE_CONTROLS"
        and h5.get("state") == "PASS_CONCENTRATION_FRAGILITY"
    )
    state = "PASS_GOOD_REGIME_IDENTITY_HARDENING" if integrity_ok and hardening_ok else "HOLD_GOOD_REGIME_IDENTITY_HARDENING"
    result = {
        "schema_version": "zel.a1.finalist.good_regime.hardening.v1",
        "state": state,
        "candidate_identity": identity,
        "transport_strategy_id": target["transport_strategy_id"],
        "identity_specific_controls": True,
        "indicator_removal_semantics": target["indicator_removal_semantics"],
        "indicator_removal_parent_trade_count": len(parent_trades),
        "indicator_removal_parent_shadow": parent_shadow,
        "candidate_trade_count": len(trades),
        "exact_first_completed_trades": MIN_TRADES,
        "fresh_boundary_utc": boundary,
        "drawdown_ordering_authority": "EXIT_TIMESTAMP_BUCKET_ASC",
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "source_quality_state": source_quality.get("state"),
        "integrity_defects": defects,
        "leakage_lookahead": lookahead,
        "h4_receipt": h4,
        "h5_receipt": h5,
        "parent_preserved": True,
        "runtime_good_boost_enabled": False,
        "next": "SURVIVOR_CANDIDATE_PASS_THEN_ROUTE_NEXT_GATE" if state.startswith("PASS_") else "PRESERVE_PARENT_AND_CHILD_EVIDENCE_NO_PROMOTION",
        **AUTH,
    }
    result["receipt_sha256"] = hard.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert set(TARGETS) == {
        "supertrend_pullback_long_reclaim_good_v1",
        "trend_ma_macd_ema_fast_up_good_v1",
    }
    assert all("RESTORE_UNCHANGED" in str(x["indicator_removal_semantics"]) for x in TARGETS.values())
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    assert MIN_TRADES == 25 and len(LIQUID6) == 6
    print("PASS_A1_FINALIST_GOOD_REGIME_H4_H5_HARDENING_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_good_regime_h4_h5_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.receipt is None:
        raise SystemExit("--receipt required")
    result = run(args.receipt, args.out)
    print(json.dumps({
        "state": result["state"],
        "candidate_identity": result["candidate_identity"],
        "candidate_trade_count": result["candidate_trade_count"],
        "H4": (result["h4_receipt"] or {}).get("state"),
        "H5": (result["h5_receipt"] or {}).get("state"),
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
