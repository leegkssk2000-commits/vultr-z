from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from backend.strategy25 import indicator_contract_repair_adapter_v1 as v1


class IndicatorContractRepairV2Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RepairSpec:
    strategy_id: str
    implementation_path: str
    expected_sha256: str
    exact_replacements: tuple[tuple[str, str], ...] = ()
    block_replacements: tuple[tuple[str, str, str], ...] = ()


ANCHOR_SWING_BLOCK = (
    "def _anchor_from_swing(df: pd.DataFrame, lookback: int) -> Tuple[int, int]:\n"
    "    # Contract repair: use confirmed pivots and exclude the signal bar.\n"
    "    reference = df.iloc[-(lookback + 5):-1].copy()\n"
    "    if len(reference) < 7:\n"
    "        reference = df.iloc[:-1].copy()\n"
    "    candidate = reference.iloc[2:-2] if len(reference) >= 5 else reference\n"
    "    low_mask = (\n"
    "        (candidate[\"low\"] <= reference[\"low\"].shift(1).reindex(candidate.index))\n"
    "        & (candidate[\"low\"] <= reference[\"low\"].shift(2).reindex(candidate.index))\n"
    "        & (candidate[\"low\"] < reference[\"low\"].shift(-1).reindex(candidate.index))\n"
    "        & (candidate[\"low\"] < reference[\"low\"].shift(-2).reindex(candidate.index))\n"
    "    )\n"
    "    high_mask = (\n"
    "        (candidate[\"high\"] >= reference[\"high\"].shift(1).reindex(candidate.index))\n"
    "        & (candidate[\"high\"] >= reference[\"high\"].shift(2).reindex(candidate.index))\n"
    "        & (candidate[\"high\"] > reference[\"high\"].shift(-1).reindex(candidate.index))\n"
    "        & (candidate[\"high\"] > reference[\"high\"].shift(-2).reindex(candidate.index))\n"
    "    )\n"
    "    low_candidates = candidate.index[low_mask.fillna(False)]\n"
    "    high_candidates = candidate.index[high_mask.fillna(False)]\n"
    "    fallback = reference.iloc[:-2] if len(reference) > 2 else reference\n"
    "    low_idx = int(low_candidates[-1]) if len(low_candidates) else int(fallback[\"low\"].idxmin())\n"
    "    high_idx = int(high_candidates[-1]) if len(high_candidates) else int(fallback[\"high\"].idxmax())\n"
    "    return low_idx, high_idx\n\n\n"
)


NEW_SPECS: Mapping[str, RepairSpec] = MappingProxyType({
    "anchor_vwap_trend": RepairSpec(
        strategy_id="anchor_vwap_trend",
        implementation_path="backend/strategies/anchor_vwap_trend.py",
        expected_sha256="37712baa33d8ccb8588c4ac7ddf7b17b143d83d4a0050ca164fb9f1655db32e3",
        block_replacements=((
            "def _anchor_from_swing(df: pd.DataFrame, lookback: int) -> Tuple[int, int]:\n",
            "def _vwap_from(df: pd.DataFrame, start_idx: int) -> pd.Series:\n",
            ANCHOR_SWING_BLOCK,
        ),),
    ),
    "grid_rebalance": RepairSpec(
        strategy_id="grid_rebalance",
        implementation_path="backend/strategies/grid_rebalance.py",
        expected_sha256="738e63b45dd8a9f47b826632448a9443b56e7660aaec52725468db93e1d6c29f",
        exact_replacements=(
            (
                "    min_atr_pct: float = 0.10\n    max_atr_pct: float = 3.20\n",
                "    min_atr_pct: float = 0.10\n    max_atr_pct: float = 3.20\n"
                "    max_ema_spread_atr: float = 1.10\n"
                "    max_ema_slope_atr: float = 0.20\n",
            ),
            (
                "    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev\n"
                "    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev\n",
                "    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev\n"
                "    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev\n"
                "    ema_spread_atr = abs(ema_fast - ema_slow) / max(atr_now, 1e-9)\n"
                "    ema_slope_atr = max(abs(ema_fast - ema_fast_prev), abs(ema_slow - ema_slow_prev)) / max(atr_now, 1e-9)\n"
                "    range_regime_ok = (\n"
                "        ema_spread_atr <= cfg.max_ema_spread_atr\n"
                "        and ema_slope_atr <= cfg.max_ema_slope_atr\n"
                "    )\n",
            ),
            (
                "        \"trend_short\": trend_short,\n",
                "        \"trend_short\": trend_short,\n"
                "        \"ema_spread_atr\": round(ema_spread_atr, 6),\n"
                "        \"ema_slope_atr\": round(ema_slope_atr, 6),\n"
                "        \"range_regime_ok\": range_regime_ok,\n",
            ),
            (
                "    if late_chase_block and (long_setup or short_setup):\n",
                "    if not range_regime_ok:\n"
                "        return _build_result(\n"
                "            side=None, action=\"hold\", size=0.0, entry=price, sl=price, tp=price,\n"
                "            pyramiding=cfg.max_pyramiding, why=\"grid_range_regime_block\", skill=\"none\",\n"
                "            confidence=0.0, tags=[\"range_regime_gate\"], indicators=indicators,\n"
                "        )\n\n"
                "    if late_chase_block and (long_setup or short_setup):\n",
            ),
        ),
    ),
    "supertrend_pullback": RepairSpec(
        strategy_id="supertrend_pullback",
        implementation_path="backend/strategies/supertrend_pullback.py",
        expected_sha256="b5398dfce04260422f04a758736d210763dc8c6097eeca953af82a56eb80fe25",
        exact_replacements=((
            "    swing_high = _to_float(df[\"high\"].iloc[-cfg.swing_lookback:].max())\n"
            "    swing_low = _to_float(df[\"low\"].iloc[-cfg.swing_lookback:].min())\n",
            "    # Contract repair: freeze pullback reference before the signal bar.\n"
            "    swing_reference = df.iloc[-(cfg.swing_lookback + 1):-1]\n"
            "    swing_high = _to_float(swing_reference[\"high\"].max())\n"
            "    swing_low = _to_float(swing_reference[\"low\"].min())\n",
        ),),
    ),
})


