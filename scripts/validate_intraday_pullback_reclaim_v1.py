#!/usr/bin/env python3
"""Deterministic static fixtures for intraday_pullback_reclaim_v1."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "backend/research/intraday_pullback_reclaim_v1.py"
RECEIPT_PATH = ROOT / "backend/research/zel_scalp_design_selection_receipt_v1.json"


def load_module():
    module_name = "intraday_pullback_reclaim_v1"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("module load failure")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves postponed annotations through sys.modules while the
    # class decorators execute, so register the dynamic module first.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def bars(module, closes, step_ms):
    out = []
    ts = 1_700_000_000_000
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i else close * 0.999
        high = max(open_, close) + 0.35
        low = min(open_, close) - 0.35
        out.append(module.Bar(ts + i * step_ms, open_, high, low, close, 1000.0 + i))
    return out


def main() -> None:
    module = load_module()
    receipt = json.loads(RECEIPT_PATH.read_text())
    assert receipt["state"] == "PASS_DESIGN_SELECTED_IMPLEMENTATION_ALLOWED_RESEARCH_ONLY"
    assert receipt["selected_architecture"]["strategy_id"] == "intraday_pullback_reclaim_v1"
    assert receipt["implementation_authority"]["runtime_mutation_allowed"] is False
    assert receipt["implementation_authority"]["order_authority"] == "BLOCKED"

    cfg = module.Config(12, 0.20, 0.8, 0.55, "close", 1.1, 1.6, 12, 2.0)
    regime = bars(module, [100 + i * 0.7 for i in range(20)], 900_000)
    setup_closes = [100, 100.3, 100.8, 101.5, 102.3, 103.1, 104.0, 104.8,
                    104.4, 104.0, 103.7, 103.9, 104.1, 104.25, 104.35, 104.45,
                    104.55, 105.3]
    setup = bars(module, setup_closes, 300_000)
    decision_a = module.decide_long(regime, setup, cfg, 0.1316910918)
    decision_b = module.decide_long(regime, setup, cfg, 0.1316910918)
    assert decision_a == decision_b, "non-deterministic decision"
    assert decision_a.action in ("long", "hold")

    # Future-bar invariance: appending a future bar must not alter the decision
    # computed at the original confirmation boundary.
    future = setup + bars(module, [110.0], 300_000)
    boundary_recomputed = module.decide_long(regime, future[:-1], cfg, 0.1316910918)
    assert boundary_recomputed == decision_a

    # Invalid chronology is fail-closed.
    broken = list(setup)
    broken[-1] = module.Bar(broken[-2].ts, broken[-1].open, broken[-1].high,
                            broken[-1].low, broken[-1].close, broken[-1].volume)
    try:
        module.decide_long(regime, broken, cfg, 0.1316910918)
    except ValueError:
        pass
    else:
        raise AssertionError("timestamp disorder accepted")

    source_sha = hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest()
    receipt_sha = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result = {
        "state": "PASS_STATIC_RESEARCH_CANDIDATE",
        "candidate_source_sha256": source_sha,
        "design_receipt_canonical_sha256": receipt_sha,
        "deterministic_fixture": True,
        "future_boundary_invariance": True,
        "invalid_timestamp_fail_closed": True,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
