from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

EXPECTED_25: Tuple[str, ...] = (
    "alpha_combo", "anchor_vwap_trend", "bb_revert", "break_and_continue",
    "ema_ribbon_scalp", "fvg_revert", "grid_rebalance", "keltner_trend",
    "liquidity_sweep", "mfi_rsi_div", "obv_trend", "pivot_reversal",
    "range_fade", "rbreaker_like", "rsi_swing_fail", "scalp_snap",
    "session_bias", "squeeze_break", "sr_levels", "supertrend_pullback",
    "trend_ma_macd", "trend_rider", "turtle_trend", "vol_spike_fade",
    "vwap_revert",
)
REQUIRED_KEYS = {
    "side", "action", "size", "entry", "sl", "tp", "pyramiding",
    "why", "skill", "confidence", "tags", "indicators",
}


@dataclass
class StrategySmoke:
    strategy_id: str
    module: str
    owner_path: str
    sha_match: bool
    module_origin_match: bool
    import_ok: bool
    signature_ok: bool
    empty_contract_ok: bool
    block_contract_ok: bool
    synthetic_contract_ok: bool
    elapsed_ms: int
    error: Optional[str]

    @property
    def passed(self) -> bool:
        return all((
            self.sha_match,
            self.module_origin_match,
            self.import_ok,
            self.signature_ok,
            self.empty_contract_ok,
            self.block_contract_ok,
            self.synthetic_contract_ok,
            self.error is None,
        ))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def synthetic_frame(rows: int = 360) -> pd.DataFrame:
    x = np.arange(rows, dtype=float)
    close = 100.0 + 0.018 * x + 1.25 * np.sin(x / 11.0) + 0.35 * np.sin(x / 3.0)
    open_ = close + 0.08 * np.sin(x / 5.0)
    high = np.maximum(open_, close) + 0.30 + 0.04 * np.cos(x / 7.0)
    low = np.minimum(open_, close) - 0.30 - 0.04 * np.sin(x / 8.0)
    volume = 1000.0 + 120.0 * np.sin(x / 9.0) + np.where((x.astype(int) % 47) == 0, 900.0, 0.0)
    timestamp = pd.date_range("2026-01-01", periods=rows, freq="min", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamp,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def finite_or_none(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float, np.integer, np.floating)):
        return math.isfinite(float(value))
    return True


def validate_output(value: Any, require_hold: bool = False) -> bool:
    if not isinstance(value, Mapping):
        return False
    if not REQUIRED_KEYS.issubset(value.keys()):
        return False
    if require_hold:
        if str(value.get("action")) != "hold":
            return False
        try:
            if float(value.get("size") or 0.0) != 0.0:
                return False
        except (TypeError, ValueError):
            return False
    for key in ("size", "entry", "sl", "tp", "confidence"):
        if not finite_or_none(value.get(key)):
            return False
    return True


def worker(active_root: Path, strategy_id: str, module_name: str, owner_path: str, expected_sha: str) -> Dict[str, Any]:
    started = time.monotonic()
    target = (active_root / owner_path).resolve()
    before_sha = sha256(target)
    error: Optional[str] = None
    origin_match = False
    import_ok = False
    signature_ok = False
    empty_ok = False
    block_ok = False
    synthetic_ok = False

    try:
        os.chdir(active_root)
        sys.path.insert(0, str(active_root))
        for name in list(sys.modules):
            if name == module_name or name.startswith(module_name + "."):
                sys.modules.pop(name, None)
        module = importlib.import_module(module_name)
        import_ok = True
        module_file = Path(inspect.getfile(module)).resolve()
        origin_match = module_file == target
        fn = getattr(module, "strategy", None)
        if not callable(fn):
            raise RuntimeError("STRATEGY_CALLABLE_MISSING")
        params = set(inspect.signature(fn).parameters)
        signature_ok = {"df", "state", "risk_action"}.issubset(params)
        if not signature_ok:
            raise RuntimeError("STRATEGY_SIGNATURE_INCOMPLETE")

        empty = fn(pd.DataFrame(), state=None, risk_action="hold")
        empty_ok = validate_output(empty, require_hold=True)
        blocked = fn(synthetic_frame(), state=None, risk_action="block")
        block_ok = validate_output(blocked, require_hold=True)
        synthetic = fn(synthetic_frame(), state=None, risk_action="hold")
        synthetic_ok = validate_output(synthetic, require_hold=False)
    except Exception as exc:
        error = f"{type(exc).__name__}:{str(exc)[:300]}"

    after_sha = sha256(target)
    return {
        "strategy_id": strategy_id,
        "module": module_name,
        "owner_path": owner_path,
        "sha_match": before_sha == expected_sha == after_sha,
        "module_origin_match": origin_match,
        "import_ok": import_ok,
        "signature_ok": signature_ok,
        "empty_contract_ok": empty_ok,
        "block_contract_ok": block_ok,
        "synthetic_contract_ok": synthetic_ok,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "error": error,
    }


