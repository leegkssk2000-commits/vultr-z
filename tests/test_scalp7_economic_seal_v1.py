"""Publication tampering tests use temporary files and saved arithmetic only."""

from __future__ import annotations

import gzip
import hashlib
import importlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

seal: Any = importlib.import_module("scripts.verify_scalp7_economic_saved_v1")
runner: Any = importlib.import_module(
    "backend.research.rebuild.scalp7_economic_runner_v1"
)


def dump(root: Path, name: str, value: Any) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    candidates = {alias: {"identity": "identity_" + alias} for alias in seal.ALIASES}
    dump(
        tmp_path,
        seal.CAMPAIGN + "/BATCH_SELECTION.json",
        {
            "candidates": candidates,
            "max_candidates": 4,
            "max_full_executions": 4,
            "max_hypotheses": 2,
            "scope_key": seal.SCOPE,
            "owner": "synthetic_owner",
        },
    )
    dump(
        tmp_path,
        seal.BASE,
        {
            "code_hashes": {"backend/research/rebuild/imported.py": ""},
            "data_hashes": {},
            "cost_path": "research/cost.json",
        },
    )
    for name in (
        *seal.MANDATORY,
        "backend/research/rebuild/imported.py",
        "research/cost.json",
        seal.CAMPAIGN + "/REPORT.md",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic fixture\n")
    for alias, candidate in candidates.items():
        dump(tmp_path, seal.CAMPAIGN + "/freezes/" + alias + ".json", {"hashes": {}})
        ledger = seal.CAMPAIGN + "/results/" + alias + ".trades.json.gz"
        signals = seal.CAMPAIGN + "/results/" + alias + ".signals.json.gz"
        dump(tmp_path, ledger, {})
        dump(tmp_path, signals, {})
        dump(
            tmp_path,
            seal.CAMPAIGN + "/results/" + alias + ".json",
            {
                "identity_key": "key_" + alias,
                "candidate": candidate,
                "alias": alias,
                "freeze_path": seal.CAMPAIGN + "/freezes/" + alias + ".json",
                "ledger_path": ledger,
                "signal_path": signals,
                "fresh_T": 0,
                "order": "BLOCKED",
                "live": "BLOCKED",
                "promotion": False,
            },
        )
    dump(
        tmp_path,
        seal.CAMPAIGN + "/EXPORT_REGISTRY.json",
        {
            "scope": seal.SCOPE,
            "owner": "synthetic_owner",
            "max_candidates": 4,
            "max_executions": 4,
            "executions_started": 4,
            "claims": [
                {
                    "identity_key": "key_" + a,
                    "candidate_id": c["identity"],
                    "state": "COMPLETED",
                    "receipt": str(
                        tmp_path / seal.CAMPAIGN / "results" / (a + ".json")
                    ),
                    "receipt_sha256": runner.base.sha(
                        tmp_path / seal.CAMPAIGN / "results" / (a + ".json")
                    ),
                    "result": {
                        "receipt": str(
                            tmp_path / seal.CAMPAIGN / "results" / (a + ".json")
                        ),
                        "sha256": runner.base.sha(
                            tmp_path / seal.CAMPAIGN / "results" / (a + ".json")
                        ),
                    },
                }
                for a, c in candidates.items()
            ],
            "events": [
                {"identity_key": "key_" + a, "event": "STARTED"} for a in candidates
            ],
        },
    )
    dump(
        tmp_path,
        seal.CAMPAIGN + "/EXECUTION_RECEIPT.json",
        {
            "scope": seal.SCOPE,
            "completed_full_executions": 4,
            "root_selection_budget": 4,
            "user_limit": 4,
            "new_identity_count": 4,
            "hypotheses": 2,
            "remaining_full_budget": 0,
            "repeated_economic_executions": 0,
            "saved_parent_economic_replays": 0,
            "fresh_T": 0,
            "order": "BLOCKED",
            "live": "BLOCKED",
            "promotion": False,
            "registry_sha256": seal.record(
                tmp_path, seal.CAMPAIGN + "/EXPORT_REGISTRY.json"
            )["sha256"],
        },
    )

    def fixture_checks(root: Path) -> None:
        seal.verify_registry(root)
        seal.verify_execution_receipt(root)

    monkeypatch.setattr(seal, "saved_checks", fixture_checks)
    seal.seal(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "mutation",
    ["missing", "added", "modified", "mode", "symlink_file", "symlink_directory"],
)
def test_saved_publication_rejects_artifact_tampering(publication: Path, mutation: str):
    report = publication / seal.CAMPAIGN / "REPORT.md"
    if mutation == "missing":
        report.unlink()
    elif mutation == "added":
        report.with_name("UNSEALED.md").write_text("unexpected publication")
    elif mutation == "modified":
        report.write_text("altered report")
    elif mutation == "mode":
        report.chmod(0o755)
    elif mutation == "symlink_file":
        target = publication / "outside.txt"
        target.write_text(report.read_text())
        report.unlink()
        report.symlink_to(target)
    else:
        (report.parent / "linked_directory").symlink_to(
            publication, target_is_directory=True
        )
    with pytest.raises(ValueError, match="SEAL_"):
        seal.verify(publication)


def test_removing_manifest_entry_does_not_hide_frozen_dependency(publication: Path):
    name = "backend/research/rebuild/imported.py"
    path = publication / seal.SEAL
    manifest = json.loads(path.read_text())
    del manifest["files"][name]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="MEMBERSHIP"):
        seal.verify(publication)


