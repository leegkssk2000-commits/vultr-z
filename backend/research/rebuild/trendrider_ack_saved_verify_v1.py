"""Verify stored ACK repair and the subsequent unaccepted WS shape only.

No transport, collector, strategy, live decoder or economic executor is imported.
Literal manifest and preregistration hashes bind all parsed evidence. Stored
frame two is inspected only for its observed shape; its lone T is not assigned
open/close meaning, normalized, or credited as an accepted timestamp witness.
"""
from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCOPE = "TRENDRIDER_UNIFIED_ACK_REPAIR_AFTER_PR1281_V1"
EVIDENCE = "research/development_evidence/" + SCOPE
MANIFEST_PATH = EVIDENCE + "/SAVED_FILE_MANIFEST.json"
SAVED_MANIFEST_SHA256 = "05f8b4a2399e26d474c4f391140becbc6cc1ea9aea00d33b46379679000b45ba"
MANIFEST_SCHEMA = "trendrider.ack.saved_file_manifest.v1"
VERIFIER_PATH = "backend/research/rebuild/trendrider_ack_saved_verify_v1.py"
TEST_PATH = "backend/research/rebuild/test_trendrider_ack_saved_verify_v1.py"
WORKFLOW_PATH = ".github/workflows/trendrider-ack-repair-saved-verify-v1.yml"
FROZEN_EXECUTOR_PATH = "backend/research/rebuild/trendrider_rest_ws_timestamp_v2.py"
PREEXEC_SHA256 = "50bde068833531f9edc163efeb22577b13c8ac1a1dfa577523acbac718d87656"
FREEZE_COMMIT = "03b6921c3b2ef3807bc864fa7d2c0b54de69c2c1"
PARENT_CONTRACT_PATH = ("research/development_evidence/"
                       "TRENDRIDER_UNIFIED_SHARED_COMMON_REPLAY_AFTER_PR1273_V1/COMMON_REPLAY_CONTRACT.json")
SESSION_ID = "trendrider-rest-ws-1282-v2"
CHANNEL = "BTC-USDT@kline_1h"
WS_ENDPOINT = "wss://open-api-swap.bingx.com/swap-market"
BLOCKED_STATE = "BLOCKED_REST_WS_TIMESTAMP_WITNESS"
FAILURE_CLASS = "WS_KLINE_SCHEMA_CONTRACT_MISMATCH"
RECORDED_ERRORS = ["WS_RECEIVE:REST_WS_SYMBOL_IDENTITY"]
EXPECTED_ACK = {"id": SESSION_ID, "code": 0, "msg": "", "dataType": "", "data": None}
EXPECTED_COUNTS = {"application_pings": 0, "application_pongs": 0, "rest_requests": 0,
                   "ws_application_frames": 2, "ws_sessions": 1, "ws_subscriptions": 1, "subscription_acks": 1}
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
CALIBRATION_FILES = {"CALIBRATION_ATTEMPT_STARTED.json", "REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json",
                     "PROBE_PROTOCOL.json", "OFFICIAL_SCHEMA_AUTHORITY.json", "WS_CONNECT_REQUEST.json",
                     "WS_HANDSHAKE_RESPONSE.json", "WS_SUBSCRIBE_REQUEST.json",
                     "raw/ws_0001.bin", "raw/ws_0001.meta.json", "raw/ws_0001.ack.json",
                     "raw/ws_0002.bin", "raw/ws_0002.meta.json"}
REQUIRED_DOCUMENTS = {"WORK_NEXT.txt", "AUTHORIZATION_ISSUE.json", "COMMON_REPLAY_CONTRACT.json",
    "ECONOMIC_CONTRACT_PRESERVATION.json", "PRESERVED_FILES.json", "OFFICIAL_REST_WS_AUTHORITY.json",
    "PROBE_PROTOCOL.json", "HISTORY_AUDIT.json", "PR1272_1281_METADATA.json", "WORKFLOW_MERGE_AUDIT.json", "EXECUTION_AUTHORITY.json", "PREEXEC_REVIEW.json", "PREEXEC_TESTS.json",
    "PREEXEC_FREEZE.json", "FREEZE_READBACK.json", "BUDGET_TERMINAL.json",
    "REPORT_KO.md", "SCOPE_RESULT.json", "ACTUAL_SESSION_AUDIT.json", "DEFERRED_OWNER_REVIEW.json"} | {
        "calibration/" + name for name in CALIBRATION_FILES}