def run_parent(active_root: Path, manifest_path: Path, output_path: Path, timeout_sec: int) -> Dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("strategies") or []
    ids = [str(entry.get("strategy_id")) for entry in entries]
    exact_25 = len(entries) == 25 and len(set(ids)) == 25 and set(ids) == set(EXPECTED_25)
    flags_safe = all(
        entry.get(flag) is False
        for entry in entries
        for flag in ("enabled_for_shadow", "enabled_for_paper", "enabled_for_live")
    )

    checks: List[StrategySmoke] = []
    for entry in sorted(entries, key=lambda item: str(item.get("strategy_id"))):
        command = [
            sys.executable, str(Path(__file__).resolve()), "--worker",
            "--active-root", str(active_root),
            "--strategy-id", str(entry["strategy_id"]),
            "--module", str(entry["owner_module"]),
            "--owner-path", str(entry["owner_path"]),
            "--expected-sha", str(entry["owner_sha256"]),
        ]
        try:
            proc = subprocess.run(
                command,
                cwd=str(active_root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_sec,
                env={**os.environ, "PYTHONPATH": str(active_root), "PYTHONDONTWRITEBYTECODE": "1"},
            )
            if proc.returncode != 0:
                payload = {
                    "strategy_id": entry["strategy_id"], "module": entry["owner_module"],
                    "owner_path": entry["owner_path"], "sha_match": False,
                    "module_origin_match": False, "import_ok": False, "signature_ok": False,
                    "empty_contract_ok": False, "block_contract_ok": False,
                    "synthetic_contract_ok": False, "elapsed_ms": 0,
                    "error": f"WORKER_EXIT_{proc.returncode}:{proc.stderr[-300:]}",
                }
            else:
                payload = json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            payload = {
                "strategy_id": entry["strategy_id"], "module": entry["owner_module"],
                "owner_path": entry["owner_path"], "sha_match": False,
                "module_origin_match": False, "import_ok": False, "signature_ok": False,
                "empty_contract_ok": False, "block_contract_ok": False,
                "synthetic_contract_ok": False, "elapsed_ms": timeout_sec * 1000,
                "error": "WORKER_TIMEOUT",
            }
        checks.append(StrategySmoke(**payload))

    pass_count = sum(check.passed for check in checks)
    if exact_25 and flags_safe and pass_count == 25:
        verdict = "EXACT25_ACTIVE_RUNTIME_SMOKE_PASS_READY_FOR_SHADOW_BIND_DESIGN"
        next_action = "BUILD_ROLLBACK_GUARDED_SHADOW_ONLY_MANIFEST_LOADER"
    else:
        verdict = "EXACT25_ACTIVE_RUNTIME_SMOKE_GAPS_REMAIN"
        next_action = "HOLD_AND_PATCH_ONLY_REPORTED_RUNTIME_SMOKE_GAPS"

    result = {
        "schema": "q4r3_exact25_active_runtime_smoke_v1",
        "status": "PASS_Q4R3_EXACT25_ACTIVE_RUNTIME_SMOKE_AUDIT",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(manifest_path),
        "exact_25": exact_25,
        "all_execution_flags_false": flags_safe,
        "strategy_smoke_pass_count": pass_count,
        "strategy_smoke_gap_count": 25 - pass_count,
        "checks": [asdict(check) | {"passed": check.passed} for check in checks],
        "safety": {
            "runtime_registry_bound": False,
            "shadow_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
            "production_files_modified": False,
            "persistent_forward_r_watcher_modified": False,
        },
    }
    atomic_json(output_path, result)
    print(json.dumps({
        "status": result["status"], "verdict": verdict,
        "pass": pass_count, "gaps": 25 - pass_count,
        "next_action": next_action,
    }, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--output-path", type=Path)
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--strategy-id")
    parser.add_argument("--module")
    parser.add_argument("--owner-path")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()

    if args.worker:
        payload = worker(
            args.active_root.resolve(), str(args.strategy_id), str(args.module),
            str(args.owner_path), str(args.expected_sha),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return

    manifest = args.manifest_path or args.active_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
    output = args.output_path or args.active_root / "runtime/q4r3_exact25_active_runtime_smoke_latest.json"
    run_parent(args.active_root.resolve(), manifest.resolve(), output.resolve(), args.timeout_sec)


if __name__ == "__main__":
    main()
