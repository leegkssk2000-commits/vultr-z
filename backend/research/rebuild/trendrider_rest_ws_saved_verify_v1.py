"""Read-only closure verification of the consumed REST/WS ACK parser failure.

Only stored bytes are read. No collector, strategy, calibration runner, transport,
or economic engine is imported. The literal saved-manifest SHA precedes JSON
parsing; every listed file is hashed before inspection. The single gzip payload
is classified solely as the observed control ACK, never as a candle witness.
This verifier does not repair or replay the frozen failed executor.
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
SCOPE = "TRENDRIDER_UNIFIED_REST_WS_TIMESTAMP_AFTER_PR1279_V1"
EVIDENCE = "research/development_evidence/" + SCOPE
MANIFEST_PATH = EVIDENCE + "/SAVED_FILE_MANIFEST.json"
SAVED_MANIFEST_SHA256 = "d1e35d78a467e7f27a8b39a62cedb1803daece72008bea642bd55905ba1c12ce"
MANIFEST_SCHEMA = "trendrider.rest_ws.saved_file_manifest.v1"
VERIFIER_PATH = "backend/research/rebuild/trendrider_rest_ws_saved_verify_v1.py"
TEST_PATH = "backend/research/rebuild/test_trendrider_rest_ws_saved_verify_v1.py"
WORKFLOW_PATH = ".github/workflows/trendrider-rest-ws-saved-verify-v1.yml"
FROZEN_EXECUTOR_PATH = "backend/research/rebuild/trendrider_rest_ws_timestamp_v1.py"
PREEXEC_SHA256 = "36c688494f96b2a3c86bd6674762ee2159e0c319e9e51beb051d407c90f145fb"
FREEZE_COMMIT = "52973ade72455bdc7211fb9da23f75277c2dbecd"
PARENT_CONTRACT_PATH = ("research/development_evidence/"
                       "TRENDRIDER_UNIFIED_SHARED_COMMON_REPLAY_AFTER_PR1273_V1/COMMON_REPLAY_CONTRACT.json")
SESSION_ID = "trendrider-rest-ws-1280-v1"
CHANNEL = "BTC-USDT@kline_1h"
WS_ENDPOINT = "wss://open-api-swap.bingx.com/swap-market"
BLOCKED_STATE = "BLOCKED_REST_WS_TIMESTAMP_WITNESS"
FAILURE_CLASS = "IMPLEMENTATION_ACK_CLASSIFICATION_FAILURE"
RECORDED_ERRORS = ["WS_RECEIVE:REST_WS_CHANNEL_IDENTITY"]
EXPECTED_ACK = {"id": SESSION_ID, "code": 0, "msg": "", "dataType": "", "data": None}
EXPECTED_COUNTS = {"application_pings": 0, "application_pongs": 0, "rest_requests": 0,
                   "ws_application_frames": 1, "ws_sessions": 1, "ws_subscriptions": 1}
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
CALIBRATION_FILES = {"CALIBRATION_ATTEMPT_STARTED.json", "REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json",
                     "PROBE_PROTOCOL.json", "OFFICIAL_SCHEMA_AUTHORITY.json", "WS_CONNECT_REQUEST.json",
                     "WS_HANDSHAKE_RESPONSE.json", "WS_SUBSCRIBE_REQUEST.json",
                     "raw/ws_0001.bin", "raw/ws_0001.meta.json"}
REQUIRED_DOCUMENTS = {"WORK_NEXT.txt", "AUTHORIZATION_ISSUE.json", "COMMON_REPLAY_CONTRACT.json",
    "ECONOMIC_CONTRACT_PRESERVATION.json", "PRESERVED_FILES.json", "OFFICIAL_REST_WS_AUTHORITY.json",
    "PROBE_PROTOCOL.json", "POST_START_MASTER_HISTORY.json", "PREEXEC_REVIEW.json", "PREEXEC_TESTS.json",
    "EXECUTION_PLAN_KO.md", "PREEXEC_FREEZE.json", "FREEZE_READBACK.json", "BUDGET_TERMINAL.json",
    "REPORT_KO.md", "ACK_POSTMORTEM.json", "ACTUAL_SESSION_AUDIT.json", "DEFERRED_OWNER_REVIEW.json"} | {
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
    _require(actual_calibration == CALIBRATION_FILES, "SAVED_CALIBRATION_EXACT_NINE_FILES")


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
        raw = _path(root, name).read_bytes()
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
    _require(len(preserved) == 108 and PARENT_CONTRACT_PATH in preserved,
             "SAVED_PRESERVED_EXACT_108")
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
    _require(len(frozen) == 15 and preexec.get("schema") == "trendrider.rest_ws.preexec.freeze.v1"
             and preexec.get("scope_key") == SCOPE
             and preexec.get("state") == "FROZEN_BEFORE_FIRST_CALIBRATION_IO"
             and _same(preexec.get("actual_before_freeze"), {"economic_runs": 0, "rest_requests": 0,
                       "source_attempts": 0, "ws_sessions": 0, "ws_subscriptions": 0}),
             "SAVED_PREEXEC_FIFTEEN_FILES_OR_AUTHORITY")
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
    _require(contract.get("schema_version") == "trendrider.rest_ws_contract.v1"
             and contract.get("scope_key") == SCOPE and contract.get("authorization_issue") == 1280,
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
    _require(protocol.get("schema") == "trendrider.rest.ws.timestamp.protocol.v1"
             and protocol.get("scope_key") == SCOPE and protocol.get("session_id") == SESSION_ID
             and protocol.get("authority_sha256") == _sha(raw("OFFICIAL_REST_WS_AUTHORITY.json"))
             and protocol.get("ws_endpoint") == WS_ENDPOINT
             and _same(protocol.get("subscription"), expected_subscription)
             and _same([protocol.get("max_sessions"), protocol.get("max_subscriptions"),
                        protocol.get("max_rest_requests"), protocol.get("retry_count"),
                        protocol.get("economics"), protocol.get("timestamp_adjustment_ms")], [1, 1, 2, 0, 0, 0]),
             "SAVED_FROZEN_CALIBRATION_PROTOCOL")

    attempt = doc("calibration/CALIBRATION_ATTEMPT_STARTED.json")
    receipt = doc("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json")
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
    _require(receipt.get("schema") == "trendrider.rest.ws.timestamp.semantic.receipt.v1"
             and receipt.get("state") == BLOCKED_STATE
             and _same(receipt.get("counts"), EXPECTED_COUNTS)
             and _same([receipt.get("actual_ws_sessions"), receipt.get("actual_ws_subscriptions"),
                        receipt.get("actual_rest_requests"), receipt.get("economic_executions"),
                        receipt.get("timestamp_adjustment_ms")], [1, 1, 0, 0, 0])
             and receipt.get("errors") == RECORDED_ERRORS
             and receipt.get("source_acquisition_authorized") is False
             and receipt.get("outcome_independent") is True
             and all(key in receipt and receipt[key] is None for key in null_fields),
             "SAVED_CALIBRATION_MUST_REMAIN_IMPLEMENTATION_BLOCKED")
    artifact_map = receipt.get("artifact_sha256")
    expected_artifacts = CALIBRATION_FILES - {"REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"}
    _require(isinstance(artifact_map, dict) and set(artifact_map) == expected_artifacts,
             "SAVED_CALIBRATION_EXACT_EIGHT_ARTIFACT_BINDINGS")
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

    postmortem = doc("ACK_POSTMORTEM.json")
    observation = postmortem.get("actual_observation", {})
    action = postmortem.get("current_scope_action", {})
    _require(postmortem.get("schema") == "trendrider.rest.ws.ack.postmortem.v1"
             and postmortem.get("scope_key") == SCOPE
             and postmortem.get("classification") == "LOCAL_SUBSCRIPTION_ACK_CLASSIFICATION_DEFECT"
             and postmortem.get("terminal_state_preserved") == BLOCKED_STATE
             and observation.get("frame_kind") == "SUBSCRIPTION_SUCCESS_ACKNOWLEDGEMENT"
             and _same(observation.get("decoded_application_message"), ack)
             and _same(observation.get("actual_counts"), EXPECTED_COUNTS)
             and _same([observation.get("kline_frames_observed"), observation.get("rest_responses_observed")], [0, 0])
             and observation.get("raw_sha256") == _sha(ack_raw)
             and _same(observation.get("raw_bytes"), len(ack_raw))
             and observation.get("semantic_receipt_sha256") == _sha(raw("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"))
             and observation.get("recorded_error") == RECORDED_ERRORS
             and observation.get("witness") is None,
             "SAVED_POSTMORTEM_MUST_IDENTIFY_LOCAL_ACK_DEFECT")
    _require(postmortem.get("root_cause", {}).get("frozen_module_sha256") == frozen[FROZEN_EXECUTOR_PATH]
             and action.get("attempt_consumed") is True
             and action.get("frozen_code_tests_protocol_modified") is False
             and _same([action.get(key) for key in ("calibration_replay", "new_economic_executions",
                       "new_rest_calls", "new_source_acquisition_calls", "new_ws_sessions", "retry_budget")], [0] * 6),
             "SAVED_NO_POST_OUTCOME_EXECUTOR_REPAIR_OR_REPLAY")

    audit = doc("ACTUAL_SESSION_AUDIT.json")
    audited = audit.get("evidence", {})
    interpretation = audit.get("interpretation", {})
    _require(audit.get("schema") == "trendrider.rest.ws.timestamp.postactual.independent.audit.v1"
             and audit.get("scope_key") == SCOPE
             and audit.get("audit_state") == "PASS_RECORDED_FAILURE_INTEGRITY"
             and audit.get("calibration_state") == BLOCKED_STATE
             and audit.get("failure_classification") == FAILURE_CLASS
             and audited.get("receipt_raw_sha256") == _sha(raw("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"))
             and audited.get("ws_raw_sha256") == _sha(ack_raw)
             and _same(audited.get("decoded_first_frame"), ack)
             and audited.get("runtime_error") == RECORDED_ERRORS
             and interpretation.get("implementation_ack_classifier_failed") is True
             and all(interpretation.get(key) is False for key in ("economic_result_available",
                       "kline_channel_absence_demonstrated", "kline_observed", "official_kline_schema_absence_demonstrated",
                       "ohlc_identity_test_performed", "rest_object_timestamp_meaning_established", "strategy_failure_demonstrated")),
             "SAVED_AUDIT_IMPLEMENTATION_FAILURE_AND_NO_UNOBSERVED_CLAIMS")
    deferred = doc("DEFERRED_OWNER_REVIEW.json")
    _require(deferred.get("schema") == "trendrider.rest.ws.common.owner.independent.review.v1"
             and deferred.get("scope_key") == SCOPE and deferred.get("state") == "PASS_DEFERRED_CODE_ONLY"
             and _same([deferred.get(key) for key in ("economic_executions", "historical_source_calls",
                                                     "live_ws_sessions", "market_rest_requests")], [0] * 4),
             "SAVED_DEFERRED_OWNER_MUST_REMAIN_CODE_ONLY")

    budget = doc("BUDGET_TERMINAL.json")
    expected_actual = {key: 0 for key in ZERO_BUDGET_KEYS} | {
        "ws_sessions": 1, "ws_subscriptions": 1, "ws_application_frames": 1, "ack_frames": 1}
    actual = budget.get("actual")
    _require(budget.get("schema") == "trendrider.rest_ws.budget.terminal.v1"
             and budget.get("scope_key") == SCOPE and budget.get("state") == BLOCKED_STATE
             and isinstance(actual, dict)
             and all(key in actual and _same(actual[key], value) for key, value in expected_actual.items())
             and all(key in expected_actual or (type(value) is int and value == 0) for key, value in actual.items()),
             "SAVED_BUDGET_ONE_WS_ACK_ZERO_REST_SOURCE_ECONOMICS")
    expected_metrics = {period: {lane: {"status": "NOT_RUN", "metrics": None}
                        for lane in ("P_COMMON", "B_COMMON", "U1", "U2")} for period in ("DEV_A", "DEV_B")}
    _require(_same(budget.get("economic_metrics"), expected_metrics), "SAVED_ECONOMICS_MUST_BE_NOT_RUN")
    _require(budget.get("failure_class") == FAILURE_CLASS
             and budget.get("economic_reject") is False
             and budget.get("exchange_kline_schema_failure_proven") is False
             and _same([budget.get("formal_credit"), budget.get("prospective_G5A_handoff"),
                        budget.get("remaining_executable_budget"), budget.get("attempt_ordinal")], [0, 0, 0, 1])
             and budget.get("production_grade") is False and budget.get("completion") == "REPORT_ONLY"
             and budget.get("automatic_successor") is False
             and budget.get("semantic_receipt_sha256") == _sha(raw("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"))
             and all(key in budget and budget[key] is None for key in
                     ("strategy_seal", "normalized_data_sha256", "rest_object_timestamp_semantics")),
             "SAVED_FAILURE_CLASS_CREDIT_OR_CLOSURE")
    return {"state": "PASS_SAVED_REST_WS_IMPLEMENTATION_FAILURE_VERIFICATION",
            "scope_state": BLOCKED_STATE, "failure_class": FAILURE_CLASS,
            "saved_files": len(files), "preserved_files": len(preserved),
            "preexec_files": len(frozen), "calibration_files": len(CALIBRATION_FILES),
            "ws_sessions": 1, "ws_subscriptions": 1, "ack_frames": 1, "kline_frames": 0,
            "diagnostic_rest_requests": 0, "source_acquisition_attempts": 0,
            "economic_runs": 0, "formal_credit": 0, "prospective_G5A_handoff": 0,
            "manifest_sha256": SAVED_MANIFEST_SHA256, "ack_raw_sha256": _sha(ack_raw),
            "semantic_receipt_sha256": _sha(raw("calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    print(_canonical(verify(args.root)).decode(), end="")
