#!/usr/bin/env python3
"""Verify saved model-closure evidence without importing engines or market data."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

CAMPAIGN = Path("research/campaigns/scalp7_20260920/model_closure_v1")
SCOPE = "G4_EXACT25_SOURCE_TO_CODE_IMPLEMENTATION_AFTER_FINAL_REVIEW_V1"
PRIOR = (
    "research/campaigns/scalp7_20260920/implementation_v1/EXACT25_IMPLEMENTATION.json"
)
RUNNER = "backend/research/rebuild/scalp7_exact25_model_runner_v1.py"
COST_SNAPSHOT = (
    "research/campaigns/scalp7_20260915/cost_snapshot_v2/"
    "SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
)
REQUIRED_SEAL = {
    str(CAMPAIGN / name)
    for name in (
        "MODEL_CLOSURE.json",
        "PREPARED_EXECUTION_REQUEST.json",
        "build_preparation_v1.py",
        "audits/RUNNER_REVIEW.json",
        "audits/DATA_AUTHORITY_READINESS.json",
    )
} | {
    PRIOR,
    RUNNER,
    COST_SNAPSHOT,
    ".pre-commit-config.yaml",
    ".github/workflows/scalp7-exact25-model-closure-v1.yml",
    "scripts/verify_scalp7_exact25_model_closure_v1.py",
    "tests/test_scalp7_exact25_model_saved_v1.py",
    "tests/test_scalp7_exact25_model_runner_v1.py",
}
PROFILES = {
    "ST_CONTROL": (
        "ST30_STRUCTURAL_CONTROL_V1",
        "supertrend_pullback",
        "NEW_SOURCE_COMPONENT_ARCHITECTURE",
        "CONTROL",
    ),
    "ST_TRAIL": (
        "ST30_COMPLETED_BAND_TRAIL_V1",
        "supertrend_pullback",
        "ST30_STRUCTURAL_CONTROL_V1",
        "SUPERTREND_TRAILING_ONLY",
    ),
    "SR_CONTROL": (
        "sr_levels_30m_prior_utc_day_box_breakout_control_v1",
        "sr_levels",
        "NEW_FIXED_UTC_REFERENCE_ARCHITECTURE",
        "CONTROL",
    ),
    "SR_RETEST": (
        "sr_levels_30m_prior_utc_day_box_intraday_v1",
        "sr_levels",
        "sr_levels_30m_prior_utc_day_box_breakout_control_v1",
        "SR_BREAKOUT_VS_LATER_RETEST",
    ),
    "NOISE_BASELINE": (
        "NOISE_OPPOSITE_BAND_UTC30_RESEARCH_V1_FIXED_SLEEVES",
        "trend_rider",
        "NEW_EXTERNAL_NOISE_BASELINE_NOT_GMMA_PARENT",
        "NEW_BASELINE",
    ),
}
PAIRS = [
    {"parent": "ST_CONTROL", "child": "ST_TRAIL", "axis": "SUPERTREND_TRAILING_ONLY"},
    {
        "parent": "SR_CONTROL",
        "child": "SR_RETEST",
        "axis": "SR_BREAKOUT_VS_LATER_RETEST",
    },
]
SYMBOLS = ["BTC-USDT", "DOGE-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT"]


def _load(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise ValueError("OBJECT_REQUIRED:" + str(path))
    return result


def _digest(value: Any) -> str:
    # Matches economic7_campaign_registry_v1.canonical/digest.
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


def _data_identity(value: Any) -> Any:
    # Matches the runner's relocation-stable semantic identity, without imports.
    locators = {
        "path",
        "directory",
        "canonical_root",
        "source_inventory_path",
        "time_authority_directory",
    }
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in locators:
                continue
            if key == "artifacts":
                out[key] = sorted(
                    [
                        {
                            "sha256": row["sha256"],
                            "role": row.get("role", "INPUT_ARTIFACT"),
                        }
                        for row in item
                    ],
                    key=lambda row: (row["role"], row["sha256"]),
                )
            else:
                out[key] = _data_identity(item)
        return out
    if isinstance(value, list):
        return [_data_identity(item) for item in value]
    if isinstance(value, str) and value.startswith("/"):
        return "ABSOLUTE_LOCATOR_EXCLUDED_FROM_EXPERIMENT_IDENTITY"
    return value


def _verify_freeze(
    repo: Path, row: dict[str, Any], request: dict[str, Any], hashes: dict[str, str]
) -> dict[str, Any]:
    path = str(CAMPAIGN / "freezes" / (row["label"] + ".json"))
    if row["freeze_path"] != path or path not in hashes:
        raise ValueError("UNSEALED_OR_WRONG_PREPARED_FREEZE")
    frozen = _load(repo / path)
    expected = row["binding_sha256"]
    payload = {k: v for k, v in frozen.items() if k != "binding_sha256"}
    if frozen["binding_sha256"] != expected or _digest(payload) != expected:
        raise ValueError("PINNED_BINDING_MISMATCH")
    fields = ("model_id", "strategy_id", "baseline_id", "changed_axis")
    if tuple(row[key] for key in fields) != PROFILES[row["label"]]:
        raise ValueError("PREPARED_PROFILE_MISMATCH")
    if any(frozen[key] != row[key] for key in fields):
        raise ValueError("PREPARED_IDENTITY_FREEZE_MISMATCH")
    if frozen["identity_key"] != row["identity"]:
        raise ValueError("PREPARED_IDENTITY_FREEZE_MISMATCH")
    identity = frozen["candidate_identity"]
    rebuilt = {
        "candidate_id": frozen["model_id"],
        "strategy_id": frozen["strategy_id"],
        "baseline_id": frozen["baseline_id"],
        "changed_axis": frozen["changed_axis"],
        "rule_sha256": _digest(
            {
                k: v
                for k, v in payload.items()
                if k
                not in {
                    "data_manifest",
                    "cost",
                    "windows",
                    "candidate_identity",
                    "identity_key",
                }
            }
        ),
        "data_sha256": _digest(_data_identity(frozen["data_manifest"])),
        "cost_sha256": _digest(frozen["cost"]),
        "window_sha256": _digest(frozen["windows"]),
    }
    if (
        identity != rebuilt
        or _digest({k: v for k, v in identity.items() if k != "candidate_id"})
        != row["identity"]
    ):
        raise ValueError("CANDIDATE_IDENTITY_CONTENT_MISMATCH")
    for field, module in (
        ("code_closure", frozen["model_module"]),
        ("loader_code_closure", frozen["data_manifest"]["loader"]["module"]),
    ):
        closure = frozen[field]
        direct = module.replace(".", "/") + ".py"
        if (
            not isinstance(closure, dict)
            or not closure
            or not {RUNNER, direct} <= closure.keys()
        ):
            raise ValueError("INCOMPLETE_FROZEN_CODE_CLOSURE")
        if any(hashes.get(name) != digest for name, digest in closure.items()):
            raise ValueError("UNSEALED_OR_CHANGED_FROZEN_CODE_CLOSURE")
    if (
        frozen["cost"] != request["cost"]
        or frozen["windows"] != request["windows"]
        or frozen["data_manifest"]["symbols"] != SYMBOLS
        or row["symbols"] != SYMBOLS
        or frozen["data_manifest"]["data_kind"] != "GENUINE_RAW_HISTORY"
        or frozen["data_manifest"]["fresh_evidence"] is not False
        or frozen["initial_cash_usdt"] != 10000.0
        or frozen["authority"]
        != {"live": "BLOCKED", "order": "BLOCKED", "promotion": False}
    ):
        raise ValueError("PREPARED_CONTRACT_MISMATCH")
    return frozen


def _verify_request(repo: Path, request: dict[str, Any], hashes: dict[str, str]) -> int:
    standalone = _load(repo / CAMPAIGN / "PREPARED_EXECUTION_REQUEST.json")
    if request != standalone:
        raise ValueError("STANDALONE_PREPARED_REQUEST_MISMATCH")
    identities = request["identities"]
    if len(identities) != 5 or {row["label"] for row in identities} != set(PROFILES):
        raise ValueError("EXACT_FIVE_PREPARED_PROFILES_REQUIRED")
    if len({row["identity"] for row in identities}) != 5:
        raise ValueError("DUPLICATE_PREPARED_IDENTITY")
    if (
        request["minimum_full_runs"] != 5
        or request["authorized"] is not False
        or request["new_budget_allocated"] != 0
        or request["new_full_runs_per_identity"] != 1
        or request["cost_2x_additional_full_runs"] != 0
        or request["future_minimum_for_remaining_exact25"] is not None
    ):
        raise ValueError("PREPARATION_IS_NOT_BUDGET_ALLOCATION")
    if (
        request["matched_pairs"] != PAIRS
        or request["independent_baselines"] != ["NOISE_BASELINE"]
        or request["noise_is_not_matched_parent_child_improvement"] is not True
        or request["source_aliases_not_independent_materials"]
        != {"session_bias": "trend_rider"}
    ):
        raise ValueError("PREPARED_COMPARISON_TOPOLOGY_MISMATCH")
    if request["data"] != {
        "calendar_days": 365,
        "missing_minutes_each": 4,
        "symbols": SYMBOLS,
    }:
        raise ValueError("PREPARED_DATA_COUNTS_MISMATCH")
    windows = request["windows"]
    if (
        len(windows) != 11
        or [w["kind"] for w in windows] != ["CONTEXT", "VALIDATION"] + ["ROLLING"] * 9
        or windows[0]["start_ts_ms"] != 1757894400000
        or windows[-1]["end_ts_ms"] != 1789430400000
        or any(a["end_ts_ms"] != b["start_ts_ms"] for a, b in zip(windows, windows[1:]))
        or [w["end_ts_ms"] - w["start_ts_ms"] for w in windows]
        != [days * 86400000 for days in [90, 30] + [30] * 8 + [5]]
    ):
        raise ValueError("PREPARED_WINDOWS_CHANGED")
    cost = request["cost"]
    if (
        cost["kind"] != "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING"
        or cost["funding_status"] != "UNKNOWN_NOT_ZERO"
        or cost["snapshot_path"] != COST_SNAPSHOT
        or cost["snapshot_sha256"] != hashes[COST_SNAPSHOT]
        or set(cost["per_side_rates"]) != set(SYMBOLS)
        or cost["one_settlement_reserve_not_reused_as_actual_historical_funding"]
        is not True
    ):
        raise ValueError("PREPARED_REFERENCE_COST_CHANGED")
    snapshots = _load(repo / COST_SNAPSHOT)["snapshots"]
    for symbol, rate in cost["per_side_rates"].items():
        source = snapshots[symbol]
        expected = (
            sum(source[k] for k in ("fee_bps", "impact_bps", "spread_bps")) / 20000.0
        )
        if (
            not math.isfinite(rate)
            or rate < 0
            or not math.isclose(rate, expected, rel_tol=1e-12)
        ):
            raise ValueError("REFERENCE_COST_DERIVATION_MISMATCH")
    freezes = {
        row["label"]: _verify_freeze(repo, row, request, hashes) for row in identities
    }
    for pair in PAIRS:
        parent, child = freezes[pair["parent"]], freezes[pair["child"]]
        for key in (
            "data_manifest",
            "cost",
            "windows",
            "initial_cash_usdt",
            "execution_mode",
            "capital_policy",
            "fill_model",
            "gap_policy",
            "price_basis",
            "environment",
            "config",
        ):
            if parent[key] != child[key]:
                raise ValueError("MATCHED_PAIR_CONTRACT_MISMATCH:" + key)
    return len(identities)


def verify(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    seal = _load(repo / CAMPAIGN / "INPUT_SEAL.json")
    report = _load(repo / CAMPAIGN / "MODEL_CLOSURE.json")
    if seal["scope_key"] != SCOPE or report["scope_key"] != SCOPE:
        raise ValueError("SCOPE_MISMATCH")
    hashes = seal["hashes"]
    if not isinstance(hashes, dict) or not REQUIRED_SEAL <= hashes.keys():
        raise ValueError("ESSENTIAL_SEAL_COVERAGE_MISSING")
    for name, digest in hashes.items():
        path = (repo / name).resolve()
        if (
            Path(name).is_absolute()
            or not path.is_relative_to(repo)
            or not path.is_file()
        ):
            raise ValueError("SEALED_FILE_MISSING_OR_OUTSIDE_REPO:" + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("SEALED_FILE_CHANGED:" + name)
    prior = _load(repo / PRIOR)
    expected = {row["strategy_id"] for row in prior["rows"]}
    actual = [row["strategy_id"] for row in report["rows"]]
    if len(actual) != 25 or len(set(actual)) != 25 or set(actual) != expected:
        raise ValueError("ORIGINAL_EXACT25_DENOMINATOR_CHANGED")
    for row in report["rows"]:
        if not row["disposition"] or not row["remaining"]:
            raise ValueError("MISSING_PER_ID_DISPOSITION_OR_LIMITATION")
        if row["new_economics"] is not None:
            raise ValueError("UNEXECUTED_ECONOMICS_MUST_BE_NULL")
    if report["new_full_runs"] != 0 or report["real_history_probes"] != 0:
        raise ValueError("THIS_SAVED_INCREMENT_HAS_NO_MARKET_RUNS")
    if report["original_full_strategy_certifications"] != 0:
        raise ValueError("DECLARED_MODEL_IS_NOT_ORIGINAL_CERTIFICATION")
    if report["authority"] != {
        "full": "NO_NEW_ALLOCATION",
        "order": "BLOCKED",
        "live": "BLOCKED",
        "promotion": "BLOCKED",
    }:
        raise ValueError("AUTHORITY_CHANGED")
    claims = {
        "new_economics": None,
        "portfolio7_economics": None,
        "joint_T_WR_Net_DD_improvements": None,
        "new_verified_economic_improvements": 0,
        "new_A_promotions": 0,
        "new_B_promotions": 0,
        "fusion_allowed": False,
        "historical_data_is_fresh": False,
        "original25_strategy_ids": 25,
        "configured_model_ids": 7,
        "configured_strategy_rows_including_shared_alias": 6,
        "material_or_unimplemented_strategy_rows": 19,
        "prepared_unique_identities": 5,
    }
    if any(report.get(key) != value for key, value in claims.items()):
        raise ValueError("UNEXECUTED_REPORT_CLAIMS_CHANGED")
    count = _verify_request(repo, report["prepared_execution_request"], hashes)
    return {
        "status": "PASS",
        "sealed_files": len(hashes),
        "exact25_rows": len(actual),
        "prepared_identities": count,
        "minimum_full_runs_requested_not_authorized": count,
        "new_full_runs": 0,
        "real_history_probes": 0,
        "market_data_loaded": False,
        "runtime_environment_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.repo), sort_keys=True))


if __name__ == "__main__":
    main()
