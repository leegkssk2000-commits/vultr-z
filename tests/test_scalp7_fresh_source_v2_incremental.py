"""One-owner incremental collector regression against exact frozen v2 receipts."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest

from backend.research.rebuild import scalp7_fresh_source_v2 as old
from backend.research.rebuild import scalp7_fresh_source_v2_incremental as fast
from backend.research.rebuild.scalp7_source_data_v2 import SourceDataError


def fetch(url: str) -> tuple[int, bytes]:
    args = parse_qs(urlparse(url).query)
    start = int(args["startTime"][0])
    end = int(args["endTime"][0]) + 1
    return (
        200,
        json.dumps(
            {
                "code": 0,
                "data": [
                    {
                        "time": stamp,
                        "open": "10",
                        "high": "12",
                        "low": "9",
                        "close": "11",
                        "volume": "3",
                    }
                    for stamp in range(start, end, 60000)
                ],
            }
        ).encode(),
    )


def source(tmp_path: Path) -> Path:
    old.collect_once(
        tmp_path,
        symbols=("BTC-USDT",),
        start_ms=0,
        end_ms=60000,
        fetch=fetch,
    )
    return tmp_path


def call(tmp_path: Path, end_ms: int, bootstrap: bool = False):
    return fast.collect_once(
        tmp_path,
        symbols=("BTC-USDT",),
        start_ms=0,
        end_ms=end_ms,
        bootstrap_prior_v2=bootstrap,
        fetch=fetch,
    )


def test_bootstrap_holds_until_explicit_original_v2_audit(tmp_path):
    source(tmp_path)
    with pytest.raises(SourceDataError, match="REQUIRES_PRIOR_V2"):
        call(tmp_path, 60000)


def test_append_parity_no_redownload_original_windows(tmp_path):
    source(tmp_path)
    original = (tmp_path / "CURSOR.json").read_bytes()
    boot = call(tmp_path, 60000, True)
    assert boot["new_requests"] == 0
    assert (tmp_path / "CURSOR.json").read_bytes() == original
    grown = call(tmp_path, 120000)
    assert grown["new_requests"] == 1
    assert call(tmp_path, 120000)["new_requests"] == 0
    v = old.load_observed_minutes(tmp_path)["BTC-USDT"]
    assert len(v) == 2
    assert v.timestamp_ms.tolist() == [0, 60000]
    cp = json.loads((tmp_path / fast.CHECKPOINT).read_bytes())
    assert cp["symbols"]["BTC-USDT"]["count"] == 2
    assert cp["full_historical_audit_every_iteration"] is False


def test_historical_cursor_pointer_mutation_fails(tmp_path):
    source(tmp_path)
    call(tmp_path, 60000, True)
    cursor_path = tmp_path / "CURSOR.json"
    cursor = json.loads(cursor_path.read_bytes())
    cursor["symbols"]["BTC-USDT"][0]["sha256"] = "0" * 64
    cursor_path.write_text(json.dumps(cursor))
    with pytest.raises(SourceDataError, match="HISTORIC_CURSOR_CHANGED"):
        call(tmp_path, 120000)


def test_extra_v2_receipt_after_checkpoint_checked_as_suffix(tmp_path):
    source(tmp_path)
    call(tmp_path, 60000, True)
    old.collect_once(
        tmp_path, symbols=("BTC-USDT",), start_ms=0, end_ms=120000, fetch=fetch
    )
    cursor = json.loads((tmp_path / "CURSOR.json").read_bytes())
    receipt_path = tmp_path / cursor["symbols"]["BTC-USDT"][-1]["path"]
    receipt = json.loads(receipt_path.read_bytes())
    (tmp_path / receipt["body_path"]).write_bytes(b"modified original body")
    with pytest.raises(SourceDataError, match="RAW_HASH"):
        call(tmp_path, 120000)


def test_writer_lock_same_as_old_v2(tmp_path):
    source(tmp_path)
    call(tmp_path, 60000, True)
    with (tmp_path / "collection.lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SourceDataError, match="WRITER_ACTIVE"):
            call(tmp_path, 120000)


def test_wrong_frozen_source_sha_is_blocked(tmp_path):
    source(tmp_path)
    with patch.object(fast, "EXPECTED_V2_SHA", "0" * 64):
        with pytest.raises(SourceDataError, match="FROZEN_V2_SOURCE_MISMATCH"):
            call(tmp_path, 60000, True)


def test_future_timestamp_rejected(tmp_path):
    source(tmp_path)
    call(tmp_path, 60000, True)
    with pytest.raises(SourceDataError, match="UNCLOSED_REQUEST"):
        call(tmp_path, 10**18)


def test_original_v2_tail_witness_rechecked_each_loop(tmp_path):
    source(tmp_path)
    call(tmp_path, 60000, True)
    p = next(tmp_path.glob("requests/BTC-USDT/*.body"))
    p.write_bytes(b"tampered")
    with pytest.raises(SourceDataError, match="RAW_HASH"):
        call(tmp_path, 60000)


def test_no_synthetic_content_on_429(tmp_path):
    source(tmp_path)
    call(tmp_path, 60000, True)
    with pytest.raises(SourceDataError, match="HTTP_STATUS"):
        fast.collect_once(
            tmp_path,
            symbols=("BTC-USDT",),
            start_ms=0,
            end_ms=120000,
            fetch=lambda _: (429, b"busy"),
        )
    assert list(tmp_path.glob("requests/BTC-USDT/*_*.http.json"))


def test_checksum_format_matches_sha256(tmp_path):
    source(tmp_path)
    call(tmp_path, 60000, True)
    cp = json.loads((tmp_path / fast.CHECKPOINT).read_bytes())
    pointers = json.loads((tmp_path / "CURSOR.json").read_bytes())["symbols"][
        "BTC-USDT"
    ]
    assert cp["symbols"]["BTC-USDT"]["prefix_sha256"] == fast.prefix_sha(pointers)
    assert len(cp["symbols"]["BTC-USDT"]["prefix_sha256"]) == 64