@pytest.mark.parametrize(
    "unsafe", ["/etc/passwd", "../escape", "a/../b", "./x", "a//b", "a\\b"]
)
def test_frozen_dependency_paths_cannot_escape(publication: Path, unsafe: str):
    path = publication / seal.CAMPAIGN / "freezes/SQ0.json"
    path.write_text(json.dumps({"hashes": {unsafe: "0" * 64}}))
    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        seal.paths(publication)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_execution",
        "duplicate_start",
        "missing_start",
        "not_completed",
        "wrong_identity",
        "budget",
    ],
)
def test_registry_cannot_be_resealed_after_execution_contract_drift(
    publication: Path, mutation: str
):
    path = publication / seal.CAMPAIGN / "EXPORT_REGISTRY.json"
    value = json.loads(path.read_text())
    if mutation == "extra_execution":
        value["executions_started"] = 6
    elif mutation == "duplicate_start":
        value["events"][0] = value["events"][1]
    elif mutation == "missing_start":
        value["events"].pop()
    elif mutation == "not_completed":
        value["claims"][0]["state"] = "RUNNING"
    elif mutation == "wrong_identity":
        value["claims"][0]["candidate_id"] = "unselected"
    else:
        value["max_executions"] = 6
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="REGISTRY"):
        seal.seal(publication)


