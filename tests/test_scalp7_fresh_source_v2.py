import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest

from backend.research.rebuild.scalp7_fresh_source_v2 import (
    collect_once,
    load_observed_minutes,
    normalize_closed,
)
from backend.research.rebuild.scalp7_source_data_v2 import SourceDataError


def body(timestamps):
    return json.dumps(
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
                for stamp in timestamps
            ],
        }
    ).encode()


def source_fetch(url):
    query = parse_qs(urlparse(url).query)
    start = int(query["startTime"][0])
    end = int(query["endTime"][0]) + 1
    return 200, body(list(range(start, end, 60_000)))


def test_restart_does_not_redownload_completed_source(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return source_fetch(url)

    collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=900_000, fetch=fetch
    )
    result = collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=900_000, fetch=fetch
    )
    assert len(calls) == 1
    assert result["new_requests"] == 0
    collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=1_800_000, fetch=fetch
    )
    frame = load_observed_minutes(tmp_path)["BTC-USDT"]
    assert len(calls) == 2
    assert len(frame) == 30
    assert (frame.received_at_ms > frame.timestamp_ms).all()


def test_gaps_remain_absent_in_observed_minutes(tmp_path):
    def fetch(url):
        return 200, body([0, 120_000])

    collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=180_000, fetch=fetch
    )
    frame = load_observed_minutes(tmp_path)["BTC-USDT"]
    assert frame.timestamp_ms.tolist() == [0, 120_000]
    cursor = json.loads((tmp_path / "CURSOR.json").read_text())
    receipt = json.loads(
        (tmp_path / cursor["symbols"]["BTC-USDT"][0]["path"]).read_text()
    )
    assert receipt["missing_minutes"] == [60_000]
    assert receipt["state"] == "GAP_PRESERVED"


def test_raw_tamper_is_detected_on_restart(tmp_path):
    collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=60_000, fetch=source_fetch
    )
    raw = next(tmp_path.glob("requests/BTC-USDT/*.body"))
    raw.write_bytes(body([60_000]))
    with pytest.raises(SourceDataError, match="FRESH_RAW_HASH"):
        collect_once(
            tmp_path,
            symbols=["BTC-USDT"],
            start_ms=0,
            end_ms=60_000,
            fetch=source_fetch,
        )


def test_new_timeframe_or_symbol_does_not_reuse_identity(tmp_path):
    collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=60_000, fetch=source_fetch
    )
    with pytest.raises(SourceDataError, match="FRESH_IDENTITY_CHANGED"):
        collect_once(
            tmp_path,
            symbols=["ETH-USDT"],
            start_ms=0,
            end_ms=60_000,
            fetch=source_fetch,
        )


@pytest.mark.parametrize("timestamps", [[0, 0], [60_000], [-60_000]])
def test_untrusted_source_rows_rejected(timestamps):
    with pytest.raises((SourceDataError, RuntimeError)):
        normalize_closed(body(timestamps), 0, 60_000, 120_000)


def test_unclosed_row_and_nonzero_code_rejected():
    with pytest.raises(SourceDataError, match="UNCLOSED"):
        normalize_closed(body([0]), 0, 60_000, 59_999)
    with pytest.raises(SourceDataError, match="REJECTED"):
        normalize_closed(b'{"code": 42, "data": []}', 0, 60_000, 60_000)


def test_http_failure_raw_is_saved_before_rejection(tmp_path):
    with pytest.raises(SourceDataError, match="FRESH_HTTP_STATUS"):
        collect_once(
            tmp_path,
            symbols=["BTC-USDT"],
            start_ms=0,
            end_ms=60_000,
            fetch=lambda url: (429, b"rate limited"),
        )
    files = list(tmp_path.glob("requests/BTC-USDT/*.body"))
    assert len(files) == 1 and files[0].read_bytes() == b"rate limited"
    assert not (tmp_path / "CURSOR.json").exists()


def test_cursor_digest_binds_exact_receipt(tmp_path):
    collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=60_000, fetch=source_fetch
    )
    cursor = json.loads((tmp_path / "CURSOR.json").read_text())
    record = cursor["symbols"]["BTC-USDT"][0]
    assert (
        record["sha256"]
        == hashlib.sha256((tmp_path / record["path"]).read_bytes()).hexdigest()
    )


def test_valid_receipt_cannot_be_mislabeled_as_another_symbol(tmp_path):
    collect_once(
        tmp_path,
        symbols=["BTC-USDT", "ETH-USDT"],
        start_ms=0,
        end_ms=60_000,
        fetch=source_fetch,
    )
    path = tmp_path / "CURSOR.json"
    cursor = json.loads(path.read_text())
    cursor["symbols"]["ETH-USDT"] = cursor["symbols"]["BTC-USDT"]
    path.write_text(json.dumps(cursor))
    with pytest.raises(SourceDataError, match="SYMBOL_OR_WINDOW"):
        load_observed_minutes(tmp_path)


def test_valid_receipt_cannot_be_reordered_in_cursor(tmp_path):
    collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=60_000, fetch=source_fetch
    )
    collect_once(
        tmp_path, symbols=["BTC-USDT"], start_ms=0, end_ms=120_000, fetch=source_fetch
    )
    path = tmp_path / "CURSOR.json"
    cursor = json.loads(path.read_text())
    cursor["symbols"]["BTC-USDT"].reverse()
    path.write_text(json.dumps(cursor))
    with pytest.raises(SourceDataError, match="SYMBOL_OR_WINDOW"):
        load_observed_minutes(tmp_path)
