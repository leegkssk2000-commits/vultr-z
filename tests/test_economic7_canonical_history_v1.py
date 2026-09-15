from __future__ import annotations

import gzip
import json
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from backend.research.rebuild import economic7_canonical_history_v1 as history

START = history.parse_utc("2025-09-15T00:00:00Z")


def source_row(ts: int, **overrides: Any) -> dict[str, Any]:
    return {
        "time": ts,
        "open": "10",
        "high": "12",
        "low": "9",
        "close": "11",
        "volume": "2",
        **overrides,
    }


def fake_fetch(url: str) -> tuple[int, bytes]:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["timeZone"] == ["0"]
    start = int(query["startTime"][0])
    end = int(query["endTime"][0]) + 1
    rows = [source_row(ts) for ts in range(start, end, history.MINUTE_MS)]
    return 200, history.json_bytes({"code": 0, "data": rows})


def test_timezone_and_grid_are_explicit() -> None:
    assert history.parse_utc("2025-09-15T00:00:00+00:00") == START
    for value in (
        "2025-09-15T00:00:00",
        "2025-09-15T00:00:00+02:00",
        "2025-09-15T00:00:01Z",
    ):
        with pytest.raises(history.HistoryError):
            history.parse_utc(value)


def test_missing_volume_and_positional_schema_never_infer() -> None:
    row = source_row(START)
    del row["volume"]
    with pytest.raises(history.HistoryError, match="MISSING_NAMED_FIELDS:volume"):
        history.normalize_row(row)
    with pytest.raises(history.HistoryError, match="NAMED_MAPPING_REQUIRED"):
        history.normalize_row([START, 10, 12, 9, 11, 2])


@pytest.mark.parametrize("value", [None, "NaN", "Infinity", "-1", True])
def test_invalid_volume_is_rejected(value: Any) -> None:
    with pytest.raises(history.HistoryError):
        history.normalize_row(source_row(START, volume=value))


def test_invalid_ohlc_and_timestamp_alias_are_rejected() -> None:
    with pytest.raises(history.HistoryError, match="OHLC_HIGH_INVALID"):
        history.normalize_row(source_row(START, high="8"))
    with pytest.raises(history.HistoryError, match="CONFLICTING_TIMESTAMP_ALIASES"):
        history.normalize_row(source_row(START, openTime=START + history.MINUTE_MS))
    with pytest.raises(history.HistoryError, match="OFF_UTC_MINUTE_GRID"):
        history.normalize_row(source_row(START + 1))


def test_gap_and_both_duplicate_types_rejected() -> None:
    for rows, expected in [
        ([source_row(START)], "HISTORY_GAP"),
        ([source_row(START), source_row(START)], "DUPLICATE_TIMESTAMP"),
        ([source_row(START), source_row(START, close="10")], "CONFLICTING_DUPLICATE"),
    ]:
        with pytest.raises(history.HistoryError, match=expected):
            history.response_rows(
                history.json_bytes({"code": 0, "data": rows}),
                START,
                START + 2 * history.MINUTE_MS,
            )


def test_daily_999_chunk_windows_do_not_overlap() -> None:
    windows = history.request_windows(START, START + history.DAY_MS)
    assert windows == [
        (START, START + 999 * history.MINUTE_MS),
        (START + 999 * history.MINUTE_MS, START + history.DAY_MS),
    ]


def test_aggregation_requires_complete_epoch_aligned_buckets() -> None:
    rows = [
        history.normalize_row(source_row(ts))
        for ts in range(START, START + 60 * history.MINUTE_MS, history.MINUTE_MS)
    ]
    for minutes, count in [(15, 4), (30, 2), (60, 1)]:
        aggregate, incomplete = history.aggregate_rows(rows, minutes)
        assert len(aggregate) == count and not incomplete
        assert aggregate[0]["volume"] == str(2 * minutes)
    aggregate, incomplete = history.aggregate_rows(rows[1:], 15)
    assert len(aggregate) == 3 and incomplete == [START]
    aggregate, incomplete = history.aggregate_rows(rows[:-1], 60)
    assert aggregate == [] and incomplete == [START]
    with pytest.raises(history.HistoryError, match="AGGREGATION_DUPLICATE"):
        history.aggregate_rows([rows[0], rows[0]], 15)


