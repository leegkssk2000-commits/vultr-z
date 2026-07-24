from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_second_nonoverlap_oos as target


def _parsed_timestamp_ms(series: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(series, utc=True, errors="raise")
    return timestamps.map(
        lambda value: int(pd.Timestamp(value).value // 1_000_000)
    ).astype("int64")


def _canonical_timestamp_ms(frame: pd.DataFrame, path: Path) -> pd.Series:
    if "timestamp_ms" in frame.columns:
        numeric = pd.to_numeric(frame["timestamp_ms"], errors="raise")
        if numeric.isna().any():
            raise ValueError(f"FIRST_WINDOW_TIMESTAMP_MS_NULL:{path}")
        values = numeric.astype("int64")
    elif "timestamp" in frame.columns:
        values = _parsed_timestamp_ms(frame["timestamp"])
    else:
        raise ValueError(f"FIRST_WINDOW_TIMESTAMP_COLUMN_MISSING:{path}")

    if len(values) < 2:
        raise ValueError(f"FIRST_WINDOW_TOO_SHORT:{path}:{len(values)}")
    if values.duplicated().any():
        duplicate = int(values[values.duplicated()].iloc[0])
        raise ValueError(f"FIRST_WINDOW_DUPLICATE_TIMESTAMP:{path}:{duplicate}")

    deltas = values.diff().dropna().astype("int64")
    bad = deltas[deltas != source.INTERVAL_MS]
    if not bad.empty:
        index = int(bad.index[0])
        previous_ms = int(values.iloc[index - 1])
        current_ms = int(values.iloc[index])
        delta_ms = int(bad.iloc[0])
        raise ValueError(
            "FIRST_WINDOW_GAP_OR_WRONG_INTERVAL:"
            f"{path}:row={index}:prev_ms={previous_ms}:current_ms={current_ms}:"
            f"delta_ms={delta_ms}:expected_ms={source.INTERVAL_MS}"
        )

    if "timestamp" in frame.columns and "timestamp_ms" in frame.columns:
        parsed_ms = _parsed_timestamp_ms(frame["timestamp"])
        mismatch = parsed_ms != values
        if mismatch.any():
            index = int(mismatch[mismatch].index[0])
            raise ValueError(
                "FIRST_WINDOW_TIMESTAMP_PARITY_MISMATCH:"
                f"{path}:row={index}:timestamp_ms={int(values.iloc[index])}:"
                f"parsed_timestamp_ms={int(parsed_ms.iloc[index])}"
            )

    return values


def _window_contract(path: Path) -> Dict[str, int]:
    if not path.is_file():
        raise FileNotFoundError(f"FIRST_WINDOW_CSV_NOT_FOUND:{path}")

    header = pd.read_csv(path, nrows=0)
    usecols = [
        column
        for column in ("timestamp_ms", "timestamp")
        if column in header.columns
    ]
    if not usecols:
        raise ValueError(f"FIRST_WINDOW_TIMESTAMP_COLUMN_MISSING:{path}")

    frame = pd.read_csv(path, usecols=usecols)
    if frame.empty:
        raise ValueError(f"FIRST_WINDOW_EMPTY:{path}")

    timestamp_ms = _canonical_timestamp_ms(frame, path)
    rows = int(len(timestamp_ms))
    start_ms = int(timestamp_ms.iloc[0])
    end_ms = int(timestamp_ms.iloc[-1])
    calculated_rows = ((end_ms - start_ms) // source.INTERVAL_MS) + 1
    if calculated_rows != rows:
        raise ValueError(
            f"FIRST_WINDOW_ROW_CONTRACT:{path}:{calculated_rows}!={rows}"
        )

    print(
        "FIRST_WINDOW_CONTRACT_PASS"
        f"|symbol_file={path.name}|rows={rows}|start_ms={start_ms}|"
        f"end_ms={end_ms}|interval_ms={source.INTERVAL_MS}"
    )
    return {"rows": rows, "start_ms": start_ms, "end_ms": end_ms}


def main() -> int:
    if source.INTERVAL != "15m" or source.INTERVAL_MS != 900_000:
        raise RuntimeError(
            f"SOURCE_INTERVAL_CONTRACT_INVALID:{source.INTERVAL}:{source.INTERVAL_MS}"
        )
    if not math.isfinite(float(source.INTERVAL_MS)):
        raise RuntimeError("SOURCE_INTERVAL_NONFINITE")

    target._window_contract = _window_contract
    print("STATE=R7A4D_SECOND_NONOVERLAP_TIMESTAMP_CONTRACT_FIX_ACTIVE")
    return target.main()


if __name__ == "__main__":
    raise SystemExit(main())
