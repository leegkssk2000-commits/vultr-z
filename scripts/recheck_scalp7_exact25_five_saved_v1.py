#!/usr/bin/env python3
"""Recompute all five saved audits in a temporary directory; never run a model."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "research/campaigns/scalp7_20261001/exact25_five_v1"
FREEZES = ROOT / "research/campaigns/scalp7_20260920/model_closure_v1/freezes"
ARITHMETIC = ROOT / "scripts/verify_scalp7_exact25_five_arithmetic_v1.py"
COMPARISON = CAMPAIGN / "audits/build_independent_comparison_audit.py"
LABELS = ("ST_CONTROL", "ST_TRAIL", "SR_CONTROL", "SR_RETEST", "NOISE_BASELINE")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def inside_repo(path: Path) -> None:
    require(
        path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED:" + str(path)
    )
    require(path.resolve().is_relative_to(ROOT), "REPO_PATH_REQUIRED:" + str(path))


def passed(audit: dict[str, Any]) -> None:
    require(
        audit.get("status") == "PASS"
        and audit.get("error_count") == 0
        and audit.get("errors") == []
        and isinstance(audit.get("check_count"), int)
        and audit["check_count"] > 0,
        "SAVED_AUDIT_NOT_PASS",
    )


def substantive(audit: dict[str, Any]) -> dict[str, Any]:
    """Only execution-location metadata and gzip storage representation may differ."""
    result = {key: value for key, value in audit.items() if key != "inputs"}
    result["inputs"] = {
        key: value
        for key, value in audit["inputs"].items()
        if key not in {"result_path", "result_storage_sha256", "freeze_path"}
    }
    return result


def run_cli(script: Path, arguments: list[str]) -> None:
    completed = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(
            "SAVED_AUDITOR_FAILED:"
            + str(script.relative_to(ROOT))
            + "\n"
            + completed.stdout[-4000:]
            + completed.stderr[-4000:]
        )


def recheck(destination: Path) -> dict[str, Any]:
    require(
        not destination.resolve().is_relative_to(ROOT),
        "TEMP_OUTPUT_MUST_BE_OUTSIDE_REPO",
    )
    output = destination / "audits"
    output.mkdir()
    report_path = CAMPAIGN / "ECONOMIC_COMPARISON.json"
    aggregate_path = CAMPAIGN / "audits/INDEPENDENT_ECONOMIC_AUDIT.json"
    protected = [Path(__file__), ARITHMETIC, COMPARISON, report_path, aggregate_path]
    for label in LABELS:
        protected.extend(
            [
                CAMPAIGN / "results" / (label + ".json.gz"),
                CAMPAIGN / "audits" / (label + "_ARITHMETIC.json"),
                FREEZES / (label + ".json"),
            ]
        )
    seal = CAMPAIGN / "INPUT_SEAL.json"
    if seal.is_file():
        protected.append(seal)
    for path in protected:
        inside_repo(path)
    before = {str(path.relative_to(ROOT)): sha(path) for path in protected}
    report = load(report_path)
    require(set(report["results"]) == set(LABELS), "EXACT_FIVE_RESULTS_REQUIRED")
    require(
        report["results_count"] == 5 and report["missing_results"] == [],
        "FIVE_NOT_COMPLETE",
    )
    source_hashes = {}
    counts = {}
    for label in LABELS:
        source = CAMPAIGN / "results" / (label + ".json.gz")
        freeze = FREEZES / (label + ".json")
        sealed_path = CAMPAIGN / "audits" / (label + "_ARITHMETIC.json")
        fresh_path = output / (label + "_ARITHMETIC.json")
        sealed = load(sealed_path)
        passed(sealed)
        run_cli(
            ARITHMETIC,
            [
                "--result",
                str(source),
                "--freeze",
                str(freeze),
                "--output",
                str(fresh_path),
            ],
        )
        fresh = load(fresh_path)
        passed(fresh)
        require(
            substantive(fresh) == substantive(sealed),
            "ARITHMETIC_PARITY_MISMATCH:" + label,
        )
        inputs = fresh["inputs"]
        require(
            inputs["result_sha256"] == report["results"][label]["source_file_sha256"]
            and inputs["freeze_sha256"] == sha(freeze)
            and inputs["verifier_sha256"] == sha(ARITHMETIC)
            and fresh["new_economic_executions"] == 0
            and fresh["model_or_loader_imported"] is False,
            "FRESH_ARITHMETIC_BINDING_MISMATCH:" + label,
        )
        require(
            sealed["inputs"]["result_storage_sha256"]
            in {inputs["result_sha256"], sha(source)},
            "SEALED_STORAGE_HASH_NEITHER_RAW_NOR_GZIP:" + label,
        )
        source_hashes[label] = inputs["result_sha256"]
        counts[label] = fresh["check_count"]
        print(
            json.dumps(
                {"label": label, "fresh_audit": "PASS", "sealed_parity": "PASS"}
            ),
            flush=True,
        )
    fresh_aggregate_path = output / "INDEPENDENT_ECONOMIC_AUDIT.json"
    run_cli(COMPARISON, ["--output", str(fresh_aggregate_path)])
    fresh_aggregate = load(fresh_aggregate_path)
    sealed_aggregate = load(aggregate_path)
    passed(fresh_aggregate)
    passed(sealed_aggregate)
    require(fresh_aggregate == sealed_aggregate, "COMPARISON_AUDIT_PARITY_MISMATCH")
    require(
        fresh_aggregate["source_result_sha256"] == source_hashes
        and fresh_aggregate["economic_comparison_sha256"] == sha(report_path)
        and fresh_aggregate["recipe_sha256"] == sha(COMPARISON)
        and fresh_aggregate["market_data_loaded"] is False
        and fresh_aggregate["new_full_runs"] == 0,
        "FRESH_COMPARISON_BINDING_MISMATCH",
    )
    after = {str(path.relative_to(ROOT)): sha(path) for path in protected}
    require(before == after, "SEALED_REPO_FILES_CHANGED_DURING_RECHECK")
    return {
        "schema": "g4.exact25.saved_audit_reexecution.v1",
        "status": "PASS",
        "completed_saved_results": list(LABELS),
        "arithmetic_check_counts": counts,
        "comparison_check_count": fresh_aggregate["check_count"],
        "source_result_sha256": source_hashes,
        "sealed_audit_parity": "PASS",
        "protected_recheck_inputs_unchanged": True,
        "market_data_loaded": False,
        "new_full_runs": 0,
        "model_or_loader_called": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    parent = args.output_root
    if parent is not None:
        require(
            not parent.resolve().is_relative_to(ROOT),
            "OUTPUT_ROOT_MUST_BE_OUTSIDE_REPO",
        )
        parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="exact25-saved-recheck-", dir=parent
    ) as directory:
        result = recheck(Path(directory))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
