from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "backend" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import r7a4d_integrated_supertrend_bingx_real_oos as target  # noqa: E402


def synthetic_frame(rows: int = 900) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.3, rows))
    open_ = np.concatenate(([close[0]], close[:-1]))
    high = np.maximum(open_, close) + rng.uniform(0.01, 0.4, rows)
    low = np.minimum(open_, close) - rng.uniform(0.01, 0.4, rows)
    return pd.DataFrame(
        {
            "timestamp_ms": np.arange(rows, dtype=np.int64) * target.INTERVAL_MS,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(1.0, 10.0, rows),
        }
    )


def test_15m_contract_and_no_lookahead_geometry() -> None:
    frame = synthetic_frame()
    target.validate(frame, len(frame))
    enriched = target.geometry(frame, warmup=400)

    assert target.INTERVAL == "15m"
    assert target.INTERVAL_MS == 900_000
    assert set(target.GEOMETRY).issubset(enriched.columns)
    assert all(enriched[column].dtype == bool for column in target.GEOMETRY)
    assert not bool(enriched.loc[:399, list(target.GEOMETRY)].to_numpy().any())
    assert target.prefix_check(frame, warmup=400) == 8


def test_timestamp_gap_is_rejected() -> None:
    frame = synthetic_frame(500)
    frame.loc[250:, "timestamp_ms"] += target.INTERVAL_MS
    try:
        target.validate(frame, len(frame))
    except ValueError as exc:
        assert "TIMESTAMP_GAP_OR_WRONG_INTERVAL" in str(exc)
    else:
        raise AssertionError("timestamp gap must fail")
