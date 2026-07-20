#!/usr/bin/env python3
from __future__ import annotations

import argparse
import builtins
import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from enum import Enum
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Iterator


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() and not path.is_symlink() else None


def git_bytes(root: Path, revision: str, repo_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "show", f"{revision}:{repo_path}"],
        cwd=root,
        capture_output=True,
        timeout=45,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def prior_gate(status: dict[str, Any], expected: int) -> bool:
    required = {
        "official_stage": "R7.A4",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": expected,
        "canonical_input_count": expected + 3,
        "canonical_git_parity_count": expected + 3,
        "required_category_coverage_count": 4,
        "active_entry_count": 0,
        "simulation_replay_execution_count": 0,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "next_stage": "R7.A4B_SIMULATION_REPLAY_DRY_RUN_MATRIX",
    }
    return all(status.get(key) == value for key, value in required.items()) and bool(status.get("input_set_id"))


def _price(regime: str, index: int) -> float:
    wave = math.sin(index / 6.0) * 0.55 + math.sin(index / 17.0) * 0.25
    if regime == "trend_up":
        return 100.0 + index * 0.085 + wave
    if regime == "trend_down":
        return 132.0 - index * 0.078 + wave
    if regime == "shock_recovery":
        base = 108.0 + math.sin(index / 8.0) * 0.7
        if 220 <= index < 240:
            return base - (index - 219) * 0.72
        if index >= 240:
            return base - 14.4 + (index - 239) * 0.18
        return base
    return 110.0 + math.sin(index / 5.0) * 1.7 + math.sin(index / 23.0) * 0.4


