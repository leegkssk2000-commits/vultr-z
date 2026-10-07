"""One-shot, costed cheap screen for Issue 1388 Internet Alpha intake.

This is research-only.  It cannot place orders or promote a strategy.  The
external signal rules are pinned by URL/commit/blob in INTAKE.json.  Historical
delivery is modeled at bar close and every fill is a conservative next-open
taker fill; this explicit adapter is not represented as the donor's live fill.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE_ROOT = Path("/home/z/z/runtime/economic7_campaign_20260915")
INTAKE_PATH = ROOT / "research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/INTAKE.json"
COST_PATH = ROOT / "research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
SOURCE_INVENTORY_SHA256 = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
COST_SHA256 = "cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73"
START_MS = 1_768_262_400_000
END_MS = 1_781_654_400_000
WARMUP_MS = 90 * 86_400_000
CANDIDATE_ID = "E_FT_SWING_HIGH_TO_SKY_15M_V1"
SOURCE_COMMIT = "f3340ce11f5bdf62f598522e64d1f5638eaa13f5"
SOURCE_BLOB = "4289cde249a7065a83401e85cf0cf37a5f6b0627"
GLOBAL_HEAVY_GROUP = "a1-global-heavy-economic-evaluator-v1"
ACTIVATION_TOKEN = "[issue1388-alpha-screen-1-20261007T1420Z-8d31b7a]"
EXECUTION_REF = "refs/heads/research-execution-consumptions/issue1388-cheap-swinghigh-v1"
RESULT_REF = "refs/heads/research-results/issue1388-cheap-swinghigh-v1"
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT", "LINK-USDT")

CENDERAWASIH_ID = "E_MULTIMA_CENDERAWASIH_30M_V1"
RSI_W1_ID = "R_PAPER_RSI_W1_30M_V1"
BBAND_RSI_ID = "E_FT_BBAND_RSI_1H_V1"
BTC_FUNDING_RAW_SHA256 = "e939345a319eb5a9de77fddf7330d7b2e4db20f60b9298f5f3527e99173239ff"
BTC_FUNDING_RECEIPT_SHA256 = "f7e889a0c03727baceadc5e0a3cd050100330cfaa397c4aac2336abbd1c8a15c"
EMA800_ID = "E_FT_EMA800_PRICE_THRESHOLD_1H_V1"
ETH_SESSION_ID = "R_ETH_SESSION_REVERSAL_1H_V1"
ETH_FUNDING_RAW_SHA256 = "cd1b4dea78e2bdc62e985fe0a0c47cd9a301f41836cadc82c136355a056f0aac"
ETH_FUNDING_RECEIPT_SHA256 = "3462c99458ef79bb06b6ca7c1ecac887cee0aa1accdc28da55d198b8004e3357"
BTC_SHOCK_ID = "R_BTC_NEGATIVE_SHOCK_1H_V1"
OTHER_FUNDING_HASHES = {'XRP-USDT': {'raw': 'ef7aedb09e5d1e86cca81ecb04363aec55c493407ba3103cff246fbc841968dd', 'receipt': 'e1fe53fdad89cd423e541837050cd5d3d30c1558332149534fe2fad276a38072'}, 'SOL-USDT': {'raw': '5e1f1e5fd1a2b75dda96e44dd0bfa22b1ce8a3c47de55f6f22bebffbc5097c3e', 'receipt': '2faa33c4ad610580231d629b86704e2530e03cbdd73b1c1564a7a78a07a537b1'}, 'LINK-USDT': {'raw': '893b570d39b3cff5e278331672688b911ae4dba8bddb5e199258b16965c1a3df', 'receipt': '042e3ecc3a27b8049e20a1328f03e80003200778a94ff5d3e288afb42d87ee84'}, 'DOGE-USDT': {'raw': '07a52994272f35a062799623ebe94d26bfe4b6868512212a9114eebb6cb4b32b', 'receipt': '6d3f77019aadef8553768fcfa957102c82e9605d0807e553155394773924b75f'}}
PROFILES: dict[str, dict[str, Any]] = {
    EMA800_ID: {
        "candidate_id": EMA800_ID,
        "source_commit": "1e154a2f6b9aeecbaacb7db5ed6b866603daee2c",
        "source_blob": "f3e7d7dbf6789787d799430be74a05f67c671345",
        "timeframe_min": 60,
        "signal_rules": "SOURCE_EXACT_EMA800_COMPLETED_CLOSE_CROSSED_ABOVE_WITH_VOLUME_GT0",
        "order_adapter": "DENSITY_PREFLIGHT_ONLY",
    },
    CANDIDATE_ID: {
        "candidate_id": CANDIDATE_ID,
        "source_commit": SOURCE_COMMIT,
        "source_blob": SOURCE_BLOB,
        "activation_token": ACTIVATION_TOKEN,
        "execution_ref": EXECUTION_REF,
        "result_ref": RESULT_REF,
        "timeframe_min": 15,
        "signal_rules": "SOURCE_EXACT_SWING_HIGH_TO_SKY_DEFAULT_PARAMETERS",
        "order_adapter": "CONSERVATIVE_NEXT_OPEN_TAKER_STOP_FIRST",
    },
    CENDERAWASIH_ID: {
        "candidate_id": CENDERAWASIH_ID,
        "source_commit": "07265bb3707e1a75526c84a2dc7f910861789b5f",
        "source_blob": "4bdb7576c09e2751a3daf3ac01710a0ab4a6ead0",
        "activation_token": "[issue1388-alpha-screen-2-cenderawasih-v1]",
        "execution_ref": "refs/heads/research-execution-consumptions/issue1388-cheap-cenderawasih-v1",
        "result_ref": "refs/heads/research-results/issue1388-cheap-cenderawasih-v1",
        "timeframe_min": 30,
        "signal_rules": "SOURCE_EXACT_CENDERAWASIH_30M_V1_DEFAULT_PARAMETERS",
        "order_adapter": "CONSERVATIVE_NEXT_OPEN_TAKER_STOP_FIRST_TRAILING_INTRABAR_WORST_CASE",
    },
    RSI_W1_ID: {
        "candidate_id": RSI_W1_ID,
        "source_version": "arXiv:2503.18096v1",
        "source_sha256": "e72cd27ae7e1852876c375f5ff183db64cd814e155d999b468e90298379dc7c5",
        "activation_token": "[issue1388-alpha-screen-3-rsi-w1-30m-v1]",
        "execution_ref": "refs/heads/research-execution-consumptions/issue1388-cheap-rsi-w1-30m-v1",
        "result_ref": "refs/heads/research-results/issue1388-cheap-rsi-w1-30m-v1",
        "timeframe_min": 30,
        "screen_symbols": ("BTC-USDT",),
        "signal_rules": "PUBLISHED_RSI_W1_30M_WILDER5_PRIOR_CLOSED_BAR_GT95_LONG_LT5_SHORT_FLIP",
        "order_adapter": "CONSERVATIVE_NEXT_OPEN_TAKER_FLIP_NO_END_FORCE_CLOSE",
    },
    BTC_SHOCK_ID: {
        "candidate_id": BTC_SHOCK_ID,
        "source_version": "DOI:10.1080/15140326.2022.2151253#PRIMARY_RULE_EVIDENCE_SNAPSHOT",
        "source_sha256": "15877f50925f39c9161f8f90c6b2ca46ff1f807db3a3ef4502b8a26b8a7a2d0d",
        "source_hash_kind": "RULE_EVIDENCE_SNAPSHOT_NOT_PDF",
        "timeframe_min": 60,
        "screen_symbols": ("BTC-USDT",),
        "signal_rules": "SOURCE_EXACT_COMPLETED_1H_LOG_RETURN_STRICT_LT_MINUS_0_015",
        "order_adapter": "INTERNAL_NEXT_OPEN_TAKER_EVENT_CLOSE_PLUS12H_SINGLE_POSITION",
        "activation_token": "[issue1388-alpha-screen-4-btc-shock-1h-v1]",
        "execution_ref": "refs/heads/research-execution-consumptions/issue1388-cheap-btc-shock-1h-v1",
        "result_ref": "refs/heads/research-results/issue1388-cheap-btc-shock-1h-v1",
    },
    BBAND_RSI_ID: {
        "candidate_id": BBAND_RSI_ID,
        "source_commit": "f3340ce11f5bdf62f598522e64d1f5638eaa13f5",
        "source_blob": "addc87268affc2f3b1b00549f1ca8b119e41e655",
        "timeframe_min": 60,
        "signal_rules": "SOURCE_EXACT_BBAND_RSI_1H_RSI14_LT30_CLOSE_LT_TYPICAL_BB20_2SIGMA",
        "order_adapter": "INTERNAL_CONSERVATIVE_CLASS_DEFAULT_GROSS_ROI10_SL25_NEXT_OPEN_STOP_FIRST",
        "activation_token": "[issue1388-alpha-screen-6-bband-rsi-1h-v1]",
        "execution_ref": "refs/heads/research-execution-consumptions/issue1388-cheap-bband-rsi-1h-v1",
        "result_ref": "refs/heads/research-results/issue1388-cheap-bband-rsi-1h-v1",
    },
    ETH_SESSION_ID: {
        "candidate_id": ETH_SESSION_ID,
        "source_version": "DOI:10.3390/jrfm19090692",
        "source_sha256": "dd22882ce5e89f40c5e10ca7a9814180b1b525f5eed4f8a62a2189cb02c139dd",
        "timeframe_min": 60,
        "signal_rules": "SOURCE_EXACT_ETH_12H_SESSIONS_05_17_UTC_NIGHT_LONG_DAY_REVERSE_PRIOR_DAY_RETURN",
        "order_adapter": "INTERNAL_FIXED_UNIT_NEXT_AVAILABLE_OPEN_SESSION_TRANSITION_NO_END_EXIT",
        "screen_symbols": ("ETH-USDT",),
        "activation_token": "[issue1388-alpha-screen-5-eth-session-1h-v1]",
        "execution_ref": "refs/heads/research-execution-consumptions/issue1388-cheap-eth-session-1h-v1",
        "result_ref": "refs/heads/research-results/issue1388-cheap-eth-session-1h-v1",
    },
}


class ScreenError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ScreenError("JSON_OBJECT_REQUIRED:" + path.name)
    return value


def write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _commit(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def _git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False).hexdigest()


def github_create(route: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if route not in ("/git/blobs", "/git/trees", "/git/commits", "/git/refs"):
        raise ScreenError("FIXED_GIT_CREATE_ROUTE_REQUIRED")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise ScreenError("GITHUB_TOKEN_REQUIRED")
    base = "https://api.github.com/repos/leegkssk2000-commits/vultr-z"
    request = Request(base + route, method="POST", data=json.dumps(payload, separators=(",", ":")).encode(), headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urlopen(request, timeout=30) as response:
            value = json.load(response)
    except HTTPError as exc:
        if route == "/git/refs" and exc.code == 422:
            raise ScreenError("PERMANENT_REF_ALREADY_EXISTS_NO_RETRY") from None
        raise ScreenError(f"GITHUB_CREATE_HTTP_{exc.code}") from None
    if not isinstance(value, dict):
        raise ScreenError("GITHUB_OBJECT_REQUIRED")
    return value


def create_record(ref_name: str, filename: str, value: Mapping[str, Any], parent: str) -> str:
    if not _commit(parent):
        raise ScreenError("PERMANENT_PARENT_REQUIRED")
    raw = canonical_bytes(value)
    expected = _git_blob_sha(raw)
    blob = github_create("/git/blobs", {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
    if blob.get("sha") != expected:
        raise ScreenError("PERMANENT_BLOB_MISMATCH")
    tree = github_create("/git/trees", {"tree": [{"path": filename, "mode": "100644", "type": "blob", "sha": expected}]})
    commit = github_create("/git/commits", {"message": "Issue1388 " + filename, "tree": tree["sha"], "parents": [parent]})
    created = github_create("/git/refs", {"ref": ref_name, "sha": commit["sha"]})
    if created.get("ref") != ref_name or created.get("object", {}).get("sha") != commit["sha"]:
        raise ScreenError("PERMANENT_REF_READBACK")
    return str(commit["sha"])


def current_head() -> str:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True)
    if dirty or not _commit(head):
        raise ScreenError("EXECUTING_CHECKOUT_NOT_EXACT_CLEAN_COMMIT")
    return head


def profile_for(candidate_id: str) -> dict[str, Any]:
    try:
        return PROFILES[candidate_id]
    except KeyError:
        raise ScreenError("UNKNOWN_CANDIDATE_ID") from None


def validate_activation(path: Path, head: str) -> dict[str, Any]:
    value = read_json(path)
    profile = profile_for(str(value.get("candidate_id", "")))
    if "activation_token" not in profile:
        raise ScreenError("DENSITY_ONLY_PROFILE_NO_ECONOMIC_ACTIVATION")
    required = {
        "schema": "zel.issue1388.alpha_screen_activation.v1",
        "issue": 1388,
        "candidate_id": profile["candidate_id"],
        "token": profile["activation_token"],
        "reviewed_source_sha": head,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "cost_sha256": COST_SHA256,
        "period_ms": [START_MS, END_MS],
        "timeframe_min": profile["timeframe_min"],
        "global_heavy_group": GLOBAL_HEAVY_GROUP,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    if "source_sha256" in profile:
        required.update(source_version=profile["source_version"], source_sha256=profile["source_sha256"])
    else:
        required.update(source_commit=profile["source_commit"], source_blob=profile["source_blob"])
    for key, expected in required.items():
        if value.get(key) != expected:
            raise ScreenError("ACTIVATION_BINDING:" + key)
    files = value.get("source_files_sha256")
    if not isinstance(files, dict):
        raise ScreenError("ACTIVATION_SOURCE_FILES")
    if profile["candidate_id"] == ETH_SESSION_ID:
        required_files = {"ops/issue1388_alpha_screen_v1.py", "ops/issue1388_eth_session_v1.py",
                          "research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/PRE_SCREEN_THESES_003_PLUS.json",
                          "research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/ETH_FUNDING_RAW.json",
                          "research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/ETH_FUNDING_RECEIPT.json",
                          "research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/ETH_EXECUTION_CONTRACT.json"}
        if not required_files.issubset(files):
            raise ScreenError("ETH_ACTIVATION_SOURCE_CLOSURE_REQUIRED")
    if profile["candidate_id"] == BBAND_RSI_ID:
        base = "research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/"
        required_files = {"ops/issue1388_alpha_screen_v1.py", "ops/issue1388_bband_rsi_v1.py", base + "BBAND_EXECUTION_CONTRACT.json"}
        required_files.update(base + symbol.split("-")[0] + "_FUNDING_" + kind + ".json" for symbol in SYMBOLS for kind in ("RAW", "RECEIPT"))
        if not required_files.issubset(files):
            raise ScreenError("BBAND_ACTIVATION_SOURCE_CLOSURE_REQUIRED")
    for relative, expected in files.items():
        if file_sha256(ROOT / relative) != expected:
            raise ScreenError("ACTIVATION_SOURCE_FILE_DRIFT:" + relative)
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1" or os.environ.get("GITHUB_EVENT_NAME") != "push":
        raise ScreenError("WORKFLOW_FIRST_ATTEMPT_PUSH_REQUIRED")
    if os.environ.get("ISSUE1388_GLOBAL_HEAVY_GROUP") != GLOBAL_HEAVY_GROUP:
        raise ScreenError("GLOBAL_HEAVY_BINDING")
    return value


def load_market(source_root: Path, profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from backend.research.rebuild import scalp7_source_data_v2 as source

    profile = profile or PROFILES[CANDIDATE_ID]
    if profile["candidate_id"] == BTC_SHOCK_ID and file_sha256(INTAKE_PATH.parent / "BTC_SHOCK_SOURCE_RECHECK.json") != profile["source_sha256"]:
        raise ScreenError("SOURCE_RULE_EVIDENCE_SNAPSHOT_DRIFT")
    if profile["candidate_id"] == EMA800_ID:
        if (file_sha256(INTAKE_PATH.parent / "EMA800_SOURCE.py") != "4bdf1cc26bb32bcae7b745c8d23482f39b73bcb0b1192a1b899f3362b0847df2"
                or file_sha256(INTAKE_PATH.parent / "EMA800_LICENSE.txt") != "876b0759d6085f07dac04471968d31c3bab4f8d278845d2c0e4c3dc581e790c6"):
            raise ScreenError("EMA800_LICENSED_SOURCE_DRIFT")
    if file_sha256(COST_PATH) != COST_SHA256:
        raise ScreenError("FROZEN_COST_FILE_DRIFT")
    timeframe_min = int(profile["timeframe_min"])
    source_timeframe_min = 30 if timeframe_min == 60 else timeframe_min
    frames = source.load_candles(source_root, source_timeframe_min, cache_dir=None)
    if timeframe_min == 60:
        frames = {symbol: aggregate_30m_to_1h(frame) for symbol, frame in frames.items()}
    if set(frames) != set(SYMBOLS):
        raise ScreenError("SOURCE_SYMBOL_COHORT_DRIFT")
    selected: dict[str, pd.DataFrame] = {}
    for symbol, frame in frames.items():
        if frame.attrs.get("source_inventory_sha256") != SOURCE_INVENTORY_SHA256:
            raise ScreenError("SOURCE_INVENTORY_ATTRIBUTE_DRIFT")
        part = frame[(frame.open_ts_ms >= START_MS - WARMUP_MS) & (frame.open_ts_ms < END_MS)].copy().reset_index(drop=True)
        if part.empty or int(part.iloc[0].open_ts_ms) > START_MS - WARMUP_MS:
            raise ScreenError("SOURCE_WARMUP_NOT_COVERED")
        if int(part.iloc[-1].close_ts_ms) != END_MS:
            raise ScreenError("SOURCE_END_NOT_COVERED")
        part.attrs = dict(frame.attrs)
        selected[symbol] = part
    costs = read_json(COST_PATH)["costs_bps"]
    if set(costs) != set(SYMBOLS) or any(float(x) <= 0 for x in costs.values()):
        raise ScreenError("COST_PROFILE")
    market = {"frames": selected, "costs": costs}
    if profile["candidate_id"] == BTC_SHOCK_ID:
        market["btc_funding"] = load_btc_funding()
    if profile["candidate_id"] == ETH_SESSION_ID:
        market["eth_funding"] = load_eth_funding()
    if profile["candidate_id"] == BBAND_RSI_ID:
        market["six_funding"] = load_six_funding()
    return market


def validate_btc_funding(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value.get("code") != 0 or not isinstance(value.get("data"), list):
        raise ScreenError("BTC_FUNDING_RESPONSE_SCHEMA")
    rows = sorted(value["data"], key=lambda row: row.get("fundingTime", 0))
    expected_times = list(range(START_MS, END_MS, 8 * 3600000))
    if [row.get("fundingTime") for row in rows] != expected_times:
        raise ScreenError("BTC_FUNDING_FIXED_WINDOW_COVERAGE")
    for row in rows:
        if row.get("symbol") != "BTC-USDT":
            raise ScreenError("BTC_FUNDING_SYMBOL")
        try:
            rate, mark = float(row["fundingRate"]), float(row["markPrice"])
        except (KeyError, TypeError, ValueError):
            raise ScreenError("BTC_FUNDING_RATE_MARK_REQUIRED") from None
        if not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0:
            raise ScreenError("BTC_FUNDING_RATE_MARK_INVALID")
    return rows


def load_btc_funding() -> list[dict[str, Any]]:
    raw_path = INTAKE_PATH.parent / "BTC_FUNDING_RAW.json"
    receipt_path = INTAKE_PATH.parent / "BTC_FUNDING_RECEIPT.json"
    if file_sha256(raw_path) != BTC_FUNDING_RAW_SHA256 or file_sha256(receipt_path) != BTC_FUNDING_RECEIPT_SHA256:
        raise ScreenError("BTC_FUNDING_INPUT_HASH_DRIFT")
    receipt = read_json(receipt_path)
    if receipt.get("raw_sha256") != BTC_FUNDING_RAW_SHA256 or receipt.get("period_ms") != [START_MS, END_MS]:
        raise ScreenError("BTC_FUNDING_RECEIPT_BINDING")
    return validate_btc_funding(read_json(raw_path))


def validate_eth_funding(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value.get("code") != 0 or not isinstance(value.get("data"), list):
        raise ScreenError("ETH_FUNDING_RESPONSE_SCHEMA")
    rows = value["data"]
    if any(not isinstance(row, dict) for row in rows):
        raise ScreenError("ETH_FUNDING_ROW_SCHEMA")
    rows = sorted(rows, key=lambda row: row.get("fundingTime", 0))
    if [row.get("fundingTime") for row in rows] != list(range(START_MS, END_MS, 8 * 3600000)):
        raise ScreenError("ETH_FUNDING_FIXED_WINDOW_COVERAGE")
    for row in rows:
        if row.get("symbol") != "ETH-USDT" or type(row.get("fundingTime")) is not int:
            raise ScreenError("ETH_FUNDING_SYMBOL_OR_CLOCK")
        try:
            rate, mark = float(row["fundingRate"]), float(row["markPrice"])
        except (KeyError, TypeError, ValueError):
            raise ScreenError("ETH_FUNDING_RATE_MARK_REQUIRED") from None
        if isinstance(row["fundingRate"], bool) or isinstance(row["markPrice"], bool) or not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0:
            raise ScreenError("ETH_FUNDING_RATE_MARK_INVALID")
    return rows


def load_eth_funding() -> list[dict[str, Any]]:
    raw = INTAKE_PATH.parent / "ETH_FUNDING_RAW.json"
    receipt = INTAKE_PATH.parent / "ETH_FUNDING_RECEIPT.json"
    if file_sha256(raw) != ETH_FUNDING_RAW_SHA256 or file_sha256(receipt) != ETH_FUNDING_RECEIPT_SHA256:
        raise ScreenError("ETH_FUNDING_INPUT_HASH_DRIFT")
    proof = read_json(receipt)
    if (proof.get("symbol") != "ETH-USDT" or proof.get("raw_sha256") != ETH_FUNDING_RAW_SHA256
            or proof.get("period_ms") != [START_MS, END_MS] or proof.get("rows") != 465
            or proof.get("historical_receipt_times") is not False
            or proof.get("account_actual_debit_certified") is not False):
        raise ScreenError("ETH_FUNDING_RECEIPT_BINDING")
    return validate_eth_funding(read_json(raw))


def validate_symbol_funding(value: Mapping[str, Any], symbol: str) -> list[dict[str, Any]]:
    if value.get("code") != 0 or not isinstance(value.get("data"), list) or any(not isinstance(r, dict) for r in value["data"]):
        raise ScreenError("FUNDING_RESPONSE_SCHEMA:" + symbol)
    rows = value["data"]
    if any(type(r.get("fundingTime")) is not int for r in rows):
        raise ScreenError("FUNDING_CLOCK:" + symbol)
    rows = sorted(rows, key=lambda r: r["fundingTime"])
    if [r["fundingTime"] for r in rows] != list(range(START_MS, END_MS, 8 * 3600000)):
        raise ScreenError("FUNDING_FIXED_WINDOW_COVERAGE:" + symbol)
    for row in rows:
        if row.get("symbol") != symbol:
            raise ScreenError("FUNDING_SYMBOL:" + symbol)
        try:
            rate, mark = float(row["fundingRate"]), float(row["markPrice"])
        except (KeyError, TypeError, ValueError):
            raise ScreenError("FUNDING_RATE_MARK_REQUIRED:" + symbol) from None
        if (isinstance(row["fundingRate"], bool) or isinstance(row["markPrice"], bool)
                or not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0):
            raise ScreenError("FUNDING_RATE_MARK_INVALID:" + symbol)
    return rows


def six_funding_hashes() -> dict[str, dict[str, str]]:
    return {"BTC-USDT": {"raw": BTC_FUNDING_RAW_SHA256, "receipt": BTC_FUNDING_RECEIPT_SHA256},
            "ETH-USDT": {"raw": ETH_FUNDING_RAW_SHA256, "receipt": ETH_FUNDING_RECEIPT_SHA256},
            **{symbol: dict(hashes) for symbol, hashes in OTHER_FUNDING_HASHES.items()}}


def load_six_funding() -> dict[str, list[dict[str, Any]]]:
    output = {"BTC-USDT": load_btc_funding(), "ETH-USDT": load_eth_funding()}
    for symbol, hashes in OTHER_FUNDING_HASHES.items():
        prefix = symbol.split("-")[0]
        raw, receipt_path = (INTAKE_PATH.parent / (prefix + "_FUNDING_" + kind + ".json") for kind in ("RAW", "RECEIPT"))
        if file_sha256(raw) != hashes["raw"] or file_sha256(receipt_path) != hashes["receipt"]:
            raise ScreenError("FUNDING_INPUT_HASH_DRIFT:" + symbol)
        receipt = read_json(receipt_path)
        if (receipt.get("symbol") != symbol or receipt.get("raw_sha256") != hashes["raw"]
                or receipt.get("period_ms") != [START_MS, END_MS] or receipt.get("rows") != 465
                or receipt.get("historical_receipt_times") is not False
                or receipt.get("account_actual_debit_certified") is not False):
            raise ScreenError("FUNDING_RECEIPT_BINDING:" + symbol)
        output[symbol] = validate_symbol_funding(read_json(raw), symbol)
    return output


def funding_for_btc_trade(trade: Mapping[str, Any], rows: list[dict[str, Any]]) -> tuple[float, int]:
    entry, exit_ = int(trade["entry_ts_ms"]), int(trade["exit_ts_ms"])
    entry_price = float(trade["entry_price"])
    funding = 0.0
    count = 0
    for row in rows:
        timestamp = int(row["fundingTime"])
        if entry <= timestamp <= exit_:
            rate = float(row["fundingRate"])
            # Receipt timing at exact funding boundary is unavailable: take the adverse bound.
            if entry < timestamp < exit_ or rate > 0:
                funding += rate * float(row["markPrice"]) / entry_price * 10000
                count += 1
    return funding, count


def aggregate_30m_to_1h(frame: pd.DataFrame) -> pd.DataFrame:
    """Build only complete causal UTC-hour bars without bridging source gaps."""
    required = {
        "open_ts_ms", "close_ts_ms", "available_ts_ms", "segment_id",
        "open", "high", "low", "close", "volume",
    }
    if not required.issubset(frame.columns) or frame.empty:
        raise ScreenError("INCOMPLETE_30M_SOURCE_FOR_1H")
    rows: list[dict[str, Any]] = []
    incomplete: list[int] = []
    hour_ms = 3_600_000
    half_hour_ms = 1_800_000
    candidate = frame.copy()
    candidate["_hour"] = (candidate.open_ts_ms.astype("int64") // hour_ms) * hour_ms
    for hour, part in candidate.groupby("_hour", sort=True):
        part = part.sort_values("open_ts_ms")
        expected = [int(hour), int(hour) + half_hour_ms]
        complete = (
            len(part) == 2
            and part.open_ts_ms.astype("int64").tolist() == expected
            and part.close_ts_ms.astype("int64").tolist() == [expected[1], int(hour) + hour_ms]
            and part.segment_id.nunique(dropna=False) == 1
        )
        if not complete:
            incomplete.append(int(hour))
            continue
        rows.append({
            "open_ts_ms": int(hour),
            "close_ts_ms": int(hour) + hour_ms,
            "available_ts_ms": int(part.available_ts_ms.max()),
            "source_segment_id": part.iloc[0].segment_id,
            "open": float(part.iloc[0].open),
            "high": float(part.high.max()),
            "low": float(part.low.min()),
            "close": float(part.iloc[-1].close),
            "volume": float(part.volume.sum()),
        })
    if not rows:
        raise ScreenError("NO_COMPLETE_1H_BUCKETS")
    output = pd.DataFrame(rows)
    boundary = (
        output.source_segment_id.ne(output.source_segment_id.shift())
        | output.open_ts_ms.diff().ne(hour_ms)
    )
    output["segment_id"] = boundary.cumsum().map(lambda value: f"DERIVED_1H_{int(value)}")
    output = output.drop(columns=["source_segment_id"])
    output.attrs = {
        **dict(frame.attrs),
        "derived_from_timeframe_min": 30,
        "timeframe_min": 60,
        "incomplete_buckets": incomplete,
    }
    return output


def source_receipt(market: Mapping[str, Any], profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or PROFILES[CANDIDATE_ID]
    rows = {}
    for symbol, frame in market["frames"].items():
        rows[symbol] = {
            "rows": len(frame),
            "first_open_ts_ms": int(frame.iloc[0].open_ts_ms),
            "last_close_ts_ms": int(frame.iloc[-1].close_ts_ms),
            "minute_gap_count": len(frame.attrs.get("minute_gaps", [])),
            "incomplete_bucket_count": len(frame.attrs.get("incomplete_buckets", [])),
        }
    value = {
        "schema": "zel.issue1388.source_receipt.v1",
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "cost_sha256": COST_SHA256,
        "period_ms": [START_MS, END_MS],
        "timeframe_min": profile["timeframe_min"],
        "frames": rows,
        "costs_bps": {k: float(v) for k, v in market["costs"].items()},
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "order_adapter": profile["order_adapter"],
        "donor_default_order_fill_claimed": False,
        "order_authority": "BLOCKED",
    }
    return {**value, "receipt_sha256": digest(value)}


def source_binding(profile: Mapping[str, Any]) -> dict[str, str]:
    if "source_sha256" in profile:
        return {"source_version": str(profile["source_version"]), "source_sha256": str(profile["source_sha256"])}
    return {"source_commit": str(profile["source_commit"]), "source_blob": str(profile["source_blob"])}


def _rsi(close: pd.Series, period: int) -> pd.Series:
    values = close.to_numpy(dtype=float)
    output = np.full(len(values), np.nan, dtype=float)
    if len(values) <= period:
        return pd.Series(output, index=close.index)
    delta = np.diff(values)
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    average_gain = float(gain[:period].mean())
    average_loss = float(loss[:period].mean())

    def value() -> float:
        denominator = average_gain + average_loss
        return 100.0 * average_gain / denominator if denominator else 0.0

    output[period] = value()
    for i in range(period + 1, len(values)):
        average_gain = (average_gain * (period - 1) + gain[i - 1]) / period
        average_loss = (average_loss * (period - 1) + loss[i - 1]) / period
        output[i] = value()
    return pd.Series(output, index=close.index)


def _cci(frame: pd.DataFrame, period: int) -> pd.Series:
    typical = (frame.high + frame.low + frame.close) / 3
    mean = typical.rolling(period, min_periods=period).mean()
    deviation = typical.rolling(period, min_periods=period).apply(lambda x: float(np.mean(np.abs(x - np.mean(x)))), raw=True)
    return (typical - mean) / (0.015 * deviation.replace(0, np.nan))


def signals(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if "segment_id" not in frame:
        raise ScreenError("SEGMENT_ID_REQUIRED")
    entry = pd.Series(False, index=frame.index)
    exit_ = pd.Series(False, index=frame.index)
    interval = 15 * 60_000
    for _, part in frame.groupby("segment_id", sort=False, dropna=False):
        if part["segment_id"].isna().any():
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if len(part) > 1 and not part["open_ts_ms"].diff().iloc[1:].eq(interval).all():
            raise ScreenError("INTRA_SEGMENT_TIME_GAP")
        entry.loc[part.index] = ((_cci(part, 72) < -175) & (_rsi(part.close, 36) < 90)).fillna(False)
        exit_.loc[part.index] = ((_cci(part, 66) > -106) & (_rsi(part.close, 45) > 88)).fillna(False)
    return entry, exit_


def rsi_w1_signals(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Published W1 rule evaluated only after each completed 30-minute bar."""
    if "segment_id" not in frame:
        raise ScreenError("SEGMENT_ID_REQUIRED")
    long_signal = pd.Series(False, index=frame.index)
    short_signal = pd.Series(False, index=frame.index)
    interval = 30 * 60_000
    for _, part in frame.groupby("segment_id", sort=False, dropna=False):
        if part["segment_id"].isna().any():
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if len(part) > 1 and not part["open_ts_ms"].diff().iloc[1:].eq(interval).all():
            raise ScreenError("INTRA_SEGMENT_TIME_GAP")
        rsi = _rsi(part.close, 5)
        long_signal.loc[part.index] = rsi.gt(95).fillna(False)
        short_signal.loc[part.index] = rsi.lt(5).fillna(False)
    return long_signal, short_signal


