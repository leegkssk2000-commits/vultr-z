from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "ZEL_TRADE_METHOD_RUNTIME_BEHAVIOR_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def strategy_ids_from_trades(path: Path) -> list[str]:
    values: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            row = json.loads(raw)
            if isinstance(row, dict):
                strategy_id = str(row.get("strategy_id") or row.get("strategy") or "")
                if strategy_id:
                    values.add(strategy_id)
    return sorted(values)


def strategy_ids_from_checkpoints(root: Path) -> list[str]:
    values: set[str] = set()
    for path in sorted(root.glob("*.json.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            strategy_id = str((payload.get("result") or {}).get("strategy_id") or "")
            if strategy_id:
                values.add(strategy_id)
        except Exception:
            continue
    return sorted(values)


def build(source_root: Path, strategy_ids: Iterable[str]) -> dict[str, Any]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    try:
        module = importlib.import_module("backend.trade_methods.resolver")
    except Exception as exc:
        module = None
        errors.append(f"IMPORT:{type(exc).__name__}:{exc}")
    if module is not None:
        for strategy_id in sorted(set(str(value) for value in strategy_ids if str(value))):
            try:
                result = module.h74tm8_resolve_trade_method(strategy_id, [], 0.0)
                if not isinstance(result, dict):
                    raise RuntimeError("RESULT_NOT_OBJECT")
                rows.append(
                    {
                        "strategy_id": strategy_id,
                        "decision": result.get("decision"),
                        "action": result.get("action"),
                        "registry_enabled": result.get("registry_enabled"),
                        "size_multiplier": result.get("size_multiplier"),
                        "target_r": result.get("target_r"),
                        "execution_authority": result.get("execution_authority"),
                        "order_authority": result.get("order_authority"),
                        "paper_execution_allowed": result.get("paper_execution_allowed"),
                        "live_execution_allowed": result.get("live_execution_allowed"),
                    }
                )
            except Exception as exc:
                errors.append(f"{strategy_id}:{type(exc).__name__}:{exc}")
    unsafe = [
        row
        for row in rows
        if str(row.get("execution_authority") or "").upper() != "NONE"
        or str(row.get("order_authority") or "").upper() != "BLOCKED"
        or row.get("paper_execution_allowed") is not False
        or row.get("live_execution_allowed") is not False
    ]
    enabled = [
        row
        for row in rows
        if row.get("registry_enabled") is True or safe_float(row.get("size_multiplier")) > 0.0
    ]
    if errors:
        state = "HOLD_TRADE_METHOD_BEHAVIOR_ERRORS"
    elif unsafe:
        state = "HOLD_TRADE_METHOD_AUTHORITY_UNSAFE"
    elif enabled:
        state = "HOLD_TRADE_METHOD_ENABLED_COUNTERFACTUAL_ADAPTER_REQUIRED"
    elif rows:
        state = "PASS_TRADE_METHOD_DISABLED_HOLD_BEHAVIOR"
    else:
        state = "HOLD_TRADE_METHOD_NO_STRATEGIES"
    receipt: dict[str, Any] = {
        "schema_version": "zel.trade_method.runtime_behavior.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "strategy_count": len(rows),
        "enabled_strategy_count": len(enabled),
        "unsafe_strategy_count": len(unsafe),
        "distinct_behavior_count": len({stable_sha(row) for row in rows}),
        "rows": rows,
        "errors": errors,
        "credentials_read": False,
        "network_requested": False,
        "writes_requested": False,
        "active_data_b_1m_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> None:
    assert safe_float("0") == 0.0
    assert safe_float("nan") == 0.0
    assert stable_sha({"a": 1}) == stable_sha({"a": 1})
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--checkpoints", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.trades:
        strategy_ids = strategy_ids_from_trades(args.trades)
    elif args.checkpoints:
        strategy_ids = strategy_ids_from_checkpoints(args.checkpoints)
    else:
        parser.error("trades or checkpoints is required")
    row = build(args.source_root.resolve(), strategy_ids)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
