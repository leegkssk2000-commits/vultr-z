"""Frozen chronology and source-admission contract for Issue 1361.

This module is metadata-only.  It does not load market bars, form signals, fit a
model, or reserve economic execution.  Historical bars retain modeled
bar-close availability; prospective observations require recorded receipts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

DAY_MS = 86_400_000
HALF_HOUR_MS = 1_800_000
MANIFEST_HASHES = {
    "canonical_12m/MANIFEST.json": "fc7787854399348856ba13df5961c29af2ddc8655e162135cd44603b20a562c3",
    "canonical_gapday_prefix/MANIFEST.json": "9ffef229544bdc7ec78c54dda6545565e64ba6757970844458538eadc2b4515c",
    "canonical_postgap_20260213/MANIFEST.json": "bce71f9b39dee91d7ebe074da0407d672f1ead645ade5ccd788c45f96cee5bf7",
}
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
RULE_SHA256 = "004d374096f31eadb3ef883e4481a58be7673eea7d679ad66ac5c59a73c1964d"
COST_SHA256 = "cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73"
SOURCE_INVENTORY_SHA256 = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
PROTOCOL_SHA256 = "5e58240d121587f91d48292324544250af904154fa9e0c59aa8d7ecefe045401"
SOURCE_ROOT = "/home/z/z/runtime/economic7_campaign_20260915"
CLASSIFICATION = "RETROSPECTIVE_PIPELINE_STABILITY_NOT_FRESH"
FORWARD_CLAIM_REF = "refs/heads/research-execution-claims/issue1361-forward-20261006-v1"


class AdmissionError(RuntimeError):
    """The frozen validation contract or its evidence is invalid."""


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def planned_history() -> list[dict[str, Any]]:
    rows = [
        ("H1", "2026-03-19T00:00:00Z", "2026-06-17T00:00:00Z", "2026-07-17T00:00:00Z"),
        ("H2", "2026-04-18T00:00:00Z", "2026-07-17T00:00:00Z", "2026-08-16T00:00:00Z"),
        ("H3", "2026-05-18T00:00:00Z", "2026-08-16T00:00:00Z", "2026-09-15T00:00:00Z"),
    ]
    return [
        {
            "id": name,
            "fit_start_ms": _ms(fit_start),
            "fit_end_ms": _ms(test_start),
            "test_start_ms": _ms(test_start),
            "test_end_ms": _ms(test_end),
            "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
            "classification": CLASSIFICATION,
            "instances": ["EMA21_BUY_LIMIT", "SQUEEZE_PARENT"],
        }
        for name, fit_start, test_start, test_end in rows
    ]


def check_history(rows: list[Mapping[str, Any]]) -> None:
    expected = planned_history()
    if len(rows) != 3:
        raise AdmissionError("HISTORY_REQUIRES_EXACTLY_THREE_FOLDS")
    for supplied, frozen in zip(rows, expected, strict=True):
        for key in (
            "id",
            "fit_start_ms",
            "fit_end_ms",
            "test_start_ms",
            "test_end_ms",
            "instances",
        ):
            if supplied.get(key) != frozen[key]:
                raise AdmissionError(f"HISTORY_FROZEN_FIELD_MISMATCH:{frozen['id']}:{key}")
        if supplied["fit_end_ms"] != supplied["test_start_ms"]:
            raise AdmissionError("FIT_MUST_END_AT_TEST_START")
        if supplied["fit_end_ms"] - supplied["fit_start_ms"] != 90 * DAY_MS:
            raise AdmissionError("FIT_NOT_90_CALENDAR_DAYS")
        if supplied["test_end_ms"] - supplied["test_start_ms"] != 30 * DAY_MS:
            raise AdmissionError("TEST_NOT_30_CALENDAR_DAYS")
        if supplied.get("clock_profile") != frozen["clock_profile"]:
            raise AdmissionError("HISTORICAL_RECEIPT_SEMANTICS_INVENTED")
        if supplied.get("classification") != CLASSIFICATION:
            raise AdmissionError("HISTORY_MUST_NOT_BE_LABELLED_FRESH_OOS")
        if supplied.get("fit_source_end_ms", supplied["fit_end_ms"]) > supplied["test_start_ms"]:
            raise AdmissionError("FUTURE_FIT_INPUT")
    if any(row.get("fit_end_ms") == _ms("2026-09-15T00:00:00Z") for row in rows[:-1]):
        raise AdmissionError("FINAL_FIT_BACKAPPLIED")


def canonical_sha(row: Mapping[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _commit_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def check_forward(
    contract: Mapping[str, Any],
    immutable_freeze_receipt: Mapping[str, Any],
    expected_freeze_receipt_sha256: str,
) -> None:
    """Validate F against a separately persisted source-binding receipt.

    The caller cannot self-assert the freeze timestamp in ``contract``.  The
    driver must first persist the receipt write-once and bind its canonical hash
    in the permanent claim; this function verifies that same hash and content.
    """
    receipt_required = {
        "schema": "scalp7.issue1361.forward_freeze.v1",
        "issue": 1361,
        "protocol_sha256": PROTOCOL_SHA256,
        "rule_sha256": RULE_SHA256,
        "source_verified": True,
        "receipt_cursor_persistent": True,
    }
    for key, value in receipt_required.items():
        if immutable_freeze_receipt.get(key) != value:
            raise AdmissionError(f"FORWARD_FREEZE_RECEIPT_MISMATCH:{key}")
    frozen = immutable_freeze_receipt.get("frozen_at_ms")
    binding_sha = immutable_freeze_receipt.get("source_binding_sha256")
    if not isinstance(frozen, int) or frozen <= 0 or not _sha(binding_sha):
        raise AdmissionError("FORWARD_FREEZE_RECEIPT_IDENTITY")
    if not _sha(expected_freeze_receipt_sha256):
        raise AdmissionError("FORWARD_TRUSTED_FREEZE_DIGEST_REQUIRED")
    receipt_sha = canonical_sha(immutable_freeze_receipt)
    if receipt_sha != expected_freeze_receipt_sha256:
        raise AdmissionError("FORWARD_FREEZE_NOT_IN_TRUSTED_CLAIM")
    if contract.get("freeze_receipt_sha256") != expected_freeze_receipt_sha256:
        raise AdmissionError("FORWARD_FREEZE_RECEIPT_HASH")
    required = {
        "fit_end_ms": _ms("2026-09-15T00:00:00Z"),
        "duration_days": 90,
        "report_days": [30, 60, 90],
        "clock_profile": "RECORDED_RECEIPT",
        "source_verified": True,
        "receipt_cursor_persistent": True,
        "carry_in_positions": False,
        "outcome_used_to_choose_start": False,
    }
    for key, value in required.items():
        if contract.get(key) != value:
            raise AdmissionError(f"FORWARD_CONTRACT_MISMATCH:{key}")
    start = contract.get("start_ms")
    first_boundary = (frozen // HALF_HOUR_MS + 1) * HALF_HOUR_MS
    if not isinstance(start, int) or start != first_boundary:
        raise AdmissionError("FORWARD_START_NOT_FIRST_POST_FREEZE_UTC30M")
    if contract.get("end_ms") != start + 90 * DAY_MS:
        raise AdmissionError("FORWARD_END_NOT_EXACTLY_90_DAYS")


def _git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def verified_forward_freeze(
    api: Callable[[str, str], Mapping[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Read the trusted digest from the fixed permanent GitHub claim ref.

    The execution driver supplies the authenticated GitHub API callback.  It
    never derives trust from the contract or receipt passed to check_forward.
    Ref administration remains a trusted-maintainer boundary.
    """
    route = "/git/ref/" + FORWARD_CLAIM_REF.removeprefix("refs/")
    ref = api("GET", route)
    if (
        ref.get("ref") != FORWARD_CLAIM_REF
        or ref.get("object", {}).get("type") != "commit"
        or not _commit_sha(ref.get("object", {}).get("sha"))
    ):
        raise AdmissionError("FORWARD_CLAIM_REF_PROFILE")
    commit = api("GET", "/git/commits/" + ref["object"]["sha"])
    tree = api("GET", "/git/trees/" + commit["tree"]["sha"])
    entries = {entry["path"]: entry for entry in tree.get("tree", [])}
    if set(entries) != {"CLAIM.json", "FREEZE.json"} or any(
        entry.get("type") != "blob" for entry in entries.values()
    ):
        raise AdmissionError("FORWARD_CLAIM_TREE_PROFILE")

    def read_blob(name: str) -> tuple[dict[str, Any], str]:
        entry = entries[name]
        blob = api("GET", "/git/blobs/" + entry["sha"])
        if blob.get("encoding") != "base64":
            raise AdmissionError("FORWARD_CLAIM_BLOB_ENCODING")
        raw = base64.b64decode(blob["content"], validate=False)
        if _git_blob(raw) != entry["sha"]:
            raise AdmissionError("FORWARD_CLAIM_BLOB_HASH")
        return json.loads(raw), entry["sha"]

    claim, _ = read_blob("CLAIM.json")
    receipt, receipt_blob_sha = read_blob("FREEZE.json")
    expected = canonical_sha(receipt)
    required_claim = {
        "schema": "scalp7.issue1361.forward_claim.v1",
        "issue": 1361,
        "state": "RESERVED_NONRETRYABLE",
        "claim_ref": FORWARD_CLAIM_REF,
        "protocol_sha256": PROTOCOL_SHA256,
        "rule_sha256": RULE_SHA256,
        "freeze_blob_sha": receipt_blob_sha,
        "freeze_receipt_sha256": expected,
        "source_binding_sha256": receipt.get("source_binding_sha256"),
    }
    for key, value in required_claim.items():
        if claim.get(key) != value:
            raise AdmissionError(f"FORWARD_CLAIM_MISMATCH:{key}")
    if not _commit_sha(claim.get("independent_approval_commit_sha")):
        raise AdmissionError("FORWARD_CLAIM_APPROVAL_IDENTITY")
    return receipt, expected


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def full_archive_inventory(
    root: str | Path,
    expected_manifests: Mapping[str, str] = MANIFEST_HASHES,
) -> dict[str, str]:
    """Hash the exact archive file set used by scalp7_source_data_v2._inventory."""
    root = Path(root)
    inventory = {
        relative: sha_file(root / relative)
        for relative in sorted(expected_manifests)
        if (root / relative).is_file()
    }
    for segment in ("canonical_12m", "canonical_postgap_20260213"):
        base = root / segment
        for sub, pattern in (
            ("daily_receipts", "*.json"),
            ("requests", "*.receipt.json"),
            ("requests", "*.body"),
            ("normalized_chunks", "*.csv.gz"),
            ("1m", "*.csv.gz"),
        ):
            for path in sorted((base / sub).rglob(pattern)):
                if path.is_file():
                    inventory[str(path.relative_to(root))] = sha_file(path)
    prefix = root / "canonical_gapday_prefix"
    for path in sorted(prefix.glob("*/1m.csv.gz")):
        if path.is_file():
            inventory[str(path.relative_to(root))] = sha_file(path)
    return inventory


