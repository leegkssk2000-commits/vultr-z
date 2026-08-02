from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_COMPOSITE_PINNED_REGISTRY_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def placeholder(value: str) -> bool:
    return len(value) != 64 or len(set(value.casefold())) <= 1


def build(registry: dict[str, Any], pin: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    modules_raw = registry.get("modules") if isinstance(registry.get("modules"), list) else []
    pins_raw = pin.get("modules") if isinstance(pin.get("modules"), list) else []
    pins = {str(row.get("module_id") or ""): row for row in pins_raw if isinstance(row, dict)}
    if len(modules_raw) != 12:
        errors.append("REGISTRY_MODULE_COUNT_NOT_12")
    if len(pins) != 12:
        errors.append("PIN_MODULE_COUNT_NOT_12")
    output_modules: list[dict[str, Any]] = []
    for raw in modules_raw:
        if not isinstance(raw, dict):
            errors.append("REGISTRY_MODULE_NOT_OBJECT")
            continue
        row = dict(raw)
        module_id = str(row.get("module_id") or "")
        bound = pins.get(module_id)
        if not isinstance(bound, dict):
            errors.append(f"PIN_MISSING:{module_id}")
            output_modules.append(row)
            continue
        digest = str(bound.get("source_bundle_sha256") or "")
        if placeholder(digest):
            errors.append(f"PIN_DIGEST_INVALID:{module_id}")
        row["source_sha256"] = digest
        row["source_binding"] = {
            "mode": "GIT_PINNED_LIVE_SOURCE_BUNDLE_SHA256",
            "pin_version": pin.get("version"),
            "pin_inventory_receipt_sha256": pin.get("inventory_receipt_sha256"),
            "selection_policy": bound.get("selection_policy"),
            "source_file_count": bound.get("file_count"),
            "source_paths": bound.get("source_paths"),
        }
        output_modules.append(row)
    ids = [str(row.get("module_id") or "") for row in output_modules]
    if len(set(ids)) != len(ids):
        errors.append("DUPLICATE_MODULE_ID")
    if set(ids) != set(pins):
        errors.append("REGISTRY_PIN_MODULE_SET_MISMATCH")
    output = dict(registry)
    output["generated_from"] = "ZEL_COMPOSITE_LIVE_SOURCE_PIN_V1"
    output["modules"] = output_modules
    safety = dict(output.get("safety") or {})
    safety.update(
        {
            "action": "hold",
            "activation_enabled": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "runtime_discovery_performed": True,
            "source_sha_placeholders_require_rebinding_before_activation": False,
            "source_pin_file_required": True,
        }
    )
    output["safety"] = safety
    placeholder_count = sum(1 for row in output_modules if placeholder(str(row.get("source_sha256") or "")))
    if placeholder_count:
        errors.append("PINNED_REGISTRY_PLACEHOLDER_REMAINS")
    state = "PASS_COMPOSITE_PINNED_REGISTRY" if not errors else "HOLD_COMPOSITE_PINNED_REGISTRY"
    receipt: dict[str, Any] = {
        "schema_version": "zel.composite.pinned_registry.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "module_count": len(output_modules),
        "placeholder_source_sha_count": placeholder_count,
        "unique_source_sha_count": len({str(row.get("source_sha256") or "") for row in output_modules}),
        "registry_sha256": stable_sha(output),
        "pin_sha256": stable_sha(pin),
        "errors": sorted(set(errors)),
        "activation_enabled": False,
        "economic_claim_allowed": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
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
    return output, receipt


def self_test() -> None:
    registry = {
        "modules": [
            {"module_id": f"M{index:02d}", "source_sha256": str(index % 10) * 64}
            for index in range(12)
        ],
        "safety": {},
    }
    pin = {
        "version": "PIN",
        "inventory_receipt_sha256": "f" * 64,
        "modules": [
            {
                "module_id": f"M{index:02d}",
                "source_bundle_sha256": hashlib.sha256(f"M{index:02d}".encode()).hexdigest(),
                "selection_policy": "TEST",
                "file_count": 1,
                "source_paths": [f"m{index}.py"],
            }
            for index in range(12)
        ],
    }
    output, receipt = build(registry, pin)
    assert receipt["state"] == "PASS_COMPOSITE_PINNED_REGISTRY", receipt
    assert receipt["placeholder_source_sha_count"] == 0, receipt
    assert len({row["source_sha256"] for row in output["modules"]}) == 12
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--pin", type=Path)
    parser.add_argument("--out-registry", type=Path)
    parser.add_argument("--out-receipt", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.registry or not args.pin or not args.out_registry or not args.out_receipt:
        parser.error("registry, pin, out-registry and out-receipt are required")
    output, receipt = build(
        json.loads(args.registry.read_text(encoding="utf-8")),
        json.loads(args.pin.read_text(encoding="utf-8")),
    )
    args.out_registry.parent.mkdir(parents=True, exist_ok=True)
    args.out_receipt.parent.mkdir(parents=True, exist_ok=True)
    args.out_registry.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "modules": receipt["module_count"], "placeholders": receipt["placeholder_source_sha_count"], "errors": receipt["errors"]}, sort_keys=True))
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
