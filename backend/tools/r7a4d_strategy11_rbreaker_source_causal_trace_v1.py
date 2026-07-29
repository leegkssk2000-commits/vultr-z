from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.strategies.rbreaker_like import RBreakerLikeConfig
from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair
prior = replay.prior

STRATEGY_ID = "rbreaker_like"
VERSION = "R7A4D_STRATEGY11_RBREAKER_SOURCE_CAUSAL_TRACE_V1"
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


def verify_source_semantics(root: Path, expected_sha: str) -> dict[str, Any]:
    path = (root / "backend/strategies/rbreaker_like.py").resolve()
    source = path.read_text(encoding="utf-8")
    actual_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{actual_sha}:{expected_sha}")
    required = {
        "prior_range": "    recent = df.iloc[-(cfg.lookback + 1):-1]",
        "breakout_buy": "    breakout_buy = hi + rng * cfg.breakout_mult",
        "breakout_sell": "    breakout_sell = lo - rng * cfg.breakout_mult",
        "rev_sell": "    rev_sell = mid + rng * cfg.reversal_mult",
        "rev_buy": "    rev_buy = mid - rng * cfg.reversal_mult",
        "long_break": "    long_break = price > breakout_buy + atr_now * cfg.breakout_buffer_atr and prev_close <= breakout_buy",
        "short_break": "    short_break = price < breakout_sell - atr_now * cfg.breakout_buffer_atr and prev_close >= breakout_sell",
        "short_reversal": "    short_reversal = prev_high >= rev_sell and price < mid - atr_now * cfg.reversal_reclaim_atr",
        "long_reversal": "    long_reversal = prev_low <= rev_buy and price > mid + atr_now * cfg.reversal_reclaim_atr",
        "vol_gate": "    if not vol_ok:",
        "late_gate": "    if late_chase_block and (long_break or short_break or long_reversal or short_reversal):",
        "long_break_entry": "    if long_break and not in_long and not in_short:",
        "short_break_entry": "    if short_break and not in_long and not in_short:",
        "long_rev_entry": "    if long_reversal and not in_long and not in_short:",
        "short_rev_entry": "    if short_reversal and not in_long and not in_short:",
    }
    counts = {name: source.count(text) for name, text in required.items()}
    if any(value != 1 for value in counts.values()):
        raise RuntimeError("SOURCE_CONTRACT_SHAPE_MISMATCH:" + json.dumps(counts, sort_keys=True))
    order = {name: source.index(text) for name, text in required.items()}
    if not (
        order["prior_range"] < order["breakout_buy"] < order["long_break"]
        < order["vol_gate"] < order["late_gate"] < order["long_break_entry"]
        < order["short_break_entry"] < order["long_rev_entry"] < order["short_rev_entry"]
    ):
        raise RuntimeError("SOURCE_ORDER_MISMATCH")
    return {
        "source_path": "backend/strategies/rbreaker_like.py",
        "source_sha": actual_sha,
        "required_clause_counts": counts,
        "prior_range_excludes_current_candle": True,
        "entry_gate_order_verified": True,
        "source_modified": False,
    }