def bband_rsi_entry_signals(frame: pd.DataFrame) -> pd.Series:
    """Pinned Freqtrade BbandRsi entry rule; no exit or PnL is evaluated here."""
    if "segment_id" not in frame:
        raise ScreenError("SEGMENT_ID_REQUIRED")
    entry = pd.Series(False, index=frame.index)
    interval = 60 * 60_000
    for _, part in frame.groupby("segment_id", sort=False, dropna=False):
        if part["segment_id"].isna().any():
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if len(part) > 1 and not part["open_ts_ms"].diff().iloc[1:].eq(interval).all():
            raise ScreenError("INTRA_SEGMENT_TIME_GAP")
        typical = (part.high + part.low + part.close) / 3
        middle = typical.rolling(20, min_periods=1).mean()
        std = typical.rolling(20, min_periods=1).std(ddof=1)
        lower = middle - 2 * std
        entry.loc[part.index] = ((_rsi(part.close, 14) < 30) & (part.close < lower)).fillna(False)
    return entry


def _episode_starts(signal: pd.Series, frame: pd.DataFrame) -> pd.Series:
    starts = pd.Series(False, index=signal.index)
    for _, part in frame.groupby("segment_id", sort=False, dropna=False):
        local = signal.loc[part.index].fillna(False)
        starts.loc[part.index] = local & ~local.shift(1, fill_value=False)
    return starts


