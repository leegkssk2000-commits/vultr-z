"""Verify the sealed source-fidelity publication using saved arithmetic only."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = "research/campaigns/scalp7_20260917/source_fidelity_v1"
BASE = (
    "research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json"
)
SEAL = CAMPAIGN + "/PUBLICATION_SEAL.json"
ALIASES = {"HG", "RSI", "BREAK", "SRP", "SRC"}
WORKFLOW = ".github/workflows/scalp7-source-fidelity-v1.yml"
MANDATORY = (
    WORKFLOW,
    "scripts/verify_scalp7_fidelity_saved_v1.py",
    "tests/test_scalp7_fidelity_seal_v1.py",
)
sys.path.insert(0, str(ROOT))


def safe_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if (
        not name
        or relative.is_absolute()
        or ".." in relative.parts
        or name != relative.as_posix()
        or "\\" in name
    ):
        raise ValueError("SEAL_UNSAFE_PATH:" + name)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("SEAL_SYMLINK:" + name)
    if not current.is_file():
        raise ValueError("SEAL_MISSING_FILE:" + name)
    return current


def read(root: Path, name: str) -> Any:
    return json.loads(safe_path(root, name).read_text())


def record(root: Path, name: str) -> dict[str, str]:
    path = safe_path(root, name)
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("SEAL_NOT_REGULAR:" + name)
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mode": "100755" if mode & 0o111 else "100644",
    }


def paths(root: Path) -> set[str]:
    """Complete published tree plus the union of saved import/data dependencies."""
    selection = read(root, CAMPAIGN + "/BATCH_SELECTION.json")
    if (
        set(selection["candidates"]) != ALIASES
        or selection["max_candidates"] != 5
        or selection["max_full_executions"] != 5
    ):
        raise ValueError("SEAL_SELECTION_BUDGET")
    names = {BASE, *MANDATORY}
    for path in (root / CAMPAIGN).rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("SEAL_SYMLINK:" + name)
        if not path.is_dir() and name != SEAL:
            names.add(name)
    base = read(root, BASE)
    names.update(base["code_hashes"])
    names.update(base["data_hashes"])
    names.add(base["cost_path"])
    for alias in ALIASES:
        frozen = read(root, CAMPAIGN + "/freezes/" + alias + ".json")
        names.update(frozen["hashes"])
        info = read(root, CAMPAIGN + "/results/" + alias + ".json")
        pointers = {
            "freeze_path": "/freezes/" + alias + ".json",
            "ledger_path": "/results/" + alias + ".trades.json.gz",
            "signal_path": "/results/" + alias + ".signals.json.gz",
        }
        if selection["candidates"][alias].get("cached_parent"):
            pointers["parent_signals_path"] = (
                "/results/" + alias + ".parent_signals.json.gz"
            )
        elif "parent_signals_path" in info:
            raise ValueError("SEAL_UNEXPECTED_PARENT_SIGNALS")
        for key, suffix in pointers.items():
            safe_path(root, info[key])
            if info[key] != CAMPAIGN + suffix:
                raise ValueError("SEAL_RESULT_POINTER:" + key)
            names.add(info[key])
    for pattern in (
        "backend/research/rebuild/scalp7_fidelity*_v1.py",
        "tests/test_scalp7_fidelity*_v1.py",
        "scripts/*scalp7*fidelity*.py",
    ):
        names.update(p.relative_to(root).as_posix() for p in root.glob(pattern))
    for name in names:
        safe_path(root, name)
    return names


def verify_registry(root: Path) -> None:
    selection = read(root, CAMPAIGN + "/BATCH_SELECTION.json")
    exported = read(root, CAMPAIGN + "/EXPORT_REGISTRY.json")
    if (
        exported["scope"] != selection["scope_key"]
        or exported["owner"] != selection["owner"]
        or exported["max_candidates"] != 5
        or exported["max_executions"] != 5
        or exported["executions_started"] != 5
    ):
        raise ValueError("SEAL_REGISTRY_BUDGET")
    expected = {}
    for alias, candidate in selection["candidates"].items():
        result = read(root, CAMPAIGN + "/results/" + alias + ".json")
        if result["alias"] != alias or result["candidate"] != candidate:
            raise ValueError("SEAL_RESULT_IDENTITY")
        expected[result["identity_key"]] = candidate["identity"]
    claims = exported["claims"]
    if (
        len(expected) != 5
        or len(claims) != 5
        or {c["identity_key"]: c["candidate_id"] for c in claims} != expected
        or any(c["state"] != "COMPLETED" for c in claims)
    ):
        raise ValueError("SEAL_REGISTRY_COMPLETION")
    for claim in claims:
        alias = next(
            a
            for a, c in selection["candidates"].items()
            if c["identity"] == claim["candidate_id"]
        )
        relative = CAMPAIGN + "/results/" + alias + ".json"
        receipt = claim[
            "receipt"
        ]  # Original absolute location is provenance, never opened.
        digest = record(root, relative)["sha256"]
        if (
            not (receipt == relative or receipt.endswith("/" + relative))
            or claim["receipt_sha256"] != digest
            or claim["result"] != {"receipt": receipt, "sha256": digest}
        ):
            raise ValueError("SEAL_REGISTRY_RECEIPT")
    starts = [e["identity_key"] for e in exported["events"] if e["event"] == "STARTED"]
    if len(starts) != 5 or set(starts) != set(expected):
        raise ValueError("SEAL_REGISTRY_STARTS")


def saved_checks(root: Path) -> None:
    verify_registry(root)
    runner: Any = importlib.import_module(
        "backend.research.rebuild.scalp7_fidelity_runner_v1"
    )
    if runner.ROOT.resolve() != root.resolve():
        raise ValueError("SEAL_RUNNER_ROOT_MISMATCH")
    for alias in sorted(ALIASES):
        runner.verify_saved(alias)
    reporter: Any = importlib.import_module(
        "backend.research.rebuild.scalp7_fidelity_report_v1"
    )
    reporter.verify()


def verify(root: Path = ROOT) -> dict[str, Any]:
    manifest = read(root, SEAL)
    if manifest["schema"] != "scalp7.source_fidelity.publication_seal.v1":
        raise ValueError("SEAL_SCHEMA")
    expected = paths(root)
    if set(manifest["files"]) != expected:
        raise ValueError("SEAL_MEMBERSHIP_DRIFT")
    for name, pinned in manifest["files"].items():
        if record(root, name) != pinned:
            raise ValueError("SEAL_FILE_DRIFT:" + name)
    saved_checks(root)
    return {
        "state": "PASS_SEALED_SAVED_FIDELITY_NO_ECONOMIC_REPLAY",
        "files": len(expected),
        "completed": 5,
        "executions_started": 5,
    }


def seal(root: Path = ROOT) -> dict[str, Any]:
    names = paths(root)
    saved_checks(root)
    value = {
        "schema": "scalp7.source_fidelity.publication_seal.v1",
        "self_exclusion_only": SEAL,
        "mode_semantics": "git regular-file modes 100644/100755",
        "files": {name: record(root, name) for name in sorted(names)},
    }
    target = root / SEAL
    if target.is_symlink():
        raise ValueError("SEAL_SYMLINK:" + SEAL)
    target.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return verify(root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seal",
        action="store_true",
        help="Explicitly create/update the final publication seal",
    )
    args = parser.parse_args()
    print(json.dumps(seal() if args.seal else verify(), sort_keys=True))


if __name__ == "__main__":
    main()
