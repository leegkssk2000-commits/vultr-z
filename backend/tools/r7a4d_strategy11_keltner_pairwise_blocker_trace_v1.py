from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair
prior = replay.prior

STRATEGY_ID = "keltner_trend"
SOURCE_PATH = Path("backend/strategies/keltner_trend.py")
VERSION = "R7A4D_STRATEGY11_KELTNER_PAIRWISE_BLOCKER_TRACE_V1"
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


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def verify_source_contract(root: Path, expected_sha: str) -> dict[str, Any]:
    path = (root / SOURCE_PATH).resolve()
    source = path.read_text(encoding="utf-8")
    actual_sha = sha_file(path)
    if actual_sha != expected_sha:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{actual_sha}:{expected_sha}")
    required = {
        "volatility_gate": "    if not vol_ok:",
        "late_chase_gate": "    if late_chase_block and (long_setup or short_setup):",
        "long_entry": "    if long_setup and not in_long and not in_short:",
        "short_entry": "    if short_setup and not in_long and not in_short:",
    }
    counts = {name: source.count(text) for name, text in required.items()}
    if any(count != 1 for count in counts.values()):
        raise RuntimeError("ENTRY_CONTRACT_SHAPE_MISMATCH:" + json.dumps(counts, sort_keys=True))
    order = {name: source.index(text) for name, text in required.items()}
    if not (order["volatility_gate"] < order["late_chase_gate"] < order["long_entry"] < order["short_entry"]):
        raise RuntimeError("ENTRY_CONTRACT_ORDER_MISMATCH")
    return {
        "source_path": str(SOURCE_PATH),
        "source_sha": actual_sha,
        "required_clause_counts": counts,
        "entry_order_verified": True,
        "source_modified": False,
    }


def trace(
    strategy: Any,
    symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], Any],
    warmup_bars: int,
    history_bars: int,
) -> dict[str, Any]:
    config_type = strategy.__globals__.get("KeltnerTrendConfig")
    if config_type is None:
        raise RuntimeError("KELTNER_CONFIG_NOT_EXPOSED")
    cfg = config_type()

    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    per_window: defaultdict[str, Counter[str]] = defaultdict(Counter)
    per_symbol: defaultdict[str, Counter[str]] = defaultdict(Counter)
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
                action = str(result.get("action") or "hold").lower()
                reason = str(result.get("why") or result.get("reason") or "UNSPECIFIED")
                reasons[reason] += 1
                indicators = result.get("indicators")
                if not isinstance(indicators, Mapping):
                    continue
                long_setup = bool(indicators.get("long_setup"))
                short_setup = bool(indicators.get("short_setup"))
                atr_pct = float(indicators.get("atr_pct") or 0.0)
                vol_ok = float(cfg.min_atr_pct) <= atr_pct <= float(cfg.max_atr_pct)
                late = bool(indicators.get("late_chase_block"))

                if long_setup:
                    add("long_setup", window_id, symbol)
                    if not vol_ok:
                        add("long_volatility_block", window_id, symbol)
                    elif late:
                        add("long_late_chase_block", window_id, symbol)
                    else:
                        add("long_entry_eligible", window_id, symbol)
                if short_setup:
                    add("short_setup", window_id, symbol)
                    if not vol_ok:
                        add("short_volatility_block", window_id, symbol)
                    elif late:
                        add("short_late_chase_block", window_id, symbol)
                    else:
                        add("short_entry_eligible", window_id, symbol)
                if action == "enter":
                    add("actual_enter", window_id, symbol)
                    side = str(result.get("side") or "").lower()
                    if side == "long":
                        add("actual_long_enter", window_id, symbol)
                    elif side == "short":
                        add("actual_short_enter", window_id, symbol)

    long_setup = counts["long_setup"]
    short_setup = counts["short_setup"]
    total_setup = long_setup + short_setup
    volatility_block = counts["long_volatility_block"] + counts["short_volatility_block"]
    late_block = counts["long_late_chase_block"] + counts["short_late_chase_block"]
    eligible = counts["long_entry_eligible"] + counts["short_entry_eligible"]
    actual = counts["actual_enter"]
    if eligible != actual:
        state = "ROUTING_CONTRACT_MISMATCH"
        next_action = "TRACE_ENTRY_ROUTER_PAYLOAD"
    elif total_setup == 0:
        state = "NO_SETUP_EVIDENCE"
        next_action = "WAIT_NEW_EVIDENCE"
    elif volatility_block == total_setup:
        state = "VOLATILITY_GATE_DOMINATES_ALL_SETUPS"
        next_action = "VERIFY_ATR_PCT_SOURCE_AND_BOUNDS"
    elif volatility_block + late_block == total_setup and eligible == 0:
        state = "VOLATILITY_AND_LATE_CHASE_EXHAUST_ALL_SETUPS"
        next_action = "ONE_BLOCKER_AT_A_TIME_DIAGNOSTIC_ABLATION"
    elif actual > 0:
        state = "CANONICAL_ENTRY_ACTIVE"
        next_action = "REPLAY_ECONOMIC_DIAGNOSIS"
    else:
        state = "PAIRWISE_BLOCKER_DECOMPOSED"
        next_action = "SOURCE_CAUSAL_REVIEW"

    return {
        "state": state,
        "next_action": next_action,
        "call_count": calls,
        "counts": dict(sorted(counts.items())),
        "reason_counts": dict(reasons.most_common()),
        "total_setup_count": total_setup,
        "volatility_block_count": volatility_block,
        "late_chase_block_count_after_vol_ok": late_block,
        "entry_eligible_count": eligible,
        "actual_enter_count": actual,
        "accounting_identity_pass": total_setup == volatility_block + late_block + eligible,
        "eligible_equals_actual_enter": eligible == actual,
        "per_window": {key: dict(sorted(value.items())) for key, value in sorted(per_window.items())},
        "per_symbol": {key: dict(sorted(value.items())) for key, value in sorted(per_symbol.items())},
        "config": {
            "min_atr_pct": float(cfg.min_atr_pct),
            "max_atr_pct": float(cfg.max_atr_pct),
            "max_chase_dist_atr": float(cfg.max_chase_dist_atr),
        },
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
    gate = exact._gate_from(baseline["candidate"])
    surgery = p.surgery_from(baseline.get("surgery"))
    if gate.required or gate.forbidden or surgery is not None:
        raise RuntimeError("EXPECTED_BASE_NO_SURGERY")
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    frames, _, _, manifest = p.load_fresh_data(args.fresh_root.resolve())
    registry = base._load_registry(root)
    registry_row = registry[STRATEGY_ID]
    expected_sha = str(registry_row["canonical_engine"]["source_sha256"])
    source_contract = verify_source_contract(root, expected_sha)
    strategy = base._load_canonical_strategy(root, STRATEGY_ID, registry_row)
    blocker_trace = trace(strategy, symbols, frames, int(manifest["warmup_bars"]), 220)

    result = {
        "schema_version": "strategy11.keltner_pairwise_blocker_trace.v1",
        "version": VERSION,
        "state": "PASS_KELTNER_PAIRWISE_BLOCKER_TRACE",
        "strategy_id": STRATEGY_ID,
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "symbols": list(symbols),
        "source_contract": source_contract,
        "blocker_trace": blocker_trace,
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
    print(result["state"], blocker_trace["state"], blocker_trace["total_setup_count"], blocker_trace["actual_enter_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
