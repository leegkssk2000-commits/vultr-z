from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import types
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_bnc_prior_box_repair_v1 as prior_box
from backend.tools import r7a4d_strategy11_bnc_setup_intersection_trace_v1 as intersection
from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair
prior = replay.prior

STRATEGY_ID = "break_and_continue"
SOURCE_PATH = Path("backend/strategies/break_and_continue.py")
VERSION = "R7A4D_STRATEGY11_BNC_NONOVERLAP_WINDOW_REPAIR_V1"
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


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def metric(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def load_nonoverlap_strategy(root: Path, expected_source_sha: str) -> tuple[Any, dict[str, Any]]:
    path = (root / SOURCE_PATH).resolve()
    source = path.read_text(encoding="utf-8")
    source_sha = sha_text(source)
    if source_sha != expected_source_sha:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source_sha}:{expected_source_sha}")
    replacements = (
        (
            '    b_start = -(cfg.breakout_bars + cfg.box_bars)',
            '    b_start = -(cfg.breakout_bars + cfg.box_bars + 1)',
        ),
        (
            '    b_end = -cfg.box_bars',
            '    b_end = -(cfg.box_bars + 1)',
        ),
        (
            '    box = df.iloc[-cfg.box_bars:]',
            '    box = df.iloc[-(cfg.box_bars + 1):-1]',
        ),
    )
    patched = source
    rows = []
    for old, new in replacements:
        count = patched.count(old)
        if count != 1:
            raise RuntimeError(f"SOURCE_REPLACEMENT_COUNT:{sha_text(old)}:{count}")
        patched = patched.replace(old, new, 1)
        rows.append({"old_sha": sha_text(old), "new_sha": sha_text(new), "count": 1})
    module_name = "backend.strategies.break_and_continue_research_nonoverlap_v1"
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = "backend.strategies"
    sys.modules[module_name] = module
    try:
        exec(compile(patched, str(path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    strategy = module.__dict__.get("strategy")
    config_type = module.__dict__.get("BreakAndContinueConfig")
    if not callable(strategy) or config_type is None:
        raise RuntimeError("PATCHED_STRATEGY_CONTRACT_MISSING")
    cfg = config_type()
    breakout_indices = list(range(-(cfg.breakout_bars + cfg.box_bars + 1), -(cfg.box_bars + 1)))
    box_indices = list(range(-(cfg.box_bars + 1), -1))
    if len(breakout_indices) != cfg.breakout_bars or len(box_indices) != cfg.box_bars:
        raise RuntimeError("WINDOW_LENGTH_MISMATCH")
    if set(breakout_indices).intersection(box_indices):
        raise RuntimeError("WINDOW_OVERLAP_REMAINS")
    if max(breakout_indices) + 1 != min(box_indices):
        raise RuntimeError("WINDOWS_NOT_ADJACENT")
    return strategy, {
        "canonical_source_sha": source_sha,
        "patched_source_sha": sha_text(patched),
        "semantic_change_count": 1,
        "text_replacement_count": len(replacements),
        "semantic_change": "OVERLAPPING_BREAKOUT_BOX_TO_ADJACENT_NONOVERLAP_WINDOWS",
        "threshold_changed": False,
        "breakout_bars_unchanged": int(cfg.breakout_bars),
        "box_bars_unchanged": int(cfg.box_bars),
        "breakout_indices": breakout_indices,
        "box_indices": box_indices,
        "overlap_count": 0,
        "adjacent": True,
        "replacements": rows,
    }


def compare(candidate: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    loss = candidate.get("loss_metrics") or {}
    stress = (candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}
    checks = {
        "trades_recovered": int(candidate.get("trade_count") or 0) > int(control.get("trade_count") or 0),
        "minimum_trades": int(candidate.get("trade_count") or 0) >= 5,
        "net_positive": metric(candidate.get("net_return_pct_sum")) > 0.0,
        "pf_above_one": metric(candidate.get("net_profit_factor")) > 1.0,
        "positive_windows_pct": metric(candidate.get("positive_fresh_windows_pct")) >= 66.67,
        "worst_loss_l090": metric(loss.get("normal_worst_net_loss_R"), -math.inf) >= -0.90,
        "stress_worst_l095": metric(stress.get("normal_worst_net_loss_R"), -math.inf) >= -0.95,
        "parity_pass": candidate.get("parity", {}).get("state") == "PASS",
        "duplicate_zero": int(candidate.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
    }
    return {
        "state": "PASS_DIAGNOSTIC_REPAIR" if all(checks.values()) else "PARTIAL_REPAIR_ONLY",
        "checks": checks,
        "trade_delta": int(candidate.get("trade_count") or 0) - int(control.get("trade_count") or 0),
        "net_delta_pct_points": metric(candidate.get("net_return_pct_sum")) - metric(control.get("net_return_pct_sum")),
        "ai_review_state": "WAIT_GROQ_QUOTA",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    baseline = json.loads(prior.find_summary(args.evidence_root.resolve(), STRATEGY_ID).read_text(encoding="utf-8"))
    source_config = baseline["candidate"]
    gate = exact._gate_from(source_config)
    surgery = p.surgery_from(baseline.get("surgery"))
    if gate.required or gate.forbidden or surgery is not None:
        raise RuntimeError("EXPECTED_BASE_NO_SURGERY")
    exit_spec = exact._exit_from(source_config)
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    frames, features, funding, manifest = p.load_fresh_data(args.fresh_root.resolve())
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = repair.market_sha_map(manifest)
    registry = base._load_registry(root)
    registry_row = registry[STRATEGY_ID]
    source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    overlapping_control, overlap_manifest = prior_box.load_patched_strategy(root, source_sha)
    candidate_strategy, repair_manifest = load_nonoverlap_strategy(root, source_sha)
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    normal_cap = float(policy["loss_ladder"][0]["normal_worst_net_loss_R_min"])
    stress_cap = float(policy["loss_ladder"][0]["stress_worst_net_loss_R_min"])

    before = intersection.trace(overlapping_control, symbols, frames, int(manifest["warmup_bars"]), 220)
    after = intersection.trace(candidate_strategy, symbols, frames, int(manifest["warmup_bars"]), 220)
    common = {
        "gate": gate,
        "surgery": surgery,
        "symbols": symbols,
        "frames": frames,
        "features": features,
        "funding": funding,
        "quantiles": quantiles,
        "manifest": manifest,
        "market_shas": market_shas,
        "strategy_source_sha": source_sha,
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "normal_cap_r": normal_cap,
        "stress_cap_r": stress_cap,
        "out": args.out.resolve() / STRATEGY_ID,
    }
    control = replay.evaluate(
        variant_id="CONTROL_OVERLAPPING_PRIOR_BOX",
        config={
            **source_config,
            "candidate_id": "CONTROL_OVERLAPPING_PRIOR_BOX",
            "axis": "CONTROL",
            "repair": overlap_manifest,
        },
        exit_spec=exit_spec,
        strategy=overlapping_control,
        **common,
    )
    candidate = replay.evaluate(
        variant_id="NONOVERLAP_BREAKOUT_PRIOR_BOX",
        config={
            **source_config,
            "candidate_id": "NONOVERLAP_BREAKOUT_PRIOR_BOX",
            "axis": "WINDOW_BOUNDARY_DEFINITION",
            "repair": repair_manifest,
        },
        exit_spec=exit_spec,
        strategy=candidate_strategy,
        **common,
    )
    relation = compare(candidate, control)
    result = {
        "schema_version": "strategy11.bnc_nonoverlap_window_repair.v1",
        "version": VERSION,
        "state": "PASS_BNC_NONOVERLAP_WINDOW_DIAGNOSTIC_COMPLETE",
        "strategy_id": STRATEGY_ID,
        "strategy_source_sha": source_sha,
        "before_trace": before,
        "after_trace": after,
        "control_repair": overlap_manifest,
        "repair": repair_manifest,
        "control": {
            "trade_count": control.get("trade_count"),
            "net_pct": control.get("net_return_pct_sum"),
            "summary_sha": stable_sha(control),
        },
        "candidate": {
            "trade_count": candidate.get("trade_count"),
            "win_rate_pct": candidate.get("win_rate_pct"),
            "net_pct": candidate.get("net_return_pct_sum"),
            "profit_factor": candidate.get("net_profit_factor"),
            "payoff": candidate.get("payoff_ratio"),
            "max_drawdown_pct": candidate.get("max_drawdown_pct"),
            "avg_loss_r": (candidate.get("loss_metrics") or {}).get("avg_loss_R"),
            "worst_loss_r": (candidate.get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "stress_worst_loss_r": ((candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "positive_windows_pct": candidate.get("positive_fresh_windows_pct"),
            "relation": relation,
            "summary_sha": stable_sha(candidate),
        },
        "canonical_source_modified": False,
        "registry_modified": False,
        "thresholds_modified": False,
        "next": "CANONICAL_MINIMAL_PATCH_REVIEW" if relation["state"] == "PASS_DIAGNOSTIC_REPAIR" else "DECOMPOSE_BNC_NONOVERLAP_RESULTS_OR_WAIT_W1",
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        **SAFETY,
    }
    result["diagnostic_sha"] = stable_sha(result)
    atomic_json(args.out.resolve() / "final.json", result)
    print(result["state"], before["dominant_first_blocker_count"], after["actual_enter_count"], candidate.get("trade_count"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
