from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping


class IndicatorContractRepairError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RepairSpec:
    strategy_id: str
    implementation_path: str
    expected_sha256: str
    exact_replacements: tuple[tuple[str, str], ...] = ()
    block_replacements: tuple[tuple[str, str, str], ...] = ()


FVG_BLOCK = (
    "    # Contract repair: ICT-style FVG is a three-candle imbalance.\n"
    "    # The current signal bar is excluded so a gap cannot be created and filled on the same bar.\n"
    "    start_idx = max(2, len(df) - cfg.lookback)\n"
    "    gap_idx = None\n"
    "    gap_dir = None\n"
    "    gap_low = None\n"
    "    gap_high = None\n"
    "    gap_size = 0.0\n\n"
    "    for i in range(start_idx, len(df) - 1):\n"
    "        hi_first = _to_float(df[\"high\"].iloc[i - 2])\n"
    "        lo_first = _to_float(df[\"low\"].iloc[i - 2])\n"
    "        hi_third = _to_float(df[\"high\"].iloc[i])\n"
    "        lo_third = _to_float(df[\"low\"].iloc[i])\n"
    "        gap_atr = _to_float(df[\"atr\"].iloc[i], atr_now)\n"
    "        gap_reference = max(_to_float(df[\"close\"].iloc[i], price), 1e-9)\n\n"
    "        up_gap_size = lo_third - hi_first\n"
    "        down_gap_size = lo_first - hi_third\n\n"
    "        if (\n"
    "            lo_third > hi_first\n"
    "            and up_gap_size >= gap_atr * cfg.min_gap_atr\n"
    "            and (up_gap_size / gap_reference) >= cfg.min_gap_pct\n"
    "        ):\n"
    "            gap_idx = i\n"
    "            gap_dir = \"up\"\n"
    "            gap_low = hi_first\n"
    "            gap_high = lo_third\n"
    "            gap_size = up_gap_size\n"
    "        elif (\n"
    "            hi_third < lo_first\n"
    "            and down_gap_size >= gap_atr * cfg.min_gap_atr\n"
    "            and (down_gap_size / gap_reference) >= cfg.min_gap_pct\n"
    "        ):\n"
    "            gap_idx = i\n"
    "            gap_dir = \"down\"\n"
    "            gap_low = hi_third\n"
    "            gap_high = lo_first\n"
    "            gap_size = down_gap_size\n\n"
)

SESSION_RESOLVER_BLOCK = (
    "def _session_name_from_ts(ts_value: Optional[float], tz_name: str, cfg: SessionBiasConfig) -> str:\n"
    "    if ts_value is None:\n"
    "        return \"unknown\"\n\n"
    "    try:\n"
    "        dt_utc = datetime.fromtimestamp(float(ts_value), tz=timezone.utc)\n"
    "        dt = dt_utc.astimezone(ZoneInfo(tz_name)) if ZoneInfo is not None else dt_utc\n"
    "    except Exception:\n"
    "        return \"unknown\"\n\n"
    "    hour = dt.hour\n"
    "    asia_active = cfg.asia_start_hour <= hour < cfg.asia_end_hour\n"
    "    london_active = cfg.london_start_hour <= hour < cfg.london_end_hour\n"
    "    ny_active = cfg.ny_start_hour <= hour < cfg.ny_end_hour\n\n"
    "    if london_active and ny_active:\n"
    "        return \"overlap\"\n"
    "    if asia_active:\n"
    "        return \"asia\"\n"
    "    if london_active:\n"
    "        return \"london\"\n"
    "    if ny_active:\n"
    "        return \"newyork\"\n"
    "    return \"off_session\"\n\n\n"
)

SESSION_BIAS_BLOCK = (
    "    if session_name == \"asia\":\n"
    "        bias_long = trend_long and price >= session_mid\n"
    "        bias_short = trend_short and price <= session_mid\n"
    "        bias_strength = 0.52\n"
    "    elif session_name == \"london\":\n"
    "        bias_long = trend_long\n"
    "        bias_short = trend_short\n"
    "        bias_strength = 0.70\n"
    "    elif session_name == \"newyork\":\n"
    "        bias_long = trend_long and long_break\n"
    "        bias_short = trend_short and short_break\n"
    "        bias_strength = 0.76\n"
    "    elif session_name == \"overlap\":\n"
    "        bias_long = trend_long and long_break\n"
    "        bias_short = trend_short and short_break\n"
    "        bias_strength = 0.82\n"
    "    else:\n"
    "        bias_long = False\n"
    "        bias_short = False\n"
    "        bias_strength = 0.0\n\n"
)


