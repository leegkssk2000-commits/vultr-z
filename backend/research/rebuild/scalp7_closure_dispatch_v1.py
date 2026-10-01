"""Thin bounded synthetic caller for the new Exact25 lifecycle repairs.

The original catalog and frozen five remain immutable. These new research
models grant no genuine-history execution, orders, LIVE, or promotion.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

import pandas as pd

from backend.research.rebuild.scalp7_exact25_pipeline_v1 import EXACT25
from backend.research.rebuild.scalp7_volume_contract_v1 import evaluate_volume_component

MODEL_ROUTES = {
    "HG1997_FIRST_PULLBACK_STOP_V1": ("scalp7_hg_closure_v1", ("keltner_trend",)),
    "KELL_BASE_BREAK_HTF15_PARTIAL_PIVOT_V1": (
        "scalp7_kell_gajjala_closure_v1",
        ("ema_ribbon_scalp",),
    ),
    "GAJJALA_FLAG15_CRYPTO_PARTIAL_PIVOT_V1": (
        "scalp7_kell_gajjala_closure_v1",
        ("break_and_continue", "scalp_snap"),
    ),
}
AUTHORITY = {"order": "BLOCKED", "live": "BLOCKED", "promotion": False}


def research_catalog() -> dict[str, Any]:
    return {
        "original25_ids": list(EXACT25),
        "original25_count": 25,
        "new_research_models": {
            key: {
                "module": module,
                "original_strategy_aliases": list(aliases),
                "economic_results": None,
                "genuine_execution_authorized": False,
            }
            for key, (module, aliases) in MODEL_ROUTES.items()
        },
        "gajjala_alias_independent_model_count": 1,
        "predecessor_frozen_five": "COMPLETED_ONCE_REMAINING_FULL_ZERO",
        "original25_complete": False,
        "g4_complete": False,
        "authority": dict(AUTHORITY),
    }


def _fixture_only(
    frames: Mapping[str, pd.DataFrame],
    details: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    if manifest.get("data_kind") != "SYNTHETIC_FIXTURE" or not (
        isinstance(manifest.get("construction_reason"), str)
        and manifest["construction_reason"].strip()
    ):
        raise PermissionError("SYNTHETIC_ONLY_NEW_FULL_AUTHORIZATION_ZERO")
    if not 0 < len(frames) <= 3 or set(frames) != set(details):
        raise ValueError("BOUNDED_MATCHED_FIXTURE_UNIVERSE_REQUIRED")
    context = config.get("context_frames", {})
    if not isinstance(context, Mapping):
        raise ValueError("EXPLICIT_CONTEXT_FRAME_MAPPING_REQUIRED")
    sources = [*frames.values(), *context.values()]
    for frame in [*sources, *details.values()]:
        if not isinstance(frame, pd.DataFrame) or (
            frame.attrs.get("data_kind") != "SYNTHETIC_FIXTURE"
            or frame.attrs.get("source_rows_are_genuine") is True
        ):
            raise PermissionError("DECLARED_SYNTHETIC_FRAME_REQUIRED")
    if sum(map(len, sources)) > 256 or sum(map(len, details.values())) > 2048:
        raise PermissionError("FIXTURE_ROW_CAP_EXCEEDED")


def run_fixture(
    model_id: str,
    frames: dict[str, pd.DataFrame],
    details: dict[str, pd.DataFrame],
    config: dict[str, Any],
    *,
    fixture_manifest: Mapping[str, Any],
    initial_cash_usdt: float = 10000,
    fee_rate: float = 0.001,
) -> dict[str, Any]:
    """Call actual family producer/execution without data loads or allocations.

    Declaration is a caller assertion, not independent provenance verification.
    Caps and explicit blocks prevent this API being a general FULL gateway.
    """
    _fixture_only(frames, details, config, fixture_manifest)
    if model_id not in MODEL_ROUTES:
        raise ValueError("UNKNOWN_NEW_RESEARCH_MODEL")
    name, _ = MODEL_ROUTES[model_id]
    module = importlib.import_module("backend.research.rebuild." + name)
    if name == "scalp7_hg_closure_v1":
        result = module.run_synthetic_fixture(
            frames,
            details,
            config,
            dataset_kind="SYNTHETIC_FIXTURE",
            capital=initial_cash_usdt,
            fee_rate=fee_rate,
        )
    else:
        result = module.run_fixture(
            model_id,
            frames,
            details,
            config,
            fixture_manifest=dict(fixture_manifest),
            initial_cash_usdt=initial_cash_usdt,
            fee_rate=fee_rate,
        )
    if result.get("new_full_runs") != 0:
        raise ValueError("FIXTURE_CALLER_EXECUTION_AUTHORITY_DRIFT")
    return {
        **result,
        "dispatcher": "scalp7_closure_dispatch_v1.run_fixture",
        "authority": dict(AUTHORITY),
        "new_economics": None,
    }


def volume_component(
    strategy_id: str,
    frames: dict[str, pd.DataFrame],
    config: dict[str, Any],
    bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Connect common dimensional admission to the existing indicator callers."""
    return evaluate_volume_component(strategy_id, frames, config, bindings)
