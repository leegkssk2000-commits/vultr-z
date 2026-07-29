from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "R7A4D_STRATEGY11_KELTNER_WINDOW_EXIT_DECOMPOSITION_V1"
STRATEGY_ID = "keltner_trend"
VARIANT_ID = "CHANNEL_OVERSHOOT_DISTANCE"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def read_one(root: Path, name: str, contains: tuple[str, ...] = ()) -> tuple[Path, Any]:
    matches = []
    for path in root.rglob(name):
        text = str(path).replace("\\", "/")
        if all(token in text for token in contains):
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError(f"ARTIFACT_RESOLUTION_FAILED:{name}:{contains}:{len(matches)}")
    return matches[0], json.loads(matches[0].read_text(encoding="utf-8"))


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def aggregate(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    trades = list(rows)
    values = [finite(row.get("net_return_pct")) for row in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    loss_rows = [row for row in trades if finite(row.get("net_return_pct")) < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / max(1, len(trades)) * 100.0,
        "net_pct": sum(values),
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else 999.0,
        "avg_loss_r": (
            sum(finite(row.get("net_loss_r")) for row in loss_rows) / len(loss_rows)
            if loss_rows else None
        ),
        "worst_loss_r": min((finite(row.get("net_loss_r")) for row in loss_rows), default=None),
        "avg_bars_held": sum(int(row.get("bars_held") or 0) for row in trades) / max(1, len(trades)),
        "window_end_count": sum(str(row.get("exit_reason")) == "WINDOW_END" for row in trades),
    }


def grouped(trades: list[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(trade.get(key) or "UNKNOWN")].append(trade)
    return {name: aggregate(rows) for name, rows in sorted(groups.items())}


def feature_contrast(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    selected = (
        "adx14", "atr_percentile", "body_atr", "close_location", "distance_ema20_atr",
        "mfi14", "rsi14", "volume_z", "vwap_distance_atr", "active_session",
        "directional_close_long", "obv_positive",
    )
    buckets = {"WIN": [], "LOSS": []}
    for trade in trades:
        bucket = "WIN" if finite(trade.get("net_return_pct")) > 0 else "LOSS"
        buckets[bucket].append(dict(trade.get("features") or {}))
    output: dict[str, Any] = {}
    for feature in selected:
        row: dict[str, Any] = {}
        for bucket, values in buckets.items():
            observed = [finite(value.get(feature)) for value in values if isinstance(value.get(feature), (int, float, bool))]
            row[bucket.lower() + "_mean"] = sum(observed) / len(observed) if observed else None
            row[bucket.lower() + "_count"] = len(observed)
        if row["win_mean"] is not None and row["loss_mean"] is not None:
            row["win_minus_loss"] = row["win_mean"] - row["loss_mean"]
        output[feature] = row
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-artifact-digest", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.artifact_root.resolve()
    final_path, final = read_one(root, "final.json")
    summary_path, summary = read_one(root, "summary.json", (STRATEGY_ID, VARIANT_ID))
    replay_a_path, replay_a = read_one(root, "replay-A.json", (STRATEGY_ID, VARIANT_ID))
    replay_b_path, replay_b = read_one(root, "replay-B.json", (STRATEGY_ID, VARIANT_ID))

    if final.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("FINAL_STRATEGY_MISMATCH")
    if summary.get("variant_id") != VARIANT_ID:
        raise RuntimeError("SUMMARY_VARIANT_MISMATCH")
    if replay_a.get("variant_id") != VARIANT_ID or replay_b.get("variant_id") != VARIANT_ID:
        raise RuntimeError("REPLAY_VARIANT_MISMATCH")
    final_copy = dict(final)
    claimed_diagnostic_sha = str(final_copy.pop("diagnostic_sha"))
    if stable_sha(final_copy) != claimed_diagnostic_sha:
        raise RuntimeError("FINAL_DIAGNOSTIC_SHA_MISMATCH")
    if stable_sha(summary) != str(final["candidate"]["summary_sha"]):
        raise RuntimeError("SUMMARY_SHA_MISMATCH")
    trades_a = list(replay_a.get("trades") or [])
    trades_b = list(replay_b.get("trades") or [])
    if stable_sha(trades_a) != stable_sha(trades_b):
        raise RuntimeError("AB_TRADE_PARITY_MISMATCH")
    trade_ids = [str(row.get("trade_id")) for row in trades_a]
    if len(trade_ids) != len(set(trade_ids)):
        raise RuntimeError("DUPLICATE_TRADE_ID")
    expected_source_sha = str(final["strategy_source_sha"])
    expected_head_sha = str(summary["source_head_sha"])
    expected_run_id = str(summary["source_run_id"])
    for trade in trades_a:
        if str(trade.get("strategy_source_sha")) != expected_source_sha:
            raise RuntimeError("TRADE_STRATEGY_SOURCE_SHA_MISMATCH")
        if str(trade.get("source_head_sha")) != expected_head_sha:
            raise RuntimeError("TRADE_SOURCE_HEAD_SHA_MISMATCH")
        if str(trade.get("source_run_id")) != expected_run_id:
            raise RuntimeError("TRADE_SOURCE_RUN_ID_MISMATCH")

    total = aggregate(trades_a)
    by_window = grouped(trades_a, "window_id")
    by_symbol = grouped(trades_a, "symbol")
    by_exit = grouped(trades_a, "exit_reason")
    by_skill = grouped(trades_a, "signal_skill")
    losses = [row for row in trades_a if finite(row.get("net_return_pct")) < 0]
    mfe_050 = [row for row in losses if finite(row.get("mfe_r")) >= 0.50]
    mfe_100 = [row for row in losses if finite(row.get("mfe_r")) >= 1.00]
    immediate_fail = [row for row in losses if finite(row.get("mfe_r")) < 0.25]
    positive_windows = [name for name, row in by_window.items() if finite(row.get("net_pct")) > 0]
    negative_windows = [name for name, row in by_window.items() if finite(row.get("net_pct")) <= 0]
    worst_window = min(by_window, key=lambda name: finite(by_window[name].get("net_pct")))
    best_window = max(by_window, key=lambda name: finite(by_window[name].get("net_pct")))
    mfe_giveback_ratio = len(mfe_050) / max(1, len(losses))

    if len(positive_windows) < 2:
        state = "HOLD_KELTNER_WINDOW_CONCENTRATION"
    else:
        state = "PASS_KELTNER_BREADTH_DIAGNOSTIC"
    if mfe_giveback_ratio >= 0.50:
        next_action = "TRACE_MFE_GIVEBACK_PATH_FOR_ONE_TRAILING_CANDIDATE"
        next_axis = "MFE_TRAILING"
    else:
        next_action = "TRACE_ENTRY_CONTEXT_BY_NEGATIVE_WINDOW"
        next_axis = "ENTRY_CONTEXT_GATE"

    result = {
        "schema_version": "strategy11.keltner_window_exit_decomposition.v1",
        "version": VERSION,
        "state": state,
        "strategy_id": STRATEGY_ID,
        "variant_id": VARIANT_ID,
        "source_authority": {
            "run_id": str(args.source_run_id),
            "artifact_digest": str(args.source_artifact_digest),
            "final_path": str(final_path.relative_to(root)),
            "summary_path": str(summary_path.relative_to(root)),
            "replay_a_path": str(replay_a_path.relative_to(root)),
            "replay_b_path": str(replay_b_path.relative_to(root)),
            "diagnostic_sha": claimed_diagnostic_sha,
            "summary_sha": str(final["candidate"]["summary_sha"]),
            "strategy_source_sha": expected_source_sha,
            "source_head_sha": expected_head_sha,
            "source_data_run_id": expected_run_id,
            "ab_trade_sha": stable_sha(trades_a),
        },
        "total": total,
        "by_window": by_window,
        "by_symbol": by_symbol,
        "by_exit_reason": by_exit,
        "by_signal_skill": by_skill,
        "feature_contrast": feature_contrast(trades_a),
        "clusters": {
            "loss_count": len(losses),
            "losses_mfe_ge_0_50r": len(mfe_050),
            "losses_mfe_ge_1_00r": len(mfe_100),
            "immediate_fail_mfe_lt_0_25r": len(immediate_fail),
            "mfe_giveback_ratio": mfe_giveback_ratio,
            "positive_windows": positive_windows,
            "negative_windows": negative_windows,
            "best_window": best_window,
            "worst_window": worst_window,
        },
        "next_axis": next_axis,
        "next_action": next_action,
        "same_data_next_generation_budget": 1,
        "control_required": True,
        "candidate_count_max": 1,
        "threshold_sweep_allowed": False,
        "canonical_source_modified": False,
        "registry_modified": False,
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        **SAFETY,
    }
    result["decomposition_sha"] = stable_sha(result)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "final.json", result)
    print(result["state"], total["trades"], positive_windows, len(mfe_050), next_axis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
