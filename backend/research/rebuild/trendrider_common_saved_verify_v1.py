"""Read-only verification of the blocked common source attempt; no economics.

Only a byte-pinned saved manifest may authorize file reads. Quarantined source
timestamps substantiate the boundary failure; no OHLC features are computed.
This module intentionally imports neither the collector nor policy/replay code.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCOPE = "TRENDRIDER_UNIFIED_SHARED_COMMON_REPLAY_AFTER_PR1273_V1"
EVIDENCE = "research/development_evidence/" + SCOPE
MANIFEST_PATH = EVIDENCE + "/SAVED_FILE_MANIFEST.json"
SAVED_MANIFEST_SHA256 = "8c896c7ec196d08f347ea6f8d983fb0756c79edbb319501e4763d652512f1b5c"
PREEXEC_SHA256 = "73b90a8093eabb08db68829c6b82a42f459009d4054ce6a97f3961fe4c68ffd4"
CUTOFF_MS = 1_788_048_000_000
HOUR_MS = 3_600_000
FIRST_OPEN_MS = CUTOFF_MS - 1000 * HOUR_MS
ENDPOINT = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")


class VerificationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _canonical(value: Any, *, newline: bool = False) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    return (text + ("\n" if newline else "")).encode("utf-8")


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "SAVED_JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise VerificationError("SAVED_JSON_INVALID") from exc


def _path(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and bool(relative), "SAVED_PATH_TYPE")
    parts = PurePosixPath(relative).parts
    _require(not relative.startswith("/") and "\\" not in relative and ":" not in relative
             and "\x00" not in relative and all(part not in (".", "..") for part in parts)
             and PurePosixPath(relative).as_posix() == relative,
             "SAVED_PATH_ESCAPE")
    _require("squeeze" not in relative.lower(), "SAVED_SQUEEZE_PATH_FORBIDDEN")
    candidate = root.joinpath(*parts)
    _require(not any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)),
             "SAVED_SYMLINK_FORBIDDEN")
    _require(candidate.resolve().is_relative_to(root.resolve()), "SAVED_PATH_ESCAPE")
    return candidate


def _file_map(value: Any, label: str) -> dict[str, str]:
    _require(isinstance(value, dict) and isinstance(value.get("files"), dict), label + "_FILES")
    files = value["files"]
    _require(bool(files), label + "_EMPTY")
    for path, digest in files.items():
        _require(isinstance(path, str) and isinstance(digest, str)
                 and HASH_RE.fullmatch(digest) is not None, label + "_ENTRY")
    return files


def _sealed(value: dict[str, Any], label: str) -> None:
    core = {key: item for key, item in value.items() if key != "receipt_sha256"}
    _require(value.get("receipt_sha256") == _sha(_canonical(core, newline=True)), label + "_SEAL")


def verify(root: str | Path | None = None) -> dict[str, Any]:
    root = Path(root) if root is not None else ROOT
    # The sole first file read has a constant path. No JSON, embedded paths or
    # referenced dependencies are inspected before its byte hash is trusted.
    _require(HASH_RE.fullmatch(SAVED_MANIFEST_SHA256) is not None, "SAVED_MANIFEST_UNSEALED")
    manifest_raw = _path(root, MANIFEST_PATH).read_bytes()
    _require(_sha(manifest_raw) == SAVED_MANIFEST_SHA256, "SAVED_MANIFEST_SHA_MISMATCH")
    manifest = _json(manifest_raw)
    files = _file_map(manifest, "SAVED_MANIFEST")
    _require(MANIFEST_PATH not in files, "SAVED_MANIFEST_SELF_REFERENCE")
    # Validate every path before reading even the first dependency.
    paths = {name: _path(root, name) for name in files}
    raw_files = {}
    for name, path in paths.items():
        raw = path.read_bytes()
        _require(_sha(raw) == files[name], "SAVED_FILE_SHA_MISMATCH:" + name)
        raw_files[name] = raw

    def raw(name: str) -> bytes:
        path = EVIDENCE + "/" + name
        _require(path in raw_files, "SAVED_REQUIRED_FILE_MISSING:" + name)
        return raw_files[path]

    def document(name: str) -> dict[str, Any]:
        value = _json(raw(name))
        _require(isinstance(value, dict), "SAVED_OBJECT_REQUIRED:" + name)
        return value

    frozen_raw = raw("PREEXEC_FREEZE.json")
    _require(_sha(frozen_raw) == PREEXEC_SHA256, "SAVED_PREEXEC_PIN_MISMATCH")
    frozen = document("PREEXEC_FREEZE.json")
    frozen_files = _file_map(frozen, "PREEXEC")
    preserved = _file_map(document("PRESERVED_TRENDRIDER_HASHES.json"), "PRESERVED")
    _require(len(frozen_files) == 12 and len(preserved) == 32, "SAVED_FROZEN_FILE_COUNTS")
    _require(frozen.get("dataset_fetch_attempts_at_freeze") == 0
             and frozen.get("economic_runs_at_freeze") == 0, "SAVED_PREEXEC_BUDGET")
    # These dependency manifests are byte-pinned by the immutable preexec pin.
    all_dependencies = {**frozen_files, **preserved}
    dependency_paths = {name: _path(root, name) for name in all_dependencies}
    for name, expected in all_dependencies.items():
        data = raw_files.get(name)
        if data is None:
            data = dependency_paths[name].read_bytes()
        _require(_sha(data) == expected, "SAVED_FROZEN_DEPENDENCY_MISMATCH:" + name)

    contract_raw = raw("COMMON_REPLAY_CONTRACT.json")
    contract = document("COMMON_REPLAY_CONTRACT.json")
    contract_sha = _sha(contract_raw)
    _require(frozen.get("contract_sha256") == contract_sha, "SAVED_CONTRACT_BINDING")
    _require(raw("source_data/SOURCE_CONTRACT.json") == contract_raw, "SAVED_SOURCE_CONTRACT_CHANGED")
    source = contract["source"]
    _require(source["endpoint"] == ENDPOINT and source["symbols"] == ["BTC-USDT", "ETH-USDT"]
             and source["interval"] == "1h" and source["cutoff_ms"] == CUTOFF_MS
             and source["bars_per_symbol"] == 1000 and source["page_limit"] == 1000
             and source["max_pages_per_symbol"] == 10, "SAVED_SOURCE_CONTRACT")
    cost = contract["common_cost"]
    _require(_sha(_canonical(cost)) == contract.get("common_cost_sha256"), "SAVED_COST_DIGEST")
    _require(cost.get("actual_funding") is False and cost.get("production_grade") is False
             and cost.get("current_depth_or_funding_fetch") is False, "SAVED_COST_SCOPE")
    _require(sum(cost[key] for key in ("fee_bps", "spread_bps", "impact_bps", "funding_proxy_bps"))
             == cost.get("round_trip_bps") == 14.0
             and cost.get("exact_2x_round_trip_bps") == 28.0, "SAVED_COST_TUPLE")
    readback = document("FREEZE_READBACK.json")
    _require(readback.get("preexec_manifest_sha256") == PREEXEC_SHA256
             and readback.get("contract_sha256") == contract_sha
             and readback.get("cost_sha256") == contract["common_cost_sha256"]
             and readback.get("remote_manifest_readback_exact_match") is True,
             "SAVED_FREEZE_READBACK")

    attempt = document("source_data/ATTEMPT_STARTED.json")
    failure = document("source_data/FAILURE_MANIFEST.json")
    response = document("source_data/raw/BTC-USDT_00.response.json")
    request = document("source_data/raw/BTC-USDT_00.request.json")
    for name, value in (("ATTEMPT", attempt), ("FAILURE", failure), ("RESPONSE", response)):
        _sealed(value, name)
    _require(attempt.get("attempt_ordinal") == 1 and attempt.get("retry_authorized") is False
             and attempt.get("contract_sha256") == contract_sha, "SAVED_ATTEMPT")
    _require(failure.get("state") == "BLOCKED_DATA"
             and failure.get("reason") == "SOURCE_TIMESTAMP_GRID_OR_WINDOW"
             and failure.get("error_type") == "SourceIntegrityError"
             and failure.get("contract_sha256") == contract_sha
             and failure.get("dataset_fetch_attempts") == 1 and failure.get("http_response_count") == 1
             and failure.get("normalized") == {} and failure.get("transport_retries") == 0
             and failure.get("retry_authorized") is False and failure.get("economic_runs") == 0
             and failure.get("formal_credit") == 0 and failure.get("production_grade") is False,
             "SAVED_FAILURE_STATE")
    expected_params = {"symbol": "BTC-USDT", "interval": "1h", "limit": 1000,
                       "endTime": CUTOFF_MS - 1}
    _require(request.get("endpoint") == ENDPOINT and request.get("params") == expected_params
             and request.get("page_index") == 0 and request.get("transport_retry_count") == 0,
             "SAVED_REQUEST")
    _require(failure.get("last_attempted_request") == request
             and failure.get("requests") == [response]
             and all(response.get(key) == value for key, value in request.items()),
             "SAVED_REQUEST_RESPONSE_BINDING")
    _require(response.get("http_status") == 200 and response.get("saved_before_decode") is True
             and response.get("raw_path") == "raw/BTC-USDT_00.bin", "SAVED_RESPONSE")
    raw_response = raw("source_data/raw/BTC-USDT_00.bin")
    _require(response.get("raw_sha256") == _sha(raw_response)
             and response.get("raw_bytes") == len(raw_response), "SAVED_RAW_BINDING")
    _require(attempt["started_at_ms"] <= request["requested_at_ms"]
             <= response["received_at_ms"] <= failure["failed_at_ms"], "SAVED_ATTEMPT_CLOCK")
    # This is a diagnostic of already pinned bytes, not a general market-data
    # parser. Extract only native timestamp/code tokens. In particular, do not
    # JSON-decode the quarantined blob's OHLC/volume values at all.
    code_tokens = re.findall(rb'(?<!\\)"code"\s*:\s*(-?\d+)\s*(?=[,}])', raw_response)
    time_tokens = re.findall(rb'(?<!\\)"time"\s*:\s*("?)([0-9]+)\1\s*(?=[,}])', raw_response)
    _require(code_tokens == [b"0"] and len(time_tokens) == 1000, "SAVED_RAW_TIMESTAMP_TOKENS")
    native_times = [int(value) for _, value in time_tokens]
    ordered_times = sorted(native_times)
    _require(ordered_times == list(range(FIRST_OPEN_MS + HOUR_MS, CUTOFF_MS + HOUR_MS, HOUR_MS)),
             "SAVED_BOUNDARY_SHIFT_DIAGNOSIS")

    result = document("SCOPE_RESULT.json")
    _require(result.get("state") == "BLOCKED_COMMON_SOURCE_DATA", "SAVED_SCOPE_STATE")
    budget = result.get("budget_consumed")
    expected_budget = {"dataset_freeze_attempts": 1, "control_economic_runs": 0,
                       "DEV_A_screens": 0, "DEV_B_confirmations": 0,
                       "canonical_candidates": 0, "child_FULL_runs": 0, "retry": 0,
                       "FIXED": 0, "Squeeze_v1_v2_data_access": 0, "arbitrary_OOS": 0,
                       "deploy": 0, "live": 0, "orders": 0, "paid_AI": 0,
                       "prospective_ledger_decode": 0, "sweep": 0}
    _require(isinstance(budget, dict) and set(budget) == set(expected_budget)
             and all(type(budget.get(key)) is int and budget[key] == value
                     for key, value in expected_budget.items()), "SAVED_SCOPE_BUDGET")
    _require(result.get("production_grade") is False and result.get("formal_credit") == 0
             and result.get("verdict_is_economic_rejection") is False
             and result.get("economic_validation") == "NOT_RUN_SOURCE_INTEGRITY_GATE"
             and result.get("prospective_G5A_handoff") == 0 and result.get("ETH_fetched") is False
             and result.get("normalized_data_sha256") is None and result.get("strategy_seal") is None
             and result.get("remaining_usable_economic_budget") == 0
             and result.get("source_HTTP_GETs") == 1 and result.get("source_http_responses") == 1
             and result.get("retry_authorized") is False and result.get("automatic_successor") is False,
             "SAVED_SCOPE_CREDIT")
    _require(result.get("source_contract_sha256") == contract_sha
             and result.get("common_cost_sha256") == contract["common_cost_sha256"]
             and result.get("rejected_raw_sha256") == response["raw_sha256"]
             and result.get("preexec_freeze_sha256") == PREEXEC_SHA256, "SAVED_SCOPE_BINDINGS")
    _require(result.get("economic_metrics") == {
        period: {lane: {"metrics": None, "status": "NOT_RUN"}
                 for lane in ("B_COMMON", "P_COMMON", "U1", "U2")}
        for period in ("DEV_A", "DEV_B")}, "SAVED_SCOPE_ECONOMICS_NOT_NULL")
    diagnostic = document("SOURCE_CLOCK_DIAGNOSTIC.json")
    expected_diagnostic = {"state": "SOURCE_CLOCK_WINDOW_MISMATCH", "ETH_request_count": 0,
                           "adjacent_clock_gap_count": 0, "duplicate_count": 0, "api_code": 0,
                           "automatic_repair_or_refetch": 0, "expected_first_open_ms": FIRST_OPEN_MS,
                           "expected_last_open_ms": CUTOFF_MS - HOUR_MS, "http_status": 200,
                           "missing_native_open_ms": [FIRST_OPEN_MS], "unexpected_native_open_ms": [CUTOFF_MS],
                           "normalized_dataset_sha256": None, "params": expected_params,
                           "raw_bytes": len(raw_response), "raw_sha256": _sha(raw_response),
                           "response_rows": 1000, "returned_first_open_ms": ordered_times[0],
                           "returned_last_open_ms": ordered_times[-1]}
    _require(all(diagnostic.get(key) == value for key, value in expected_diagnostic.items()),
             "SAVED_SOURCE_DIAGNOSTIC")
    source_files = {path.relative_to(_path(root, EVIDENCE + "/source_data")).as_posix()
                    for path in _path(root, EVIDENCE + "/source_data").rglob("*") if path.is_file()}
    _require(source_files == {"ATTEMPT_STARTED.json", "SOURCE_CONTRACT.json", "FAILURE_MANIFEST.json",
                              "raw/BTC-USDT_00.request.json", "raw/BTC-USDT_00.response.json",
                              "raw/BTC-USDT_00.bin"}, "SAVED_SOURCE_EXTRA_OUTPUT")
    for path in _path(root, EVIDENCE).rglob("*"):
        if path.is_file():
            name = path.relative_to(root).as_posix()
            _require(name in files or name in {MANIFEST_PATH, EVIDENCE + "/EXACT_MERGE_VERIFICATION.json"},
                     "SAVED_UNMANIFESTED_SCOPE_FILE:" + name)
    return {"state": "PASS_SAVED_BLOCKED_SOURCE_VERIFICATION", "scope_state": result["state"],
            "saved_files": len(files), "frozen_files": len(frozen_files), "preserved_files": len(preserved),
            "dataset_fetch_attempts": 1, "http_responses": 1, "raw_timestamp_rows": 1000,
            "first_observed_open_ms": ordered_times[0], "last_observed_open_ms": ordered_times[-1],
            "first_expected_open_ms": FIRST_OPEN_MS, "last_expected_open_ms": CUTOFF_MS - HOUR_MS,
            "ETH_attempted": False, "normalization": False, "economic_runs": 0,
            "prospective_handoff": 0, "saved_manifest_sha256": SAVED_MANIFEST_SHA256}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    print(json.dumps(verify(args.root), sort_keys=True))
