"""Verify saved Exact25 implementation evidence; never load market history or replay."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

CAMPAIGN = Path("research/campaigns/scalp7_20260920/implementation_v1")
GROUPS = ("capital", "indicators", "reference", "session", "structure")
EXPECTED = frozenset(
    "alpha_combo anchor_vwap_trend bb_revert break_and_continue ema_ribbon_scalp "
    "fvg_revert grid_rebalance keltner_trend liquidity_sweep mfi_rsi_div "
    "obv_trend pivot_reversal range_fade rbreaker_like rsi_swing_fail "
    "scalp_snap session_bias squeeze_break sr_levels supertrend_pullback "
    "trend_ma_macd trend_rider turtle_trend vol_spike_fade vwap_revert".split()
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_file_seal(root: Path, hashes: dict[str, str], required: set[str]) -> None:
    root = root.resolve()
    if not required.issubset(hashes):
        raise ValueError("SEAL_MISSING_REQUIRED_MEMBER")
    for name, expected in hashes.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("SEAL_UNSAFE_PATH")
        path = root / relative
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("SEAL_MISSING_OR_EXTERNAL_FILE:" + name)
        if digest(path) != expected:
            raise ValueError("SEAL_HASH_DRIFT:" + name)


def local_dependencies(root: Path, names: set[str]) -> set[str]:
    """Read local import closure without importing unverified producer bytes."""
    pending = [name for name in names if name.endswith(".py")]
    found: set[str] = set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        path = root / name
        if not path.is_file():
            continue
        for parent in path.relative_to(root).parents:
            init = parent / "__init__.py"
            if (root / init).is_file() and str(init) not in found:
                pending.append(str(init))
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [
                    node.module,
                    *[node.module + "." + alias.name for alias in node.names],
                ]
            for module in modules:
                if module.startswith(("backend.", "scripts.")):
                    candidate = module.replace(".", "/") + ".py"
                    if (root / candidate).is_file() and candidate not in found:
                        pending.append(candidate)
    return found


def verify_coverage_claims(coverage: dict[str, Any]) -> None:
    """Check zero-run claims and exact rows, including duplicate aliases."""
    expected_counts = {
        "exact25_count": 25,
        "new_full_runs": 0,
        "ready_new_baselines": 0,
        "required_new_controls": 0,
        "minimum_full_runs_for_ready_models": 0,
        "unresolved_model_count": 25,
        "economic_execution_authorized": False,
    }
    for key, expected in expected_counts.items():
        actual = coverage[key]
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError("COVERAGE_STATUS_DRIFT:" + key)
    nested = coverage["coverage"]
    for key, expected in {
        "exact25_count": 25,
        "callable_scoped_component_rows": 25,
        "full_original_strategies_certified": 0,
        "frozen_complete_research_baselines": 0,
        "economic_ready_baselines": 0,
        "new_full_runs": 0,
        "fresh_runs": 0,
        "promotions": 0,
    }.items():
        if type(nested[key]) is not int or nested[key] != expected:
            raise ValueError("NESTED_COVERAGE_STATUS_DRIFT:" + key)
    ready = coverage["execution_readiness"]
    for key in (
        "ready_new_baselines",
        "required_new_controls_for_current_frozen_set",
        "minimum_full_executions_for_current_frozen_set",
    ):
        if type(ready[key]) is not int or ready[key] != 0:
            raise ValueError("READINESS_STATUS_DRIFT:" + key)
    if (
        ready["current_frozen_set"] != []
        or ready["new_full_execution_authority"] != "NOT_GRANTED"
    ):
        raise ValueError("READINESS_AUTHORITY_DRIFT")
    rows = coverage["rows"]
    if len(rows) != 25 or {row["strategy_id"] for row in rows} != EXPECTED:
        raise ValueError("COVERAGE_EXACT25_MEMBERSHIP")
    if sorted(row["number"] for row in rows) != list(range(1, 26)):
        raise ValueError("COVERAGE_EXACT25_NUMBERING")
    for row in rows:
        for key in (
            "full_original_strategy_complete",
            "frozen_complete_research_candidate",
            "economics_ready",
            "original_source_trade_parity_verified",
        ):
            if row[key] is not False:
                raise ValueError("ROW_UNSUPPORTED_COMPLETENESS:" + row["strategy_id"])
        if type(row["new_economic_runs"]) is not int or row["new_economic_runs"] != 0:
            raise ValueError("ROW_ECONOMIC_RUN_DRIFT")
        if any(value is not None for value in row["new_economics"].values()):
            raise ValueError("ROW_FABRICATED_ECONOMIC_VALUES")
        if (
            row["economic_status"] != "NOT_RUN_NO_NEW_FULL_AUTHORITY"
            or row["new_grade"] is not None
        ):
            raise ValueError("ROW_ECONOMIC_STATUS_DRIFT")
    economics = coverage["economic_report"]
    if (
        economics["state"] != "NOT_RUN"
        or economics["metric_values"] is not None
        or economics["delta_values"] is not None
    ):
        raise ValueError("ECONOMIC_REPORT_STATUS_DRIFT")
    if coverage["authority"] != {
        "order": "BLOCKED",
        "live": "BLOCKED",
        "promotion": False,
        "paid_spend": 0,
        "services_changed": 0,
        "deployment_required": False,
    }:
        raise ValueError("COVERAGE_AUTHORITY_DRIFT")


def verify_row_bindings(
    root: Path, coverage: dict[str, Any], hashes: dict[str, str]
) -> None:
    for row in coverage["rows"]:
        group = row["group"]
        if (
            group not in GROUPS
            or row["module_path"]
            != f"backend/research/rebuild/scalp7_exact25_{group}_v1.py"
        ):
            raise ValueError("ROW_MODULE_BINDING_DRIFT")
        for path_key, sha_key in (
            ("module_path", "module_sha256"),
            ("test_path", "test_sha256"),
            ("binding_receipt_path", "binding_receipt_sha256"),
        ):
            path, sha = row[path_key], row[sha_key]
            if not path or hashes.get(path) != sha:
                raise ValueError("ROW_SAVED_HASH_BINDING_DRIFT:" + str(path))
        module_name = row["module_path"].removesuffix(".py").replace("/", ".")
        module = importlib.import_module(module_name)
        if row["strategy_id"] not in module.catalog():
            raise ValueError("ROW_CATALOG_OWNER_DRIFT")
        if not row["function_bindings"]:
            raise ValueError("ROW_FUNCTION_BINDINGS_EMPTY")
        for item in row["function_bindings"]:
            prefix, name = item["function"].rsplit(".", 1)
            if prefix != module_name or not name.isidentifier():
                raise ValueError("ROW_FUNCTION_BINDING_DRIFT")
            function = getattr(module, name)
            actual = hashlib.sha256(inspect.getsource(function).encode()).hexdigest()
            if actual != item["source_sha256"]:
                raise ValueError("ROW_FUNCTION_HASH_DRIFT:" + item["function"])
    basis = coverage["basis"]
    if hashes.get(basis["source_package_path"]) != basis["source_package_sha256"]:
        raise ValueError("SOURCE_BASIS_HASH_DRIFT")
    source = json.loads((root / basis["source_package_path"]).read_text())
    source_rows = {item["strategy_id"]: item for item in source["strategies"]}
    for row in coverage["rows"]:
        original = source_rows[row["strategy_id"]]
        if row["number"] != original["number"] or set(row["source_ids"]) != set(
            original["r3_source_ids"]
        ):
            raise ValueError("ROW_SOURCE_PACKAGE_BINDING_DRIFT")


def verify(root: Path) -> dict[str, Any]:
    root = root.resolve()
    folder = root / CAMPAIGN
    seal = json.loads((folder / "INPUT_SEAL.json").read_text())
    required = {
        "backend/research/rebuild/scalp7_implementation_contract_v1.py",
        "tests/test_scalp7_implementation_numeric_v1.py",
        "scripts/verify_scalp7_exact25_implementation_v1.py",
        ".github/workflows/scalp7-exact25-implementation-v1.yml",
        str(CAMPAIGN / "EXACT25_IMPLEMENTATION.json"),
        str(CAMPAIGN / "COVERAGE.md"),
        str(CAMPAIGN / "recovery/AUTHORIZATION.json"),
        str(CAMPAIGN / "recovery/SOURCE_TEXT_COPY.json"),
    }
    for group in (*GROUPS, "execution", "pipeline"):
        required.add(f"backend/research/rebuild/scalp7_exact25_{group}_v1.py")
        required.add(f"tests/test_scalp7_exact25_{group}_v1.py")
    required.add("tests/test_scalp7_exact25_saved_v1.py")
    for sub in ("source_package", "recovery", "audits"):
        required.update(
            str(p.relative_to(root)) for p in (folder / sub).rglob("*") if p.is_file()
        )
    required |= local_dependencies(root, required)
    verify_file_seal(root, seal["hashes"], required)
    copied = json.loads((folder / "recovery/SOURCE_TEXT_COPY.json").read_text())
    source_names = {
        str(p.relative_to(folder / "source_package"))
        for p in (folder / "source_package").rglob("*")
        if p.is_file()
    }
    if source_names != set(copied["files"]):
        raise ValueError("SOURCE_COPY_MEMBERSHIP_DRIFT")
    verify_file_seal(folder / "source_package", copied["files"], source_names)
    authority = json.loads((folder / "recovery/AUTHORIZATION.json").read_text())
    for key in (
        "new_full_authorized",
        "new_full_performed",
        "new_real_history_signal_probes",
    ):
        if type(authority[key]) is not int or authority[key] != 0:
            raise ValueError("IMPLEMENTATION_ONLY_AUTHORITY_DRIFT:" + key)
    if (
        authority["prior_full_budget_used"] != 4
        or authority["prior_full_budget_total"] != 4
    ):
        raise ValueError("OLD_BUDGET_NOT_REUSABLE")
    if authority["old_budget_carryover"] is not False:
        raise ValueError("OLD_BUDGET_CARRYOVER")
    if authority["authority"] != {
        "order": "BLOCKED",
        "live": "BLOCKED",
        "promotion": False,
        "deployment": False,
    }:
        raise ValueError("AUTHORITY_DRIFT")
    catalog: dict[str, Any] = {}
    for group in GROUPS:
        module = importlib.import_module(
            "backend.research.rebuild.scalp7_exact25_" + group + "_v1"
        )
        expected_module = (
            root / "backend/research/rebuild" / ("scalp7_exact25_" + group + "_v1.py")
        )
        if (
            module.__file__ is None
            or Path(module.__file__).resolve() != expected_module.resolve()
        ):
            raise ValueError("VERIFICATION_IMPORTED_OTHER_CHECKOUT")
        rows = module.catalog()
        if set(rows) & set(catalog):
            raise ValueError("DUPLICATE_STRATEGY")
        catalog.update(rows)
    if set(catalog) != EXPECTED:
        raise ValueError("ORIGINAL_EXACT25_MEMBERSHIP")
    if any(v.get("complete_strategy") is not False for v in catalog.values()):
        raise ValueError("UNSUPPORTED_COMPLETE_STRATEGY_CLAIM")
    coverage = json.loads((folder / "EXACT25_IMPLEMENTATION.json").read_text())
    verify_coverage_claims(coverage)
    verify_row_bindings(root, coverage, seal["hashes"])
    return {
        "state": "PASS",
        "sealed_files": len(seal["hashes"]),
        "exact25_count": 25,
        "new_full_runs": 0,
        "ready_new_baselines": 0,
        "claim": "IMPLEMENTATION_AND_SAVED_EVIDENCE_ONLY_NOT_G4_ECONOMIC_COMPLETION",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    print(json.dumps(verify(args.repo), sort_keys=True))