def test_resealing_cashflow_tampering_still_calls_unchanged_saved_arithmetic(
    publication: Path, monkeypatch: pytest.MonkeyPatch
):
    windows = [
        {"label": "v", "partition": "validation", "start_ms": 0, "end_ms": 10000},
        {"label": "r", "partition": "rolling", "start_ms": 10000, "end_ms": 20000},
    ]
    selection_path = publication / seal.CAMPAIGN / "BATCH_SELECTION.json"
    selection = json.loads(selection_path.read_text())
    candidate = {
        **selection["candidates"]["SQ0"],
        "lane": "fixture_lane",
        "parent": "fixture_parent",
        "axis": "fixture_cashflow_verification",
    }
    selection["candidates"]["SQ0"] = candidate
    selection_path.write_text(json.dumps(selection))
    signal = {
        "identity": candidate["identity"],
        "symbol": "BTC-USDT",
        "side": 1,
        "timeframe_min": 15,
        "signal_ts_ms": 1000,
        "meta": {},
    }
    row: dict[str, Any] = {
        "identity": candidate["identity"],
        "signal": signal,
        "timeframe_min": 15,
        "symbol": "BTC-USDT",
        "side": 1,
        "window_label": "v",
        "signal_ts_ms": 1000,
        "entry_ts_ms": 2000,
        "exit_ts_ms": 4000,
        "outcome_available_ts_ms": 5000,
        "entry_prices": {"BTC-USDT": 100.0},
        "exit_prices": {"BTC-USDT": 105.0},
        "partial_cashflows": [],
        "terminal_fraction_original_notional": 1.0,
        "gross_bps": 500.0,
        "cost_bps": 14.0,
        "net_bps": 486.0,
    }
    frozen = {
        "windows": windows,
        "hashes": {},
        "candidate": candidate,
        "rule_sha256": "a" * 64,
        "execution_sha256": "b" * 64,
        "data_sha256": "c" * 64,
        "cost_sha256": "d" * 64,
        "window_sha256": runner.base.digest(windows),
    }
    freeze_path = seal.CAMPAIGN + "/freezes/SQ0.json"
    dump(publication, freeze_path, frozen)
    payload = {"trades": [row], "unresolved": [], "window_receipts": []}
    ledger_name = seal.CAMPAIGN + "/results/SQ0.trades.json.gz"
    ledger = publication / ledger_name
    ledger.write_bytes(gzip.compress(json.dumps(payload).encode()))
    signals_name = seal.CAMPAIGN + "/results/SQ0.signals.json.gz"
    (publication / signals_name).write_bytes(
        gzip.compress(json.dumps([signal]).encode())
    )
    info = {
        "alias": "SQ0",
        "candidate": candidate,
        "identity_key": runner.candidate_claim(frozen).key,
        "fresh_T": 0,
        "order": "BLOCKED",
        "live": "BLOCKED",
        "promotion": False,
        "freeze_path": freeze_path,
        "freeze_sha256": runner.base.sha(publication / freeze_path),
        "signal_path": signals_name,
        "signals_sha256": runner.base.sha(publication / signals_name),
        "ledger_path": ledger_name,
        "ledger_sha256": runner.base.sha(ledger),
        "summary": runner.summarize([row], windows),
        "unresolved_count": 0,
        "window_receipts": [],
    }
    dump(publication, seal.CAMPAIGN + "/results/SQ0.json", info)
    monkeypatch.setattr(runner, "ROOT", publication)
    monkeypatch.setattr(runner, "OUT", publication / seal.CAMPAIGN)
    monkeypatch.setattr(runner, "verify_freeze", lambda _: frozen)
    monkeypatch.setattr(seal, "saved_checks", lambda _: runner.verify_saved("SQ0"))
    monkeypatch.setattr(runner, "run", lambda _: pytest.fail("economic run forbidden"))
    seal.seal(publication)
    row["exit_prices"]["BTC-USDT"] = 106.0
    ledger.write_bytes(gzip.compress(json.dumps(payload).encode()))
    info["ledger_sha256"] = runner.base.sha(ledger)
    dump(publication, seal.CAMPAIGN + "/results/SQ0.json", info)
    with pytest.raises(ValueError, match="CASHFLOW_ARITHMETIC"):
        seal.seal(publication)