REPAIR_SPECS: Mapping[str, RepairSpec] = MappingProxyType({
    "break_and_continue": RepairSpec(
        strategy_id="break_and_continue",
        implementation_path="backend/strategies/break_and_continue.py",
        expected_sha256="74950c1f68ef9d261a71421590c671532908d003839482409ebfb99a920d832d",
        exact_replacements=((
            "    box = df.iloc[-cfg.box_bars:]\n",
            "    # Contract repair: reference box must be frozen before the signal bar.\n"
            "    box = df.iloc[-(cfg.box_bars + 1):-1]\n",
        ),),
    ),
    "fvg_revert": RepairSpec(
        strategy_id="fvg_revert",
        implementation_path="backend/strategies/fvg_revert.py",
        expected_sha256="d755efdcebf45e0b26e9ec8ff988226d3e85a13789b512ea5f9a705fc579bb54",
        exact_replacements=((
            "    fill_pct = (price - gap_low) / gap_range\n",
            "    # Fill depth is measured from the origin side of the imbalance.\n"
            "    fill_pct = ((gap_high - price) / gap_range) if gap_dir == \"up\" else ((price - gap_low) / gap_range)\n",
        ),),
        block_replacements=((
            "    start_idx = max(1, len(df) - cfg.lookback)\n",
            "    if gap_idx is None or gap_low is None or gap_high is None or gap_dir is None:\n",
            FVG_BLOCK,
        ),),
    ),
    "session_bias": RepairSpec(
        strategy_id="session_bias",
        implementation_path="backend/strategies/session_bias.py",
        expected_sha256="de9314ca72f686c8793a3f0a56b81937302b9a89de4ea11edd3ec33e90efe123",
        exact_replacements=((
            "    recent = df.iloc[-cfg.range_lookback:]\n",
            "    # Contract repair: session reference range is frozen before the signal bar.\n"
            "    recent = df.iloc[-(cfg.range_lookback + 1):-1]\n",
        ),),
        block_replacements=(
            (
                "def _session_name_from_ts(ts_value: Optional[float], tz_name: str, cfg: SessionBiasConfig) -> str:\n",
                "def _payload_session_tz(payload: Optional[Mapping[str, Any]], cfg: SessionBiasConfig) -> str:\n",
                SESSION_RESOLVER_BLOCK,
            ),
            (
                "    if session_name == \"asia\":\n",
                "    long_beam = (\n",
                SESSION_BIAS_BLOCK,
            ),
        ),
    ),
    "sr_levels": RepairSpec(
        strategy_id="sr_levels",
        implementation_path="backend/strategies/sr_levels.py",
        expected_sha256="81961254c685e735d90df418fb9e75d527199017370237efda8614ef74d680f1",
        exact_replacements=((
            "    recent = df.iloc[-cfg.lookback:]\n",
            "    # Contract repair: S/R levels are frozen before the signal bar.\n"
            "    recent = df.iloc[-(cfg.lookback + 1):-1]\n",
        ),),
    ),
})


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _replace_block(source: str, start_marker: str, end_marker: str, replacement: str, strategy_id: str) -> str:
    start_count = source.count(start_marker)
    end_count = source.count(end_marker)
    if start_count != 1 or end_count != 1:
        raise IndicatorContractRepairError(
            f"BLOCK_MARKER_COUNT:{strategy_id}:start={start_count}:end={end_count}"
        )
    start = source.index(start_marker)
    end = source.index(end_marker, start + len(start_marker))
    if end <= start:
        raise IndicatorContractRepairError(f"BLOCK_MARKER_ORDER:{strategy_id}")
    return source[:start] + replacement + source[end:]


def transformed_source(root: str | Path, strategy_id: str) -> str:
    try:
        spec = REPAIR_SPECS[strategy_id]
    except KeyError as exc:
        raise IndicatorContractRepairError(f"UNKNOWN_REPAIR_STRATEGY:{strategy_id}") from exc

    root_path = Path(root).resolve()
    source_path = root_path / spec.implementation_path
    if not source_path.is_file() or source_path.is_symlink():
        raise IndicatorContractRepairError(f"SOURCE_INVALID:{strategy_id}:{spec.implementation_path}")

    source_bytes = source_path.read_bytes()
    actual_sha = _sha256_bytes(source_bytes)
    if actual_sha != spec.expected_sha256:
        raise IndicatorContractRepairError(
            f"SOURCE_SHA_MISMATCH:{strategy_id}:expected={spec.expected_sha256}:actual={actual_sha}"
        )

    source = source_bytes.decode("utf-8")
    for old, new in spec.exact_replacements:
        count = source.count(old)
        if count != 1:
            raise IndicatorContractRepairError(f"EXACT_REPLACEMENT_COUNT:{strategy_id}:{count}:{old!r}")
        source = source.replace(old, new, 1)

    for start_marker, end_marker, replacement in spec.block_replacements:
        source = _replace_block(source, start_marker, end_marker, replacement, strategy_id)

    compile(source, f"<repair:{strategy_id}>", "exec")
    return source


def load_repaired_namespace(root: str | Path, strategy_id: str) -> dict[str, Any]:
    source = transformed_source(root, strategy_id)
    namespace: dict[str, Any] = {
        "__name__": f"backend.strategy25.repaired_{strategy_id}_v1",
        "__file__": str(Path(root).resolve() / REPAIR_SPECS[strategy_id].implementation_path),
        "__package__": "backend.strategies",
    }
    exec(compile(source, namespace["__file__"], "exec"), namespace, namespace)
    return namespace


def load_repaired_strategy(root: str | Path, strategy_id: str) -> Callable[..., Any]:
    namespace = load_repaired_namespace(root, strategy_id)
    strategy = namespace.get("strategy")
    if not callable(strategy):
        raise IndicatorContractRepairError(f"STRATEGY_CALLABLE_MISSING:{strategy_id}")
    return strategy


def repair_manifest() -> tuple[Mapping[str, Any], ...]:
    return tuple(
        MappingProxyType({
            "strategy_id": spec.strategy_id,
            "implementation_path": spec.implementation_path,
            "expected_sha256": spec.expected_sha256,
            "read_only_child": True,
            "canonical_mutated": False,
            "execution_allowed": False,
        })
        for spec in REPAIR_SPECS.values()
    )
