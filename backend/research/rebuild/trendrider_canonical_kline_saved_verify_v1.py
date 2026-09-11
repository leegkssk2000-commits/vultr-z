"""Read-only verification of the two-probe canonical-schema blocked closure.

No collector, strategy, market transport or replay is imported. A reviewed
literal manifest hash is checked before JSON decoding. Raw market responses
are inspected with timestamp/shape regular expressions only; OHLC is unused.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[3]
SCOPE = "TRENDRIDER_UNIFIED_CANONICAL_KLINE_AFTER_PR1277_V1"
EVIDENCE = "research/development_evidence/" + SCOPE
MANIFEST_PATH = EVIDENCE + "/SAVED_FILE_MANIFEST.json"
SAVED_MANIFEST_SHA256 = "6867d26d4609fbbf5b701ccca7552cf263d7bcfba052254149c2f64754a7f3a2"
MANIFEST_SCHEMA = "trendrider.canonical_kline.saved_file_manifest.v1"
VERIFIER_PATH = "backend/research/rebuild/trendrider_canonical_kline_saved_verify_v1.py"
TEST_PATH = "backend/research/rebuild/test_trendrider_canonical_kline_saved_verify_v1.py"
WORKFLOW_PATH = ".github/workflows/trendrider-canonical-kline-saved-verify-v1.yml"
PREEXEC_SHA256 = "9ecb6ad6aca051a4a87026abd283d9e36bccbb526f8ba15aad6dc1027389d1d9"
FREEZE_COMMIT = "f24b303a7f9e813ce9264b903d0323caa622cc42"
PARENT_CONTRACT_PATH = ("research/development_evidence/"
                        "TRENDRIDER_UNIFIED_SHARED_COMMON_REPLAY_AFTER_PR1273_V1/COMMON_REPLAY_CONTRACT.json")
HOUR_MS = 3_600_000
PROBE_T_MS = 1_784_332_800_000
ENDPOINT = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
REQUEST_HEADERS = {"Accept": "application/json", "X-SOURCE-KEY": "BX-AI-SKILL",
                   "Host": "open-api.bingx.com", "Connection": "close",
                   "User-Agent": "Python-urllib/3.12", "Accept-Encoding": "identity"}
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
CALIBRATION_FILES = {"CALIBRATION_ATTEMPT_STARTED.json", "CANONICAL_KLINE_TIMESTAMP_RECEIPT.json",
                     "PROBE_PROTOCOL.json", "OFFICIAL_SCHEMA_AUTHORITY.json"} | {
                         f"raw/probe_{label}.{suffix}" for label in ("A", "B")
                         for suffix in ("bin", "request.json", "response.json")}
REQUIRED_DOCUMENTS = {"WORK_NEXT.txt", "AUTHORIZATION_ISSUE.json", "COMMON_REPLAY_CONTRACT.json",
                      "PRESERVED_FILES.json", "OFFICIAL_KLINE_SCHEMA_RECEIPT.json", "PROBE_PROTOCOL.json",
                      "EXECUTION_PLAN_KO.md", "PREEXEC_FREEZE.json", "FREEZE_READBACK.json",
                      "BUDGET_TERMINAL.json", "REPORT_KO.md"} | {"calibration/" + name for name in CALIBRATION_FILES}
ZERO_BUDGET_KEYS = {
    "source_acquisition_attempts", "http_pages_BTC", "http_pages_ETH", "control_runs",
    "DEV_A_screens", "DEV_B_confirmations", "canonical_candidates", "child_FULL_runs",
    "retries", "sweeps", "prospective_ledger_decode", "paid_AI", "live", "orders", "deploy", "formal_credit",
}
FROZEN_ECONOMIC_FIELDS = (
    "common_cost", "common_cost_sha256", "execution", "policies", "partitions", "genes",
    "stage1", "stage2", "stage3", "runtime", "historical_archives",
    "excluded_terminal_predicates", "gene_provenance", "source_authority_hashes",
    "formal_credit", "production_grade",
)


class VerificationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def _same(a: Any, b: Any) -> bool:
    return _canonical(a) == _canonical(b)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "SAVED_JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _json(raw: bytes) -> Any:
    def reject(value):
        raise VerificationError("SAVED_JSON_NONFINITE:" + value)
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=reject)
    except (UnicodeError, ValueError) as exc:
        raise VerificationError("SAVED_JSON_INVALID") from exc


def _path(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and bool(relative), "SAVED_PATH_TYPE")
    parts = PurePosixPath(relative).parts
    _require(not relative.startswith("/") and "\\" not in relative and ":" not in relative
             and "\x00" not in relative and all(part not in (".", "..") for part in parts)
             and PurePosixPath(relative).as_posix() == relative, "SAVED_PATH_ESCAPE")
    _require("squeeze" not in relative.lower(), "SAVED_SQUEEZE_PATH_FORBIDDEN")
    candidate = root.joinpath(*parts)
    _require(not any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)),
             "SAVED_SYMLINK_FORBIDDEN")
    _require(candidate.resolve().is_relative_to(root.resolve()), "SAVED_PATH_ESCAPE")
    return candidate


def _file_map(value: Any, label: str) -> dict[str, str]:
    _require(isinstance(value, dict) and isinstance(value.get("files"), dict) and bool(value["files"]), label + "_FILES")
    for name, digest in value["files"].items():
        _require(isinstance(name, str) and isinstance(digest, str) and HASH_RE.fullmatch(digest) is not None,
                 label + "_ENTRY")
    return value["files"]


def _seal(value: dict[str, Any], label: str, required: bool = True) -> None:
    if required or "receipt_sha256" in value:
        unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
        _require(value.get("receipt_sha256") == _sha(_canonical(unsigned)), "SAVED_INTERNAL_SEAL:" + label)


def _tree(root: Path, saved: set[str]) -> None:
    unmanifested = {MANIFEST_PATH, EVIDENCE + "/EXACT_MERGE_VERIFICATION.json"}
    actual_calibration = set()
    for path in _path(root, EVIDENCE).rglob("*"):
        name = path.relative_to(root).as_posix()
        _path(root, name)
        local = name[len(EVIDENCE) + 1:]
        parts = [part.lower() for part in local.split("/")]
        _require(not any(part in {"source", "source_data", "source_data_v2", "source_data_v3", "owner", "results", "sources"}
                         or part.startswith(("data_freeze", "owner_input_freeze")) for part in parts),
                 "SAVED_FORBIDDEN_FOLLOWUP_ARTIFACT:" + name)
        if path.is_file():
            _require(name in saved or name in unmanifested, "SAVED_UNMANIFESTED_SCOPE_FILE:" + name)
            if local.startswith("calibration/"):
                actual_calibration.add(local[len("calibration/"):])
    _require(actual_calibration == CALIBRATION_FILES, "SAVED_CALIBRATION_EXACT_TEN_FILES")


def _raw_timestamp_only(raw: bytes, expected: int) -> None:
    # Deliberately never JSON-decode the market response or interpret prices.
    codes = re.findall(rb'(?<!\\)"code"\s*:\s*(-?\d+)\s*(?=[,}])', raw)
    times = re.findall(rb'(?<!\\)"time"\s*:\s*("?)([0-9]+)\1\s*(?=[,}])', raw)
    objects = re.findall(rb'"data"\s*:\s*\[\s*(\{[^{}\[\]]*\})\s*\]', raw)
    _require(codes == [b"0"] and len(objects) == 1 and len(times) == 1
             and int(times[0][1]) == expected, "SAVED_RAW_TIMESTAMP_OR_OBJECT_SHAPE")
    keys = re.findall(rb'"([^"\\]+)"\s*:', objects[0])
    _require(len(keys) == 6 and set(keys) == {b"open", b"close", b"high", b"low", b"volume", b"time"},
             "SAVED_RAW_OBJECT_KEYS_NO_CROSS_SCHEMA_WITNESS")


def verify(root: str | Path | None = None) -> dict[str, Any]:
    root = Path(root) if root is not None else ROOT
    _require(HASH_RE.fullmatch(SAVED_MANIFEST_SHA256) is not None, "SAVED_MANIFEST_UNSEALED")
    manifest_raw = _path(root, MANIFEST_PATH).read_bytes()
    _require(_sha(manifest_raw) == SAVED_MANIFEST_SHA256, "SAVED_MANIFEST_SHA_MISMATCH")
    manifest = _json(manifest_raw)
    files = _file_map(manifest, "SAVED_MANIFEST")
    _require(manifest.get("schema") == MANIFEST_SCHEMA and manifest.get("scope_key") == SCOPE, "SAVED_MANIFEST_SCOPE")
    _require(MANIFEST_PATH not in files and VERIFIER_PATH not in files
             and EVIDENCE + "/EXACT_MERGE_VERIFICATION.json" not in files, "SAVED_MANIFEST_CIRCULAR_OR_MERGE_RECEIPT")
    _require({TEST_PATH, WORKFLOW_PATH}.issubset(files), "SAVED_REQUIRED_TEST_OR_WORKFLOW")
    _tree(root, set(files))
    raw_files = {}
    for name, expected in files.items():
        raw = _path(root, name).read_bytes()
        _require(_sha(raw) == expected, "SAVED_FILE_SHA_MISMATCH:" + name)
        raw_files[name] = raw
    _require({EVIDENCE + "/" + name for name in REQUIRED_DOCUMENTS}.issubset(raw_files), "SAVED_REQUIRED_DOCUMENT_MISSING")
    def raw(name):
        return raw_files[EVIDENCE + "/" + name]
    def doc(name):
        value = _json(raw(name))
        _require(isinstance(value, dict), "SAVED_OBJECT_REQUIRED:" + name)
        _seal(value, name, required=False)
        return value

    preserved = _file_map(doc("PRESERVED_FILES.json"), "SAVED_PRESERVED")
    _require(len(preserved) == 80 and PARENT_CONTRACT_PATH in preserved, "SAVED_PRESERVED_EXACT_EIGHTY")
    for name, expected in preserved.items():
        _require(name not in files or files[name] == expected, "SAVED_PRESERVED_MAP_CONFLICT")
        value = _path(root, name).read_bytes()
        _require(_sha(value) == expected, "SAVED_PRESERVED_FILE_SHA_MISMATCH:" + name)
        raw_files[name] = value
    _require(_sha(raw("PREEXEC_FREEZE.json")) == PREEXEC_SHA256, "SAVED_PREEXEC_LITERAL_SHA_MISMATCH")
    preexec = doc("PREEXEC_FREEZE.json")
    _seal(preexec, "PREEXEC_FREEZE.json")
    frozen = _file_map(preexec, "SAVED_PREEXEC")
    _require(len(frozen) == 9 and preexec.get("schema") == "trendrider.canonical_kline.preexec_freeze.v1"
             and preexec.get("scope_key") == SCOPE and preexec.get("authorization_issue") == 1278,
             "SAVED_PREEXEC_NINE_FILES_OR_AUTHORITY")
    for name, expected in frozen.items():
        _require(name in raw_files and _sha(raw_files[name]) == expected, "SAVED_PREEXEC_FILE_BINDING:" + name)
    readback = doc("FREEZE_READBACK.json")
    _require(readback.get("verified_commit_sha") == FREEZE_COMMIT
             and readback.get("preexec_manifest_sha256") == PREEXEC_SHA256
             and readback.get("remote_manifest_readback_exact_match") is True
             and _same([readback.get("market_calls_before_readback"), readback.get("economic_executions_before_readback")], [0, 0]),
             "SAVED_PREEXEC_REMOTE_READBACK")

    authority = doc("OFFICIAL_KLINE_SCHEMA_RECEIPT.json")
    _require(authority.get("schema") == "trendrider.official.canonical.kline.schema.evidence.v1"
             and authority.get("facts", {}).get("object_time_open_or_close_mapping") == "NOT_ESTABLISHED",
             "SAVED_OFFICIAL_SCHEMA_AUTHORITY")
    contract = doc("COMMON_REPLAY_CONTRACT.json")
    _require(contract.get("schema_version") == "trendrider.canonical_kline_contract.v1"
             and contract.get("scope_key") == SCOPE and contract.get("authorization_issue") == 1278,
             "SAVED_CONTRACT_AUTHORITY")
    parent = _json(raw_files[PARENT_CONTRACT_PATH])
    for field in FROZEN_ECONOMIC_FIELDS:
        _require(field in contract and field in parent and _same(contract[field], parent[field]), "SAVED_FROZEN_ECONOMICS_CHANGED:" + field)
    protocol = doc("PROBE_PROTOCOL.json")
    _seal(protocol, "PROBE_PROTOCOL.json")
    _require(raw("PROBE_PROTOCOL.json") == raw("calibration/PROBE_PROTOCOL.json")
             and raw("OFFICIAL_KLINE_SCHEMA_RECEIPT.json") == raw("calibration/OFFICIAL_SCHEMA_AUTHORITY.json"),
             "SAVED_CALIBRATION_PREREGISTERED_COPY")
    expected_probes = [{"id": label, "params": {"symbol": "BTC-USDT", "interval": "1h", "startTime": stamp,
                        "endTime": stamp + HOUR_MS - 1, "limit": 3}}
                       for label, stamp in (("A", PROBE_T_MS), ("B", PROBE_T_MS + HOUR_MS))]
    _require(protocol.get("schema") == "trendrider.canonical.kline.probe.protocol.v1"
             and _same(protocol.get("probes"), expected_probes)
             and _same(protocol.get("request_headers"), REQUEST_HEADERS)
             and protocol.get("official_authority_sha256") == _sha(raw("OFFICIAL_KLINE_SCHEMA_RECEIPT.json"))
             and _same([protocol.get("max_http_calls"), protocol.get("max_attempts"), protocol.get("retry_count"), protocol.get("min_request_spacing_ms")], [2, 1, 0, 1100]),
             "SAVED_FIXED_PROBE_PROTOCOL")
    attempt = doc("calibration/CALIBRATION_ATTEMPT_STARTED.json")
    _seal(attempt, "CALIBRATION_ATTEMPT_STARTED")
    receipt = doc("calibration/CANONICAL_KLINE_TIMESTAMP_RECEIPT.json")
    _seal(receipt, "CANONICAL_KLINE_TIMESTAMP_RECEIPT")
    for value in (attempt, receipt):
        _require(value.get("protocol_sha256") == _sha(raw("PROBE_PROTOCOL.json"))
                 and value.get("official_authority_sha256") == _sha(raw("OFFICIAL_KLINE_SCHEMA_RECEIPT.json"))
                 and _same([value.get("attempt_ordinal"), value.get("retry_count"), value.get("economic_executions")], [1, 0, 0]),
                 "SAVED_CALIBRATION_INPUT_OR_ATTEMPT_BINDING")
    _require(receipt.get("schema") == "trendrider.canonical.kline.timestamp.receipt.v1"
             and receipt.get("state") == "BLOCKED_CANONICAL_KLINE_SCHEMA"
             and receipt.get("reasons") == ["OBJECT_TIME_WITHOUT_CROSS_SCHEMA_WITNESS"]
             and _same([receipt.get("actual_http_calls"), receipt.get("max_http_calls")], [2, 2])
             and receipt.get("acquisition_authorized") is False
             and receipt.get("object_time_mapping_authorized") is False
             and receipt.get("outcome_independent") is True
             and receipt.get("ohlc_numeric_interpretation") is False
             and all(key in receipt and receipt[key] is None for key in
                     ("supported_canonical_lane", "canonical_open_transform", "canonical_close_exclusive_transform", "native_close_convention")),
             "SAVED_CALIBRATION_MUST_REMAIN_BLOCKED")
    responses, outcomes = [], []
    previous_request = previous_received = None
    for spec in expected_probes:
        label, stamp = spec["id"], spec["params"]["startTime"]
        stem = "calibration/raw/probe_" + label
        request, response = doc(stem + ".request.json"), doc(stem + ".response.json")
        _seal(response, stem + ".response.json")
        _require(all(key in response and _same(response[key], value) for key, value in request.items()), "SAVED_REQUEST_RESPONSE_BINDING")
        _require(request.get("probe_id") == label and request.get("endpoint") == ENDPOINT
                 and request.get("method") == "GET" and _same(request.get("params"), spec["params"])
                 and _same(request.get("request_headers"), REQUEST_HEADERS)
                 and request.get("opener_default_headers") == [] and request.get("redirects") is False
                 and _same([request.get("timeout_seconds"), request.get("min_request_spacing_ms"), request.get("retry_count")], [30, 1100, 0]),
                 "SAVED_REQUEST_FIXED_PARAMETERS_OR_HEADERS")
        pairs = parse_qsl(request.get("query", ""), keep_blank_values=True)
        _require(len(pairs) == len(spec["params"]) and dict(pairs) == {key: str(value) for key, value in spec["params"].items()}
                 and request.get("url") == ENDPOINT + "?" + request["query"], "SAVED_REQUEST_QUERY_OR_URL")
        header_items = request.get("urllib_request_header_items")
        _require(isinstance(header_items, list) and len(header_items) == len(REQUEST_HEADERS)
                 and {key.lower(): value for key, value in header_items} == {key.lower(): value for key, value in REQUEST_HEADERS.items()},
                 "SAVED_ACTUAL_OUTBOUND_HEADER_ITEMS")
        source_raw = raw(stem + ".bin")
        _require(response.get("raw_path") == "raw/probe_" + label + ".bin"
                 and response.get("raw_sha256") == _sha(source_raw)
                 and _same([response.get("http_status"), response.get("saved_raw_bytes")], [200, len(source_raw)])
                 and response.get("saved_before_decode") is True and response.get("truncated") is False
                 and response.get("full_response_length_known") is True,
                 "SAVED_RAW_RESPONSE_BINDING_OR_STATUS")
        requested, received = request.get("requested_at_ms"), response.get("received_at_ms")
        _require(all(type(value) is int for value in (requested, received, attempt.get("started_at_ms"), receipt.get("completed_at_ms")))
                 and attempt["started_at_ms"] <= requested <= received <= receipt["completed_at_ms"], "SAVED_REQUEST_RESPONSE_TIME_ORDER")
        if previous_request is not None:
            _require(previous_received <= requested and requested - previous_request >= 1100, "SAVED_PROBE_ADJACENT_REQUEST_ORDER_OR_PACING")
        previous_request, previous_received = requested, received
        _raw_timestamp_only(source_raw, stamp)
        responses.append(response)
        outcomes.append({"probe_id": label, "target_open_ms": stamp, "row_count": 1,
                         "ohlc_values_interpreted": False, "guard_rows_economic_input": 0,
                         "array_timestamp_rows": [], "object_timestamp_rows": [{"field_names": ["time"], "timestamp_fields": {"time": stamp}}],
                         "schemas": ["object"], "guard_count": 0, "state": "FAIL_SEMANTIC",
                         "reasons": ["OBJECT_TIME_WITHOUT_CROSS_SCHEMA_WITNESS"]})
    _require(_same(receipt.get("raw_responses"), responses) and _same(receipt.get("probe_outcomes"), outcomes), "SAVED_RECEIPT_RAW_OR_TIMESTAMP_OUTCOMES")

    budget = doc("BUDGET_TERMINAL.json")
    expected_actual = {key: 0 for key in ZERO_BUDGET_KEYS} | {"diagnostic_rest_probes": 2}
    _require(budget.get("schema") == "trendrider.canonical_kline.budget_terminal.v1"
             and budget.get("scope_key") == SCOPE and budget.get("state") == "BLOCKED_CANONICAL_KLINE_SCHEMA"
             and _same(budget.get("actual"), expected_actual), "SAVED_BUDGET_ACTUAL_MUST_BE_TWO_PROBES_ONLY")
    expected_metrics = {period: {lane: {"status": "NOT_RUN", "metrics": None} for lane in ("P_COMMON", "B_COMMON", "U1", "U2")}
                        for period in ("DEV_A", "DEV_B")}
    _require(_same(budget.get("economic_metrics"), expected_metrics), "SAVED_ECONOMICS_MUST_BE_NOT_RUN")
    _require(_same([budget.get("formal_credit"), budget.get("prospective_G5A_handoff")], [0, 0])
             and budget.get("production_grade") is False and budget.get("completion") == "REPORT_ONLY"
             and all(key in budget and budget[key] is None for key in ("strategy_seal", "normalized_data_sha256")),
             "SAVED_SCOPE_CREDIT_OR_CLOSURE")
    return {"state": "PASS_SAVED_BLOCKED_CANONICAL_KLINE_SCHEMA_VERIFICATION",
            "scope_state": "BLOCKED_CANONICAL_KLINE_SCHEMA", "saved_files": len(files), "preserved_files": len(preserved),
            "calibration_files": len(CALIBRATION_FILES), "diagnostic_rest_probes": 2,
            "source_acquisition_attempts": 0, "economic_runs": 0, "formal_credit": 0,
            "prospective_G5A_handoff": 0, "manifest_sha256": SAVED_MANIFEST_SHA256,
            "canonical_timestamp_receipt_sha256": _sha(raw("calibration/CANONICAL_KLINE_TIMESTAMP_RECEIPT.json"))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    print(_canonical(verify(args.root)).decode(), end="")
