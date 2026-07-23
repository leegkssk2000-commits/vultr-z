#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd


SPEC_PATH = "research/supertrend_flip_authentic_contract_and_child_spec_v1.json"
CHILD_PATH = "backend/strategies/authentic/supertrend_flip_authentic.py"
PARENT_PATH = "backend/strategies/supertrend_pullback.py"
REGISTRY_PATH = Path("backend/strategy25/canonical_strategy_registry_v1.json")
CONFIG_PATH = Path("backend/strategy25/canonical_strategy25_config_v1.json")
PRIOR_RUNTIME = Path("runtime/r7a4d2_supertrend_authentic_contract_and_child_spec/supertrend_authentic_contract_and_child_spec_verification_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_supertrend_authentic_child_implementation_and_formula_fixtures")
OUTPUT_JSON = OUTPUT_DIR / "supertrend_authentic_child_formula_fixture_verification_v1.json"

EXPECTED_PARENT_SHA256 = "b5398dfce04260422f04a758736d210763dc8c6097eeca953af82a56eb80fe25"
EXPECTED_FIXTURE_CLASSES = {
    "ATR_WARMUP_AND_RMA_SEED",
    "MONOTONIC_UPTREND",
    "MONOTONIC_DOWNTREND",
    "SINGLE_UP_FLIP",
    "SINGLE_DOWN_FLIP",
    "WHIPSAW_MULTI_FLIP",
    "GAP_ACROSS_BAND",
    "EQUAL_BAND_BOUNDARY",
    "MISSING_OR_NONFINITE_INPUT_FAIL_CLOSED",
}
FORBIDDEN_IDENTIFIERS = {
    "ema",
    "pullback",
    "reclaim",
    "beam",
    "scale_in",
    "dip_add",
    "pyramiding",
    "take_profit",
    "profit_target",
}


def git_show(root: Path, sha: str, path: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{sha}:{path}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"GIT_SHOW_FAILED:{path}:{proc.stderr.decode('utf-8', errors='replace').strip()}")
    return proc.stdout


