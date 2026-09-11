"""Read-only verification of source-repair closure at the timestamp semantic gate.

No collector, market source, policy, or economic runner is imported. The reviewed
literal manifest pin is checked before parsing any saved document. All saved and
preserved dependencies are byte-verified before their contents are interpreted.
The later exact merge receipt is a separate durable record, outside this seal.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCOPE = "TRENDRIDER_UNIFIED_SOURCE_REPAIR_AFTER_PR1275_V1"
EVIDENCE = "research/development_evidence/" + SCOPE
MANIFEST_PATH = EVIDENCE + "/SAVED_FILE_MANIFEST.json"
MANIFEST_FILE_SHA256 = "292e398945ea9208d268e5ab0a6efd91d8fcaab6744724573d567508dab0d8ff"
MANIFEST_SCHEMA = "trendrider.source_repair.saved_file_manifest.v1"
VERIFIER_PATH = "backend/research/rebuild/trendrider_source_repair_saved_verify_v1.py"
PARENT_CONTRACT_PATH = ("research/development_evidence/"
                        "TRENDRIDER_UNIFIED_SHARED_COMMON_REPLAY_AFTER_PR1273_V1/COMMON_REPLAY_CONTRACT.json")
PARENT_RAW_PATH = PARENT_CONTRACT_PATH.rsplit("/", 1)[0] + "/source_data/raw/BTC-USDT_00.bin"
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_DOCUMENTS = (
    "TIMESTAMP_SEMANTIC_RECEIPT.json", "SOURCE_REPAIR_CONTRACT.json",
    "PRESERVED_FILES.json", "REPORT_KO.md", "BUDGET_TERMINAL.json",
    "DOCUMENTARY_EVIDENCE.json", "AUTHORIZATION_ISSUE.json", "WORK_NEXT.txt",
)
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
SOURCE_RULES = {
    "endpoint": "https://open-api.bingx.com/openApi/swap/v3/quote/klines",
    "symbols": ["BTC-USDT", "ETH-USDT"], "interval": "1h",
    "cutoff_ms": 1_788_048_000_000, "first_open_ms": 1_784_448_000_000,
    "bars_per_symbol": 1000, "page_limit": 1000, "max_pages_per_symbol": 3,
}


class VerificationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "SAVED_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _json(raw: bytes) -> Any:
    def reject_constant(value):
        raise VerificationError("SAVED_JSON_NONFINITE:" + value)
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeError) as exc:
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
    _require(isinstance(value, dict) and isinstance(value.get("files"), dict), label + "_FILES")
    files = value["files"]
    _require(bool(files), label + "_EMPTY")
    for name, digest in files.items():
        _require(isinstance(name, str) and isinstance(digest, str)
                 and HASH_RE.fullmatch(digest) is not None, label + "_ENTRY")
    return files


def _scope_tree(root: Path, saved_files: set[str]) -> None:
    allowed_unmanifested = {MANIFEST_PATH, EVIDENCE + "/EXACT_MERGE_VERIFICATION.json"}
    for entry in _path(root, EVIDENCE).rglob("*"):
        relative = entry.relative_to(root).as_posix()
        _path(root, relative)
        parts = relative[len(EVIDENCE) + 1:].split("/")
        lowered = [part.lower() for part in parts]
        _require(not any(part in {"source_data", "source_data_v2", "owner", "results"}
                         or part.startswith(("attempt", "data_freeze")) for part in lowered),
                 "SAVED_FORBIDDEN_EXECUTION_ARTIFACT:" + relative)
        if entry.is_file():
            _require(relative in saved_files or relative in allowed_unmanifested,
                     "SAVED_UNMANIFESTED_SCOPE_FILE:" + relative)


def verify(root: str | Path | None = None) -> dict[str, Any]:
    root = Path(root) if root is not None else ROOT
    _require(HASH_RE.fullmatch(MANIFEST_FILE_SHA256) is not None, "SAVED_MANIFEST_UNSEALED")
    manifest_raw = _path(root, MANIFEST_PATH).read_bytes()
    _require(_sha(manifest_raw) == MANIFEST_FILE_SHA256, "SAVED_MANIFEST_SHA_MISMATCH")
    manifest = _json(manifest_raw)
    files = _file_map(manifest, "SAVED_MANIFEST")
    _require(manifest.get("schema") == MANIFEST_SCHEMA and manifest.get("scope_key") == SCOPE,
             "SAVED_MANIFEST_SCOPE")
    _require(MANIFEST_PATH not in files and VERIFIER_PATH not in files,
             "SAVED_MANIFEST_CIRCULAR_REFERENCE")
    _require(EVIDENCE + "/EXACT_MERGE_VERIFICATION.json" not in files,
             "SAVED_EXACT_MERGE_RECEIPT_MUST_BE_SEPARATE")
    paths = {name: _path(root, name) for name in files}
    _scope_tree(root, set(files))
    raw_files = {}
    for name, path in paths.items():
        value = path.read_bytes()
        _require(_sha(value) == files[name], "SAVED_FILE_SHA_MISMATCH:" + name)
        raw_files[name] = value
    for name in REQUIRED_DOCUMENTS:
        _require(EVIDENCE + "/" + name in raw_files, "SAVED_REQUIRED_FILE_MISSING:" + name)

    def raw(name: str) -> bytes:
        return raw_files[EVIDENCE + "/" + name]

    def document(name: str) -> dict[str, Any]:
        value = _json(raw(name))
        _require(isinstance(value, dict), "SAVED_OBJECT_REQUIRED:" + name)
        return value

    preserved = _file_map(document("PRESERVED_FILES.json"), "PRESERVED")
    _require(PARENT_CONTRACT_PATH in preserved, "SAVED_PARENT_CONTRACT_NOT_PRESERVED")
    preserved_paths = {name: _path(root, name) for name in preserved}
    for name, expected in preserved.items():
        _require(name not in files or files[name] == expected, "SAVED_PRESERVED_MAP_CONFLICT:" + name)
        value = raw_files.get(name)
        if value is None:
            value = preserved_paths[name].read_bytes()
        _require(_sha(value) == expected, "SAVED_PRESERVED_FILE_SHA_MISMATCH:" + name)
        raw_files[name] = value

    semantic = document("TIMESTAMP_SEMANTIC_RECEIPT.json")
    _require(semantic.get("schema") == "trendrider.common.timestamp.semantic.v1"
             and semantic.get("scope_key") == SCOPE, "SAVED_TIMESTAMP_SEMANTIC_SCHEMA")
    unsigned_semantic = {key: value for key, value in semantic.items() if key != "receipt_sha256"}
    _require(semantic.get("receipt_sha256") == _sha(_canonical(unsigned_semantic)),
             "SAVED_TIMESTAMP_SEMANTIC_INTERNAL_SEAL")
    _require(semantic.get("state") == "BLOCKED_TIMESTAMP_SEMANTIC",
             "SAVED_TIMESTAMP_SEMANTIC_STATE")
    _require("canonical_transform" in semantic and semantic["canonical_transform"] is None
             and semantic.get("native_timestamp_meaning") == "UNRESOLVED_OPEN_VS_CLOSE"
             and semantic.get("canonical_bar_timestamp") == "OPEN_TIME_MS"
             and "request_cursor_rule" in semantic and semantic["request_cursor_rule"] is None
             and semantic.get("acquisition_authorized") is False
             and semantic.get("proposed_rules_active") is False
             and type(semantic.get("new_market_api_requests")) is int and semantic["new_market_api_requests"] == 0
             and type(semantic.get("economic_runs")) is int and semantic["economic_runs"] == 0,
             "SAVED_TIMESTAMP_SEMANTIC_MUST_BLOCK_ACQUISITION")
    _require(semantic.get("raw_evidence_path") == PARENT_RAW_PATH
             and PARENT_RAW_PATH in preserved
             and semantic.get("raw_evidence_sha256") == preserved[PARENT_RAW_PATH],
             "SAVED_TIMESTAMP_RAW_BINDING")
    quarantined_raw = raw_files[PARENT_RAW_PATH]
    # The already hashed quarantine is inspected for timestamp/code tokens only.
    # Its OHLC and volume payload is never JSON-decoded, normalized or priced.
    code_tokens = re.findall(rb'(?<!\\)"code"\s*:\s*(-?\d+)\s*(?=[,}])', quarantined_raw)
    time_tokens = re.findall(rb'(?<!\\)"time"\s*:\s*("?)([0-9]+)\1\s*(?=[,}])', quarantined_raw)
    _require(code_tokens == [b"0"] and len(time_tokens) == 1000, "SAVED_RAW_TIMESTAMP_TOKENS")
    observed_times = sorted(int(value) for _, value in time_tokens)
    first, cutoff, hour = SOURCE_RULES["first_open_ms"], SOURCE_RULES["cutoff_ms"], 3_600_000
    _require(observed_times == list(range(first + hour, cutoff + hour, hour)),
             "SAVED_RAW_TIMESTAMP_CONTINUITY")
    expected_continuity = {
        "adjacent_gap_count": 0, "adjacent_interval_ms": hour, "duplicate_timestamp_count": 0,
        "expected_target_first_ms": first, "expected_target_last_ms": cutoff - hour,
        "extra_native_timestamps": [cutoff], "missing_target_timestamps": [first],
        "native_first_ms": first + hour, "native_last_ms": cutoff,
        "ohlc_values_interpreted": False, "raw_max_minus_request_endTime_ms": 1,
        "raw_rows": 1000, "request_endTime_ms": cutoff - 1, "unique_timestamps": 1000,
    }
    _require(semantic.get("observed_raw_continuity") == expected_continuity,
             "SAVED_SEMANTIC_RAW_DIAGNOSTIC")
    documentary = document("DOCUMENTARY_EVIDENCE.json")
    _require(documentary.get("schema") == "trendrider.source_repair.documentary_evidence.v1"
             and documentary.get("scope_key") == SCOPE
             and type(documentary.get("local_preflight_network_calls")) is int
             and documentary["local_preflight_network_calls"] == 0
             and type(documentary.get("new_market_api_requests")) is int
             and documentary["new_market_api_requests"] == 0
             and documentary.get("subsequent_optional_official_document_lookup_performed") is True
             and documentary.get("official_document_network_reads_zero") is False
             and isinstance(documentary.get("authority"), str) and "Issue1276" in documentary["authority"],
             "SAVED_DOCUMENTARY_LOOKUP_ACCOUNTING")
    doc_sources = documentary.get("sources")
    _require(isinstance(doc_sources, list) and bool(doc_sources)
             and all(isinstance(item, dict) and item.get("direct_object_open_semantic_proof") is False
                     and isinstance(item.get("url"), str)
                     and item["url"].startswith("https://github.com/BingX-API/")
                     and isinstance(item.get("source_sha256"), str)
                     and HASH_RE.fullmatch(item["source_sha256"]) is not None for item in doc_sources),
             "SAVED_DOCUMENTARY_PROOF_SCOPE")
    contract = document("SOURCE_REPAIR_CONTRACT.json")
    _require(contract.get("schema_version") == "trendrider.source_repair_contract.v1"
             and contract.get("scope_key") == SCOPE and contract.get("authorization_issue") == 1276
             and contract.get("prior_contract") == {"path": PARENT_CONTRACT_PATH,
                                                      "sha256": preserved[PARENT_CONTRACT_PATH]},
             "SAVED_CONTRACT_AUTHORIZATION_OR_PARENT_BINDING")
    parent_contract = _json(raw_files[PARENT_CONTRACT_PATH])
    _require(isinstance(parent_contract, dict), "SAVED_PARENT_CONTRACT_OBJECT")
    for key in FROZEN_ECONOMIC_FIELDS:
        _require(key in contract and key in parent_contract and contract[key] == parent_contract[key],
                 "SAVED_ECONOMIC_RULE_CHANGED:" + key)
    source = contract.get("source")
    _require(isinstance(source, dict), "SAVED_SOURCE_CONTRACT_OBJECT")
    for key, value in SOURCE_RULES.items():
        _require(source.get(key) == value and type(source.get(key)) is type(value),
                 "SAVED_SOURCE_CONTRACT_MISMATCH:" + key)
    _require(source.get("timestamp_semantic_receipt_sha256") == _sha(raw("TIMESTAMP_SEMANTIC_RECEIPT.json")),
             "SAVED_CONTRACT_SEMANTIC_BINDING")
    budget = document("BUDGET_TERMINAL.json")
    _require(budget.get("schema") == "trendrider.source_repair.budget_terminal.v1"
             and budget.get("scope_key") == SCOPE, "SAVED_BUDGET_SCHEMA")
    _require(budget.get("state") == "BLOCKED_TIMESTAMP_SEMANTIC", "SAVED_BUDGET_STATE")
    actual = budget.get("actual")
    _require(isinstance(actual, dict) and set(actual) == ZERO_BUDGET_KEYS
             and all(type(value) is int and value == 0 for value in actual.values()),
             "SAVED_ACTUAL_BUDGET_NONZERO_OR_INCOMPLETE")
    expected_metrics = {
        period: {lane: {"status": "NOT_RUN", "metrics": None}
                 for lane in ("P_COMMON", "B_COMMON", "U1", "U2")}
        for period in ("DEV_A", "DEV_B")
    }
    _require(budget.get("economic_metrics") == expected_metrics, "SAVED_ECONOMIC_METRICS_MUST_BE_NOT_RUN")
    _require(type(budget.get("formal_credit")) is int and budget["formal_credit"] == 0
             and budget.get("production_grade") is False
             and type(budget.get("prospective_G5A_handoff")) is int and budget["prospective_G5A_handoff"] == 0
             and "strategy_seal" in budget and budget["strategy_seal"] is None
             and "normalized_data_sha256" in budget and budget["normalized_data_sha256"] is None
             and budget.get("completion") == "REPORT_ONLY", "SAVED_SCOPE_CREDIT_OR_CLOSURE")
    return {
        "state": "PASS_SAVED_BLOCKED_TIMESTAMP_SEMANTIC_VERIFICATION",
        "scope_state": "BLOCKED_TIMESTAMP_SEMANTIC", "saved_files": len(files),
        "preserved_files": len(preserved), "source_acquisition_attempts": 0,
        "market_data_http_pages": 0, "economic_runs": 0, "formal_credit": 0,
        "prospective_G5A_handoff": 0, "manifest_sha256": MANIFEST_FILE_SHA256,
        "timestamp_semantic_receipt_sha256": _sha(raw("TIMESTAMP_SEMANTIC_RECEIPT.json")),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    print(json.dumps(verify(args.root), sort_keys=True))
