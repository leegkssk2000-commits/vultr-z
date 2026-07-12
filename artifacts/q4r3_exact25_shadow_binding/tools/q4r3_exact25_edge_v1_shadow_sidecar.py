from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get("Q4R3_ROOT", "/home/z/z"))
MANIFEST = ROOT / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
BINDING = ROOT / "backend/config/q4r3_exact25_shadow_binding_v1.json"
LOADER_DIR = ROOT / "backend/engine"


def synthetic_ohlcv(rows: int = 420) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="min", tz="UTC")
    trend = np.linspace(100.0, 104.0, rows)
    cycle = np.sin(np.linspace(0.0, 18.0, rows)) * 0.8
    close = trend + cycle
    open_ = close - np.sin(np.linspace(0.0, 8.0, rows)) * 0.08
    high = np.maximum(open_, close) + 0.25
    low = np.minimum(open_, close) - 0.25
    volume = 1000.0 + np.cos(np.linspace(0.0, 24.0, rows)) * 150.0
    return pd.DataFrame(
        {
            "timestamp": index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def load_components():
    sys.path.insert(0, str(LOADER_DIR))
    try:
        from q4r3_exact25_shadow_manifest_loader import (  # type: ignore
            decorate_measurement_event,
            load_shadow_registry,
            validate_binding_config,
        )
    finally:
        if sys.path and sys.path[0] == str(LOADER_DIR):
            sys.path.pop(0)
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    validate_binding_config(binding)
    registry = load_shadow_registry(ROOT, MANIFEST, BINDING)
    return binding, registry, decorate_measurement_event


def dry_run() -> Dict[str, Any]:
    binding, registry, decorate = load_components()
    frame = synthetic_ohlcv()
    checks = []
    for strategy_id, owner in sorted(registry.items()):
        issues = []
        try:
            result = owner.strategy(frame.copy(), state=None, risk_action="hold")
            if not isinstance(result, dict):
                issues.append("result_not_dict")
                result = {}
            if "action" not in result or "size" not in result:
                issues.append("signal_contract_incomplete")
            decorated = decorate(
                {
                    "event_type": "signal_dry_run",
                    "symbol": "BTCUSDT",
                    "side": str(result.get("side") or "flat"),
                    "regime": "synthetic_smoke",
                    "entry_ts": None,
                    "exit_ts": None,
                    "entry_price": result.get("entry"),
                    "stop_price": result.get("sl"),
                    "initial_risk_usdt": None,
                    "realized_pnl_usdt": None,
                    "realized_R": None,
                    "fee": 0.0,
                    "slippage": 0.0,
                    "latency_ms": 0.0,
                    "MFE_R": None,
                    "MAE_R": None,
                    "time_exposure_min": 0.0,
                },
                owner,
                binding,
            )
            if decorated.get("epoch_id") != "EXACT25_EDGE_V1":
                issues.append("epoch_decoration_failed")
            if any(decorated.get(key) is not False for key in ("paper_enabled", "live_enabled", "order_enabled")):
                issues.append("unsafe_execution_flag")
        except Exception as exc:
            issues.append(f"exception:{type(exc).__name__}:{str(exc)[:160]}")
        checks.append({"strategy_id": strategy_id, "issues": issues, "pass": not issues})

    passed = sum(bool(item["pass"]) for item in checks)
    return {
        "schema": "q4r3_exact25_edge_v1_shadow_sidecar_dry_run_v1",
        "status": "PASS" if passed == 25 else "HOLD",
        "verdict": "EXACT25_SHADOW_SIDECAR_DRY_RUN_PASS" if passed == 25 else "EXACT25_SHADOW_SIDECAR_DRY_RUN_GAPS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "epoch_id": binding["epoch_id"],
        "strategy_count": len(checks),
        "pass_count": passed,
        "gap_count": len(checks) - passed,
        "write_enabled": False,
        "canary_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.dry_run:
        raise SystemExit("ONLY_DRY_RUN_ALLOWED_IN_STAGED_BIND")
    result = dry_run()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps({key: result[key] for key in ("status", "verdict", "strategy_count", "pass_count", "gap_count")}, ensure_ascii=False))
    raise SystemExit(0 if result["gap_count"] == 0 else 2)


if __name__ == "__main__":
    main()
