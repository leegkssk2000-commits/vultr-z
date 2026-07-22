from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_FROZEN_SOURCE_AUDIT"])
    spec = importlib.util.spec_from_file_location("frozen_source_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen_manifest() -> dict:
    return {"state": "PASS"}


def selected_manifest() -> dict:
    return {
        "state": "PASS",
        "selected_segments": [
            {"segment_id": "s1", "source_path": "data/BTCUSDT.json"},
            {"segment_id": "s2", "source_path": "data/ETHUSDT.json"},
            {"segment_id": "s3", "source_path": "data/SOLUSDT.json"},
        ],
    }


def accepted_sources() -> list[dict]:
    return [
        {
            "path": "data/BTCUSDT.json",
            "required_by_selected_manifest": True,
            "symbol": "BTCUSDT",
            "derivable_timeframes": ["5m", "15m"],
        },
        {
            "path": "data/ETHUSDT.json",
            "required_by_selected_manifest": True,
            "symbol": "ETHUSDT",
            "derivable_timeframes": ["5m", "15m"],
        },
        {
            "path": "data/SOLUSDT.json",
            "required_by_selected_manifest": True,
            "symbol": "SOLUSDT",
            "derivable_timeframes": ["5m", "15m"],
        },
    ]


def test_auxiliary_rejects_do_not_block_canonical_allowlist() -> None:
    module = load_module()
    rejected = [
        {
            "path": "backend/contracts/market_data_freshness.schema.json",
            "required_by_selected_manifest": False,
            "path_role": "AUXILIARY_CONTRACT_OR_METADATA",
            "reason": "ValueError:MARKET_COLUMNS_MISSING:open,high,low,close",
            "reason_class": "OHLC_SCHEMA_MISSING",
            "blocking": False,
        }
    ]
    audit, blockers = module.build_audit(frozen_manifest(), selected_manifest(), accepted_sources(), rejected)
    assert blockers == []
    assert audit["state"] == "PASS_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT"
    assert audit["auxiliary_rejected_source_count"] == 1
    assert audit["auxiliary_rejects_blocking"] is False
    assert audit["canonical_allowlist_source_count"] == 3
    assert audit["next_stage"] == "R7.A4D2_SHORT_SCALP_TIMEFRAME_REDESIGN_PLAN_SOURCE_ALLOWLIST_BIND"


def test_required_selected_source_reject_fail_closes() -> None:
    module = load_module()
    accepted = accepted_sources()[:2]
    rejected = [
        {
            "path": "data/SOLUSDT.json",
            "required_by_selected_manifest": True,
            "path_role": "MARKET_DATA_CANDIDATE",
            "reason": "ValueError:FROZEN_SHA_MISMATCH",
            "reason_class": "SHA_MISMATCH",
            "blocking": True,
        }
    ]
    audit, blockers = module.build_audit(frozen_manifest(), selected_manifest(), accepted, rejected)
    assert "REQUIRED_MARKET_SOURCE_REJECTED:1" in blockers
    assert audit["state"] == "HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT"


def test_allowlist_requires_three_symbols_and_both_timeframes() -> None:
    module = load_module()
    accepted = accepted_sources()
    accepted[2]["symbol"] = "ETHUSDT"
    accepted[2]["derivable_timeframes"] = ["5m"]
    audit, blockers = module.build_audit(frozen_manifest(), selected_manifest(), accepted, [])
    assert any(item.startswith("CANONICAL_ALLOWLIST_SOURCE_LT_3") for item in blockers)
    assert any(item.startswith("CANONICAL_ALLOWLIST_SYMBOL_LT_3") for item in blockers)
    assert audit["state"] == "HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT"


def test_path_and_reason_classification_are_deterministic() -> None:
    module = load_module()
    assert module.path_role("_backups/x/contracts/market.schema.json") == "AUXILIARY_BACKUP_OR_PATCH"
    assert module.path_role("backend/contracts/market.schema.json") == "AUXILIARY_CONTRACT_OR_METADATA"
    assert module.classify_reason("ValueError:MARKET_COLUMNS_MISSING:open") == "OHLC_SCHEMA_MISSING"
    assert module.classify_reason("ValueError:FROZEN_SHA_MISMATCH") == "SHA_MISMATCH"