def archive_inventory_sha256(inventory: Mapping[str, str]) -> str:
    raw = (json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def inventory_source(
    root: str | Path,
    expected: Mapping[str, str] = MANIFEST_HASHES,
    expected_inventory_sha256: str = SOURCE_INVENTORY_SHA256,
) -> dict[str, Any]:
    root = Path(root)
    entries = []
    for relative, expected_sha in sorted(expected.items()):
        path = root / relative
        if not path.is_file():
            entries.append({
                "path": relative,
                "state": "MISSING",
                "expected_sha256": expected_sha,
                "actual_sha256": None,
            })
            continue
        actual = sha_file(path)
        entries.append({
            "path": relative,
            "state": "AVAILABLE_HASH_MATCH" if actual == expected_sha else "HASH_MISMATCH",
            "expected_sha256": expected_sha,
            "actual_sha256": actual,
        })
    full_inventory = full_archive_inventory(root, expected)
    inventory_sha = archive_inventory_sha256(full_inventory)
    manifests_match = all(row["state"] == "AVAILABLE_HASH_MATCH" for row in entries)
    inventory_matches = inventory_sha == expected_inventory_sha256
    ready = manifests_match and inventory_matches
    return {
        "schema": "scalp7.issue1361.source_inventory.v1",
        "root": str(root),
        "entries": entries,
        "full_inventory_files": len(full_inventory),
        "full_inventory_sha256": inventory_sha,
        "expected_full_inventory_sha256": expected_inventory_sha256,
        "full_inventory_state": "HASH_MATCH" if inventory_matches else "HASH_MISMATCH",
        "history_input_state": "READY" if ready else "INPUT_NOT_READY",
        "economic_authority": False,
        "network_actions": 0,
        "service_actions": 0,
    }


def protocol() -> dict[str, Any]:
    rows = planned_history()
    check_history(rows)
    return {
        "schema": "scalp7.issue1361.repeatability_protocol.v1",
        "issue": 1361,
        "strategy": {
            "candidate": "EMA21_BUY_LIMIT",
            "comparator": "SQUEEZE_PARENT",
            "rule_sha256": RULE_SHA256,
            "new_rule_candidates": 0,
            "tuning_allowed": False,
        },
        "source": {
            "symbols": list(SYMBOLS),
            "manifest_sha256": dict(MANIFEST_HASHES),
            "published_inventory_sha256": SOURCE_INVENTORY_SHA256,
            "historical_clock": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
            "forward_clock": "RECORDED_RECEIPT_REQUIRED",
            "volume_unit": "UNKNOWN_NOT_SIZING_AUTHORITY",
        },
        "cost": {
            "snapshot_sha256": COST_SHA256,
            "profiles": ["1x", "2x"],
            "same_fills_recalculation_only": True,
            "funding_mark_nav_unknown_not_zero": True,
        },
        "history": rows,
        "forward": {
            "fit_end_ms": _ms("2026-09-15T00:00:00Z"),
            "duration_days": 90,
            "report_days": [30, 60, 90],
            "status": "INPUT_NOT_READY",
            "requires_recorded_receipt": True,
            "no_retroactive_start": True,
            "no_boundary_liquidation_or_reset": True,
        },
        "allocation": {
            "history_max_full": 6,
            "forward_model_streams": 2,
            "total_validation_instances": 8,
            "issue1358_budget_untouched": True,
        },
        "authority": "METADATA_ONLY_NO_SIGNAL_NO_FIT_NO_ECONOMIC_CLAIM",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=SOURCE_ROOT)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = {"protocol": protocol(), "inventory": inventory_source(args.source_root)}
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