def workflow_filters(text: str, event: str) -> list[str]:
    # Parse only the deliberately simple two-space event/four-space paths subset.
    body = re.search(
        r"^  " + event + r":\n(.*?)(?=^  \w|^\w|\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert body is not None
    return re.findall(r"^      - ['\"]([^'\"]+)['\"]$", body.group(1), re.MULTILINE)


def test_ci_pr_and_push_filters_cover_every_freeze_and_manifest_path():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / seal.WORKFLOW).read_text()
    names = {seal.SEAL, *seal.MANDATORY}
    base = json.loads((root / seal.BASE).read_text())
    names.update(base["code_hashes"])
    names.update(base["data_hashes"])
    names.add(base["cost_path"])
    for path in (root / seal.CAMPAIGN / "freezes").glob("*.json"):
        names.add(path.relative_to(root).as_posix())
        names.update(json.loads(path.read_text())["hashes"])
    for path in (root / seal.CAMPAIGN).rglob("*"):
        if path.is_file():
            names.add(path.relative_to(root).as_posix())
    manifest = root / seal.SEAL
    if manifest.exists():
        names.update(json.loads(manifest.read_text())["files"])
    for event in ("pull_request", "push"):
        filters = workflow_filters(workflow, event)
        assert filters
        patterns = [
            re.escape(p).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") for p in filters
        ]
        assert not {
            name for name in names if not any(re.fullmatch(p, name) for p in patterns)
        }


def test_previous_workflows_remain_byte_identical():
    root = Path(__file__).resolve().parents[1]
    for name, expected in {
        "scalp7-source-fidelity-v1.yml": "3b9de31eb249c799953738a9246973c29853128b71db77a48af1c74cb4007da7",
        "scalp7-source-ab-saved-v1.yml": "c7903f8859c369ae0fbd38d2a696da919b5f19df04b12ddaa9ec5e75dbad15a3",
        "scalp7-broad-v2-saved-verify.yml": "7e82dc85e78da254771e04dfcb1101b5bf3c301d377984f193df16786c7f4c00",
    }.items():
        assert (
            hashlib.sha256((root / ".github/workflows" / name).read_bytes()).hexdigest()
            == expected
        )


@pytest.mark.parametrize("key", ["freeze_path", "ledger_path", "signal_path"])
@pytest.mark.parametrize("escape", ["absolute", "parent", "unsealed", "wrong_alias"])
def test_receipt_pointers_cannot_escape_sealed_alias_files(
    publication: Path, key: str, escape: str
):
    path = publication / seal.CAMPAIGN / "results/SQ0.json"
    info = json.loads(path.read_text())
    external = publication / "outside.json"
    external.write_text("{}")
    info[key] = {
        "absolute": str(external),
        "parent": "../outside.json",
        "unsealed": "outside.json",
        "wrong_alias": seal.CAMPAIGN + "/freezes/SQ2.json",
    }[escape]
    path.write_text(json.dumps(info))
    with pytest.raises(ValueError, match="UNSAFE_PATH|RESULT_POINTER"):
        seal.seal(publication)


def test_drift_rejected_before_saved_dependency_import(publication: Path, monkeypatch):
    monkeypatch.setattr(
        seal, "saved_checks", lambda _: pytest.fail("drifted code executed")
    )
    (publication / "backend/research/rebuild/imported.py").write_text("tampered")
    with pytest.raises(ValueError, match="SEAL_FILE_DRIFT"):
        seal.verify(publication)


@pytest.mark.parametrize("key", ["receipt", "receipt_sha256", "result"])
def test_registry_receipts_must_bind_selected_saved_results(
    publication: Path, key: str
):
    path = publication / seal.CAMPAIGN / "EXPORT_REGISTRY.json"
    value = json.loads(path.read_text())
    value["claims"][0][key] = {} if key == "result" else "unbound"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="REGISTRY_RECEIPT"):
        seal.seal(publication)


@pytest.mark.parametrize("mutation", ["modified", "deleted", "unlisted"])
def test_hook_configuration_is_required_and_sealed(publication: Path, mutation: str):
    config = publication / ".pre-commit-config.yaml"
    manifest_path = publication / seal.SEAL
    manifest = json.loads(manifest_path.read_text())
    assert ".pre-commit-config.yaml" in manifest["files"]
    if mutation == "modified":
        config.write_text("repos: []\n")
    elif mutation == "deleted":
        config.unlink()
    else:
        del manifest["files"][".pre-commit-config.yaml"]
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="SEAL_"):
        seal.verify(publication)


