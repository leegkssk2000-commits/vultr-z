"""BingX 100410 is a saved transient rejection, never an accepted candle."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest

from backend.research.rebuild import scalp7_fresh_source_v2 as v2
from backend.research.rebuild import scalp7_fresh_source_v2_incremental as inc
from backend.research.rebuild.scalp7_source_data_v2 import SourceDataError


def valid(url: str) -> tuple[int, bytes]:
    q = parse_qs(urlparse(url).query)
    first = int(q["startTime"][0])
    last = int(q["endTime"][0]) + 1
    body = {
        "code": 0,
        "data": [
            {
                "time": t,
                "open": "10",
                "high": "12",
                "low": "9",
                "close": "11",
                "volume": "3",
            }
            for t in range(first, last, 60000)
        ],
    }
    return 200, json.dumps(body).encode()


def boot(tmp_path):
    v2.collect_once(
        tmp_path, symbols=("BTC-USDT",), start_ms=0, end_ms=60000, fetch=valid
    )
    inc.collect_once(
        tmp_path,
        symbols=("BTC-USDT",),
        start_ms=0,
        end_ms=60000,
        fetch=valid,
        bootstrap_prior_v2=True,
    )


def test_transient_100410_saves_body_but_never_commits(tmp_path):
    boot(tmp_path)
    cursor = (tmp_path / "CURSOR.json").read_bytes()
    rejected = json.dumps({"code": 100410, "msg": "please retry later"}).encode()
    with pytest.raises(SourceDataError, match="TRANSIENT_100410"):
        inc.collect_once(
            tmp_path,
            symbols=("BTC-USDT",),
            start_ms=0,
            end_ms=120000,
            fetch=lambda _: (200, rejected),
        )
    assert (tmp_path / "CURSOR.json").read_bytes() == cursor
    assert any(
        p.read_bytes() == rejected
        for p in (tmp_path / "requests/BTC-USDT").glob("*.body")
    )
    result = inc.collect_once(
        tmp_path, symbols=("BTC-USDT",), start_ms=0, end_ms=120000, fetch=valid
    )
    assert result["new_requests"] == 1
    assert v2.load_observed_minutes(tmp_path)["BTC-USDT"].timestamp_ms.tolist() == [
        0,
        60000,
    ]


def test_other_rejection_fails_closed(tmp_path):
    boot(tmp_path)
    with pytest.raises(SourceDataError, match="FRESH_SOURCE_RESPONSE_REJECTED"):
        inc.collect_once(
            tmp_path,
            symbols=("BTC-USDT",),
            start_ms=0,
            end_ms=120000,
            fetch=lambda _: (200, b'{"code": 100500, "msg": "different error"}'),
        )


def test_malformed_body_not_relabeled_transient(tmp_path):
    boot(tmp_path)
    with pytest.raises(ValueError, match="Expecting value"):
        inc.collect_once(
            tmp_path,
            symbols=("BTC-USDT",),
            start_ms=0,
            end_ms=120000,
            fetch=lambda _: (200, b"not valid json"),
        )


def test_main_retries_only_100410_and_obeys_bounded_exit(tmp_path, capsys):
    def fail(*args, **kwargs):
        raise SourceDataError("INCREMENTAL_UPSTREAM_TRANSIENT_100410")

    with patch.object(inc, "collect_once", side_effect=fail), patch.object(
        inc.time, "monotonic", side_effect=[10, 20]
    ):
        with patch(
            "sys.argv",
            [
                "collector",
                "--out",
                str(tmp_path),
                "--start-ms",
                "0",
                "--max-seconds",
                "5",
            ],
        ):
            assert inc.main() == 0
    raw = capsys.readouterr().out
    msg = json.loads(raw)
    assert msg["state"] == "HOLD_TRANSIENT_PROVIDER_100410_RAW_SAVED"
    assert msg["committed_failed_response_as_candle"] is False
    assert msg["order_authority"] == "BLOCKED"