ZERO_BUDGET_KEYS = {
    "diagnostic_rest_requests", "source_acquisition_attempts", "http_pages_BTC", "http_pages_ETH",
    "control_runs", "DEV_A_screens", "DEV_B_confirmations", "canonical_candidates", "child_FULL_runs",
    "retries", "sweeps", "prospective_ledger_decode", "paid_AI", "live", "orders", "deploy",
    "formal_credit", "kline_frames", "source_refetches", "timestamp_adjustment_ms",
}
FROZEN_ECONOMIC_FIELDS = (
    "common_cost", "common_cost_sha256", "execution", "policies", "partitions", "genes",
    "stage1", "stage2", "stage3", "runtime", "historical_archives", "excluded_terminal_predicates",
    "gene_provenance", "source_authority_hashes", "formal_credit", "production_grade",
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
    allowed_unmanifested = {MANIFEST_PATH, EVIDENCE + "/EXACT_MERGE_VERIFICATION.json"}
    actual_calibration = set()
    for path in _path(root, EVIDENCE).rglob("*"):
        name = path.relative_to(root).as_posix()
        _path(root, name)
        local = name[len(EVIDENCE) + 1:]
        parts = [part.lower() for part in local.split("/")]
        _require(not any(part in {"source", "source_data", "owner", "results", "sources"}
                         or part.startswith(("source_data_", "data_freeze", "owner_input_freeze",
                                             "source_authorization", "strategy_seal", "g5a_handoff"))
                         for part in parts), "SAVED_FORBIDDEN_FOLLOWUP_ARTIFACT:" + name)
        if path.is_file():
            _require(name in saved or name in allowed_unmanifested,
                     "SAVED_UNMANIFESTED_SCOPE_FILE:" + name)
            if local.startswith("calibration/"):
                actual_calibration.add(local[len("calibration/"):])
    _require(actual_calibration == CALIBRATION_FILES, "SAVED_CALIBRATION_EXACT_TWELVE_FILES")


def _classify_stored_ack(raw: bytes) -> dict[str, Any]:
    """Bounded inspection of one stored control response, with no market fields."""
    _require(len(raw) <= 4096, "SAVED_ACK_RAW_LIMIT")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            decoded = stream.read(4097)
    except (OSError, EOFError) as exc:
        raise VerificationError("SAVED_ACK_GZIP") from exc
    _require(len(decoded) <= 4096, "SAVED_ACK_DECOMPRESSED_LIMIT")
    message = _json(decoded)
    _require(_same(message, EXPECTED_ACK), "SAVED_EXACT_SUBSCRIPTION_SUCCESS_ACK_REQUIRED")
    return message



def _inspect_unaccepted_market_frame(raw: bytes) -> dict[str, Any]:
    """Read the actual observed shape without assigning timestamp semantics."""
    _require(len(raw) <= 4096, "SAVED_FRAME2_RAW_LIMIT")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            decoded = stream.read(4097)
    except (OSError, EOFError) as exc:
        raise VerificationError("SAVED_FRAME2_GZIP") from exc
    _require(len(decoded) <= 4096, "SAVED_FRAME2_DECOMPRESSED_LIMIT")
    frame = _json(decoded)
    _require(isinstance(frame, dict) and set(frame) == {"code", "dataType", "s", "data"}
             and type(frame["code"]) is int and frame["code"] == 0
             and frame["dataType"] == CHANNEL and frame["s"] == "BTC-USDT"
             and isinstance(frame["data"], list) and len(frame["data"]) == 1,
             "SAVED_FRAME2_OBSERVED_LIST_ENVELOPE")
    item = frame["data"][0]
    _require(isinstance(item, dict) and set(item) == {"o", "h", "l", "c", "v", "T"}
             and type(item["T"]) is int and item["T"] > 0
             and all(isinstance(item[key], str) for key in ("o", "h", "l", "c", "v")),
             "SAVED_FRAME2_NO_K_t_K_T_WITNESS")
    return frame


def _check_actual_audit(audit, receipt, ack, frame, receipt_sha, ack_sha, frame_sha):
    _require(audit.get("schema") == "trendrider.ack.actual.session.audit.v1"
             and audit.get("scope_key") == SCOPE
             and audit.get("state") == "PASS_AUDIT_OF_TERMINAL_SCHEMA_BLOCK"
             and audit.get("execution_state") == BLOCKED_STATE
             and audit.get("exact_execution_error") == RECORDED_ERRORS
             and audit.get("actual_ack_repair") == "PASS_ACTUAL_SUBSCRIPTION_ACK_OK"
             and audit.get("economic_failure") is False and audit.get("unified_created") is False
             and audit.get("preexecution_remote_commit") == FREEZE_COMMIT,
             "SAVED_AUDIT_ACK_PASS_SCHEMA_BLOCK_NO_ECONOMIC_REJECT")
    hashes = audit.get("evidence_sha256", {})
    _require(hashes.get("receipt") == receipt_sha and hashes.get("preexec_freeze") == PREEXEC_SHA256,
             "SAVED_AUDIT_HASH_BINDING")
    chronology = audit.get("chronology")
    _require(isinstance(chronology, list) and len(chronology) == 2, "SAVED_AUDIT_TWO_FRAMES")
    for ordinal, payload, digest in ((1, ack, ack_sha), (2, frame, frame_sha)):
        item = chronology[ordinal - 1]
        _require(item.get("ordinal") == ordinal and item.get("raw_sha256") == digest
                 and item.get("raw_path") == f"raw/ws_{ordinal:04d}.bin"
                 and _same(item.get("raw_decoded_payload"), payload), "SAVED_AUDIT_CHRONOLOGY_BINDING")
    structure = audit.get("second_frame_structure", {})
    _require(structure.get("data_container") == "array"
             and _same([structure.get("observed_channel_frames"), structure.get("accepted_canonical_klines")], [1, 0])
             and structure.get("canonical_K_present") is False
             and structure.get("canonical_data_s_present") is False
             and structure.get("explicit_lowercase_t_present") is False
             and structure.get("raw_T_semantics") == "UNPROVEN_NO_OPEN_CLOSE_INTERPRETATION"
             and structure.get("raw_T_value") == frame["data"][0]["T"], "SAVED_AUDIT_NO_INVENTED_TIMESTAMP")
    counts = audit.get("counts", {})
    expected = {"ws_sessions": 1, "subscriptions": 1, "application_frames": 2,
                "accepted_ACK": 1, "observed_channel_frames": 1}
    _require(isinstance(counts, dict) and all(_same(counts.get(k), v) for k, v in expected.items())
             and all(k in expected or (type(v) is int and v == 0) for k, v in counts.items()),
             "SAVED_AUDIT_ZERO_DOWNSTREAM")
    witness = audit.get("timestamp_witness", {})
    _require(witness.get("state") == "NOT_ESTABLISHED" and witness.get("witness") is None
             and witness.get("historical_source_authorized") is False
             and witness.get("infer_T_as_open_or_close") is False
             and witness.get("infer_missing_t") is False
             and witness.get("closed_candle_assessed") is False, "SAVED_AUDIT_NO_TIMESTAMP_WITNESS")

def verify(root: str | Path | None = None) -> dict[str, Any]:
    root = Path(root) if root is not None else ROOT
    _require(HASH_RE.fullmatch(SAVED_MANIFEST_SHA256) is not None, "SAVED_MANIFEST_UNSEALED")
    manifest_raw = _path(root, MANIFEST_PATH).read_bytes()
    _require(_sha(manifest_raw) == SAVED_MANIFEST_SHA256, "SAVED_MANIFEST_SHA_MISMATCH")
    manifest = _json(manifest_raw)
    files = _file_map(manifest, "SAVED_MANIFEST")
    _require(manifest.get("schema") == MANIFEST_SCHEMA and manifest.get("scope_key") == SCOPE,
             "SAVED_MANIFEST_SCOPE")
    _require(MANIFEST_PATH not in files and VERIFIER_PATH not in files
             and EVIDENCE + "/EXACT_MERGE_VERIFICATION.json" not in files,
             "SAVED_MANIFEST_CIRCULAR_OR_MERGE_RECEIPT")
    _require({TEST_PATH, WORKFLOW_PATH}.issubset(files), "SAVED_REQUIRED_TEST_OR_WORKFLOW")
    _tree(root, set(files))
    raw_files = {}
    for name, expected in files.items():
        path = _path(root, name)
        _require(path.is_file(), "SAVED_FILE_MISSING:" + name)
        raw = path.read_bytes()
        _require(_sha(raw) == expected, "SAVED_FILE_SHA_MISMATCH:" + name)
        raw_files[name] = raw
    _require({EVIDENCE + "/" + name for name in REQUIRED_DOCUMENTS}.issubset(raw_files),
             "SAVED_REQUIRED_DOCUMENT_MISSING")
    def raw(name):
        return raw_files[EVIDENCE + "/" + name]
    def doc(name):
        value = _json(raw(name))
        _require(isinstance(value, dict), "SAVED_OBJECT_REQUIRED:" + name)
        _seal(value, name, required=False)
        return value

    preserved = _file_map(doc("PRESERVED_FILES.json"), "SAVED_PRESERVED")
    _require(len(preserved) == 149 and PARENT_CONTRACT_PATH in preserved,
             "SAVED_PRESERVED_EXACT_149")
    for name, expected in preserved.items():
        _require(name not in files or files[name] == expected, "SAVED_PRESERVED_MAP_CONFLICT")
        content = _path(root, name).read_bytes()
        _require(_sha(content) == expected, "SAVED_PRESERVED_FILE_SHA_MISMATCH:" + name)
        raw_files[name] = content
    _require(_sha(raw("PREEXEC_FREEZE.json")) == PREEXEC_SHA256,
             "SAVED_PREEXEC_LITERAL_SHA_MISMATCH")
    preexec = doc("PREEXEC_FREEZE.json")
    _seal(preexec, "PREEXEC_FREEZE.json")
    frozen = _file_map(preexec, "SAVED_PREEXEC")
    _require(len(frozen) == 23 and preexec.get("schema") == "trendrider.ack.preexec.freeze.v1"
             and preexec.get("scope_key") == SCOPE
             and preexec.get("state") == "FROZEN_BEFORE_FIRST_CALIBRATION_IO"
             and _same(preexec.get("actual_before_freeze"), {"economic_runs": 0, "rest_requests": 0,
                       "source_attempts": 0, "ws_sessions": 0, "ws_subscriptions": 0}),
             "SAVED_PREEXEC_TWENTYTHREE_FILES_OR_AUTHORITY")
    for name, expected in frozen.items():
        _require(name in raw_files and _sha(raw_files[name]) == expected,
                 "SAVED_PREEXEC_FILE_BINDING:" + name)
    readback = doc("FREEZE_READBACK.json")
    _require(readback.get("verified_commit_sha") == FREEZE_COMMIT
             and readback.get("preexec_raw_sha256") == PREEXEC_SHA256
             and readback.get("readback_verified") is True
             and readback.get("before_first_ws_session") is True
             and readback.get("before_first_rest_request") is True
             and _same(readback.get("economic_runs"), 0), "SAVED_PREEXEC_REMOTE_READBACK")
    contract = doc("COMMON_REPLAY_CONTRACT.json")
    _require(contract.get("schema_version") == "trendrider.ack_repair_contract.v1"
             and contract.get("scope_key") == SCOPE and contract.get("authorization_issue") == 1282,
             "SAVED_CONTRACT_AUTHORITY")
    parent = _json(raw_files[PARENT_CONTRACT_PATH])
    for field in FROZEN_ECONOMIC_FIELDS:
        _require(field in contract and field in parent and _same(contract[field], parent[field]),
                 "SAVED_FROZEN_ECONOMICS_CHANGED:" + field)
    protocol = doc("PROBE_PROTOCOL.json")
    _seal(protocol, "PROBE_PROTOCOL.json")
    _require(raw("PROBE_PROTOCOL.json") == raw("calibration/PROBE_PROTOCOL.json")
             and raw("OFFICIAL_REST_WS_AUTHORITY.json") == raw("calibration/OFFICIAL_SCHEMA_AUTHORITY.json"),
             "SAVED_CALIBRATION_PREREGISTERED_COPY")
    expected_subscription = {"dataType": CHANNEL, "id": SESSION_ID, "reqType": "sub"}
    _require(protocol.get("schema") == "trendrider.rest.ws.timestamp.protocol.v2"
             and protocol.get("scope_key") == SCOPE and protocol.get("session_id") == SESSION_ID
             and protocol.get("authority_sha256") == _sha(raw("OFFICIAL_REST_WS_AUTHORITY.json"))
             and protocol.get("ws_endpoint") == WS_ENDPOINT
             and _same(protocol.get("subscription"), expected_subscription)
             and _same([protocol.get("max_sessions"), protocol.get("max_subscriptions"),
                        protocol.get("max_rest_requests"), protocol.get("retry_count"),
                        protocol.get("economics"), protocol.get("timestamp_adjustment_ms")], [1, 1, 2, 0, 0, 0]),
             "SAVED_FROZEN_CALIBRATION_PROTOCOL")

    attempt = doc("calibration/CALIBRATION_ATTEMPT_STARTED.json")
    receipt = doc("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json")
    connect = doc("calibration/WS_CONNECT_REQUEST.json")
    handshake = doc("calibration/WS_HANDSHAKE_RESPONSE.json")
    subscribe = doc("calibration/WS_SUBSCRIBE_REQUEST.json")
    metadata = doc("calibration/raw/ws_0001.meta.json")
    for label, value in (("attempt", attempt), ("receipt", receipt), ("connect", connect),
                         ("handshake", handshake), ("subscribe", subscribe), ("metadata", metadata)):
        _seal(value, label)
        _require(value.get("session_id") == SESSION_ID, "SAVED_SESSION_ID_BINDING:" + label)
    for value in (attempt, receipt):
        _require(value.get("scope_key") == SCOPE
                 and value.get("protocol_sha256") == _sha(raw("PROBE_PROTOCOL.json"))
                 and value.get("authority_sha256") == _sha(raw("OFFICIAL_REST_WS_AUTHORITY.json"))
                 and _same(value.get("retry_count"), 0), "SAVED_CALIBRATION_INPUT_BINDING")
    _require(_same(attempt.get("attempt_ordinal"), 1), "SAVED_ONE_CONSUMED_ATTEMPT")
    null_fields = ("supported_canonical_lane", "canonical_open_transform", "canonical_close_rule",
                   "canonical_close_delta_ms", "native_ws_close_delta_ms", "close_minus_open_ms", "witness")
    _require(receipt.get("schema") == "trendrider.rest.ws.timestamp.semantic.receipt.v2"
             and receipt.get("state") == BLOCKED_STATE
             and _same(receipt.get("counts"), EXPECTED_COUNTS)
             and _same([receipt.get("actual_ws_sessions"), receipt.get("actual_ws_subscriptions"),
                        receipt.get("actual_rest_requests"), receipt.get("economic_executions"),
                        receipt.get("timestamp_adjustment_ms")], [1, 1, 0, 0, 0])
             and receipt.get("errors") == RECORDED_ERRORS
             and receipt.get("source_acquisition_authorized") is False
             and receipt.get("outcome_independent") is True
             and all(key in receipt and receipt[key] is None for key in null_fields),
             "SAVED_CALIBRATION_MUST_REMAIN_SCHEMA_BLOCKED")
    artifact_map = receipt.get("artifact_sha256")
    expected_artifacts = CALIBRATION_FILES - {"REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json"}
    _require(isinstance(artifact_map, dict) and set(artifact_map) == expected_artifacts,
             "SAVED_CALIBRATION_EXACT_ELEVEN_ARTIFACT_BINDINGS")
    for name, digest in artifact_map.items():
        _require(digest == _sha(raw("calibration/" + name)), "SAVED_CALIBRATION_ARTIFACT_SHA:" + name)
    _require(connect.get("endpoint") == WS_ENDPOINT
             and _same([connect.get("attempt_ordinal"), connect.get("retry_count")], [1, 0])
             and connect.get("reconnect") is False and connect.get("redirects") is False,
             "SAVED_SINGLE_WS_CONNECT_REQUEST")
    _require(_same(handshake.get("status"), 101) and isinstance(handshake.get("headers"), list),
             "SAVED_WS_HANDSHAKE_STATUS")
    header_items = handshake["headers"]
    _require(all(isinstance(item, list) and len(item) == 2 and all(isinstance(x, str) for x in item)
                 for item in header_items), "SAVED_WS_HANDSHAKE_HEADER_LIST")
    _require(any(key.lower() == "upgrade" and value.lower() == "websocket" for key, value in header_items),
             "SAVED_WS_HANDSHAKE_UPGRADE")
    _require(_same(subscribe.get("payload"), expected_subscription), "SAVED_SINGLE_SUBSCRIPTION_PAYLOAD")
    ack_raw = raw("calibration/raw/ws_0001.bin")
    _require(metadata.get("raw_path") == "raw/ws_0001.bin"
             and metadata.get("raw_sha256") == _sha(ack_raw)
             and _same([metadata.get("ordinal"), metadata.get("raw_bytes")], [1, len(ack_raw)])
             and len(ack_raw) == 104 and metadata.get("binary") is True, "SAVED_ACK_RAW_BINDING")
    times = [attempt.get("started_at_ms"), connect.get("requested_at_ms"), handshake.get("received_at_ms"),
             subscribe.get("sent_at_ms"), metadata.get("received_at_ms"), receipt.get("finished_at_ms")]
    _require(all(type(stamp) is int for stamp in times) and times == sorted(times)
             and receipt.get("started_at_ms") == times[0], "SAVED_SESSION_EVENT_TIME_ORDER")
    duration = receipt.get("duration_seconds")
    _require(type(duration) in (int, float) and 0 <= duration <= protocol["session_timeout_seconds"]
             and abs((times[-1] - times[0]) / 1000 - duration) < .002,
             "SAVED_SESSION_DURATION")
    ack = _classify_stored_ack(ack_raw)

    frame_metadata = doc("calibration/raw/ws_0002.meta.json")
    _seal(frame_metadata, "frame2_metadata")
    frame_raw = raw("calibration/raw/ws_0002.bin")
    _require(frame_metadata.get("session_id") == SESSION_ID
             and frame_metadata.get("raw_path") == "raw/ws_0002.bin"
             and frame_metadata.get("raw_sha256") == _sha(frame_raw)
             and _same([frame_metadata.get("ordinal"), frame_metadata.get("raw_bytes")], [2, len(frame_raw)])
             and frame_metadata.get("binary") is True, "SAVED_FRAME2_RAW_BINDING")
    _require(metadata["received_at_ms"] <= frame_metadata.get("received_at_ms", -1) <= receipt["finished_at_ms"],
             "SAVED_ACK_BEFORE_FRAME2_CHRONOLOGY")
    frame = _inspect_unaccepted_market_frame(frame_raw)
    decision = doc("calibration/raw/ws_0001.ack.json")
    expected_decision = {"session_id": SESSION_ID, "ordinal": 1,
        "received_at_ms": metadata["received_at_ms"], "raw_path": metadata["raw_path"],
        "raw_sha256": _sha(ack_raw), "decision": {"kind": "ack",
            "classification": "SUBSCRIPTION_ACK_OK", "subscription_request_id": SESSION_ID,
            "data_form": "NULL", "data_type_form": "EMPTY"}}
    _require(_same({k: v for k, v in decision.items() if k != "receipt_sha256"}, expected_decision),
             "SAVED_ACK_DECISION_BINDING")
    expected_chronology = [{"classification": "SUBSCRIPTION_ACK_OK", "ordinal": 1,
        "raw_path": "raw/ws_0001.bin", "raw_sha256": _sha(ack_raw),
        "decision_path": "raw/ws_0001.ack.json"}]
    _require(_same(receipt.get("ack_chronology"), expected_chronology), "SAVED_ACK_CHRONOLOGY_BINDING")

    _check_actual_audit(doc("ACTUAL_SESSION_AUDIT.json"), receipt, ack, frame,
                        _sha(raw("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json")),
                        _sha(ack_raw), _sha(frame_raw))
    deferred = doc("DEFERRED_OWNER_REVIEW.json")
    _require(deferred.get("schema") == "trendrider.ack.economic.owner.readiness.review.v1"
             and deferred.get("scope_key") == SCOPE and deferred.get("state") == "PASS_PREPARED_NO_ECONOMICS"
             and _same([deferred.get(key) for key in ("actual_economic_runs", "actual_historical_source_calls",
                                                     "actual_ws_sessions", "actual_market_requests")], [0] * 4),
             "SAVED_DEFERRED_OWNER_MUST_REMAIN_CODE_ONLY")

    budget = doc("BUDGET_TERMINAL.json")
    expected_actual = {key: 0 for key in ZERO_BUDGET_KEYS} | {
        "ws_sessions": 1, "ws_subscriptions": 1, "ws_application_frames": 2,
        "subscription_acks": 1, "kline_channel_frames": 1}
    actual = budget.get("actual")
    _require(budget.get("schema") == "trendrider.ack.budget.terminal.v1"
             and budget.get("scope_key") == SCOPE and budget.get("state") == BLOCKED_STATE
             and isinstance(actual, dict)
             and all(key in actual and _same(actual[key], value) for key, value in expected_actual.items())
             and all(key in expected_actual or (type(value) is int and value == 0) for key, value in actual.items()),
             "SAVED_BUDGET_ACK_REPAIRED_ZERO_REST_SOURCE_ECONOMICS")
    expected_metrics = {period: {lane: {"status": "NOT_RUN", "metrics": None}
                        for lane in ("P_COMMON", "B_COMMON", "U1", "U2")} for period in ("DEV_A", "DEV_B")}
    _require(_same(budget.get("economic_metrics"), expected_metrics), "SAVED_ECONOMICS_MUST_BE_NOT_RUN")
    result = doc("SCOPE_RESULT.json")
    for name, value, schema in (("budget", budget, "trendrider.ack.budget.terminal.v1"),
                                ("result", result, "trendrider.ack.scope.result.v1")):
        _require(value.get("schema") == schema and value.get("scope_key") == SCOPE
                 and value.get("state") == BLOCKED_STATE and value.get("failure_class") == FAILURE_CLASS
                 and value.get("economic_reject") is False and value.get("unified_created") is False
                 and _same(value.get("prospective_G5A_handoff"), 0)
                 and value.get("automatic_successor") is False and value.get("closure") == "REPORT_ONLY",
                 "SAVED_FAILURE_CLASS_NO_STRATEGY_REJECT_OR_SUCCESSOR:" + name)
    _require(_same(result.get("actual"), actual) and _same(result.get("economic_metrics"), expected_metrics)
             and result.get("G1_G6") == "NOT_RUN_NO_COMMON_CONTROLS"
             and result.get("U1_U2") == "NOT_CREATED" and result.get("survivors") == "NOT_EVALUATED"
             and result.get("canonical_kline_accepted") is False
             and _same(result.get("formal_credit"), 0), "SAVED_SCOPE_RESULT_NO_FABRICATED_ECONOMICS")
    for symbol in ("BTC-USDT", "ETH-USDT"):
        source = result.get("exact1000", {}).get(symbol, {})
        _require(_same(source, {"status": "NOT_RUN", "data_sha256": None, "normalized_rows": None}),
                 "SAVED_SOURCE_MUST_REMAIN_NOT_RUN")
    _require(_same([budget.get("formal_credit"), budget.get("remaining_executable_budget"),
                    budget.get("attempt_ordinal")], [0, 0, 1])
             and budget.get("production_grade") is False and budget.get("strategy_seal") is None
             and budget.get("normalized_data_sha256") is None, "SAVED_ZERO_CREDIT_NO_SEAL")
    _require(budget.get("semantic_receipt_sha256") == _sha(raw("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json")),
             "SAVED_BUDGET_SEMANTIC_RECEIPT_BINDING")
    _require(raw("REPORT_KO.md").decode("utf-8").splitlines()[0] == "TrendRider Unified v1 = 생성안됨",
             "SAVED_REPORT_EXACT_FIRST_LINE")
    return {"state": "PASS_SAVED_ACK_REPAIR_SCHEMA_FAILURE_VERIFICATION",
            "scope_state": BLOCKED_STATE, "failure_class": FAILURE_CLASS,
            "saved_files": len(files), "preserved_files": len(preserved),
            "preexec_files": len(frozen), "calibration_files": len(CALIBRATION_FILES),
            "ws_sessions": 1, "ws_subscriptions": 1, "ack_frames": 1,
            "kline_channel_frames": 1, "accepted_kline_frames": 0,
            "diagnostic_rest_requests": 0, "source_acquisition_attempts": 0,
            "economic_runs": 0, "formal_credit": 0, "prospective_G5A_handoff": 0,
            "manifest_sha256": SAVED_MANIFEST_SHA256, "ack_raw_sha256": _sha(ack_raw),
            "frame2_raw_sha256": _sha(frame_raw),
            "semantic_receipt_sha256": _sha(raw("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json"))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    print(_canonical(verify(args.root)).decode(), end="")