def git_json(root: Path, sha: str, path: str) -> Dict[str, Any]:
    value = json.loads(git_show(root, sha, path).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def local_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(paths: Iterable[Path]) -> Dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def atomic_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def import_module_from_bytes(source: bytes, directory: Path):
    module_path = directory / "supertrend_flip_authentic.py"
    module_path.write_bytes(source)
    spec = importlib.util.spec_from_file_location("supertrend_flip_authentic_fixture_target", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_bars(closes: List[float], *, gap_open: Dict[int, float] | None = None) -> pd.DataFrame:
    rows: List[Dict[str, float | int]] = []
    previous = float(closes[0])
    gap_open = gap_open or {}
    for index, close in enumerate(closes):
        close_value = float(close)
        open_value = float(gap_open.get(index, previous if index else close_value))
        high = max(open_value, close_value) + 0.5
        low = min(open_value, close_value) - 0.5
        rows.append(
            {
                "ts": 1_780_000_000_000 + index * 300_000,
                "open": open_value,
                "high": high,
                "low": low,
                "close": close_value,
            }
        )
        previous = close_value
    return pd.DataFrame(rows)


def reference_true_range(frame: pd.DataFrame) -> List[float]:
    result: List[float] = []
    previous_close: float | None = None
    for row in frame.itertuples(index=False):
        high = float(row.high)
        low = float(row.low)
        close = float(row.close)
        values = [high - low]
        if previous_close is not None:
            values.extend([abs(high - previous_close), abs(low - previous_close)])
        result.append(max(values))
        previous_close = close
    return result


def reference_rma(values: List[float], length: int) -> List[float]:
    result = [float("nan")] * len(values)
    if len(values) < length:
        return result
    previous = sum(values[:length]) / length
    result[length - 1] = previous
    for index in range(length, len(values)):
        previous = ((previous * (length - 1)) + values[index]) / length
        result[index] = previous
    return result


def reference_supertrend(frame: pd.DataFrame, length: int = 10, factor: float = 3.0) -> Dict[str, List[float]]:
    tr = reference_true_range(frame)
    atr = reference_rma(tr, length)
    count = len(frame)
    basic_upper = [float("nan")] * count
    basic_lower = [float("nan")] * count
    final_upper = [float("nan")] * count
    final_lower = [float("nan")] * count
    direction = [float("nan")] * count
    line = [float("nan")] * count
    closes = [float(value) for value in frame["close"].tolist()]

    seed = length - 1
    if count <= seed:
        return {
            "true_range": tr,
            "atr": atr,
            "basic_upper": basic_upper,
            "basic_lower": basic_lower,
            "final_upper": final_upper,
            "final_lower": final_lower,
            "direction": direction,
            "supertrend_line": line,
        }

    for index in range(seed, count):
        midpoint = (float(frame["high"].iloc[index]) + float(frame["low"].iloc[index])) / 2.0
        basic_upper[index] = midpoint + factor * atr[index]
        basic_lower[index] = midpoint - factor * atr[index]

    final_upper[seed] = basic_upper[seed]
    final_lower[seed] = basic_lower[seed]
    direction[seed] = -1.0
    line[seed] = final_upper[seed]

    for index in range(seed + 1, count):
        upper_now = basic_upper[index]
        lower_now = basic_lower[index]
        final_upper[index] = (
            upper_now
            if upper_now < final_upper[index - 1] or closes[index - 1] > final_upper[index - 1]
            else final_upper[index - 1]
        )
        final_lower[index] = (
            lower_now
            if lower_now > final_lower[index - 1] or closes[index - 1] < final_lower[index - 1]
            else final_lower[index - 1]
        )
        if int(direction[index - 1]) == -1:
            direction[index] = 1.0 if closes[index] > final_upper[index] else -1.0
        else:
            direction[index] = -1.0 if closes[index] < final_lower[index] else 1.0
        line[index] = final_lower[index] if int(direction[index]) == 1 else final_upper[index]

    return {
        "true_range": tr,
        "atr": atr,
        "basic_upper": basic_upper,
        "basic_lower": basic_lower,
        "final_upper": final_upper,
        "final_lower": final_lower,
        "direction": direction,
        "supertrend_line": line,
    }


def numeric_equal(left: float, right: float, tolerance: float) -> bool:
    if math.isnan(left) and math.isnan(right):
        return True
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def parity_check(module: Any, frame: pd.DataFrame, *, tolerance: float) -> Tuple[bool, float]:
    actual = module.compute_supertrend(frame)
    expected = reference_supertrend(frame)
    maximum_error = 0.0
    for column, expected_values in expected.items():
        actual_values = [float(value) for value in actual[column].tolist()]
        if len(actual_values) != len(expected_values):
            return False, float("inf")
        for left, right in zip(actual_values, expected_values):
            if math.isnan(left) and math.isnan(right):
                continue
            error = abs(left - right)
            maximum_error = max(maximum_error, error)
            if not numeric_equal(left, right, tolerance):
                return False, maximum_error
    return True, maximum_error


def raw_flip_counts(indicator: pd.DataFrame) -> Tuple[int, int]:
    up = int(indicator["flip_up"].sum())
    down = int(indicator["flip_down"].sum())
    return up, down


def ast_forbidden_identifiers(source: bytes) -> List[str]:
    tree = ast.parse(source.decode("utf-8"), filename=CHILD_PATH)
    found: set[str] = set()
    for node in ast.walk(tree):
        name: str | None = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        if name:
            lowered = name.lower()
            for forbidden in FORBIDDEN_IDENTIFIERS:
                if lowered == forbidden or lowered.startswith(forbidden + "_") or lowered.endswith("_" + forbidden):
                    found.add(name)
    return sorted(found)


def fixture_frames() -> Dict[str, pd.DataFrame]:
    flat = [100.0 + ((index % 3) - 1) * 0.15 for index in range(16)]
    monotonic_up = [100.0 + index * 1.6 for index in range(34)]
    monotonic_down = [150.0 - index * 1.6 for index in range(34)]
    single_up = flat + [112.0, 120.0, 122.0, 124.0, 126.0, 128.0]
    single_down = flat + [112.0, 122.0, 124.0, 126.0, 110.0, 92.0, 86.0, 82.0]
    whipsaw = flat + [122.0, 126.0, 82.0, 78.0, 124.0, 128.0, 80.0, 76.0, 126.0, 130.0]
    gap = flat + [100.0, 101.0, 132.0, 134.0, 136.0]
    return {
        "ATR_WARMUP_AND_RMA_SEED": make_bars([100.0 + index * 0.4 for index in range(18)]),
        "MONOTONIC_UPTREND": make_bars(monotonic_up),
        "MONOTONIC_DOWNTREND": make_bars(monotonic_down),
        "SINGLE_UP_FLIP": make_bars(single_up),
        "SINGLE_DOWN_FLIP": make_bars(single_down),
        "WHIPSAW_MULTI_FLIP": make_bars(whipsaw),
        "GAP_ACROSS_BAND": make_bars(gap, gap_open={18: 130.0}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    blockers: List[str] = []
    fixture_results: Dict[str, Dict[str, Any]] = {}

    try:
        spec = git_json(root, args.target_sha, SPEC_PATH)
        child_source = git_show(root, args.target_sha, CHILD_PATH)
        parent_source = git_show(root, args.target_sha, PARENT_PATH)
    except Exception as exc:
        print("STATE=HOLD_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES_INPUT")
        print("BLOCKERS=" + json.dumps([f"GIT_OBJECT_INPUT_ERROR:{type(exc).__name__}:{exc}"]))
        print("RC=2")
        return 2

    protected_paths = [
        root / PARENT_PATH,
        root / REGISTRY_PATH,
        root / CONFIG_PATH,
        root / PRIOR_RUNTIME,
    ]
    before = snapshot(protected_paths)

    if spec.get("schema") != "r7a4d2_supertrend_flip_authentic_contract_and_child_spec_v1":
        blockers.append("SPEC_SCHEMA_INVALID")
    if spec.get("next_stage") != "R7.A4D2_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES":
        blockers.append("SPEC_STAGE_TRANSITION_INVALID")
    if sha256_bytes(parent_source) != EXPECTED_PARENT_SHA256:
        blockers.append("LEGACY_PARENT_GIT_OBJECT_HASH_MISMATCH")
    if b"backend.engine" in child_source or b"LBotStrategy" in child_source:
        blockers.append("CHILD_EXECUTION_ADAPTER_COUPLING_FORBIDDEN")

    forbidden = ast_forbidden_identifiers(child_source)
    if forbidden:
        blockers.append("LEGACY_ONLY_IDENTIFIERS_PRESENT:" + ",".join(forbidden))

    with tempfile.TemporaryDirectory(prefix="r7a4d2-supertrend-authentic-") as temporary:
        module = import_module_from_bytes(child_source, Path(temporary))
        expected_intents = {
            "HOLD",
            "ENTER_LONG",
            "ENTER_SHORT",
            "EXIT_LONG",
            "EXIT_SHORT",
            "REVERSE_TO_LONG",
            "REVERSE_TO_SHORT",
        }
        if set(module.ALLOWED_INTENTS) != expected_intents:
            blockers.append("BIDIRECTIONAL_INTENT_SET_INVALID")
        if module.SupertrendFlipAuthenticConfig().atr_length != 10:
            blockers.append("ATR_LENGTH_INVALID")
        if not math.isclose(module.SupertrendFlipAuthenticConfig().factor, 3.0, rel_tol=0.0, abs_tol=0.0):
            blockers.append("SUPERTREND_FACTOR_INVALID")

        frames = fixture_frames()
        tolerance = float(spec.get("verification_plan", {}).get("numeric_tolerance", 1e-10))
        for fixture_class, frame in frames.items():
            parity, maximum_error = parity_check(module, frame, tolerance=tolerance)
            indicator = module.compute_supertrend(frame)
            up_count, down_count = raw_flip_counts(indicator)
            replay = module.replay_flip_intents(
                frame,
                symbol="BTCUSDT",
                timeframe="5m",
                replay_fold_id="fixture",
            )
            emitted = int(replay["flip_event_count"])
            if not parity:
                blockers.append(f"FORMULA_PARITY_FAIL:{fixture_class}")
            if emitted != up_count + down_count:
                blockers.append(f"FLIP_INTENT_COUNT_MISMATCH:{fixture_class}")
            if replay.get("short_intent_suppressed_count") != 0:
                blockers.append(f"SHORT_INTENT_SUPPRESSED:{fixture_class}")
            if replay.get("native_segment_exit_count") != 0:
                blockers.append(f"SEGMENT_NATIVE_EXIT_PRESENT:{fixture_class}")
            if replay != module.replay_flip_intents(
                frame,
                symbol="BTCUSDT",
                timeframe="5m",
                replay_fold_id="fixture",
            ):
                blockers.append(f"NONDETERMINISTIC_REPLAY:{fixture_class}")
            events = replay.get("events") if isinstance(replay.get("events"), list) else []
            if events and events[0].get("intent") != "HOLD":
                blockers.append(f"INITIAL_DIRECTION_NOT_HOLD:{fixture_class}")
            for event in events:
                if str(event.get("intent") or "").startswith("REVERSE_TO_"):
                    legs = event.get("ledger_legs") if isinstance(event.get("ledger_legs"), list) else []
                    if len(legs) != 2 or legs[0].get("signal_ts") != legs[1].get("signal_ts"):
                        blockers.append(f"REVERSAL_LEDGER_INVALID:{fixture_class}")
            fixture_results[fixture_class] = {
                "formula_parity": parity,
                "maximum_abs_error": maximum_error,
                "raw_up_flip_count": up_count,
                "raw_down_flip_count": down_count,
                "emitted_flip_intent_count": emitted,
                "valid_direction_bar_count": replay.get("valid_direction_bar_count"),
                "final_position_side": replay.get("final_position_side"),
            }

        warmup = frames["ATR_WARMUP_AND_RMA_SEED"]
        tr = reference_true_range(warmup)
        expected_seed = sum(tr[:10]) / 10
        actual_seed = float(module.compute_supertrend(warmup)["atr"].iloc[9])
        if not numeric_equal(actual_seed, expected_seed, tolerance):
            blockers.append("ATR_RMA_SEED_INVALID")

        single_up_indicator = module.compute_supertrend(frames["SINGLE_UP_FLIP"])
        single_up_counts = raw_flip_counts(single_up_indicator)
        if single_up_counts[0] != 1:
            blockers.append("SINGLE_UP_FIXTURE_DID_NOT_PRODUCE_ONE_UP_FLIP")

        single_down_indicator = module.compute_supertrend(frames["SINGLE_DOWN_FLIP"])
        single_down_counts = raw_flip_counts(single_down_indicator)
        if single_down_counts[1] != 1:
            blockers.append("SINGLE_DOWN_FIXTURE_DID_NOT_PRODUCE_ONE_DOWN_FLIP")

        whipsaw_counts = raw_flip_counts(module.compute_supertrend(frames["WHIPSAW_MULTI_FLIP"]))
        if sum(whipsaw_counts) < 3:
            blockers.append("WHIPSAW_FIXTURE_FLIP_COUNT_TOO_LOW")

        equal_down = module.direction_step(module.DOWN, 110.0, 110.0, 90.0)
        equal_up = module.direction_step(module.UP, 90.0, 110.0, 90.0)
        if equal_down != module.DOWN or equal_up != module.UP:
            blockers.append("EQUAL_BAND_BOUNDARY_NOT_STRICT")
        fixture_results["EQUAL_BAND_BOUNDARY"] = {
            "close_equals_upper_from_down": equal_down,
            "close_equals_lower_from_up": equal_up,
            "strict_crossing_preserved": equal_down == module.DOWN and equal_up == module.UP,
        }

        invalid = frames["ATR_WARMUP_AND_RMA_SEED"].copy()
        invalid.loc[5, "close"] = float("nan")
        invalid_result = module.strategy(invalid)
        if invalid_result.get("ok") is not False or invalid_result.get("intent") != "BLOCK":
            blockers.append("NONFINITE_INPUT_NOT_FAIL_CLOSED")
        fixture_results["MISSING_OR_NONFINITE_INPUT_FAIL_CLOSED"] = {
            "ok": invalid_result.get("ok"),
            "intent": invalid_result.get("intent"),
            "reason": invalid_result.get("reason"),
        }

    if set(fixture_results) != EXPECTED_FIXTURE_CLASSES:
        blockers.append("FORMULA_FIXTURE_CLASS_SET_INVALID")

    after = snapshot(protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append(f"READ_ONLY_PROTECTED_INPUT_MUTATION:{len(mutation_paths)}")

    blockers = list(dict.fromkeys(blockers))
    state = (
        "PASS_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES"
        if not blockers
        else "HOLD_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES"
    )
    next_stage = (
        "R7.A4D2_SUPERTREND_AUTHENTIC_STATE_TRANSITION_AND_BIDIRECTIONAL_REPLAY"
        if not blockers
        else "R7.A4D2_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES_REPAIR"
    )

    result = {
        "schema": "r7a4d2_supertrend_authentic_child_formula_fixture_verification_v1",
        "official_stage": "R7.A4D2_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "child_strategy_id": "supertrend_flip_authentic",
        "child_implementation_path": CHILD_PATH,
        "child_source_sha256": sha256_bytes(child_source),
        "legacy_parent_source_sha256": sha256_bytes(parent_source),
        "legacy_parent_immutable": sha256_bytes(parent_source) == EXPECTED_PARENT_SHA256,
        "atr_method": "WILDER_RMA",
        "atr_length": 10,
        "factor": 3.0,
        "formula_fixture_class_count": len(fixture_results),
        "formula_fixture_results": fixture_results,
        "forbidden_identifier_count": len(forbidden),
        "forbidden_identifiers": forbidden,
        "bidirectional_intent_count": 7,
        "short_intent_suppressed_count": 0,
        "native_segment_exit_count": 0,
        "economic_test_executed": False,
        "performance_claim_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "promotion_allowed": False,
        "input_mutation_count": len(mutation_paths),
        "input_mutation_paths": mutation_paths,
        "next_stage": next_stage,
    }

    output = root / OUTPUT_JSON
    atomic_json(output, result)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("CHILD_STRATEGY_ID=supertrend_flip_authentic")
    print("CHILD_SOURCE_SHA256=" + sha256_bytes(child_source))
    print("LEGACY_PARENT_SHA256=" + sha256_bytes(parent_source))
    print("LEGACY_PARENT_IMMUTABLE=" + str(result["legacy_parent_immutable"]).lower())
    print("ATR_METHOD=WILDER_RMA")
    print("ATR_LENGTH=10")
    print("SUPERTREND_FACTOR=3.0")
    print("FORMULA_FIXTURE_CLASS_COUNT=" + str(len(fixture_results)))
    for name in sorted(fixture_results):
        print("FORMULA_FIXTURE=" + name + "|" + json.dumps(fixture_results[name], sort_keys=True))
    print("FORBIDDEN_IDENTIFIER_COUNT=" + str(len(forbidden)))
    print("BIDIRECTIONAL_INTENT_COUNT=7")
    print("SHORT_INTENT_SUPPRESSED_COUNT=0")
    print("NATIVE_SEGMENT_EXIT_COUNT=0")
    print("ECONOMIC_TEST_EXECUTED=false")
    print("PERFORMANCE_CLAIM_ALLOWED=false")
    print("INPUT_MUTATION_COUNT=" + str(len(mutation_paths)))
    print("SUMMARY_JSON=" + str(output))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
