"""Create preregistered bindings from metadata; never load market price rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.research.rebuild import scalp7_exact25_indicator_models_v1 as indicator
from backend.research.rebuild import scalp7_exact25_model_data_v1 as data
from backend.research.rebuild import scalp7_exact25_model_runner_v1 as runner
from backend.research.rebuild import scalp7_exact25_reference_models_v1 as reference
from backend.research.rebuild import scalp7_exact25_session_models_v1 as session

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "research/campaigns/scalp7_20260920/model_closure_v1"


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    )


def build(*, time_authority_directory: str) -> dict:
    audit = json.loads((OUT / "audits/DATA_AUTHORITY_READINESS.json").read_text())
    history = audit["canonical_history"]
    symbols = sorted(history["symbols"])
    if set(symbols) != set(data.source.SYMBOLS):
        raise ValueError("FULL_SIX_SYMBOL_UNIVERSE_REQUIRED")
    manifest = data.canonical_manifest(
        canonical_root="/home/z/z/runtime/economic7_campaign_20260915",
        source_inventory_path=history["source_inventory"]["path"],
        time_authority_directory=time_authority_directory,
        symbols=symbols,
        timeframe_min=30,
    )
    cost_path = ROOT / audit["cost_and_valuation"]["snapshot"]["path"]
    if (
        hashlib.sha256(cost_path.read_bytes()).hexdigest()
        != audit["cost_and_valuation"]["snapshot"]["file_sha256"]
    ):
        raise ValueError("AUDITED_COST_SNAPSHOT_CHANGED")
    cost_source = json.loads(cost_path.read_text())
    cost = {
        "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
        "per_side_rates": {
            symbol: sum(
                cost_source["snapshots"][symbol][key]
                for key in ("fee_bps", "impact_bps", "spread_bps")
            )
            / 20000
            for symbol in symbols
        },
        "funding_status": "UNKNOWN_NOT_ZERO",
        "snapshot_path": str(cost_path.relative_to(ROOT)),
        "snapshot_sha256": hashlib.sha256(cost_path.read_bytes()).hexdigest(),
        "derivation": "(fee_bps+impact_bps+spread_bps)/20000 at each actual model fill notional",
        "one_settlement_reserve_not_reused_as_actual_historical_funding": True,
        "stress_2x": "IDENTICAL_FILLS_AND_QUANTITIES_REVALUED_NOT_A_SECOND_EXECUTION",
    }
    windows = [
        {
            "name": "initial_context90",
            "kind": "CONTEXT",
            "start_ts_ms": history["start_ms"],
            "end_ts_ms": audit["practical_window_assignment"]["windows"][0]["start_ms"],
        }
    ]
    windows.extend(
        {
            "name": row["label"],
            "kind": row["partition"].upper(),
            "start_ts_ms": row["start_ms"],
            "end_ts_ms": row["end_ms"],
            "historical_inspection": "ALREADY_INSPECTED_DEVELOPMENT_HISTORY_NOT_FRESH",
            "rule_policy": "FROZEN_RULES_NO_WINDOW_RETUNING",
        }
        for row in audit["practical_window_assignment"]["windows"]
    )
    definitions = [
        (
            "ST_CONTROL",
            indicator.__name__,
            indicator.CONTROL,
            "supertrend_pullback",
            "NEW_SOURCE_COMPONENT_ARCHITECTURE",
            "CONTROL",
            indicator.CONFIG,
            "compile_model",
            "DETAIL_CONDITIONAL",
        ),
        (
            "ST_TRAIL",
            indicator.__name__,
            indicator.TRAIL,
            "supertrend_pullback",
            indicator.CONTROL,
            "SUPERTREND_TRAILING_ONLY",
            indicator.CONFIG,
            "compile_model",
            "DETAIL_CONDITIONAL",
        ),
        (
            "SR_CONTROL",
            reference.__name__,
            reference.SR_CONTROL,
            "sr_levels",
            "NEW_FIXED_UTC_REFERENCE_ARCHITECTURE",
            "CONTROL",
            {},
            "compile_model",
            "DETAIL_CONDITIONAL",
        ),
        (
            "SR_RETEST",
            reference.__name__,
            reference.SR,
            "sr_levels",
            reference.SR_CONTROL,
            "SR_BREAKOUT_VS_LATER_RETEST",
            {},
            "compile_model",
            "DETAIL_CONDITIONAL",
        ),
        (
            "NOISE_BASELINE",
            session.__name__,
            session.PORTFOLIO_MODEL_ID,
            "trend_rider",
            "NEW_EXTERNAL_NOISE_BASELINE_NOT_GMMA_PARENT",
            "NEW_BASELINE",
            session.noise_portfolio_config(symbols),
            "noise_portfolio_schedule",
            "SESSION_TARGET",
        ),
    ]
    identities = []
    for (
        short,
        module,
        model,
        strategy,
        baseline,
        axis,
        config,
        compiler,
        mode,
    ) in definitions:
        frozen = runner.freeze_model(
            model_module=module,
            model_id=model,
            strategy_id=strategy,
            baseline_id=baseline,
            changed_axis=axis,
            config=config,
            data_manifest=manifest,
            cost=cost,
            windows=windows,
            initial_cash_usdt=10000,
            compiler=compiler,
            execution_mode=mode,
        )
        runner.verify_binding(frozen, frozen["binding_sha256"])
        path = OUT / "freezes" / (short + ".json")
        write(path, frozen)
        identities.append(
            {
                "label": short,
                "model_id": model,
                "strategy_id": strategy,
                "identity": frozen["identity_key"],
                "binding_sha256": frozen["binding_sha256"],
                "freeze_path": str(path.relative_to(ROOT)),
                "baseline_id": baseline,
                "changed_axis": axis,
                "symbols": symbols,
                "readiness": "PREPARED_REFERENCE_COST_MODEL_ONLY_PENDING_NEW_FULL_ALLOCATION",
            }
        )
    request = {
        "schema": "scalp7.exact25.prepared_execution_request.v1",
        "identities": identities,
        "minimum_full_runs": len(identities),
        "authorized": False,
        "new_budget_allocated": 0,
        "matched_pairs": [
            {
                "parent": "ST_CONTROL",
                "child": "ST_TRAIL",
                "axis": "SUPERTREND_TRAILING_ONLY",
            },
            {
                "parent": "SR_CONTROL",
                "child": "SR_RETEST",
                "axis": "SR_BREAKOUT_VS_LATER_RETEST",
            },
        ],
        "independent_baselines": ["NOISE_BASELINE"],
        "noise_is_not_matched_parent_child_improvement": True,
        "source_aliases_not_independent_materials": {"session_bias": "trend_rider"},
        "data": {"calendar_days": 365, "symbols": symbols, "missing_minutes_each": 4},
        "cost": cost,
        "windows": windows,
        "future_minimum_for_remaining_exact25": None,
        "new_full_runs_per_identity": 1,
        "cost_2x_additional_full_runs": 0,
        "prohibitions": ["orders", "LIVE", "services", "paid spending", "promotion"],
    }
    write(OUT / "PREPARED_EXECUTION_REQUEST.json", request)
    return request


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--time-authority-directory", required=True)
    args = parser.parse_args()
    result = build(time_authority_directory=args.time_authority_directory)
    print(
        json.dumps(
            {"prepared_identities": result["minimum_full_runs"], "new_full_runs": 0}
        )
    )