def test_raw_response_survives_json_failure(tmp_path: Path) -> None:
    body = b"source returned malformed JSON"
    result = history.collect(
        out=tmp_path,
        symbols=["BTC-USDT"],
        start_ms=START,
        end_ms=START + history.MINUTE_MS,
        max_requests=1,
        fetch=lambda _: (200, body),
    )
    assert result["state"] == "HOLD_SOURCE_INTEGRITY"
    assert next(tmp_path.glob("requests/*/*.body")).read_bytes() == body
    receipt = json.loads(next(tmp_path.glob("requests/*/*.receipt.json")).read_bytes())
    assert receipt["body_sha256"] == history.sha_bytes(body)
    assert not list(tmp_path.glob("1m/*/*.gz"))


def test_empty_unsupported_history_and_http_failure_are_preserved(
    tmp_path: Path,
) -> None:
    for name, status, payload, reason in [
        ("empty", 200, b'{"code":0,"data":[]}', "HISTORY_UNAVAILABLE"),
        ("http", 429, b'{"code":429}', "SOURCE_HTTP_STATUS:429"),
    ]:

        def fetch(
            _url: str, response_status: int = status, response_payload: bytes = payload
        ) -> tuple[int, bytes]:
            return response_status, response_payload

        out = tmp_path / name
        result = history.collect(
            out=out,
            symbols=["BTC-USDT"],
            start_ms=START,
            end_ms=START + history.MINUTE_MS,
            fetch=fetch,
        )
        assert result["state"] == "HOLD_SOURCE_INTEGRITY"
        assert reason in result["failures_or_limit"][0]["reason"]
        assert next(out.glob("requests/*/*.body")).read_bytes() == payload


def test_bounded_resume_reuses_raw_and_has_immutable_output(tmp_path: Path) -> None:
    first = history.collect(
        out=tmp_path,
        symbols=["BTC-USDT"],
        start_ms=START,
        end_ms=START + history.DAY_MS,
        max_requests=1,
        fetch=fake_fetch,
    )
    assert first["state"] == "PARTIAL_REQUEST_LIMIT"
    first_body = next(tmp_path.glob("requests/*/*.body"))
    first_hash = history.sha_bytes(first_body.read_bytes())
    second = history.collect(
        out=tmp_path,
        symbols=["BTC-USDT"],
        start_ms=START,
        end_ms=START + history.DAY_MS,
        max_requests=1,
        fetch=fake_fetch,
    )
    assert second["data_integrity_complete"] is True
    assert second["new_requests_used"] == 1
    assert second["source_responses_reused"] == 1
    assert second["volume_unit"] == "UNKNOWN"
    assert second["promotion_authority"] is False
    assert history.sha_bytes(first_body.read_bytes()) == first_hash
    rows = gzip.decompress(next(tmp_path.glob("15m/*/*.gz")).read_bytes()).splitlines()
    assert len(rows) == 97
    third = history.collect(
        out=tmp_path,
        symbols=["BTC-USDT"],
        start_ms=START,
        end_ms=START + history.DAY_MS,
        max_requests=1,
        fetch=lambda _: (_ for _ in ()).throw(AssertionError("network repeated")),
    )
    assert third["new_requests_used"] == 0
    first_body.write_bytes(b"corrupt")
    with pytest.raises(history.HistoryError, match="SOURCE_BODY_HASH_MISMATCH"):
        history.collect(
            out=tmp_path,
            symbols=["BTC-USDT"],
            start_ms=START,
            end_ms=START + history.DAY_MS,
            fetch=fake_fetch,
        )