REPAIR_SPECS: Mapping[str, Any] = MappingProxyType({**dict(v1.REPAIR_SPECS), **dict(NEW_SPECS)})


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _replace_block(source: str, start_marker: str, end_marker: str, replacement: str, strategy_id: str) -> str:
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise IndicatorContractRepairV2Error(f"BLOCK_MARKER_COUNT:{strategy_id}")
    start = source.index(start_marker)
    end = source.index(end_marker, start + len(start_marker))
    return source[:start] + replacement + source[end:]


def transformed_source(root: str | Path, strategy_id: str) -> str:
    if strategy_id in v1.REPAIR_SPECS:
        return v1.transformed_source(root, strategy_id)
    try:
        spec = NEW_SPECS[strategy_id]
    except KeyError as exc:
        raise IndicatorContractRepairV2Error(f"UNKNOWN_REPAIR_STRATEGY:{strategy_id}") from exc

    source_path = Path(root).resolve() / spec.implementation_path
    if not source_path.is_file() or source_path.is_symlink():
        raise IndicatorContractRepairV2Error(f"SOURCE_INVALID:{strategy_id}:{spec.implementation_path}")
    source_bytes = source_path.read_bytes()
    actual_sha = _sha256_bytes(source_bytes)
    if actual_sha != spec.expected_sha256:
        raise IndicatorContractRepairV2Error(
            f"SOURCE_SHA_MISMATCH:{strategy_id}:expected={spec.expected_sha256}:actual={actual_sha}"
        )
    source = source_bytes.decode("utf-8")
    for old, new in spec.exact_replacements:
        count = source.count(old)
        if count != 1:
            raise IndicatorContractRepairV2Error(f"EXACT_REPLACEMENT_COUNT:{strategy_id}:{count}:{old!r}")
        source = source.replace(old, new, 1)
    for start_marker, end_marker, replacement in spec.block_replacements:
        source = _replace_block(source, start_marker, end_marker, replacement, strategy_id)
    compile(source, f"<repair-v2:{strategy_id}>", "exec")
    return source


def repair_manifest() -> tuple[Mapping[str, Any], ...]:
    return tuple(
        MappingProxyType({
            "strategy_id": strategy_id,
            "implementation_path": spec.implementation_path,
            "expected_sha256": spec.expected_sha256,
            "read_only_child": True,
            "canonical_mutated": False,
            "registry_mutated": False,
            "execution_allowed": False,
        })
        for strategy_id, spec in REPAIR_SPECS.items()
    )