def test_ci_uses_existing_isolated_hooks_without_skipping_gates():
    root = Path(__file__).resolve().parents[1]
    # Match the established hook contract without a new PyYAML dependency.
    config = (root / ".pre-commit-config.yaml").read_bytes()
    assert hashlib.sha256(config).hexdigest() == (
        "692b639feb584ba22b73eecf71df3d3385a05a7fef0e1c71c0a745eecef82f53"
    )
    workflow = (root / seal.WORKFLOW).read_text()
    assert 'pre-commit run --files "${files[@]}"' in workflow
    assert "pre-commit==4.6.0" in workflow
    assert "SKIP" not in workflow and "continue-on-error" not in workflow
    assert not re.search(r"^          (black|ruff|mypy) ", workflow, re.MULTILINE)
    for event in ("pull_request", "push"):
        assert ".pre-commit-config.yaml" in workflow_filters(workflow, event)


@pytest.mark.parametrize(
    "key,value",
    [
        ("hypotheses", 3),
        ("new_identity_count", 5),
        ("completed_full_executions", 5),
        ("remaining_full_budget", 1),
        ("repeated_economic_executions", 1),
        ("saved_parent_economic_replays", 1),
        ("fresh_T", 1),
        ("order", "ALLOW"),
        ("live", "ALLOW"),
        ("promotion", True),
        ("registry_sha256", "unbound"),
    ],
)
def test_execution_receipt_cannot_claim_extra_authority_or_unbound_registry(
    publication: Path, key: str, value: Any
):
    path = publication / seal.CAMPAIGN / "EXECUTION_RECEIPT.json"
    receipt = json.loads(path.read_text())
    receipt[key] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="SEAL_EXECUTION_"):
        seal.seal(publication)


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_hypotheses", 3),
        ("max_candidates", 5),
        ("max_full_executions", 5),
        ("scope_key", "different_scope"),
    ],
)
def test_selection_rejects_budget_and_scope_changes(
    publication: Path, key: str, value: Any
):
    path = publication / seal.CAMPAIGN / "BATCH_SELECTION.json"
    selection = json.loads(path.read_text())
    selection[key] = value
    path.write_text(json.dumps(selection))
    with pytest.raises(ValueError, match="SELECTION_BUDGET"):
        seal.seal(publication)


@pytest.mark.parametrize(
    "key,value",
    [("fresh_T", 1), ("order", "ALLOW"), ("live", "ALLOW"), ("promotion", True)],
)
def test_result_does_not_authorize_fresh_counts_orders_or_promotion(
    publication: Path, key: str, value: Any
):
    path = publication / seal.CAMPAIGN / "results/SQ0.json"
    info = json.loads(path.read_text())
    info[key] = value
    path.write_text(json.dumps(info))
    with pytest.raises(ValueError, match="RESULT_AUTHORITY"):
        seal.seal(publication)


def test_selected_identities_must_be_unique(publication: Path):
    path = publication / seal.CAMPAIGN / "BATCH_SELECTION.json"
    selection = json.loads(path.read_text())
    selection["candidates"]["SQ2"]["identity"] = selection["candidates"]["SQ0"][
        "identity"
    ]
    path.write_text(json.dumps(selection))
    with pytest.raises(ValueError, match="SELECTION_BUDGET"):
        seal.seal(publication)


def test_ci_has_no_economic_execution_or_automatic_resealing():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / seal.WORKFLOW).read_text()
    assert "scalp7_economic_runner_v1" not in workflow
    assert "--seal" not in workflow
    assert "scalp7_economic_report_v1" not in workflow
    assert "python scripts/verify_scalp7_fidelity_saved_v1.py" in workflow
    assert "python scripts/verify_scalp7_economic_saved_v1.py" in workflow