def build_fixture(regime: str, bars: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous = _price(regime, 0)
    for index in range(bars):
        close = max(_price(regime, index), 1.0)
        open_ = previous + math.sin(index / 9.0) * 0.08
        width = 0.42 + abs(math.sin(index / 11.0)) * 0.28
        high = max(open_, close) + width
        low = min(open_, close) - width
        volume = 950.0 + (index % 19) * 17.0 + abs(close - open_) * 120.0
        timestamp = 1_700_000_000_000 + index * 300_000
        rows.append({
            "timestamp": timestamp,
            "ts": timestamp,
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "open": round(open_, 8),
            "high": round(high, 8),
            "low": round(low, 8),
            "close": round(close, 8),
            "volume": round(volume, 8),
            "quote_volume": round(volume * close, 8),
            "trades": 100 + index % 31,
            "taker_buy_volume": round(volume * (0.48 + math.sin(index / 13.0) * 0.04), 8),
            "funding_8h": 0.0001,
            "funding_rate": 0.0001,
            "spread_bps": 1.5,
            "latency_ms": 40,
            "open_interest": 1_000_000.0 + index * 100.0,
        })
        previous = close
    return rows


class AttrBox(SimpleNamespace):
    def __getattr__(self, name: str) -> Any:
        return None


def build_context(strategy_id: str, rows: list[dict[str, Any]]) -> AttrBox:
    payload = {
        "ohlcv": rows,
        "candles": rows,
        "bars": rows,
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "position_side": "",
        "position_qty": 0.0,
        "avg_entry": 0.0,
        "add_count": 0,
        "risk_action": "hold",
        "fee_rate": 0.0,
        "slippage_bps": 0.0,
        "latency_ms": 0,
        "market_regime": "dry_run",
    }
    return AttrBox(
        signal=AttrBox(payload=payload, symbol="BTCUSDT", strategy_id=strategy_id, confidence=1.0),
        risk=AttrBox(action="hold", blocked=False),
        position=AttrBox(side="", qty=0.0, avg_entry=0.0),
        market=AttrBox(symbol="BTCUSDT", timeframe="5m"),
        metadata={"dry_run": True, "strategy_id": strategy_id},
    )


def normalize(value: Any, seen: set[int] | None = None) -> Any:
    if seen is None:
        seen = set()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return round(value, 12)
    if isinstance(value, Enum):
        return normalize(value.value, seen)
    object_id = id(value)
    if object_id in seen:
        return "<cycle>"
    if isinstance(value, dict):
        seen.add(object_id)
        result = {str(key): normalize(item, seen) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
        seen.remove(object_id)
        return result
    namedtuple_asdict = getattr(value, "_asdict", None)
    if callable(namedtuple_asdict):
        return normalize(namedtuple_asdict(), seen)
    if isinstance(value, (list, tuple)):
        seen.add(object_id)
        result = [normalize(item, seen) for item in value]
        seen.remove(object_id)
        return result
    if isinstance(value, (set, frozenset)):
        return sorted((normalize(item, seen) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if dataclasses.is_dataclass(value):
        return normalize(dataclasses.asdict(value), seen)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return normalize(item(), seen)
        except Exception:
            pass
    try:
        attributes = vars(value)
    except TypeError:
        attributes = None
    if isinstance(attributes, dict):
        seen.add(object_id)
        result = {
            str(key): normalize(item, seen)
            for key, item in sorted(attributes.items())
            if not str(key).startswith("_")
        }
        seen.remove(object_id)
        return result
    text = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", str(value))
    return text


def normalized_hash(value: Any) -> tuple[Any, str]:
    normalized = normalize(value)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return normalized, sha256_bytes(encoded)


def contains_dangerous_true(value: Any, dangerous_keys: set[str]) -> list[str]:
    findings: list[str] = []

    def walk(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                next_path = f"{path}.{key}" if path else str(key)
                if str(key).lower() in dangerous_keys and child is True:
                    findings.append(next_path)
                walk(child, next_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")

    walk(value, "")
    return findings


def extract_intent(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("intent", "action", "decision"):
            if key in value and value[key] is not None:
                return str(value[key]).lower()
        for child in value.values():
            found = extract_intent(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = extract_intent(child)
            if found is not None:
                return found
    return None


class SideEffectBlocked(RuntimeError):
    pass


@contextmanager
def side_effect_guard(attempts: list[str]) -> Iterator[None]:
    original_open = builtins.open
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    original_popen = subprocess.Popen
    original_run = subprocess.run
    original_check_call = subprocess.check_call
    original_check_output = subprocess.check_output
    original_system = os.system
    original_remove = os.remove
    original_unlink = os.unlink
    original_rename = os.rename
    original_replace = os.replace

    def deny(label: str):
        def blocked(*args: Any, **kwargs: Any) -> Any:
            attempts.append(label)
            raise SideEffectBlocked(label)
        return blocked

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            attempts.append(f"file_write:{file}")
            raise SideEffectBlocked(f"file_write:{file}")
        return original_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open
    socket.socket.connect = deny("socket.connect")  # type: ignore[assignment]
    socket.create_connection = deny("socket.create_connection")  # type: ignore[assignment]
    subprocess.Popen = deny("subprocess.Popen")  # type: ignore[assignment]
    subprocess.run = deny("subprocess.run")  # type: ignore[assignment]
    subprocess.check_call = deny("subprocess.check_call")  # type: ignore[assignment]
    subprocess.check_output = deny("subprocess.check_output")  # type: ignore[assignment]
    os.system = deny("os.system")  # type: ignore[assignment]
    os.remove = deny("os.remove")  # type: ignore[assignment]
    os.unlink = deny("os.unlink")  # type: ignore[assignment]
    os.rename = deny("os.rename")  # type: ignore[assignment]
    os.replace = deny("os.replace")  # type: ignore[assignment]
    try:
        yield
    finally:
        builtins.open = original_open
        socket.socket.connect = original_connect  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]
        subprocess.Popen = original_popen  # type: ignore[assignment]
        subprocess.run = original_run  # type: ignore[assignment]
        subprocess.check_call = original_check_call  # type: ignore[assignment]
        subprocess.check_output = original_check_output  # type: ignore[assignment]
        os.system = original_system  # type: ignore[assignment]
        os.remove = original_remove  # type: ignore[assignment]
        os.unlink = original_unlink  # type: ignore[assignment]
        os.rename = original_rename  # type: ignore[assignment]
        os.replace = original_replace  # type: ignore[assignment]


def load_module(root: Path, repo_path: str, strategy_id: str):
    path = root / repo_path
    module_name = f"r7a4b_strategy_{strategy_id}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def resolve_callable(module: Any, dotted: str) -> tuple[type[Any], str]:
    parts = dotted.split(".")
    if len(parts) != 2:
        raise RuntimeError(f"CALLABLE_FORMAT_INVALID:{dotted}")
    owner = getattr(module, parts[0], None)
    if not isinstance(owner, type) or not callable(getattr(owner, parts[1], None)):
        raise RuntimeError(f"CALLABLE_NOT_RESOLVED:{dotted}")
    return owner, parts[1]


def instantiate(owner: type[Any]) -> Any:
    try:
        return owner()
    except TypeError:
        instance = owner.__new__(owner)
        if instance is None:
            raise RuntimeError(f"CALLABLE_OWNER_INIT_FAILED:{owner.__name__}")
        return instance


def run_once(owner: type[Any], method_name: str, context: AttrBox, attempts: list[str]) -> Any:
    instance = instantiate(owner)
    method = getattr(instance, method_name)
    with side_effect_guard(attempts):
        return method(context)


def active_lineage_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(encoded)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    fixture_names = [str(item) for item in contract.get("fixture_names", [])]
    fixture_bars = int(contract.get("fixture_bars", 320))
    repeat_count = int(contract.get("repeat_count", 2))
    allowed_intents = {str(item).lower() for item in contract.get("allowed_output_intents", [])}
    dangerous_keys = {str(item).lower() for item in contract.get("dangerous_true_keys", [])}

    prior_status = load_json(root / str(contract["prior_status_path"]))
    prior_manifest = load_json(root / str(contract["prior_manifest_path"]))
    registry_repo = safe_repo_path(str(contract["registry_path"]))
    registry_path = root / registry_repo
    registry = load_json(registry_path)
    blockers: list[str] = []

    if not prior_gate(prior_status, expected):
        blockers.append("PRIOR_A4_STATUS_INVALID")
    if prior_manifest.get("state") != "PASS" or prior_manifest.get("input_set_id") != prior_status.get("input_set_id"):
        blockers.append("A4_MANIFEST_STATUS_MISMATCH")
    if len(fixture_names) != int(contract.get("expected_fixture_count", 4)) or repeat_count != 2:
        blockers.append("DRY_RUN_FIXTURE_CONTRACT_INVALID")

    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    if len(entries) != expected:
        blockers.append(f"REGISTRY_COUNT_INVALID:{len(entries)}")

    canonical_inputs = [row for row in prior_manifest.get("canonical_inputs", []) if isinstance(row, dict)]
    canonical_paths: list[Path] = []
    canonical_input_parity_count = 0
    for entry in canonical_inputs:
        try:
            repo_path = safe_repo_path(str(entry.get("path") or ""))
        except ValueError as exc:
            blockers.append(str(exc))
            continue
        path = root / repo_path
        canonical_paths.append(path)
        canonical_input_parity_count += int(
            path.is_file()
            and not path.is_symlink()
            and bool(entry.get("sha256"))
            and sha256_file(path) == entry.get("sha256")
        )
    if len(canonical_inputs) != expected + 3 or canonical_input_parity_count != expected + 3:
        blockers.append("CANONICAL_INPUT_PARITY_FAILED")

    protected_paths = [Path(str(item)) for item in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)
    matrix_rows: list[dict[str, Any]] = []
    strategy_pass_count = 0
    deterministic_pair_count = 0
    dry_run_call_count = 0
    successful_call_count = 0
    side_effect_attempts: list[str] = []
    import_count = 0

    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    try:
        for row in entries:
            strategy_id = str(row.get("strategy_id") or "")
            engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
            implementation_path = str(engine.get("implementation_path") or "")
            callable_name = str(engine.get("callable") or "")
            row_errors: list[str] = []
            fixture_results: list[dict[str, Any]] = []

            try:
                implementation_path = safe_repo_path(implementation_path)
                module = load_module(root, implementation_path, strategy_id)
                import_count += 1
                owner, method_name = resolve_callable(module, callable_name)
            except Exception as exc:
                row_errors.append(f"LOAD_OR_CALLABLE:{type(exc).__name__}:{exc}")
                matrix_rows.append({
                    "strategy_id": strategy_id,
                    "implementation_path": implementation_path,
                    "callable": callable_name,
                    "pass": False,
                    "errors": row_errors,
                    "fixtures": fixture_results,
                })
                continue

            for fixture_name in fixture_names:
                rows = build_fixture(fixture_name, fixture_bars)
                hashes: list[str] = []
                outputs: list[Any] = []
                fixture_errors: list[str] = []
                fixture_attempts_before = len(side_effect_attempts)
                for _ in range(repeat_count):
                    dry_run_call_count += 1
                    try:
                        output = run_once(owner, method_name, build_context(strategy_id, rows), side_effect_attempts)
                        normalized, digest = normalized_hash(output)
                        outputs.append(normalized)
                        hashes.append(digest)
                        successful_call_count += 1
                        dangerous = contains_dangerous_true(normalized, dangerous_keys)
                        if dangerous:
                            fixture_errors.append("DANGEROUS_TRUE:" + ",".join(dangerous))
                        intent = extract_intent(normalized)
                        if intent is not None and allowed_intents and intent not in allowed_intents:
                            fixture_errors.append(f"OUTPUT_INTENT_NOT_ALLOWED:{intent}")
                    except Exception as exc:
                        fixture_errors.append(f"CALL_FAILED:{type(exc).__name__}:{exc}")

                deterministic = len(hashes) == repeat_count and len(set(hashes)) == 1
                deterministic_pair_count += int(deterministic)
                if not deterministic:
                    fixture_errors.append("NON_DETERMINISTIC_OUTPUT")
                if len(side_effect_attempts) > fixture_attempts_before:
                    fixture_errors.append("SIDE_EFFECT_ATTEMPTED")
                if fixture_errors:
                    row_errors.extend(f"{fixture_name}:{error}" for error in fixture_errors)
                fixture_results.append({
                    "fixture": fixture_name,
                    "bars": fixture_bars,
                    "repeat_count": repeat_count,
                    "deterministic": deterministic,
                    "output_hash": hashes[0] if deterministic else None,
                    "hashes": hashes,
                    "sample_output": outputs[0] if outputs else None,
                    "errors": fixture_errors,
                })

            row_pass = not row_errors and len(fixture_results) == len(fixture_names)
            strategy_pass_count += int(row_pass)
            matrix_rows.append({
                "strategy_id": strategy_id,
                "implementation_path": implementation_path,
                "callable": callable_name,
                "pass": row_pass,
                "errors": row_errors,
                "fixtures": fixture_results,
            })
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    after = snapshot(canonical_paths + protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    canonical_set = {str(path) for path in canonical_paths}
    protected_set = {str(path) for path in protected_paths}
    canonical_mutation_count = sum(1 for path in mutation_paths if path in canonical_set)
    protected_change_count = sum(1 for path in mutation_paths if path in protected_set)
    if mutation_paths:
        blockers.append("DRY_RUN_MUTATION_DETECTED")

    category_inputs = prior_manifest.get("category_inputs") if isinstance(prior_manifest.get("category_inputs"), dict) else {}
    deferred_candidate_count = sum(len(items) for items in category_inputs.values() if isinstance(items, list))
    runner_repo = "tools/r7a4b_strategy25_deterministic_dry_run_matrix.py"
    runner_bytes = git_bytes(root, args.target_sha, runner_repo)
    if runner_bytes is None:
        blockers.append("DRY_RUN_RUNNER_GIT_OBJECT_MISSING")
    fixture_spec = {
        "schema": "r7a4b_synthetic_fixture_v1",
        "names": fixture_names,
        "bars": fixture_bars,
        "repeat_count": repeat_count,
        "generator": "deterministic_math_no_random_no_external_data",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
    }
    lineage_payload = {
        "prior_input_set_id": prior_status.get("input_set_id"),
        "target_commit": args.target_sha,
        "canonical_inputs": [
            {key: entry.get(key) for key in ("path", "sha256", "size_bytes", "target_git_parity")}
            for entry in canonical_inputs
        ],
        "runner": {"path": runner_repo, "sha256": sha256_bytes(runner_bytes) if runner_bytes is not None else None},
        "fixture_spec": fixture_spec,
    }
    dry_run_input_set_id = active_lineage_id(lineage_payload)

    expected_pair_count = int(contract.get("expected_pair_count", expected * len(fixture_names)))
    expected_call_count = int(contract.get("expected_call_count", expected_pair_count * repeat_count))
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPTS:{len(side_effect_attempts)}")
    if strategy_pass_count != expected:
        blockers.append(f"STRATEGY_DRY_RUN_FAILURES:{expected - strategy_pass_count}")
    if deterministic_pair_count != expected_pair_count:
        blockers.append(f"DETERMINISTIC_PAIR_GAP:{expected_pair_count - deterministic_pair_count}")
    if dry_run_call_count != expected_call_count or successful_call_count != expected_call_count:
        blockers.append(f"DRY_RUN_CALL_GAP:{expected_call_count - successful_call_count}")

    all_blockers = list(dict.fromkeys(blockers))
    success = bool(
        not all_blockers
        and strategy_pass_count == expected
        and deterministic_pair_count == expected_pair_count
        and dry_run_call_count == expected_call_count
        and successful_call_count == expected_call_count
        and len(side_effect_attempts) == 0
        and canonical_mutation_count == 0
        and protected_change_count == 0
        and int(registry.get("active_entry_count", -1)) == 0
    )
    state = "PASS" if success else "HOLD"
    next_stage = str(contract["next_stage_pass"] if success else contract["next_stage_fail"])

    matrix = {
        "schema": "r7a4b_strategy25_deterministic_dry_run_matrix_v1",
        "official_stage": "R7.A4B",
        "state": state,
        "target_commit": args.target_sha,
        "prior_input_set_id": prior_status.get("input_set_id"),
        "dry_run_input_set_id": dry_run_input_set_id,
        "fixture_spec": fixture_spec,
        "strategies": matrix_rows,
        "side_effect_attempts": side_effect_attempts,
        "blockers": all_blockers,
    }
    lineage_manifest = {
        "schema": "r7a4b_active_input_lineage_v1",
        "official_stage": "R7.A4B",
        "state": state,
        "prior_input_set_id": prior_status.get("input_set_id"),
        "dry_run_input_set_id": dry_run_input_set_id,
        "active_physical_input_count": len(canonical_inputs) + int(runner_bytes is not None),
        "active_virtual_fixture_count": 1,
        "canonical_inputs": canonical_inputs,
        "runner": lineage_payload["runner"],
        "fixture_spec": fixture_spec,
        "deferred_external_candidate_count": deferred_candidate_count,
        "deferred_categories": {
            category: len(items) for category, items in category_inputs.items() if isinstance(items, list)
        },
        "historical_market_data_used": False,
        "execution_cost_model_applied": False,
        "historical_replay_executed": False,
    }
    proof = {
        "schema": "r7a4b_strategy25_deterministic_dry_run_proof_v1",
        "official_stage": "R7.A4B",
        "state": state,
        "target_commit": args.target_sha,
        "prior_input_set_id": prior_status.get("input_set_id"),
        "dry_run_input_set_id": dry_run_input_set_id,
        "mutation_paths": mutation_paths,
        "side_effect_attempts": side_effect_attempts,
        "blockers": all_blockers,
    }
    status = {
        "official_stage": "R7.A4B",
        "state": state,
        "blocker_count": len(all_blockers),
        "blockers": all_blockers,
        "strategy_count": expected,
        "strategy_import_count": import_count,
        "strategy_pass_count": strategy_pass_count,
        "fixture_count": len(fixture_names),
        "repeat_count": repeat_count,
        "deterministic_pair_count": deterministic_pair_count,
        "dry_run_call_count": dry_run_call_count,
        "successful_call_count": successful_call_count,
        "side_effect_attempt_count": len(side_effect_attempts),
        "canonical_input_parity_count": canonical_input_parity_count,
        "active_lineage_physical_input_count": len(canonical_inputs) + int(runner_bytes is not None),
        "active_virtual_fixture_count": 1,
        "deferred_external_candidate_count": deferred_candidate_count,
        "prior_input_set_id": prior_status.get("input_set_id"),
        "dry_run_input_set_id": dry_run_input_set_id,
        "historical_market_data_used_count": 0,
        "execution_cost_model_applied_count": 0,
        "historical_replay_execution_count": 0,
        "active_entry_count": int(registry.get("active_entry_count", -1)),
        "canonical_mutation_count": canonical_mutation_count,
        "protected_change_count": protected_change_count,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "paper_live_order_count": 0,
        "next_stage": next_stage,
        "matrix_path": str(root / str(contract["matrix_path"])),
        "lineage_manifest_path": str(root / str(contract["lineage_manifest_path"])),
        "proof_path": str(root / str(contract["proof_path"])),
    }

    atomic_json(root / str(contract["matrix_path"]), matrix)
    atomic_json(root / str(contract["lineage_manifest_path"]), lineage_manifest)
    atomic_json(root / str(contract["proof_path"]), proof)
    atomic_json(root / str(contract["status_path"]), status)

    for key in (
        "state", "blocker_count", "strategy_count", "strategy_import_count",
        "strategy_pass_count", "fixture_count", "repeat_count", "deterministic_pair_count",
        "dry_run_call_count", "successful_call_count", "side_effect_attempt_count",
        "canonical_input_parity_count", "active_lineage_physical_input_count",
        "active_virtual_fixture_count", "deferred_external_candidate_count",
        "prior_input_set_id", "dry_run_input_set_id", "historical_market_data_used_count",
        "execution_cost_model_applied_count", "historical_replay_execution_count",
        "active_entry_count", "canonical_mutation_count", "protected_change_count",
        "router_mutation_count", "service_mutation_count", "paper_live_order_count",
        "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("BLOCKERS=" + json.dumps(all_blockers, ensure_ascii=False))
    print("MATRIX_JSON=" + status["matrix_path"])
    print("LINEAGE_JSON=" + status["lineage_manifest_path"])
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + ("0" if success else "2"))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
