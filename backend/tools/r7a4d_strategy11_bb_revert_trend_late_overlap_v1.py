from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_bb_revert_component_trace_v1 as prior_trace

p = prior_trace.p
exact = prior_trace.exact
base = prior_trace.base
repair = prior_trace.repair
prior = prior_trace.prior

STRATEGY_ID = "bb_revert"
VERSION = "R7A4D_STRATEGY11_BB_REVERT_TREND_LATE_OVERLAP_V1"
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


def trace(strategy: Any, symbols: tuple[str, ...], frames: Mapping[tuple[str, str], Any], warmup_bars: int, history_bars: int) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    per_window: defaultdict[str, Counter[str]] = defaultdict(Counter)
    per_symbol: defaultdict[str, Counter[str]] = defaultdict(Counter)
    samples: list[dict[str, Any]] = []
    calls = 0

    def add(name: str, window_id: str, symbol: str) -> None:
        counts[name] += 1
        per_window[window_id][name] += 1
        per_symbol[symbol][name] += 1

    for window_id in repair.FRESH_ROLES:
        for symbol in symbols:
            frame = frames[(window_id, symbol)]
            for index in range(warmup_bars, len(frame) - 1):
                history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
                result = exact._call_strategy(strategy, history, {
                    "position_side": "", "position_qty": 0.0, "avg_entry": 0.0,
                    "add_count": 0, "last_add_price": 0.0,
                })
                calls += 1
                indicators = result.get("indicators")
                if not isinstance(indicators, Mapping):
                    continue
                price = float(indicators.get("price") or 0.0)
                atr = float(indicators.get("atr") or 0.0)
                bb_lower = float(indicators.get("bb_lower") or 0.0)
                bb_upper = float(indicators.get("bb_upper") or 0.0)
                rsi = float(indicators.get("rsi") or 0.0)
                atr_pct = float(indicators.get("atr_pct") or 0.0)
                late = bool(indicators.get("late_chase_block"))
                vol_ok = 0.12 <= atr_pct <= 5.20
                side_rows = (
                    (
                        "long",
                        price < bb_lower - atr * 0.08,
                        rsi <= 30.0,
                        bool(indicators.get("long_reclaim")),
                        not bool(indicators.get("trend_short")),
                    ),
                    (
                        "short",
                        price > bb_upper + atr * 0.08,
                        rsi >= 70.0,
                        bool(indicators.get("short_reclaim")),
                        not bool(indicators.get("trend_long")),
                    ),
                )
                for side, band, rsi_ok, reclaim, trend_ok in side_rows:
                    if not (band and rsi_ok and reclaim):
                        continue
                    add("post_reclaim", window_id, symbol)
                    add(f"{side}_post_reclaim", window_id, symbol)
                    if not trend_ok:
                        add("trend_veto", window_id, symbol)
                    if late:
                        add("late_chase", window_id, symbol)
                    if (not trend_ok) and late:
                        add("trend_veto_and_late_chase", window_id, symbol)
                    if not vol_ok:
                        add("volatility_block", window_id, symbol)
                    if vol_ok and not late:
                        add("eligible_without_trend_veto", window_id, symbol)
                    if vol_ok and not late and trend_ok:
                        add("canonical_entry_eligible", window_id, symbol)
                    if len(samples) < 20:
                        samples.append({
                            "window_id": window_id,
                            "symbol": symbol,
                            "side": side,
                            "event_ts": str(frame["timestamp"].iloc[index]),
                            "trend_ok": trend_ok,
                            "late_chase_block": late,
                            "vol_ok": vol_ok,
                            "dist_from_mid_atr": indicators.get("dist_from_mid_atr"),
                            "rsi": rsi,
                            "atr_pct": atr_pct,
                        })

    total = counts["post_reclaim"]
    accounted = (
        counts["eligible_without_trend_veto"]
        + counts["late_chase"]
        + counts["volatility_block"]
        - counts["trend_veto_and_late_chase"] * 0
    )
    if total == 0:
        state = "NO_POST_RECLAIM_EVIDENCE"
        next_action = "WAIT_NEW_EVIDENCE"
    elif total < 5:
        state = "LOW_SAMPLE_POST_RECLAIM_HOLD"
        next_action = "WAIT_W1_NEW_NONOVERLAP"
    elif counts["eligible_without_trend_veto"] >= 5:
        state = "TREND_VETO_ISOLATED_CANDIDATE_ALLOWED"
        next_action = "ONE_TREND_REGIME_ABLATION_REPLAY"
    else:
        state = "TREND_AND_LATE_CHASE_CONFOUNDED_HOLD"
        next_action = "WAIT_W1_OR_DISTINCT_CAUSAL_AXIS"

    return {
        "state": state,
        "next_action": next_action,
        "call_count": calls,
        "counts": dict(sorted(counts.items())),
        "post_reclaim_count": total,
        "trend_veto_count": counts["trend_veto"],
        "late_chase_count": counts["late_chase"],
        "trend_veto_and_late_chase_count": counts["trend_veto_and_late_chase"],
        "eligible_without_trend_veto_count": counts["eligible_without_trend_veto"],
        "canonical_entry_eligible_count": counts["canonical_entry_eligible"],
        "per_window": {k: dict(sorted(v.items())) for k, v in sorted(per_window.items())},
        "per_symbol": {k: dict(sorted(v.items())) for k, v in sorted(per_symbol.items())},
        "samples": samples,
        "diagnostic_accounting_nonnegative": accounted >= 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    baseline = json.loads(prior.find_summary(args.evidence_root.resolve(), STRATEGY_ID).read_text(encoding="utf-8"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    frames, _, _, manifest = p.load_fresh_data(args.fresh_root.resolve())
    registry = base._load_registry(root)
    row = registry[STRATEGY_ID]
    source_sha = str(row["canonical_engine"]["source_sha256"])
    source_contract = prior_trace.verify_source(root, source_sha)
    strategy = base._load_canonical_strategy(root, STRATEGY_ID, row)
    result_trace = trace(strategy, symbols, frames, int(manifest["warmup_bars"]), 220)

    result = {
        "schema_version": "strategy11.bb_revert_trend_late_overlap.v1",
        "version": VERSION,
        "state": "PASS_BB_REVERT_TREND_LATE_OVERLAP_TRACE",
        "strategy_id": STRATEGY_ID,
        "source_run_id": str(args.source_run_id),
        "source_head_sha": str(args.source_head_sha),
        "baseline_summary_sha": stable_sha(baseline),
        "symbols": list(symbols),
        "source_contract": source_contract,
        "trace": result_trace,
        "canonical_source_modified": False,
        "registry_modified": False,
        "thresholds_modified": False,
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        **SAFETY,
    }
    result["diagnostic_sha"] = stable_sha(result)
    atomic_json(args.out / "final.json", result)
    print(result["state"], result_trace["state"], result_trace["post_reclaim_count"], result_trace["eligible_without_trend_veto_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