def trace(
    strategy: Any,
    symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], Any],
    warmup_bars: int,
    history_bars: int,
) -> dict[str, Any]:
    cfg = RBreakerLikeConfig()
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
                result = exact._call_strategy(
                    strategy,
                    history,
                    {
                        "position_side": "",
                        "position_qty": 0.0,
                        "avg_entry": 0.0,
                        "add_count": 0,
                        "last_add_price": 0.0,
                    },
                )
                calls += 1
                indicators = result.get("indicators")
                if not isinstance(indicators, Mapping):
                    continue

                price = float(indicators["price"])
                atr_now = float(indicators["atr"])
                mid = float(indicators["mid"])
                breakout_buy = float(indicators["breakout_buy"])
                breakout_sell = float(indicators["breakout_sell"])
                rev_buy = float(indicators["rev_buy"])
                rev_sell = float(indicators["rev_sell"])
                prev = history.iloc[-2]
                prev_close = float(prev["close"])
                prev_high = float(prev["high"])
                prev_low = float(prev["low"])
                atr_pct = float(indicators["atr_pct"])

                vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
                late = bool(indicators.get("late_chase_block"))

                components = {
                    "long_break_price": price > breakout_buy + atr_now * cfg.breakout_buffer_atr,
                    "long_break_prev": prev_close <= breakout_buy,
                    "short_break_price": price < breakout_sell - atr_now * cfg.breakout_buffer_atr,
                    "short_break_prev": prev_close >= breakout_sell,
                    "long_reversal_touch": prev_low <= rev_buy,
                    "long_reversal_reclaim": price > mid + atr_now * cfg.reversal_reclaim_atr,
                    "short_reversal_touch": prev_high >= rev_sell,
                    "short_reversal_reclaim": price < mid - atr_now * cfg.reversal_reclaim_atr,
                }
                for key, value in components.items():
                    if value:
                        add(f"{key}_true", window_id, symbol)

                signals = {
                    "long_break": bool(indicators.get("long_break")),
                    "short_break": bool(indicators.get("short_break")),
                    "long_reversal": bool(indicators.get("long_reversal")),
                    "short_reversal": bool(indicators.get("short_reversal")),
                }
                for signal, active in signals.items():
                    if not active:
                        continue
                    add(f"{signal}_true", window_id, symbol)
                    if not vol_ok:
                        blocker = "volatility_gate_block"
                    elif late:
                        blocker = "late_chase_block"
                    else:
                        blocker = "entry_eligible"
                    add(f"{signal}_{blocker}", window_id, symbol)
                    if len(samples) < 30:
                        samples.append({
                            "window_id": window_id,
                            "symbol": symbol,
                            "signal": signal,
                            "first_blocker": blocker,
                            "atr_pct": atr_pct,
                            "dist_from_fast_atr": indicators.get("dist_from_fast_atr"),
                            "price": price,
                            "mid": mid,
                            "breakout_buy": breakout_buy,
                            "breakout_sell": breakout_sell,
                            "rev_buy": rev_buy,
                            "rev_sell": rev_sell,
                        })
                if str(result.get("action") or "hold").lower() == "enter":
                    add("actual_enter", window_id, symbol)

    signal_names = ("long_break", "short_break", "long_reversal", "short_reversal")
    blocker_names = ("volatility_gate_block", "late_chase_block", "entry_eligible")
    identities = {}
    for signal in signal_names:
        identities[signal] = counts[f"{signal}_true"] == sum(counts[f"{signal}_{blocker}"] for blocker in blocker_names)

    total_signals = sum(counts[f"{signal}_true"] for signal in signal_names)
    eligible = sum(counts[f"{signal}_entry_eligible"] for signal in signal_names)
    actual = counts["actual_enter"]

    long_touch = counts["long_reversal_touch_true"]
    long_reclaim = counts["long_reversal_reclaim_true"]
    long_joint = counts["long_reversal_true"]
    short_touch = counts["short_reversal_touch_true"]
    short_reclaim = counts["short_reversal_reclaim_true"]
    short_joint = counts["short_reversal_true"]

    if eligible != actual:
        state = "ROUTING_CONTRACT_MISMATCH"
        next_action = "TRACE_ENTRY_ROUTER_PAYLOAD"
    elif total_signals > 0 and eligible == 0:
        state = "PRE_ENTRY_GATES_BLOCK_ALL_SIGNALS"
        next_action = "DECOMPOSE_VOLATILITY_VS_DISTANCE_DEFINITION"
    elif long_joint == 0 and short_joint == 0 and min(long_touch, long_reclaim, short_touch, short_reclaim) > 0:
        state = "REVERSAL_COMPONENTS_NEVER_INTERSECT"
        next_action = "WAIT_W1_OR_VERIFY_FORMULA_GEOMETRY"
    elif total_signals < 5:
        state = "LOW_FREQUENCY_RBREAKER_SIGNAL_HOLD"
        next_action = "WAIT_W1_NEW_NONOVERLAP"
    else:
        state = "RBREAKER_CAUSAL_COMPONENTS_DECOMPOSED"
        next_action = "SOURCE_CAUSAL_REVIEW"

    return {
        "state": state,
        "next_action": next_action,
        "call_count": calls,
        "counts": dict(sorted(counts.items())),
        "total_signal_count": total_signals,
        "entry_eligible_count": eligible,
        "actual_enter_count": actual,
        "eligible_equals_actual_enter": eligible == actual,
        "signal_accounting_identity_pass": all(identities.values()),
        "signal_accounting": identities,
        "reversal_component_summary": {
            "long_touch": long_touch,
            "long_reclaim": long_reclaim,
            "long_joint": long_joint,
            "short_touch": short_touch,
            "short_reclaim": short_reclaim,
            "short_joint": short_joint,
        },
        "per_window": {key: dict(sorted(value.items())) for key, value in sorted(per_window.items())},
        "per_symbol": {key: dict(sorted(value.items())) for key, value in sorted(per_symbol.items())},
        "samples": samples,
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
    baseline_path = prior.find_summary(args.evidence_root.resolve(), STRATEGY_ID)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    frames, _, _, manifest = p.load_fresh_data(args.fresh_root.resolve())
    registry = base._load_registry(root)
    registry_row = registry[STRATEGY_ID]
    expected_sha = str(registry_row["canonical_engine"]["source_sha256"])
    source_contract = verify_source_semantics(root, expected_sha)
    strategy = base._load_canonical_strategy(root, STRATEGY_ID, registry_row)
    result_trace = trace(strategy, symbols, frames, int(manifest["warmup_bars"]), 220)

    result = {
        "schema_version": "strategy11.rbreaker_source_causal_trace.v1",
        "version": VERSION,
        "state": "PASS_RBREAKER_SOURCE_CAUSAL_TRACE",
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
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "final.json", result)
    print(result["state"], result_trace["state"], result_trace["total_signal_count"], result_trace["actual_enter_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
