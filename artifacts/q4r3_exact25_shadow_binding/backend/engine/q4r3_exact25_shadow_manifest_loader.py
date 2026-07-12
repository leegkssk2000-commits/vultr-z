from __future__ import annotations

import hashlib
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping

EXPECTED_STRATEGY_COUNT = 25
REQUIRED_MEASUREMENT_FIELDS = (
    "strategy_id",
    "owner_sha256",
    "symbol",
    "side",
    "regime",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "stop_price",
    "initial_risk_usdt",
    "realized_pnl_usdt",
    "realized_R",
    "fee",
    "slippage",
    "latency_ms",
    "MFE_R",
    "MAE_R",
    "time_exposure_min",
    "epoch_id",
)


@dataclass(frozen=True)
class ShadowOwner:
    strategy_id: str
    owner_module: str
    owner_path: str
    owner_sha256: str
    strategy: Callable[..., Mapping[str, Any]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def validate_binding_config(config: Mapping[str, Any]) -> None:
    if config.get("schema") != "q4r3_exact25_shadow_binding_v1":
        raise ValueError("BINDING_SCHEMA_MISMATCH")
    if config.get("epoch_id") != "EXACT25_EDGE_V1":
        raise ValueError("EPOCH_ID_MISMATCH")
    if config.get("preexisting_data_label") != "PRE_EXACT25":
        raise ValueError("PREEXISTING_LABEL_MISMATCH")
    if config.get("forward_rows_only") is not True:
        raise ValueError("FORWARD_ONLY_REQUIRED")
    if config.get("historical_r_backfill_allowed") is not False:
        raise ValueError("HISTORICAL_BACKFILL_FORBIDDEN")
    if config.get("shadow_enabled") is not True:
        raise ValueError("SHADOW_FLAG_REQUIRED")
    for key in ("paper_enabled", "live_enabled", "order_enabled", "write_enabled", "canary_enabled"):
        if config.get(key) is not False:
            raise ValueError(f"UNSAFE_BINDING_FLAG:{key}")
    if config.get("dynamic_fallback_allowed") is not False:
        raise ValueError("DYNAMIC_FALLBACK_FORBIDDEN")
    if config.get("authoritative_lifecycle_writer") != "tools/q4r3_vwap_mfe_mae_capture_sidecar.py":
        raise ValueError("AUTHORITATIVE_WRITER_MISMATCH")
    if config.get("secondary_close_writer_mode") != "OBSERVER_ONLY_NOT_BOUND":
        raise ValueError("SECONDARY_WRITER_MUST_REMAIN_OBSERVER")


def load_shadow_registry(
    root: Path,
    manifest_path: Path,
    binding_path: Path,
) -> Dict[str, ShadowOwner]:
    root = root.resolve()
    manifest = _load_json(manifest_path)
    binding = _load_json(binding_path)
    validate_binding_config(binding)

    if manifest.get("schema") != "q4r3_canonical_strategy_owner_manifest_v1":
        raise ValueError("MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("authority_rule") != "ONE_OWNER_PER_STRATEGY_EXACTLY_25_NO_DYNAMIC_FALLBACK":
        raise ValueError("MANIFEST_AUTHORITY_RULE_MISMATCH")
    if manifest.get("dynamic_fallback_allowed") is not False:
        raise ValueError("MANIFEST_DYNAMIC_FALLBACK_FORBIDDEN")

    entries = manifest.get("strategies")
    if not isinstance(entries, list) or len(entries) != EXPECTED_STRATEGY_COUNT:
        raise ValueError("EXACT25_MANIFEST_COUNT_MISMATCH")

    ids = [str(item.get("strategy_id") or "") for item in entries if isinstance(item, dict)]
    if len(ids) != EXPECTED_STRATEGY_COUNT or len(set(ids)) != EXPECTED_STRATEGY_COUNT or any(not item for item in ids):
        raise ValueError("EXACT25_MANIFEST_IDENTITY_MISMATCH")

    registry: Dict[str, ShadowOwner] = {}
    old_path = list(sys.path)
    sys.path.insert(0, str(root))
    try:
        for entry in entries:
            strategy_id = str(entry["strategy_id"])
            owner_module = str(entry["owner_module"])
            owner_rel = str(entry["owner_path"])
            owner_sha = str(entry["owner_sha256"])
            if entry.get("contract_pass") is not True:
                raise ValueError(f"CONTRACT_NOT_PASSED:{strategy_id}")
            if entry.get("enabled_for_paper") is not False or entry.get("enabled_for_live") is not False:
                raise ValueError(f"UNSAFE_MANIFEST_EXECUTION_FLAG:{strategy_id}")

            owner_path = (root / owner_rel).resolve()
            if root not in owner_path.parents:
                raise ValueError(f"OWNER_PATH_ESCAPES_ROOT:{strategy_id}")
            if not owner_path.is_file():
                raise FileNotFoundError(f"OWNER_FILE_MISSING:{strategy_id}:{owner_path}")
            if _sha256(owner_path) != owner_sha:
                raise ValueError(f"OWNER_SHA_MISMATCH:{strategy_id}")

            importlib.invalidate_caches()
            module = importlib.import_module(owner_module)
            module_file = Path(str(getattr(module, "__file__", ""))).resolve()
            if module_file != owner_path:
                raise ValueError(f"OWNER_IMPORT_PATH_MISMATCH:{strategy_id}:{module_file}")
            strategy_fn = getattr(module, "strategy", None)
            if not callable(strategy_fn):
                raise ValueError(f"STRATEGY_CALLABLE_MISSING:{strategy_id}")

            registry[strategy_id] = ShadowOwner(
                strategy_id=strategy_id,
                owner_module=owner_module,
                owner_path=owner_rel,
                owner_sha256=owner_sha,
                strategy=strategy_fn,
            )
    finally:
        sys.path[:] = old_path

    return registry


def decorate_measurement_event(
    event: Mapping[str, Any],
    owner: ShadowOwner,
    binding: Mapping[str, Any],
) -> Dict[str, Any]:
    result = dict(event)
    result["strategy_id"] = owner.strategy_id
    result["owner_sha256"] = owner.owner_sha256
    result["epoch_id"] = str(binding["epoch_id"])
    result["measurement_namespace"] = "forward_only"
    result["paper_enabled"] = False
    result["live_enabled"] = False
    result["order_enabled"] = False
    return result


def validate_closed_measurement_row(row: Mapping[str, Any]) -> None:
    missing = [field for field in REQUIRED_MEASUREMENT_FIELDS if field not in row]
    if missing:
        raise ValueError("MEASUREMENT_FIELDS_MISSING:" + ",".join(missing))
    if row.get("epoch_id") != "EXACT25_EDGE_V1":
        raise ValueError("MEASUREMENT_EPOCH_MISMATCH")
    initial_risk = float(row.get("initial_risk_usdt") or 0.0)
    if initial_risk <= 0:
        raise ValueError("INITIAL_RISK_MUST_BE_POSITIVE")
    realized_r = float(row.get("realized_R"))
    realized_pnl = float(row.get("realized_pnl_usdt"))
    expected = realized_pnl / initial_risk
    if abs(realized_r - expected) > 1e-9:
        raise ValueError("REALIZED_R_FORMULA_MISMATCH")
