from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

V1_PATH = Path(__file__).with_name("vwap_revert_150d_durability.py")
FIX_ID = "VWAP150_ZERO_SENTINEL_MANIFEST_ADAPTER_ONLY"


def load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("vwap_revert_150d_durability_v1_wrapped", V1_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("V1_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


v1 = load_v1()
_original_pick_post_rows = v1.pick_post_rows


def fixed_pick_post_rows(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    copied = dict(manifest)
    results: list[Any] = []
    for raw in manifest.get("results") or []:
        if not isinstance(raw, Mapping):
            results.append(raw)
            continue
        row = dict(raw)
        # V1 incorrectly used `value or -1`, which turns valid integer zero into -1.
        # Convert only the two already-verified zero integrity counters to truthy "0"
        # so the original frozen validation logic evaluates int("0") == 0.
        if row.get("missing_interval_count") == 0:
            row["missing_interval_count"] = "0"
        if row.get("duplicate_timestamp_count") == 0:
            row["duplicate_timestamp_count"] = "0"
        results.append(row)
    copied["results"] = results
    return _original_pick_post_rows(copied)


v1.pick_post_rows = fixed_pick_post_rows

# Methodology locks: wrapper changes no market data, owner, strategy, threshold,
# feature gate, exit, cost model, funding rule, window, or promotion authority.
STRATEGY_PARAMETER_CHANGES = 0
FEATURE_GATE_CHANGES = 0
MARKET_DATA_CHANGES = 0
WINDOW_CHANGES = 0


if __name__ == "__main__":
    raise SystemExit(v1.main())