def eth_session_decisions(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Past-only ETH session decisions and actual position transitions.

    The 05:00 UTC day decision uses only the preceding completed 05:00-17:00
    return.  The 17:00 UTC night decision is long.  Gaps reset all state.
    """
    if "segment_id" not in frame:
        raise ScreenError("SEGMENT_ID_REQUIRED")
    available = pd.Series(False, index=frame.index)
    transitions = pd.Series(False, index=frame.index)
    hour_ms = 3_600_000
    for _, part in frame.groupby("segment_id", sort=False, dropna=False):
        if part["segment_id"].isna().any():
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if len(part) > 1 and not part["open_ts_ms"].diff().iloc[1:].eq(hour_ms).all():
            raise ScreenError("INTRA_SEGMENT_TIME_GAP")
        prior_day_return: float | None = None
        day_boundary_close: float | None = None
        prior_close: float | None = None
        current_side = 0
        for idx, row in part.iterrows():
            hour = pd.Timestamp(int(row.open_ts_ms), unit="ms", tz="UTC").hour
            desired: int | None = None
            if hour == 5:
                day_boundary_close = prior_close
                if prior_day_return is not None:
                    desired = -1 if prior_day_return > 0 else (1 if prior_day_return < 0 else 0)
                    available.loc[idx] = True
            elif hour == 17:
                desired = 1
                available.loc[idx] = True
            if desired is not None and desired != current_side:
                transitions.loc[idx] = True
                current_side = desired
            if hour == 17:
                prior_day_return = None if day_boundary_close is None or prior_close is None else prior_close / day_boundary_close - 1.0
                day_boundary_close = None
            prior_close = float(row.close)
    return available, transitions


def btc_shock_signals(frame: pd.DataFrame) -> pd.Series:
    """Only consecutive completed hourly closes, never across a source gap."""
    prior = frame.close.shift()
    contiguous = (frame.segment_id.eq(frame.segment_id.shift())
                  & frame.open_ts_ms.eq(frame.close_ts_ms.shift()))
    finite = np.isfinite(frame.close) & np.isfinite(prior) & frame.close.gt(0) & prior.gt(0)
    log_return = np.log(frame.close.where(finite) / prior.where(finite))
    return (contiguous & log_return.lt(-0.015)).fillna(False)


def ema800_entry_signals(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Licensed exact entry census only; no exit, return or trailing simulation."""
    if not {"close", "volume", "segment_id", "open_ts_ms"}.issubset(frame.columns):
        raise ScreenError("EMA800_CENSUS_FIELDS_REQUIRED")
    raw = pd.Series(False, index=frame.index)
    ready = pd.Series(False, index=frame.index)
    for _, part in frame.groupby("segment_id", sort=False, dropna=False):
        if part.segment_id.isna().any() or (len(part) > 1 and not part.open_ts_ms.diff().iloc[1:].eq(3600000).all()):
            raise ScreenError("EMA800_CENSUS_SEGMENT_GAP")
        close = part["close"].astype(float)
        ema = _ema_talib(close, 800)
        ready.loc[part.index] = ema.notna()
        raw.loc[part.index] = ((close > ema) & (close.shift(1) <= ema.shift(1)) & (part.volume > 0)).fillna(False)
    return raw, ready


def density_census(market: Mapping[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    """No-PnL preflight: signal/episode counts only; exits and future outcomes are forbidden."""
    days = (END_MS - START_MS) / 86_400_000
    candidates: dict[str, Any] = {}
    for candidate_id in candidate_ids:
        profile = profile_for(candidate_id)
        by_symbol: dict[str, Any] = {}
        raw_total = episode_total = 0
        warmup_ready_by_symbol: dict[str, int] = {}
        for symbol in SYMBOLS:
            frame = market["frames"][symbol]
            in_window = (frame.open_ts_ms >= START_MS) & (frame.open_ts_ms < END_MS)
            if candidate_id == RSI_W1_ID:
                long_signal, short_signal = rsi_w1_signals(frame)
                raw = long_signal | short_signal
                state = pd.Series(0, index=frame.index, dtype=int)
                state.loc[long_signal] = 1
                state.loc[short_signal] = -1
                episodes = pd.Series(False, index=frame.index)
                prior = 0
                prior_segment: Any = None
                for idx, row in frame.iterrows():
                    segment = row["segment_id"]
                    if segment != prior_segment:
                        prior = 0
                        prior_segment = segment
                    current = int(state.loc[idx])
                    if current and current != prior:
                        episodes.loc[idx] = True
                        prior = current
            elif candidate_id == BTC_SHOCK_ID:
                raw = btc_shock_signals(frame)
                in_window &= frame.close_ts_ms.lt(END_MS) & frame.available_ts_ms.lt(END_MS)
                # Each threshold exceedance is a source event, including consecutive shocks.
                episodes = raw.copy()
            elif candidate_id == BBAND_RSI_ID:
                raw = bband_rsi_entry_signals(frame)
                episodes = _episode_starts(raw, frame)
            elif candidate_id == ETH_SESSION_ID:
                raw, episodes = eth_session_decisions(frame)
            elif candidate_id == EMA800_ID:
                raw, ready = ema800_entry_signals(frame)
                in_window &= frame.close_ts_ms.lt(END_MS) & frame.available_ts_ms.lt(END_MS)
                episodes = raw.copy()
                warmup_ready_by_symbol[symbol] = int((ready & in_window).sum())
            else:
                raise ScreenError("DENSITY_CANDIDATE_UNSUPPORTED:" + candidate_id)
            raw_count = int((raw & in_window).sum())
            episode_count = int((episodes & in_window).sum())
            raw_total += raw_count
            episode_total += episode_count
            by_symbol[symbol] = {
                "raw_signal_bars": raw_count,
                "source_exact_episodes": episode_count,
                "episodes_per_day": episode_count / days,
            }
        candidate = {
            "candidate_id": candidate_id,
            **source_binding(profile),
            "timeframe_min": profile["timeframe_min"],
            "signal_rules": profile["signal_rules"],
            "raw_signal_bars": raw_total,
            "source_exact_episodes": episode_total,
            "episodes_per_day": episode_total / days,
            "symbols_with_episodes": sum(1 for row in by_symbol.values() if row["source_exact_episodes"] > 0),
            "by_symbol": by_symbol,
        }
        if candidate_id in (RSI_W1_ID, BTC_SHOCK_ID):
            candidate["source_native_btc"] = by_symbol["BTC-USDT"]
            candidate["six_symbol_application"] = "DENSITY_COMPATIBILITY_ONLY; ECONOMIC_SCREEN_MUST_REMAIN_SOURCE_NATIVE_BTC"
            if candidate_id == BTC_SHOCK_ID:
                candidate["source_hash_kind"] = "RULE_EVIDENCE_SNAPSHOT_NOT_PDF"
        elif candidate_id == ETH_SESSION_ID:
            candidate["source_native_eth"] = by_symbol["ETH-USDT"]
            candidate["source_exact_episodes"] = by_symbol["ETH-USDT"]["source_exact_episodes"]
            candidate["episodes_per_day"] = by_symbol["ETH-USDT"]["episodes_per_day"]
            candidate["six_symbol_compatibility_transition_total"] = episode_total
            candidate["six_symbol_application"] = "DENSITY_COMPATIBILITY_ONLY; ECONOMIC_SCREEN_MUST_REMAIN_SOURCE_NATIVE_ETH"
        if candidate_id == EMA800_ID:
            candidate["source_native_overlap"] = {symbol: by_symbol[symbol] for symbol in ("BTC-USDT", "ETH-USDT", "XRP-USDT")}
            candidate["six_symbol_application"] = "NATIVE_OVERLAP_BTC_ETH_XRP; SOL_DOGE_LINK_COMPATIBILITY_ONLY; NO_ECONOMIC_ADAPTER_READY"
            candidate["warmup_ready_bars_by_symbol"] = warmup_ready_by_symbol
        candidates[candidate_id] = candidate
    value = {
        "schema": "zel.issue1388.signal_density_preflight.v1",
        "issue": 1388,
        "classification": "NO_PNL_NO_EXIT_NO_FUTURE_OUTCOME_SOURCE_EXACT_SIGNAL_CENSUS",
        "period_ms": [START_MS, END_MS],
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "candidates": candidates,
        "economic_screen_consumed": 0,
        "order_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    return {**value, "result_sha256": digest(value)}


def _tv_wma(series: pd.Series, length: int) -> pd.Series:
    """Exact loop used by the pinned donor, including its one-bar shift."""
    norm = 0
    total: pd.Series | int = 0
    for i in range(1, length - 1):
        weight = (length - i) * length
        norm += weight
        total = total + series.shift(i) * weight
    return total / norm if norm else pd.Series(0.0, index=series.index)


def _tv_hma(close: pd.Series, length: int) -> pd.Series:
    half = math.floor(length / 2)
    root = math.floor(math.sqrt(length))
    return _tv_wma(2 * _tv_wma(close, half) - _tv_wma(close, length), root)


def _ema_talib(series: pd.Series, period: int) -> pd.Series:
    """TA-Lib-compatible EMA: SMA seed, then recursive alpha update."""
    values = series.to_numpy(dtype=float)
    output = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return pd.Series(output, index=series.index)
    seed = float(np.mean(values[:period]))
    output[period - 1] = seed
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        output[i] = alpha * values[i] + (1 - alpha) * output[i - 1]
    return pd.Series(output, index=series.index)


def _completed_informative(frame: pd.DataFrame, interval_ms: int) -> pd.DataFrame:
    expected = interval_ms // (30 * 60_000)
    records: list[dict[str, Any]] = []
    for segment, part in frame.groupby("segment_id", sort=False, dropna=False):
        if pd.isna(segment):
            raise ScreenError("SEGMENT_ID_REQUIRED")
        work = part.assign(_bucket=(part.open_ts_ms // interval_ms) * interval_ms)
        for bucket, group in work.groupby("_bucket", sort=True):
            if (
                len(group) == expected
                and int(group.iloc[0].open_ts_ms) == int(bucket)
                and int(group.iloc[-1].close_ts_ms) == int(bucket + interval_ms)
            ):
                records.append({
                    "segment_id": segment,
                    "close_ts_ms": int(bucket + interval_ms),
                    "close": float(group.iloc[-1].close),
                    "all_volume_positive": bool((group.volume > 0).all()),
                })
    return pd.DataFrame(records, columns=["segment_id", "close_ts_ms", "close", "all_volume_positive"])


def _informative_at_bar_close(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    pct_2h = pd.Series(np.nan, index=frame.index, dtype=float)
    age_ok = pd.Series(False, index=frame.index, dtype=bool)
    two_hour = _completed_informative(frame, 2 * 60 * 60_000)
    daily = _completed_informative(frame, 24 * 60 * 60_000)
    for segment, base in frame.groupby("segment_id", sort=False, dropna=False):
        two = two_hour[two_hour.segment_id == segment].copy()
        if not two.empty:
            two["value"] = two.close.pct_change()
            merged = pd.merge_asof(
                base[["close_ts_ms"]].sort_values("close_ts_ms"),
                two[["close_ts_ms", "value"]].sort_values("close_ts_ms"),
                on="close_ts_ms", direction="backward", allow_exact_matches=True,
            )
            pct_2h.loc[base.sort_values("close_ts_ms").index] = merged.value.to_numpy()
        day = daily[daily.segment_id == segment].copy()
        if not day.empty:
            day["value"] = day.all_volume_positive.rolling(30, min_periods=30).min().fillna(0).astype(bool)
            merged = pd.merge_asof(
                base[["close_ts_ms"]].sort_values("close_ts_ms"),
                day[["close_ts_ms", "value"]].sort_values("close_ts_ms"),
                on="close_ts_ms", direction="backward", allow_exact_matches=True,
            )
            age_ok.loc[base.sort_values("close_ts_ms").index] = merged.value.eq(True).to_numpy(dtype=bool)
    return pct_2h, age_ok


def cenderawasih_signals(symbol: str, frame: pd.DataFrame, btc_frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if "segment_id" not in frame or "segment_id" not in btc_frame:
        raise ScreenError("SEGMENT_ID_REQUIRED")
    interval = 30 * 60_000
    entry = pd.Series(False, index=frame.index)
    exit_ = pd.Series(False, index=frame.index)
    pct_2h, age_ok = _informative_at_bar_close(frame)
    btc_rsi = pd.Series(np.nan, index=frame.index, dtype=float)
    btc_values = pd.Series(np.nan, index=btc_frame.index, dtype=float)
    for _, btc_part in btc_frame.groupby("segment_id", sort=False, dropna=False):
        btc_values.loc[btc_part.index] = _rsi(btc_part.close, 14)
    btc_available = pd.DataFrame({"close_ts_ms": btc_frame.close_ts_ms, "btc_rsi": btc_values})
    if btc_available.close_ts_ms.duplicated().any():
        raise ScreenError("BTC_TIME_DUPLICATE")
    aligned = frame[["close_ts_ms"]].merge(btc_available, on="close_ts_ms", how="left", validate="one_to_one")
    btc_rsi.loc[frame.index] = aligned.btc_rsi.to_numpy()
    for _, part in frame.groupby("segment_id", sort=False, dropna=False):
        if part["segment_id"].isna().any():
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if len(part) > 1 and not part.open_ts_ms.diff().iloc[1:].eq(interval).all():
            raise ScreenError("INTRA_SEGMENT_TIME_GAP")
        close = part.close
        rsi = _rsi(close, 14)
        live = (part.volume > 0).rolling(72, min_periods=72).min().fillna(0).astype(bool)
        startup_complete = pd.Series(np.arange(len(part)) >= 999, index=part.index)
        common = startup_complete & live & age_ok.loc[part.index] & (close < part.open)
        branch = (
            ((close < _tv_hma(close, 130) * 0.83) & (btc_rsi.loc[part.index] < 30) & (rsi < 42) & (pct_2h.loc[part.index] > -0.06) & (pct_2h.loc[part.index] < 0.04))
            | ((close < _tv_hma(close, 63) * 0.85) & (btc_rsi.loc[part.index] >= 30) & (btc_rsi.loc[part.index] < 50) & (rsi < 48) & (pct_2h.loc[part.index] > -0.18))
            | ((close < _tv_hma(close, 30) * 0.84) & (btc_rsi.loc[part.index] >= 50) & (btc_rsi.loc[part.index] < 70) & (pct_2h.loc[part.index] > -0.17))
            | ((close < _tv_hma(close, 39) * 0.90) & (btc_rsi.loc[part.index] >= 70) & (pct_2h.loc[part.index] > -0.11))
        )
        pct = close.pct_change()
        exits = (
            (close > _ema_talib(close, 5) * 1.0)
            | (close < _ema_talib(close, 102) * 0.87)
            | ((close < _ema_talib(close, 71) * 0.89).rolling(2).min() > 0)
            | ((close > _ema_talib(close, 133) * 1.17).rolling(2).min() > 0)
            | (pct.rolling(3).sum() > 0.06)
        ) & (part.volume > 0)
        entry.loc[part.index] = (common & branch).fillna(False)
        exit_.loc[part.index] = exits.fillna(False)
    return entry, exit_


def _roi(duration_minutes: int) -> float:
    if duration_minutes >= 244:
        return 0.0
    if duration_minutes >= 64:
        return 0.04093
    if duration_minutes >= 33:
        return 0.0853
    return 0.27058


def replay_symbol(symbol: str, frame: pd.DataFrame, cost_bps: float) -> tuple[list[dict[str, Any]], int, int, int, int]:
    entry_signal, exit_signal = signals(frame)
    rows = frame.to_dict("records")
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    pending_entry: dict[str, int] | None = None
    pending_exit = False
    prior_segment: Any = None
    gap_quarantined = 0
    signal_count = int(entry_signal[(frame.open_ts_ms >= START_MS) & (frame.open_ts_ms < END_MS)].sum())
    rejected_occupied = 0
    for i, bar in enumerate(rows):
        open_ms = int(bar["open_ts_ms"])
        if open_ms >= END_MS:
            break
        segment = bar.get("segment_id")
        if segment is None or (isinstance(segment, float) and math.isnan(segment)):
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if prior_segment is not None and segment != prior_segment:
            gap_quarantined += int(position is not None or pending_entry is not None)
            position = None
            pending_entry = None
            pending_exit = False
        prior_segment = segment
        if pending_exit and position is not None:
            exit_price = float(bar["open"])
            gross = (exit_price / position["entry_price"] - 1) * 10_000
            trades.append({**position, "exit_ts_ms": open_ms, "exit_price": exit_price, "exit_reason": "NEXT_OPEN_EXIT_SIGNAL", "gross_bps": gross, "cost_bps": cost_bps, "net_bps": gross - cost_bps})
            position = None
            pending_exit = False
        if pending_entry is not None and position is None and START_MS <= open_ms < END_MS:
            position = {
                "identity": CANDIDATE_ID,
                "symbol": symbol,
                "signal_open_ts_ms": pending_entry["signal_open_ts_ms"],
                "signal_available_ts_ms": pending_entry["signal_available_ts_ms"],
                "entry_ts_ms": open_ms,
                "entry_price": float(bar["open"]),
                "side": "LONG",
            }
            pending_entry = None
        if position is not None:
            stop = position["entry_price"] * (1 - 0.34338)
            duration = max(0, (open_ms - position["entry_ts_ms"]) // 60_000)
            target = position["entry_price"] * (1 + _roi(int(duration)))
            exit_price = None
            reason = None
            if float(bar["low"]) <= stop:
                exit_price = min(float(bar["open"]), stop)
                reason = "STOP_FIRST"
            elif float(bar["high"]) >= target:
                exit_price = max(float(bar["open"]), target)
                reason = "ROI_TOUCH"
            if exit_price is not None:
                gross = (exit_price / position["entry_price"] - 1) * 10_000
                trades.append({**position, "exit_ts_ms": int(bar["close_ts_ms"]), "exit_price": exit_price, "exit_reason": reason, "gross_bps": gross, "cost_bps": cost_bps, "net_bps": gross - cost_bps})
                position = None
        if open_ms >= START_MS and bool(entry_signal.iloc[i]):
            if position is None and pending_entry is None and i + 1 < len(rows):
                pending_entry = {
                    "signal_open_ts_ms": open_ms,
                    "signal_available_ts_ms": int(bar["close_ts_ms"]),
                }
            else:
                rejected_occupied += 1
        if position is not None and bool(exit_signal.iloc[i]):
            pending_exit = True
    unresolved = int(position is not None or pending_entry is not None)
    return trades, signal_count, rejected_occupied, unresolved, gap_quarantined


def replay_cenderawasih_symbol(
    symbol: str, frame: pd.DataFrame, btc_frame: pd.DataFrame, cost_bps: float,
) -> tuple[list[dict[str, Any]], int, int, int, int]:
    entry_signal, exit_signal = cenderawasih_signals(symbol, frame, btc_frame)
    rows = frame.to_dict("records")
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    pending_entry: dict[str, int] | None = None
    pending_exit = False
    prior_segment: Any = None
    gap_quarantined = 0
    rejected_occupied = 0
    signal_count = int(entry_signal[(frame.open_ts_ms >= START_MS) & (frame.open_ts_ms < END_MS)].sum())

    def close_position(bar: Mapping[str, Any], price: float, reason: str, *, at_open: bool = False) -> None:
        nonlocal position
        assert position is not None
        gross = (price / float(position["entry_price"]) - 1) * 10_000
        trades.append({
            **position, "exit_ts_ms": int(bar["open_ts_ms"] if at_open else bar["close_ts_ms"]), "exit_price": price,
            "exit_reason": reason, "gross_bps": gross, "cost_bps": cost_bps,
            "net_bps": gross - cost_bps,
        })
        position = None

    for i, bar in enumerate(rows):
        open_ms = int(bar["open_ts_ms"])
        if open_ms >= END_MS:
            break
        segment = bar.get("segment_id")
        if segment is None or (isinstance(segment, float) and math.isnan(segment)):
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if prior_segment is not None and segment != prior_segment:
            gap_quarantined += int(position is not None or pending_entry is not None)
            position = None
            pending_entry = None
            pending_exit = False
        prior_segment = segment
        if pending_exit and position is not None:
            close_position(bar, float(bar["open"]), "NEXT_OPEN_EXIT_SIGNAL", at_open=True)
            pending_exit = False
        if pending_entry is not None and position is None and START_MS <= open_ms < END_MS:
            entry_price = float(bar["open"])
            position = {
                "identity": CENDERAWASIH_ID, "symbol": symbol,
                "signal_open_ts_ms": pending_entry["signal_open_ts_ms"],
                "signal_available_ts_ms": pending_entry["signal_available_ts_ms"],
                "entry_ts_ms": open_ms, "entry_price": entry_price, "side": "LONG",
                "peak_price": entry_price, "trailing_active": False,
            }
            pending_entry = None
        if position is not None:
            entry_price = float(position["entry_price"])
            fixed_stop = entry_price * 0.01
            open_price, low, high = float(bar["open"]), float(bar["low"]), float(bar["high"])
            if low <= fixed_stop:
                close_position(bar, min(open_price, fixed_stop), "STOP_FIRST")
            else:
                prior_peak = float(position["peak_price"])
                if bool(position["trailing_active"]):
                    prior_trail = prior_peak * 0.99
                    if low <= prior_trail:
                        close_position(bar, min(open_price, prior_trail), "TRAILING_STOP_PRIOR_BAR")
                if position is not None:
                    peak = max(prior_peak, high)
                    active = bool(position["trailing_active"]) or peak >= entry_price * 1.15
                    position["peak_price"] = peak
                    position["trailing_active"] = active
                    if active and low <= peak * 0.99:
                        close_position(bar, peak * 0.99, "TRAILING_STOP_SAME_BAR_WORST_CASE")
        if open_ms >= START_MS and bool(entry_signal.iloc[i]):
            if position is None and pending_entry is None and i + 1 < len(rows):
                pending_entry = {"signal_open_ts_ms": open_ms, "signal_available_ts_ms": int(bar["close_ts_ms"])}
            else:
                rejected_occupied += 1
        if position is not None and bool(exit_signal.iloc[i]):
            pending_exit = True
    unresolved = int(position is not None or pending_entry is not None)
    for trade in trades:
        trade.pop("peak_price", None)
        trade.pop("trailing_active", None)
    return trades, signal_count, rejected_occupied, unresolved, gap_quarantined


def replay_rsi_w1_symbol(
    symbol: str, frame: pd.DataFrame, cost_bps: float,
) -> tuple[list[dict[str, Any]], int, int, int, int]:
    long_signal, short_signal = rsi_w1_signals(frame)
    rows = frame.to_dict("records")
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    pending_side: str | None = None
    pending_signal: dict[str, int] | None = None
    prior_segment: Any = None
    gap_quarantined = rejected_same_side = transitions = 0

    def close_at_open(bar: Mapping[str, Any], reason: str) -> None:
        nonlocal position
        assert position is not None
        exit_price = float(bar["open"])
        direction = 1.0 if position["side"] == "LONG" else -1.0
        gross = direction * (exit_price / float(position["entry_price"]) - 1) * 10_000
        trades.append({
            **position,
            "exit_ts_ms": int(bar["open_ts_ms"]),
            "exit_price": exit_price,
            "exit_reason": reason,
            "gross_bps": gross,
            "cost_bps": cost_bps,
            "net_bps": gross - cost_bps,
        })
        position = None

    for i, bar in enumerate(rows):
        open_ms = int(bar["open_ts_ms"])
        if open_ms >= END_MS:
            break
        segment = bar.get("segment_id")
        if segment is None or (isinstance(segment, float) and math.isnan(segment)):
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if prior_segment is not None and segment != prior_segment:
            gap_quarantined += int(position is not None or pending_side is not None)
            position = None
            pending_side = None
            pending_signal = None
        prior_segment = segment
        if pending_side is not None and START_MS <= open_ms < END_MS:
            if position is not None and position["side"] != pending_side:
                close_at_open(bar, "NEXT_OPEN_OPPOSITE_EXTREME_FLIP")
            if position is None:
                assert pending_signal is not None
                position = {
                    "identity": RSI_W1_ID,
                    "symbol": symbol,
                    "signal_open_ts_ms": pending_signal["signal_open_ts_ms"],
                    "signal_available_ts_ms": pending_signal["signal_available_ts_ms"],
                    "entry_ts_ms": open_ms,
                    "entry_price": float(bar["open"]),
                    "side": pending_side,
                }
            pending_side = None
            pending_signal = None
        desired = "LONG" if bool(long_signal.iloc[i]) else ("SHORT" if bool(short_signal.iloc[i]) else None)
        if open_ms >= START_MS and desired is not None:
            current_or_pending = pending_side or (position["side"] if position is not None else None)
            if desired != current_or_pending and i + 1 < len(rows):
                transitions += 1
                pending_side = desired
                pending_signal = {
                    "signal_open_ts_ms": open_ms,
                    "signal_available_ts_ms": int(bar["close_ts_ms"]),
                }
            else:
                rejected_same_side += 1
    unresolved = int(position is not None or pending_side is not None)
    return trades, transitions, rejected_same_side, unresolved, gap_quarantined


def replay_btc_shock_symbol(
    symbol: str, frame: pd.DataFrame, cost_bps: float,
) -> tuple[list[dict[str, Any]], int, int, int, int]:
    """Internal execution translation; never a reproduction of event-study ACR."""
    events = btc_shock_signals(frame)
    rows = frame.to_dict("records")
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    prior_segment: Any = None
    attempts = rejected = quarantined = 0
    for i, bar in enumerate(rows):
        open_ms = int(bar["open_ts_ms"])
        if open_ms >= END_MS:
            break
        segment = bar["segment_id"]
        if prior_segment is not None and segment != prior_segment:
            quarantined += int(position is not None or pending is not None)
            position = pending = None
        prior_segment = segment
        if position is not None and open_ms >= position["exit_deadline_ts_ms"]:
            if open_ms != position["exit_deadline_ts_ms"]:
                raise ScreenError("SHOCK_EXIT_DEADLINE_MISSING_WITHOUT_GAP")
            gross = (float(bar["open"]) / position["entry_price"] - 1) * 10000
            trades.append({**position, "exit_ts_ms": open_ms, "exit_price": float(bar["open"]),
                           "exit_reason": "FROZEN_EVENT_CLOSE_PLUS12H", "gross_bps": gross,
                           "cost_bps": cost_bps, "net_bps": gross - cost_bps})
            position = None
        if pending is not None and open_ms >= pending["signal_available_ts_ms"]:
            # Delayed availability cannot extend the frozen event deadline.
            if open_ms < pending["exit_deadline_ts_ms"]:
                position = {**pending, "entry_ts_ms": open_ms, "entry_price": float(bar["open"])}
            else:
                quarantined += 1
            pending = None
        close_ms = int(bar["close_ts_ms"])
        if open_ms >= START_MS and close_ms < END_MS and bool(events.iloc[i]):
            attempts += 1
            # A shock immediately before scheduled exit was observed while occupied.
            if position is not None or pending is not None:
                rejected += 1
            else:
                pending = {"identity": BTC_SHOCK_ID, "symbol": symbol, "side": "LONG",
                           "signal_open_ts_ms": open_ms,
                           "signal_available_ts_ms": max(close_ms, int(bar["available_ts_ms"])),
                           "exit_deadline_ts_ms": close_ms + 12 * 3600000}
    return trades, attempts, rejected, int(position is not None or pending is not None) + quarantined, quarantined


def summarize(trades: list[dict[str, Any]], multiplier: int) -> dict[str, Any]:
    days = (END_MS - START_MS) / 86_400_000
    nets = [float(t["gross_bps"]) - multiplier * float(t["cost_bps"]) - float(t.get("funding_bps", 0.0)) for t in trades]
    gross = sum(float(t["gross_bps"]) for t in trades)
    trading_cost = multiplier * sum(float(t["cost_bps"]) for t in trades)
    funding = sum(float(t.get("funding_bps", 0.0)) for t in trades)
    cost = trading_cost + funding
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    equity = 0.0
    peak = 0.0
    dd = 0.0
    streak = max_streak = 0
    by_symbol: dict[str, float] = {}
    for trade, net in zip(trades, nets):
        equity += net
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        streak = streak + 1 if net <= 0 else 0
        max_streak = max(max_streak, streak)
        by_symbol[trade["symbol"]] = by_symbol.get(trade["symbol"], 0.0) + net
    total_abs = sum(abs(v) for v in by_symbol.values())
    return {
        "T": len(trades), "T_per_day": len(trades) / days,
        "WR_pct": 100 * len(wins) / len(trades) if trades else 0.0,
        "Gross_bps": gross, "Cost_bps": cost, "Net_bps": gross - cost,
        "ExplicitTradingCost_bps": trading_cost,
        "Funding_bps": funding if trades and all("funding_bps" in t for t in trades) else None,
        "GrossExp_bps_T": gross / len(trades) if trades else None,
        "CostExp_bps_T": cost / len(trades) if trades else None,
        "NetExp_bps_T": (gross - cost) / len(trades) if trades else None,
        "Net_bps_per_day": (gross - cost) / days,
        "payoff": (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None,
        "PF": sum(wins) / abs(sum(losses)) if losses else (None if not wins else "INF"),
        "DD_kind": "REALIZED_TRADE_CLOSE_EQUITY_BPS", "DD_bps": dd,
        "MaxLossStreak": max_streak,
        "concentration": {"largest_symbol_abs_net_share": max((abs(v) for v in by_symbol.values()), default=0.0) / total_abs if total_abs else None, "by_symbol_net_bps": by_symbol},
    }


def screen_bband_rsi(market: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    from ops.issue1388_bband_rsi_v1 import bind_bband_decisions, exit_flags_from_rsi14, replay_bband_rsi
    if set(market.get("six_funding", {})) != set(SYMBOLS):
        raise ScreenError("BBAND_SIX_FUNDING_REQUIRED_BEFORE_MODEL")
    funding = {symbol: validate_symbol_funding({"code": 0, "data": market["six_funding"][symbol]}, symbol) for symbol in SYMBOLS}
    accounting, all_trades = {}, []
    for symbol in SYMBOLS:
        frame = market["frames"][symbol]
        rows = frame.to_dict("records")
        entry = bband_rsi_entry_signals(frame).tolist()
        exits = {}
        for _, part in frame.groupby("segment_id", sort=False, dropna=False):
            exits.update(zip(part.open_ts_ms.astype("int64"), exit_flags_from_rsi14(_rsi(part.close, 14).tolist())))
        decisions = bind_bband_decisions(rows, entry, [exits[row["open_ts_ms"]] for row in rows])
        value = replay_bband_rsi(symbol, rows, decisions, funding[symbol], start_ms=START_MS, end_ms=END_MS,
                                 roundtrip_cost_bps=float(market["costs"][symbol]))
        accounting[symbol] = value
        all_trades.extend(value["trades"])
    all_trades.sort(key=lambda row: (row["exit_ts_ms"], row["symbol"]))
    one, two = summarize(all_trades, 1), summarize(all_trades, 2)
    census = {"signals_or_attempts": sum(x["signals"] for x in accounting.values()), "completed": len(all_trades),
              "occupied_rejections": sum(x["occupied_rejections"] for x in accounting.values()),
              "pending_rejections": sum(x["pending_entry_rejections"] for x in accounting.values()),
              "gap_quarantined": sum(int(x["gap_quarantine"] is not None or x["protective_touch_quarantine"] is not None) for x in accounting.values()),
              "unresolved_end": sum(x["unresolved_end"] for x in accounting.values())}
    census["missing_fill_evidence"] = census["gap_quarantined"]
    disposition = ("BLOCKED_INPUT_GAP_OR_PROTECTIVE_CLOCK" if census["gap_quarantined"] else
                   "BLOCKED_TERMINAL_OUTCOME_UNRESOLVED" if census["unresolved_end"] else
                   "SCREEN_SURVIVOR_PENDING_FULL" if one["T"] > 0 and one["Net_bps"] > 0 and two["Net_bps"] > 0 else "REJECT_ECONOMIC_EARLY")
    value = {"schema": "zel.issue1388.cheap_screen_result.v1", "issue": 1388,
             "candidate_id": BBAND_RSI_ID, **source_binding(profile), "period_ms": [START_MS, END_MS],
             "timeframe_min": 60, "classification": "DEVELOPMENT_ONLY_NOT_FRESH_NOT_OOS",
             "signal_rules": profile["signal_rules"], "order_adapter": profile["order_adapter"],
             "source_replication": False, "donor_live_fill_equivalence": False,
             "donor_config_and_net_roi_engine_reproduced": False,
             "trades": all_trades, "cost_1x": one, "cost_2x": two, "census": census,
             "symbol_accounting": accounting, "funding_hashes": six_funding_hashes(),
             "mark_account_NAV": None, "funding_actual_account_debit_certified": False,
             "disposition": disposition, "full_consumed": 0,
             "order_authority": "BLOCKED", "exchange_order_submitted": False, "promotion": False}
    return {**value, "result_sha256": digest(value)}


def screen_eth_session(market: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    from ops.issue1388_eth_session_v1 import replay_eth_sessions, terminal_eth_report
    if "eth_funding" not in market:
        raise ScreenError("ETH_FUNDING_REQUIRED_BEFORE_MODEL")
    # Certify archive coverage before any signal/order compute, even direct use.
    funding = validate_eth_funding({"code": 0, "data": market["eth_funding"]})
    rows = market["frames"]["ETH-USDT"].to_dict("records")
    replay = replay_eth_sessions(rows, funding, start_ms=START_MS, end_ms=END_MS,
                                 roundtrip_cost_bps=float(market["costs"]["ETH-USDT"]))
    trades = sorted(replay["trades"], key=lambda row: row["exit_ts_ms"])
    one, two = summarize(trades, 1), summarize(trades, 2)
    terminal = terminal_eth_report(replay, rows, end_ms=END_MS)
    if replay["gap_quarantine"] is not None:
        disposition = "BLOCKED_INPUT_GAP_WITH_OPEN_STATE"
    elif replay["unresolved_end"]:
        disposition = "BLOCKED_TERMINAL_OUTCOME_UNRESOLVED"
    else:
        disposition = "SCREEN_SURVIVOR_PENDING_FULL" if one["T"] > 0 and one["Net_bps"] > 0 and two["Net_bps"] > 0 else "REJECT_ECONOMIC_EARLY"
    value = {
        "schema": "zel.issue1388.cheap_screen_result.v1", "issue": 1388,
        "candidate_id": ETH_SESSION_ID, **source_binding(profile),
        "period_ms": [START_MS, END_MS], "timeframe_min": 60,
        "classification": "DEVELOPMENT_ONLY_NOT_FRESH_NOT_OOS",
        "signal_rules": profile["signal_rules"], "order_adapter": profile["order_adapter"],
        "source_replication": False, "donor_live_fill_equivalence": False,
        "fixed_unit_not_source_nav_rebalance": True,
        "trades": trades, "cost_1x": one, "cost_2x": two,
        "census": {"signals_or_attempts": len(replay["orders"]) + len(replay["same_side_boundaries"]) + len(replay["expired_targets"]),
                   "completed": len(trades), "occupied_rejections": 0,
                   "gap_quarantined": int(replay["gap_quarantine"] is not None),
                   "unresolved_end": replay["unresolved_end"],
                   "missing_fill_evidence": int(replay["gap_quarantine"] is not None),
                   "expired_targets": len(replay["expired_targets"])},
        "session_accounting": replay, "terminal_report": terminal,
        "funding_source_sha256": ETH_FUNDING_RAW_SHA256,
        "funding_receipt_sha256": ETH_FUNDING_RECEIPT_SHA256,
        "funding_model": "ARCHIVED_SIGNED_RATE_MARK_FIXED_QUANTITY_ADVERSE_TRANSITION_BOUNDARY",
        "mark_account_NAV": None, "funding_actual_account_debit_certified": False,
        "disposition": disposition, "full_consumed": 0,
        "order_authority": "BLOCKED", "exchange_order_submitted": False, "promotion": False,
    }
    return {**value, "result_sha256": digest(value)}


def screen(market: Mapping[str, Any], profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or PROFILES[CANDIDATE_ID]
    if profile["candidate_id"] == ETH_SESSION_ID:
        return screen_eth_session(market, profile)
    if profile["candidate_id"] == BBAND_RSI_ID:
        return screen_bband_rsi(market, profile)
    if profile["candidate_id"] not in (CANDIDATE_ID, CENDERAWASIH_ID, RSI_W1_ID, BTC_SHOCK_ID):
        raise ScreenError("ECONOMIC_ADAPTER_NOT_IMPLEMENTED")
    all_trades: list[dict[str, Any]] = []
    signals_total = occupied = unresolved = gap_quarantined = 0
    for symbol in profile.get("screen_symbols", SYMBOLS):
        if profile["candidate_id"] == CENDERAWASIH_ID:
            trades, signal_count, rejected, open_count, quarantined = replay_cenderawasih_symbol(
                symbol, market["frames"][symbol], market["frames"]["BTC-USDT"], float(market["costs"][symbol]),
            )
        elif profile["candidate_id"] == BTC_SHOCK_ID:
            trades, signal_count, rejected, open_count, quarantined = replay_btc_shock_symbol(
                symbol, market["frames"][symbol], float(market["costs"][symbol]),
            )
        elif profile["candidate_id"] == RSI_W1_ID:
            trades, signal_count, rejected, open_count, quarantined = replay_rsi_w1_symbol(
                symbol, market["frames"][symbol], float(market["costs"][symbol]),
            )
        else:
            trades, signal_count, rejected, open_count, quarantined = replay_symbol(
                symbol, market["frames"][symbol], float(market["costs"][symbol]),
            )
        all_trades.extend(trades)
        signals_total += signal_count
        occupied += rejected
        unresolved += open_count
        gap_quarantined += quarantined
    if profile["candidate_id"] == BTC_SHOCK_ID and "btc_funding" in market:
        for trade in all_trades:
            signed_funding, settlements = funding_for_btc_trade(trade, market["btc_funding"])
            trade.update(funding_bps=signed_funding, funding_settlements=settlements,
                         net_bps=trade["gross_bps"] - trade["cost_bps"] - signed_funding)
    all_trades.sort(key=lambda row: (row["exit_ts_ms"], row["symbol"]))
    one, two = summarize(all_trades, 1), summarize(all_trades, 2)
    if gap_quarantined:
        disposition = "BLOCKED_INPUT_GAP_WITH_OPEN_STATE"
    elif profile["candidate_id"] == BTC_SHOCK_ID and unresolved:
        disposition = "BLOCKED_TERMINAL_OUTCOME_UNRESOLVED"
    else:
        disposition = "SCREEN_SURVIVOR_PENDING_FULL" if one["T"] > 0 and one["Net_bps"] > 0 and two["Net_bps"] > 0 else "REJECT_ECONOMIC_EARLY"
    value = {
        "schema": "zel.issue1388.cheap_screen_result.v1", "issue": 1388,
        "candidate_id": profile["candidate_id"], **source_binding(profile),
        "period_ms": [START_MS, END_MS], "timeframe_min": profile["timeframe_min"],
        "classification": "DEVELOPMENT_ONLY_NOT_FRESH_NOT_OOS",
        "signal_rules": profile["signal_rules"],
        "order_adapter": profile["order_adapter"],
        "donor_live_fill_equivalence": False,
        "census": {"signals_or_attempts": signals_total, "completed": len(all_trades), "occupied_rejections": occupied, "gap_quarantined": gap_quarantined, "unresolved_end": unresolved, "missing_fill_evidence": gap_quarantined},
        "trades": all_trades, "cost_1x": one, "cost_2x": two,
        "disposition": disposition, "full_consumed": 0,
        "order_authority": "BLOCKED", "exchange_order_submitted": False, "promotion": False,
    }
    if profile["candidate_id"] == BTC_SHOCK_ID:
        if "btc_funding" not in market and value["disposition"] in ("SCREEN_SURVIVOR_PENDING_FULL", "REJECT_ECONOMIC_EARLY"):
            # Funding credits as well as debits can change the costed verdict.
            value["disposition"] = "BLOCKED_MISSING_FUNDING"
        value.update(source_hash_kind="RULE_EVIDENCE_SNAPSHOT_NOT_PDF", source_replication=False,
                     funding_bps=one["Funding_bps"] if "btc_funding" in market else None, mark_account_NAV=None,
                     funding_source_sha256=BTC_FUNDING_RAW_SHA256 if "btc_funding" in market else None,
                     funding_model="OBSERVED_RATE_MARK_FIXED_QUANTITY_ADVERSE_BOUNDARY" if "btc_funding" in market else "UNKNOWN",
                     economics_profile="EXPLICIT_TAKER_COST_SCENARIO_WITH_SIGNED_OBSERVED_FUNDING" if "btc_funding" in market else "EXPLICIT_TAKER_COST_SCENARIO_FUNDING_UNVERIFIED")
    return {**value, "result_sha256": digest(value)}


def validate_btc_preflight(activation: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    """Bind a saved no-PnL result to this exact source, period and input receipt."""
    proof = activation.get("density_preflight")
    if not isinstance(proof, dict):
        raise ScreenError("BTC_SHOCK_PREFLIGHT_REQUIRED")
    payload = {k: v for k, v in proof.items() if k != "result_sha256"}
    if proof.get("result_sha256") != digest(payload):
        raise ScreenError("BTC_SHOCK_PREFLIGHT_HASH")
    if (proof.get("period_ms") != [START_MS, END_MS]
            or proof.get("source_inventory_sha256") != SOURCE_INVENTORY_SHA256
            or proof.get("economic_screen_consumed") != 0
            or proof.get("order_authority") != "BLOCKED"):
        raise ScreenError("BTC_SHOCK_PREFLIGHT_BINDING")
    candidate = proof.get("candidates", {}).get(BTC_SHOCK_ID, {})
    profile = PROFILES[BTC_SHOCK_ID]
    if any(candidate.get(k) != v for k, v in source_binding(profile).items()):
        raise ScreenError("BTC_SHOCK_PREFLIGHT_SOURCE")
    if candidate.get("signal_rules") != profile["signal_rules"] or candidate.get("timeframe_min") != 60:
        raise ScreenError("BTC_SHOCK_PREFLIGHT_RULE")
    count = candidate.get("source_native_btc", {}).get("raw_signal_bars")
    if type(count) is not int or count <= 0:
        raise ScreenError("BTC_SHOCK_ZERO_OR_UNCONFIRMED_DENSITY")
    saved_receipt = proof.get("receipts", {}).get("60", {})
    if saved_receipt != receipt:
        raise ScreenError("BTC_SHOCK_PREFLIGHT_INPUT_DRIFT")


def audit_eth_result(result: Mapping[str, Any], rows: list[dict[str, Any]],
                     funding_rows: list[dict[str, Any]], roundtrip_cost_bps: float) -> None:
    from ops.issue1388_eth_session_v1 import terminal_eth_report
    accounting = result.get("session_accounting", {})
    if (result.get("trades") != accounting.get("trades")
            or result.get("terminal_report") != terminal_eth_report(accounting, rows, end_ms=END_MS)):
        raise ScreenError("ETH_SAVED_TERMINAL_OR_LEDGER_AUDIT_FAIL")
    # Independent stored-order arithmetic, not another signal/market replay.
    prices = {row["open_ts_ms"]: float(row["open"]) for row in rows}
    trades = result["trades"]
    position = None
    trade_index = 0
    paid_cost = 0.0
    last_time = None
    one_way = roundtrip_cost_bps / 2
    def funding(entry: int, exit_: int, side: int, basis: float, closed: bool) -> tuple[float, int]:
        total = 0.0
        count = 0
        for row in funding_rows:
            stamp = row["fundingTime"]
            if entry <= stamp <= exit_ and stamp < END_MS:
                debit = side * float(row["fundingRate"]) * float(row["markPrice"]) / basis * 10000
                if stamp != entry and (not closed or stamp != exit_) or debit > 0:
                    total += debit
                    count += 1
        return total, count
    for order in accounting["orders"]:
        stamp, price = order["execution_ts_ms"], order["execution_price"]
        current = 0 if position is None else position["signed_units"]
        desired = order["desired_units"]
        if (type(desired) is not int or desired not in (-1, 0, 1) or order["current_units"] != current
                or order["quantity"] != abs(desired - current) or order["quantity"] == 0
                or not START_MS <= stamp < END_MS or (last_time is not None and stamp <= last_time)
                or not order["available_ts_ms"] <= stamp < order["expires_ts_ms"]
                or prices.get(stamp) != price
                or not math.isclose(order["cost_bps"], order["quantity"] * one_way, abs_tol=1e-9)):
            raise ScreenError("ETH_SAVED_ORDER_ARITHMETIC_AUDIT_FAIL")
        paid_cost += order["cost_bps"]
        last_time = stamp
        if position is not None:
            if trade_index >= len(trades):
                raise ScreenError("ETH_SAVED_CLOSED_LEDGER_COUNT")
            trade = trades[trade_index]
            basis, entry = position["entry_price"], position["entry_ts_ms"]
            gross = current * (price / basis - 1) * 10000
            signed_funding, settlements = funding(entry, stamp, current, basis, True)
            if (any(trade.get(k) != position[k] for k in ("entry_ts_ms", "entry_price", "signed_units"))
                    or trade["exit_ts_ms"] != stamp or trade["exit_price"] != price
                    or not math.isclose(trade["gross_bps"], gross, abs_tol=1e-9)
                    or not math.isclose(trade["cost_bps"], roundtrip_cost_bps, abs_tol=1e-9)
                    or not math.isclose(trade["funding_bps"], signed_funding, abs_tol=1e-9)
                    or trade["funding_settlements"] != settlements
                    or not math.isclose(trade["net_bps"], gross - roundtrip_cost_bps - signed_funding, abs_tol=1e-9)):
                raise ScreenError("ETH_SAVED_CLOSED_ARITHMETIC_AUDIT_FAIL")
            trade_index += 1
            position = None
        if desired:
            position = {"signed_units": desired, "entry_price": price, "entry_ts_ms": stamp}
    if trade_index != len(trades) or not math.isclose(paid_cost, accounting["paid_trading_cost_bps"], abs_tol=1e-9):
        raise ScreenError("ETH_SAVED_LEDGER_COUNT_COST_AUDIT_FAIL")
    open_position = accounting["open_position"]
    unresolved = int(open_position is not None or accounting["pending_target"] is not None or accounting["gap_quarantine"] is not None)
    expected_disposition = ("BLOCKED_INPUT_GAP_WITH_OPEN_STATE" if accounting["gap_quarantine"] is not None else
                            "BLOCKED_TERMINAL_OUTCOME_UNRESOLVED" if unresolved else
                            "SCREEN_SURVIVOR_PENDING_FULL" if result["cost_1x"]["T"] > 0 and result["cost_1x"]["Net_bps"] > 0 and result["cost_2x"]["Net_bps"] > 0 else "REJECT_ECONOMIC_EARLY")
    if (accounting["unresolved_end"] != unresolved or result["census"]["unresolved_end"] != unresolved
            or result["disposition"] != expected_disposition):
        raise ScreenError("ETH_SAVED_DISPOSITION_AUDIT_FAIL")
    if ((position is None) != (open_position is None)
            or position is not None and any(position[k] != open_position.get(k) for k in position)):
        raise ScreenError("ETH_SAVED_OPEN_LEDGER_AUDIT_FAIL")
    if open_position is not None and accounting["gap_quarantine"] is None:
        expected, settlements = funding(position["entry_ts_ms"], END_MS, position["signed_units"], position["entry_price"], False)
        if not math.isclose(open_position["funding_bps_to_end_exclusive"], expected, abs_tol=1e-9) or open_position["funding_settlements"] != settlements:
            raise ScreenError("ETH_SAVED_OPEN_FUNDING_AUDIT_FAIL")


def audit_bband_result(result: Mapping[str, Any], market: Mapping[str, Any]) -> None:
    from decimal import Decimal
    from ops.issue1388_bband_rsi_v1 import bind_bband_decisions, exit_flags_from_rsi14
    accounting = result["symbol_accounting"]
    trades = sorted([t for x in accounting.values() for t in x["trades"]], key=lambda t: (t["exit_ts_ms"], t["symbol"]))
    if result["trades"] != trades:
        raise ScreenError("BBAND_SAVED_TRADE_BINDING")
    for symbol in SYMBOLS:
        saved = accounting[symbol]
        rows = market["frames"][symbol].to_dict("records")
        opens = {r["open_ts_ms"]: r for r in rows}
        closes = {r["close_ts_ms"]: r for r in rows}
        frame = market["frames"][symbol]
        exits = {}
        for _, part in frame.groupby("segment_id", sort=False, dropna=False):
            exits.update(zip(part.open_ts_ms.astype("int64"), exit_flags_from_rsi14(_rsi(part.close, 14).tolist())))
        # No order/model replay: independently certify source decisions and clocks.
        decisions = bind_bband_decisions(rows, bband_rsi_entry_signals(frame).tolist(),
                                         [exits[r["open_ts_ms"]] for r in rows])
        by_signal = {d["signal_open_ts_ms"]: d for d in decisions}
        clock_keys = ("signal_open_ts_ms", "signal_close_ts_ms", "signal_available_ts_ms")
        def verify_signal(order: Mapping[str, Any], flag: str, execution: int) -> Mapping[str, Any]:
            decision = by_signal.get(order.get("signal_open_ts_ms"))
            if (decision is None or not decision[flag]
                    or any(order.get(k) != decision[k] for k in clock_keys)
                    or not START_MS <= decision["signal_open_ts_ms"] < decision["signal_close_ts_ms"] < END_MS):
                raise ScreenError("BBAND_SAVED_SOURCE_SIGNAL_BINDING")
            eligible = next((r for r in rows if r["open_ts_ms"] >= decision["signal_available_ts_ms"]), None)
            if (eligible is None or eligible["open_ts_ms"] != execution
                    or eligible["segment_id"] != decision["segment_id"]):
                raise ScreenError("BBAND_SAVED_EARLIEST_CAUSAL_OPEN")
            return decision
        one_way = float(market["costs"][symbol]) / 2
        position, trade_index, paid, last_stamp = None, 0, 0.0, -1
        def funding(entry: int, exit_: int, basis: float, closed: bool) -> tuple[float, int]:
            debit, count = 0.0, 0
            for row in market["six_funding"][symbol]:
                stamp = row["fundingTime"]
                if entry <= stamp <= exit_ and stamp < END_MS:
                    value = float(row["fundingRate"]) * float(row["markPrice"]) / basis * 10000
                    if stamp != entry and (not closed or stamp != exit_) or value > 0:
                        debit += value
                        count += 1
            return debit, count
        for order in saved["orders"]:
            stamp, price = order["execution_ts_ms"], order["price"]
            if (order["quantity"] != 1 or not START_MS <= stamp < END_MS
                    or not math.isclose(order["cost_bps"], one_way, abs_tol=1e-9)):
                raise ScreenError("BBAND_SAVED_ORDER_COST_CLOCK")
            if stamp < last_stamp:
                raise ScreenError("BBAND_SAVED_EXECUTION_CHRONOLOGY")
            last_stamp = stamp
            paid += one_way
            if order["kind"] == "ENTRY":
                if position is not None or stamp not in opens or price != float(opens[stamp]["open"]):
                    raise ScreenError("BBAND_SAVED_ENTRY_PRICE")
                verify_signal(order, "entry", stamp)
                identity = f"{symbol}:{stamp}:{order['signal_open_ts_ms']}"
                if order["entry_identity"] != identity:
                    raise ScreenError("BBAND_SAVED_ENTRY_SIGNAL_IDENTITY")
                position = {"entry_ts_ms": stamp, "entry_price": price, "entry_identity": identity,
                            **{k: order[k] for k in clock_keys}}
            elif order["kind"] == "EXIT":
                if position is None or order["entry_identity"] != position["entry_identity"] or trade_index >= len(saved["trades"]):
                    raise ScreenError("BBAND_SAVED_EXIT_BINDING")
                if stamp <= position["entry_ts_ms"]:
                    raise ScreenError("BBAND_SAVED_EXECUTION_CHRONOLOGY")
                trade = saved["trades"][trade_index]
                if order["reason"] == "NEXT_AVAILABLE_OPEN_RSI_EXIT":
                    decision = verify_signal(order, "exit", stamp)
                    first = next((d for d in decisions if d["exit"] and
                                  d["signal_open_ts_ms"] >= position["entry_ts_ms"]), None)
                    if (first != decision or any(trade.get("exit_" + k) != decision[k] for k in clock_keys)):
                        raise ScreenError("BBAND_SAVED_EXIT_FIRST_SIGNAL_BINDING")
                basis = position["entry_price"]
                stop, roi = float(Decimal(str(basis)) * Decimal("0.75")), float(Decimal(str(basis)) * Decimal("1.10"))
                reason = order["reason"]
                if reason.startswith("INTRABAR"):
                    bar = closes.get(stamp)
                    valid = (bar is not None and bar["available_ts_ms"] == stamp and stop < float(bar["open"]) < roi
                             and (reason == "INTRABAR_STOP_FIRST" and float(bar["low"]) <= stop and price == stop
                                  or reason == "INTRABAR_ROI" and float(bar["low"]) > stop and float(bar["high"]) >= roi and price == roi))
                else:
                    bar = opens.get(stamp)
                    valid = bar is not None and price == float(bar["open"]) and (
                        reason == "OPEN_STOP" and price <= stop or reason == "OPEN_ROI" and price >= roi
                        or reason == "NEXT_AVAILABLE_OPEN_RSI_EXIT" and stop < price < roi)
                gross = (price / basis - 1) * 10000
                debit, count = funding(position["entry_ts_ms"], stamp, basis, True)
                if (not valid or any(trade.get(k) != position[k] for k in position)
                        or trade["symbol"] != symbol or trade["exit_ts_ms"] != stamp or trade["exit_price"] != price
                        or trade["exit_reason"] != reason or not math.isclose(trade["gross_bps"], gross, abs_tol=1e-9)
                        or not math.isclose(trade["cost_bps"], 2 * one_way, abs_tol=1e-9)
                        or not math.isclose(trade["funding_bps"], debit, abs_tol=1e-9)
                        or trade["funding_settlements"] != count
                        or not math.isclose(trade["net_bps"], gross - 2 * one_way - debit, abs_tol=1e-9)):
                    raise ScreenError("BBAND_SAVED_EXIT_GROSS_FUNDING_AUDIT")
                trade_index += 1
                position = None
            else:
                raise ScreenError("BBAND_SAVED_ORDER_KIND")
        open_position = saved["open_position"]
        if ((position is None) != (open_position is None) or trade_index != len(saved["trades"])
                or position is not None and any(position[k] != open_position.get(k) for k in position)
                or not math.isclose(paid, saved["paid_trading_cost_bps"], abs_tol=1e-9)
                or not math.isclose(paid, sum(t["cost_bps"] for t in saved["trades"]) + (one_way if position else 0), abs_tol=1e-9)):
            raise ScreenError("BBAND_SAVED_OPEN_COUNT_PAID_COST_AUDIT")
        if position is not None and open_position["funding_bps_to_end_exclusive"] is not None:
            debit, count = funding(position["entry_ts_ms"], END_MS, position["entry_price"], False)
            if not math.isclose(open_position["funding_bps_to_end_exclusive"], debit, abs_tol=1e-9) or open_position["funding_settlements"] != count:
                raise ScreenError("BBAND_SAVED_OPEN_FUNDING_AUDIT")
    gaps = sum(int(x["gap_quarantine"] is not None or x["protective_touch_quarantine"] is not None) for x in accounting.values())
    unresolved = sum(int(x["open_position"] is not None or x["pending_entry"] is not None or x["pending_exit"] is not None or x["gap_quarantine"] is not None or x["protective_touch_quarantine"] is not None) for x in accounting.values())
    disposition = ("BLOCKED_INPUT_GAP_OR_PROTECTIVE_CLOCK" if gaps else "BLOCKED_TERMINAL_OUTCOME_UNRESOLVED" if unresolved else
                   "SCREEN_SURVIVOR_PENDING_FULL" if result["cost_1x"]["T"] > 0 and result["cost_1x"]["Net_bps"] > 0 and result["cost_2x"]["Net_bps"] > 0 else "REJECT_ECONOMIC_EARLY")
    if result["census"]["gap_quarantined"] != gaps or result["census"]["unresolved_end"] != unresolved or result["disposition"] != disposition:
        raise ScreenError("BBAND_SAVED_DISPOSITION_AUDIT")


def validate_bband_preflight(activation: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    proof = activation.get("density_preflight")
    if not isinstance(proof, dict) or proof.get("result_sha256") != digest({k: v for k, v in proof.items() if k != "result_sha256"}):
        raise ScreenError("BBAND_PREFLIGHT_HASH_REQUIRED")
    candidate = proof.get("candidates", {}).get(BBAND_RSI_ID, {})
    if (proof.get("period_ms") != [START_MS, END_MS] or proof.get("source_inventory_sha256") != SOURCE_INVENTORY_SHA256
            or proof.get("economic_screen_consumed") != 0 or proof.get("order_authority") != "BLOCKED"
            or any(candidate.get(k) != v for k, v in source_binding(PROFILES[BBAND_RSI_ID]).items())
            or candidate.get("signal_rules") != PROFILES[BBAND_RSI_ID]["signal_rules"] or candidate.get("timeframe_min") != 60
            or type(candidate.get("source_exact_episodes")) is not int or candidate["source_exact_episodes"] <= 0):
        raise ScreenError("BBAND_PREFLIGHT_SOURCE_RULE_WINDOW_DENSITY")
    saved, expected = dict(proof.get("receipts", {}).get("60", {})), dict(receipt)
    for value in (saved, expected):
        value.pop("receipt_sha256", None)
        value.pop("order_adapter", None)
    if saved != expected or activation.get("funding_hashes") != six_funding_hashes():
        raise ScreenError("BBAND_PREFLIGHT_INPUT_FUNDING_BINDING")


def validate_eth_preflight(activation: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    proof = activation.get("density_preflight")
    if not isinstance(proof, dict) or proof.get("result_sha256") != digest({k: v for k, v in proof.items() if k != "result_sha256"}):
        raise ScreenError("ETH_PREFLIGHT_HASH_REQUIRED")
    candidate = proof.get("candidates", {}).get(ETH_SESSION_ID, {})
    if (proof.get("period_ms") != [START_MS, END_MS]
            or proof.get("source_inventory_sha256") != SOURCE_INVENTORY_SHA256
            or proof.get("economic_screen_consumed") != 0 or proof.get("order_authority") != "BLOCKED"
            or any(candidate.get(k) != v for k, v in source_binding(PROFILES[ETH_SESSION_ID]).items())
            or candidate.get("signal_rules") != PROFILES[ETH_SESSION_ID]["signal_rules"]
            or candidate.get("timeframe_min") != 60):
        raise ScreenError("ETH_PREFLIGHT_SOURCE_RULE_WINDOW")
    count = candidate.get("source_native_eth", {}).get("source_exact_episodes")
    if type(count) is not int or count <= 0:
        raise ScreenError("ETH_ZERO_OR_UNCONFIRMED_DENSITY")
    saved = dict(proof.get("receipts", {}).get("60", {}))
    expected = dict(receipt)
    # Density receipt certifies the same inputs; only execution adapter changed.
    for value in (saved, expected):
        value.pop("receipt_sha256", None)
        value.pop("order_adapter", None)
    if saved != expected:
        raise ScreenError("ETH_PREFLIGHT_INPUT_DRIFT")
    if (activation.get("funding_raw_sha256") != ETH_FUNDING_RAW_SHA256
            or activation.get("funding_receipt_sha256") != ETH_FUNDING_RECEIPT_SHA256):
        raise ScreenError("ETH_FUNDING_ACTIVATION_BINDING")


def execute(source_root: Path, activation_path: Path, output_dir: Path) -> dict[str, Any]:
    head = current_head()
    activation = validate_activation(activation_path, head)
    profile = profile_for(activation["candidate_id"])
    if output_dir.exists():
        raise ScreenError("OUTPUT_DIRECTORY_ALREADY_EXISTS_NO_RETRY")
    market = load_market(source_root, profile)
    receipt = source_receipt(market, profile)
    if profile["candidate_id"] == BTC_SHOCK_ID:
        validate_btc_preflight(activation, receipt)
        if activation.get("funding_raw_sha256") != BTC_FUNDING_RAW_SHA256 or activation.get("funding_receipt_sha256") != BTC_FUNDING_RECEIPT_SHA256:
            raise ScreenError("BTC_FUNDING_ACTIVATION_BINDING")
    if profile["candidate_id"] == ETH_SESSION_ID:
        validate_eth_preflight(activation, receipt)
    if profile["candidate_id"] == BBAND_RSI_ID:
        validate_bband_preflight(activation, receipt)
    start = {
        "schema": "zel.issue1388.alpha_screen_start.v1", "issue": 1388,
        "candidate_id": profile["candidate_id"], "state": "STARTED_AFTER_INPUT_VALIDATION_BEFORE_SIGNAL_COMPUTE",
        "reviewed_source_sha": head, "source_receipt_sha256": receipt["receipt_sha256"],
        "activation_sha256": digest(activation), "period_ms": [START_MS, END_MS],
        "global_heavy_group": GLOBAL_HEAVY_GROUP, "order_authority": "BLOCKED",
    }
    if profile["candidate_id"] == BTC_SHOCK_ID:
        start.update(funding_raw_sha256=BTC_FUNDING_RAW_SHA256, funding_receipt_sha256=BTC_FUNDING_RECEIPT_SHA256)
    if profile["candidate_id"] == ETH_SESSION_ID:
        start.update(funding_raw_sha256=ETH_FUNDING_RAW_SHA256, funding_receipt_sha256=ETH_FUNDING_RECEIPT_SHA256)
    if profile["candidate_id"] == BBAND_RSI_ID:
        start.update(funding_hashes=six_funding_hashes())
    start_commit = create_record(profile["execution_ref"], "STARTED.json", start, head)
    output_dir.mkdir(parents=True)
    write_once(output_dir / "SOURCE_RECEIPT.json", receipt)
    write_once(output_dir / "STARTED.json", {**start, "execution_commit_sha": start_commit})
    if profile["candidate_id"] == BTC_SHOCK_ID:
        for filename in ("BTC_FUNDING_RAW.json", "BTC_FUNDING_RECEIPT.json"):
            with (output_dir / filename).open("xb") as handle:
                handle.write((INTAKE_PATH.parent / filename).read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
    if profile["candidate_id"] == ETH_SESSION_ID:
        for filename in ("ETH_FUNDING_RAW.json", "ETH_FUNDING_RECEIPT.json"):
            with (output_dir / filename).open("xb") as handle:
                handle.write((INTAKE_PATH.parent / filename).read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
    if profile["candidate_id"] == BBAND_RSI_ID:
        for symbol in SYMBOLS:
            for kind in ("RAW", "RECEIPT"):
                filename = symbol.split("-")[0] + "_FUNDING_" + kind + ".json"
                with (output_dir / filename).open("xb") as handle:
                    handle.write((INTAKE_PATH.parent / filename).read_bytes())
                    handle.flush()
                    os.fsync(handle.fileno())
    result = screen(market, profile)
    write_once(output_dir / "RESULT.json", result)
    audited = read_json(output_dir / "RESULT.json")
    supplied = audited.pop("result_sha256")
    if supplied != digest(audited) or audited.get("cost_1x") != summarize(audited["trades"], 1) or audited.get("cost_2x") != summarize(audited["trades"], 2):
        raise ScreenError("SAVED_RESULT_AUDIT_FAIL")
    if profile["candidate_id"] == ETH_SESSION_ID:
        audit_eth_result(audited, market["frames"]["ETH-USDT"].to_dict("records"), market["eth_funding"], float(market["costs"]["ETH-USDT"]))
    if profile["candidate_id"] == BBAND_RSI_ID:
        audit_bband_result(audited, market)
    envelope = {"schema": "zel.issue1388.persisted_result.v1", "issue": 1388, "execution_commit_sha": start_commit, "result": result, "order_authority": "BLOCKED"}
    envelope = {**envelope, "envelope_sha256": digest(envelope)}
    result_commit = create_record(profile["result_ref"], "RESULT.json", envelope, start_commit)
    write_once(output_dir / "PERSISTED.json", {**envelope, "result_commit_sha": result_commit})
    return {"state": "COMPLETE_PERSISTED_AND_AUDITED", "disposition": result["disposition"], "result_sha256": result["result_sha256"], "result_commit_sha": result_commit, "economic_table": {"1x": result["cost_1x"], "2x": result["cost_2x"]}}


def execute_density(source_root: Path, candidate_ids: list[str], output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise ScreenError("OUTPUT_DIRECTORY_ALREADY_EXISTS_NO_RETRY")
    if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
        raise ScreenError("DENSITY_CANDIDATES_REQUIRED_UNIQUE")
    frames_by_timeframe: dict[int, Mapping[str, Any]] = {}
    combined: dict[str, Any] = {}
    receipts: dict[str, Any] = {}
    for candidate_id in candidate_ids:
        profile = profile_for(candidate_id)
        timeframe = int(profile["timeframe_min"])
        market = frames_by_timeframe.get(timeframe)
        if market is None:
            market = load_market(source_root, profile)
            frames_by_timeframe[timeframe] = market
            receipts[str(timeframe)] = source_receipt(market, profile)
        result = density_census(market, [candidate_id])
        combined[candidate_id] = result["candidates"][candidate_id]
    value = {
        "schema": "zel.issue1388.signal_density_preflight.v1",
        "issue": 1388,
        "classification": "NO_PNL_NO_EXIT_NO_FUTURE_OUTCOME_SOURCE_EXACT_SIGNAL_CENSUS",
        "period_ms": [START_MS, END_MS],
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "receipts": receipts,
        "candidates": combined,
        "economic_screen_consumed": 0,
        "order_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    result = {**value, "result_sha256": digest(value)}
    output_dir.mkdir(parents=True)
    write_once(output_dir / "DENSITY.json", result)
    return {"state": "NO_PNL_DENSITY_COMPLETE", "result_sha256": result["result_sha256"], "candidates": combined}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--activation", type=Path)
    parser.add_argument("--density-candidates")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.activation) == bool(args.density_candidates):
        raise ScreenError("EXACTLY_ONE_OF_ACTIVATION_OR_DENSITY_CANDIDATES")
    if args.density_candidates:
        candidate_ids = [value.strip() for value in args.density_candidates.split(",") if value.strip()]
        value = execute_density(args.source_root, candidate_ids, args.output_dir)
    else:
        value = execute(args.source_root, args.activation, args.output_dir)
    print(json.dumps(value, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