def test_changed_range_does_not_overwrite_freeze(tmp_path: Path) -> None:
    history.collect(
        out=tmp_path,
        symbols=["BTC-USDT"],
        start_ms=START,
        end_ms=START + history.MINUTE_MS,
        fetch=fake_fetch,
    )
    with pytest.raises(history.HistoryError, match="IMMUTABLE_CONFLICT:FREEZE.json"):
        history.collect(
            out=tmp_path,
            symbols=["BTC-USDT"],
            start_ms=START,
            end_ms=START + 2 * history.MINUTE_MS,
            fetch=fake_fetch,
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("artifacts", [], "REQUIRED_ARTIFACT_SET"),
        ("source_receipts", [], "REQUIRED_SOURCE_CHUNKS"),
        ("rows_1m", 0, "IDENTITY_OR_COVERAGE"),
        ("expected_rows_1m", 0, "IDENTITY_OR_COVERAGE"),
        ("gap_count", 1, "IDENTITY_OR_COVERAGE"),
    ],
)
def test_rehashed_daily_receipt_cannot_fabricate_coverage(
    tmp_path: Path, field: str, value: Any, reason: str
) -> None:
    history.collect(
        out=tmp_path,
        symbols=["BTC-USDT"],
        start_ms=START,
        end_ms=START + 15 * history.MINUTE_MS,
        fetch=fake_fetch,
    )
    path = next(tmp_path.glob("daily_receipts/*/*.json"))
    receipt = json.loads(path.read_bytes())
    receipt[field] = value
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = history.sha_bytes(history.json_bytes(receipt))
    path.write_bytes(history.json_bytes(receipt))
    with pytest.raises(history.HistoryError, match=reason):
        history.collect(
            out=tmp_path,
            symbols=["BTC-USDT"],
            start_ms=START,
            end_ms=START + 15 * history.MINUTE_MS,
            fetch=fake_fetch,
        )


def test_daily_receipt_self_hash_is_required(tmp_path: Path) -> None:
    history.collect(
        out=tmp_path,
        symbols=["BTC-USDT"],
        start_ms=START,
        end_ms=START + 15 * history.MINUTE_MS,
        fetch=fake_fetch,
    )
    path = next(tmp_path.glob("daily_receipts/*/*.json"))
    receipt = json.loads(path.read_bytes())
    receipt["rows_1m"] = 1
    path.write_bytes(history.json_bytes(receipt))
    with pytest.raises(history.HistoryError, match="SELF_HASH"):
        history.collect(
            out=tmp_path,
            symbols=["BTC-USDT"],
            start_ms=START,
            end_ms=START + 15 * history.MINUTE_MS,
            fetch=fake_fetch,
        )


def test_normalized_chunk_is_checked_against_hash_and_source(tmp_path: Path) -> None:
    history.collect(
        out=tmp_path,
        symbols=["BTC-USDT"],
        start_ms=START,
        end_ms=START + 15 * history.MINUTE_MS,
        fetch=fake_fetch,
    )
    normalized_path = next(tmp_path.glob("normalized_chunks/*/*.csv.gz"))
    normalized_path.write_bytes(history.csv_gzip([]))
    arguments: dict[str, Any] = {
        "out": tmp_path,
        "symbols": ["BTC-USDT"],
        "start_ms": START,
        "end_ms": START + 15 * history.MINUTE_MS,
        "fetch": fake_fetch,
    }
    with pytest.raises(history.HistoryError, match="NORMALIZED_CHUNK_HASH"):
        history.collect(**arguments)
    path = next(tmp_path.glob("daily_receipts/*/*.json"))
    receipt = json.loads(path.read_bytes())
    receipt["source_receipts"][0]["normalized_sha256"] = history.sha_bytes(
        normalized_path.read_bytes()
    )
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = history.sha_bytes(history.json_bytes(receipt))
    path.write_bytes(history.json_bytes(receipt))
    with pytest.raises(history.HistoryError, match="NORMALIZED_CHUNK_SOURCE"):
        history.collect(**arguments)
