from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.tools import r7a4d_strategy11_continuous_data_collector_v1_1 as repair


def main() -> int:
    last_event = 1_785_427_200_000  # 2026-07-30 16:00 UTC
    no_event_end = 1_785_455_100_000  # 2026-07-30 23:45 UTC
    event_due_end = 1_785_458_700_000  # 2026-07-31 00:45 UTC

    assert repair.funding_event_expected(last_event + 1, no_event_end) is False
    assert repair.funding_event_expected(last_event + 1, event_due_end) is True
    assert repair.first_expected_funding_ms(last_event + 1) == 1_785_456_000_000

    original = repair.collector.request_json
    try:
        repair.collector.request_json = lambda _url: {"code": 0, "data": []}
        rows, endpoint = repair.fetch_funding_gap_aware("BTCUSDT", last_event + 1, no_event_end)
        assert rows == []
        assert endpoint == repair.FUNDING_ENDPOINT

        try:
            repair.fetch_funding_gap_aware("BTCUSDT", last_event + 1, event_due_end)
        except RuntimeError as exc:
            assert str(exc).startswith("EXPECTED_FUNDING_EVENT_MISSING:BTCUSDT:")
        else:
            raise AssertionError("EXPECTED_FUNDING_EVENT_MISSING_NOT_RAISED")

        repair.collector.request_json = lambda _url: {
            "code": 0,
            "data": [{"fundingTime": 1_785_456_000_000, "fundingRate": "0.00012"}],
        }
        rows, _ = repair.fetch_funding_gap_aware("BTCUSDT", last_event + 1, event_due_end)
        assert rows == [{"timestamp_ms": 1_785_456_000_000, "funding_rate": 0.00012}]
    finally:
        repair.collector.request_json = original

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "funding" / "BTCUSDT.json"
        repair._ORIGINAL_ATOMIC_JSON(path, {
            "symbol": "BTCUSDT",
            "rows": [{"timestamp_ms": last_event, "funding_rate": 0.0001}],
            "source": repair.FUNDING_ENDPOINT,
        })
        repair.atomic_json_preserve_funding_source(path, {
            "symbol": "BTCUSDT",
            "rows": [{"timestamp_ms": last_event, "funding_rate": 0.0001}],
            "source": None,
        })
        saved = json.loads(path.read_text())
        assert saved["source"] == repair.FUNDING_ENDPOINT

    assert repair.collector.VERSION == "R7A4D_STRATEGY11_CONTINUOUS_DATA_COLLECTOR_V1"
    print("PASS_CONTINUOUS_FUNDING_GAP_AWARE_AND_IDEMPOTENT_SOURCE_FIXTURE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
