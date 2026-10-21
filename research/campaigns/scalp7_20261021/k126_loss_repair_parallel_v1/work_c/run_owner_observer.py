"""A-only, one exact-incumbent instrumentation replay; never a new policy run.

C tests the helpers synthetically and does NOT invoke main with --run-once.
Runtime sources/caches are read-only. Only a new output directory is written.
The acknowledgement is not a claim, allocation, budget reset or authority grant.
The existing owner must arrange its current claim and shared-heavy slot first.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

OWNER = "CLOUD_WORK_COORDINATOR_ISSUE1358_V1"
IDENTITY = "k126_native_state_origin_observer_c_v1"
INCUMBENT_COMMIT = "81a12c422ee9329996d2f6b983267d2def490d4b"
STAGE = Path("/home/z/z/runtime/k126_pullback_structure_failure_20261021_v1")
CACHE = Path("/home/z/z/runtime/k_winner_handoff_20261021T1230Z")
GUARD_STAGE = Path("/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1")
HANDOFF_STAGE = Path("/home/z/z/runtime/k_winner_handoff_context_order_attempt2_20261021")
TIMEOUT_STAGE = Path("/home/z/z/runtime/k_winner_timeout_20261021T1142Z")
RUNTIME_PINS = {
    STAGE / "structural_failure.py": "a260f6461d4fd96316c3716ebb1177d802752a7e4c842f80ea1966694ff236c3",
    HANDOFF_STAGE / "handoff_comparison.py": "abc704b1eb1051eb3e2adeb8720d494d2d3082d72c460bbddc87fc2f828cabd9",
    TIMEOUT_STAGE / "winner_timeout_comparison.py": "4a73266f1000dda483c910d90c22ae86f2969faef0b50738cf561349a56b50e2",
    GUARD_STAGE / "guard_exact_allocation_once.py": "70e23fa80140decedb77b3c5e5c174d8c9dda844f3b4d4f38502bf8ad11ca705",
    GUARD_STAGE / "guard_existing_slot.py": "2c180dccf0f3a17f66a9d005123579d93cb9de48b332713db3c2f4c62020fec0",
    GUARD_STAGE / "owner_record.py": "98ef137712c823c73019b2ceaee3dcc7a4792be14baef95602de67e63885150b",
}
REPO_PINS = {
    "backend/research/rebuild/scalp7_positive_lanes_v2.py": "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2",
    "backend/research/rebuild/scalp7_execution_v2.py": "d1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1",
    "backend/research/rebuild/scalp7_source_data_v2.py": "7cf2507ad4a23827644d7f58a33512ea6c83590305c5630cce6ff1063ae506e5",
    "backend/research/rebuild/scalp7_rolling_context_v2.py": "672934c9df51d2fd30c43e5099342d7bda1c5b0661dec1670165ad9fd7a6ceaf",
    "ops/scalp7_keltner_fresh_touch_successor_v1.py": "e0afbe1d76c4a3c8b4470aae82b152bd3f59676339294653719c3f3a85e2f855",
    "ops/scalp7_benchmark_observer_v1.py": "683a08d37ad0eab674ba194ebe0c4ff9400c3c586e3728b8dce67fe9747db6a0",
    "research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json": "25df48fdf874e6d175a8615780539ad6be6d7c892e34a5f1cf5e944c262b50ff",
    "research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json": "cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73",
}
INPUT_PINS = {
    "ROWS.json.gz": "5f45180aa762dc091c16e8fa2d208dcf027c16f795d9533911d2c11d73a30c77",
    "SUMMARY.json": "a69e1cce4b5dffe004d49820ced626962795952f2e7b06226eb71ad77b8f7812",
}
ROWS_PLAIN_SHA = "98eaa46994eb8c4e9d89e7e17bbb9a9cce97b86f6a3a727c11e8136da75a85f3"
BINDING_SHA = "c94dcfe38855f9ed71230f73e7a2d92ddbed21b47d9354c1c76b87080329a3e9"
CONTEXT_SHA = "168044bf3bfd2bc4299c55fca84bc45c2e3ce56a79310e4583b02277c296b86c"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode()


def checked_bytes(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError("PIN_CHANGED:" + str(path))
    return raw


def load_saved(directory: Path):
    payloads = {name: checked_bytes(directory / name, pin)
                for name, pin in INPUT_PINS.items()}
    plain = gzip.decompress(payloads["ROWS.json.gz"])
    if sha(plain) != ROWS_PLAIN_SHA:
        raise ValueError("INCUMBENT_ROWS_PLAIN_CHANGED")
    saved, summary = json.loads(plain), json.loads(payloads["SUMMARY.json"])
    if len(saved["raw_trades"]) != 126 or summary["context_fit_sha256"] != CONTEXT_SHA:
        raise ValueError("INCUMBENT126_CONTRACT_CHANGED")
    return saved, summary


def trade_key(row):
    return str(row["symbol"]), int(row["side"]), int(row["signal_ts_ms"])


def verify_parity(result, saved, expected_count=126):
    """Compare entire raw rows, order, unresolved and boundary collections."""
    for output_key, saved_key in (("trades", "raw_trades"),
                                  ("unresolved", "unresolved"),
                                  ("boundary_excluded", "boundary_excluded")):
        actual = [r for r in result[output_key] if r["partition"] == "rolling"]
        if actual != saved[saved_key]:
            raise ValueError("OBSERVER_CHANGED_INCUMBENT:" + output_key)
    if len(saved["raw_trades"]) != expected_count:
        raise ValueError("INCUMBENT_COUNT_MISMATCH")
    if len({trade_key(r) for r in saved["raw_trades"]}) != expected_count:
        raise ValueError("INCUMBENT_DUPLICATE_KEYS")


def join_entries(observations, saved_rows):
    """Join native origin records to every saved entry; never select by PnL."""
    wanted = {trade_key(r) for r in saved_rows}
    found = {}
    for rec in observations:
        event = rec.get("native_event_observed")
        if event is None:
            continue
        key = (rec["symbol"], int(event[0]), int(rec["signal_ts_ms"]))
        if key not in wanted:
            continue
        if key in found:
            raise ValueError("ORIGIN_ENTRY_JOIN_DUPLICATE")
        if rec["admission"]["state"] != "ACCEPTED":
            raise ValueError("ORIGIN_ENTRY_NOT_ACCEPTED")
        found[key] = rec
    if set(found) != wanted:
        raise ValueError("ORIGIN_ENTRY_JOIN_INCOMPLETE")
    joined = []
    for row in saved_rows:
        key = trade_key(row)
        rec = found[key]
        signal = row["signal"]
        if int(rec["admission"]["decision_ts_ms"]) != int(row["entry_ts_ms"]):
            raise ValueError("ORIGIN_ENTRY_CLOCK_MISMATCH")
        if float(rec["native_event_observed"][1]) != float(signal["invalidation_price"]):
            raise ValueError("ORIGIN_REFERENCE_PRICE_MISMATCH")
        entry = float(row["entry_prices"][row["symbol"]])
        stop = float(signal["stop_price"])
        atr = float(signal["meta"]["atr_price"])
        fallback = int(row["side"]) * (entry - stop) <= 0
        risk = (float(signal["meta"]["fallback_stop_atr_mult"]) * atr
                if fallback else abs(entry - stop))
        joined.append({"trade_key": list(key), "entry_ts_ms": row["entry_ts_ms"],
                       "entry_price": entry,
                       "signal_invalidation_price": signal["invalidation_price"],
                       "signal_stop_price": stop, "signal_atr_price": atr,
                       "initial_stop_after_entry_admission": entry - int(row["side"]) * risk,
                       "fallback_stop_applied": fallback,
                       "initial_risk_price": risk, "initial_risk_over_signal_atr": risk / atr,
                       "existing_scratch_040R_hurdle_price": 0.4 * risk,
                       "risk_fields_meaning": "EXPLANATORY_FROZEN_INITIAL_RISK_UNITS_NOT_A_NEW_THRESHOLD",
                       "origin_observation": rec,
                       "outcomes_used_as_conditions": False})
    return joined


def observe_once(incumbent, frames, costs, windows, saved, patch, finalize,
                 expected_count=126):
    """One fixed callable; no disabled/enabled policy comparison or carry replay."""
    observations = []
    with patch():
        result = incumbent(frames, costs, windows,
                           benchmark_observations=observations)
    verify_parity(result, saved, expected_count)
    finalized = finalize(observations)
    joined = join_entries(finalized, saved["raw_trades"])
    return finalized, joined


@contextmanager
def existing_lock(path: Path):
    """Never create or truncate a runtime lock; fail if missing or busy."""
    with path.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save_new(directory: Path, name: str, value, compressed=False):
    raw = encoded(value)
    if compressed:
        raw = gzip.compress(raw, mtime=0)
    with (directory / name).open("xb") as handle:
        handle.write(raw)
    return {"sha256": sha(raw), "bytes": len(raw)}


def require_capacity(cap):
    busy, evidence = cap.live_capacity()
    local = cap.original.local_busy()
    if busy or local:
        raise RuntimeError("CAPACITY_BUSY_NO_WAIT_NO_REPLAY:" +
                           json.dumps({"global": busy, "local": local}, sort_keys=True))
    return evidence


def run(args):
    if args.owner_ack != OWNER or not args.run_once:
        raise ValueError("OWNER_ONLY_EXPLICIT_INSTRUMENTATION_REQUIRED")
    saved, _summary = load_saved(args.incumbent_input_dir)
    for path, pin in RUNTIME_PINS.items():
        checked_bytes(path, pin)
    # This is a new process and a new output directory. Nothing is queued/retried.
    args.output_dir.mkdir(parents=False, exist_ok=False)
    started = False
    try:
        sys.path[:0] = [str(STAGE), str(GUARD_STAGE)]
        a = load_module("_work_c_exact_incumbent", STAGE / "structural_failure.py")
        cap = load_module("_work_c_existing_capacity", GUARD_STAGE / "guard_exact_allocation_once.py")
        # Existing guard diagnostics write only to the new isolated output.
        # Do not invoke either guard.main or owner_record.update.
        cap.S = args.output_dir
        cap.original.S = args.output_dir
        cap.original.REQUESTS = 0
        h = a.h
        for path, pin in REPO_PINS.items():
            checked_bytes(h.REPO / path, pin)
        h.timeout.verify_dependencies()
        from backend.research.rebuild import scalp7_source_data_v2 as source
        from backend.research.rebuild import scalp7_rolling_context_v2 as context
        import pandas as pd
        # Keep local observation code discoverable after incumbent alters sys.path.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from observer import observation_patch, finalize_observations
        with existing_lock(h.BASE / "paired.lock"):
            capacity = require_capacity(cap)
            binding = json.loads(checked_bytes(h.BASE / "CHRONO_SOURCE_BINDING.json", BINDING_SHA))
            cache = json.loads((CACHE / "INPUT_CACHE.json").read_bytes())
            if set(cache["symbols"]) != set(source.SYMBOLS) or set(binding) != set(source.SYMBOLS):
                raise ValueError("SOURCE_SYMBOL_SET_CHANGED")
            frames, data_pins = {}, {}
            for symbol in source.SYMBOLS:
                rec = cache["symbols"][symbol]
                path = (CACHE / rec["path"]).resolve()
                if not path.is_relative_to(CACHE.resolve()):
                    raise ValueError("CACHE_PATH_OUTSIDE_PINNED_CACHE")
                raw = checked_bytes(path, rec["sha256"])
                frame = pd.read_csv(io.BytesIO(raw), compression="gzip", float_precision="round_trip")
                csv_sha = sha(frame.to_csv(index=False).encode())
                if len(frame) != 17519 or csv_sha != binding[symbol]["full_csv_sha256"]:
                    raise ValueError("SOURCE_FRAME_CHANGED:" + symbol)
                frames[symbol] = frame
                data_pins[symbol] = {"cache_sha256": sha(raw), "full_csv_sha256": csv_sha, "rows": len(frame)}
            windows = json.loads((h.REPO / "research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json").read_bytes())["windows"]
            costs = json.loads((h.REPO / "research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json").read_bytes())["costs_bps"]
            # Check again after input validation and before the single source run.
            capacity = require_capacity(cap)
            save_new(args.output_dir, "STARTED.json", {
                "at_utc": datetime.now(timezone.utc).isoformat(), "owner": OWNER,
                "identity": IDENTITY, "incumbent_commit": INCUMBENT_COMMIT,
                "kind": "EXACT_INCUMBENT_INSTRUMENTATION_ONLY",
                "new_policy_comparisons": 0, "source_inputs": data_pins,
                "capacity_evidence": capacity, "input_pins": INPUT_PINS,
                "runtime_pins": {str(p): v for p, v in RUNTIME_PINS.items()},
                "repo_pins": REPO_PINS, "no_blind_retry": True})
            started = True
            bound, fits = context.bind_context(frames, context.cross_features(frames), windows)
            fit_sha = sha(json.dumps(fits, sort_keys=True, separators=(",", ":")).encode())
            if fit_sha != CONTEXT_SHA:
                raise ValueError("CONTEXT_FIT_CHANGED")
            incumbent = a.ExitComparison(True).build()
            observations, entries = observe_once(
                incumbent, bound, costs, windows, saved,
                observation_patch, finalize_observations)
            all_pin = save_new(args.output_dir, "NATIVE_ORIGINS_ALL.json.gz", observations, True)
            entry_pin = save_new(args.output_dir, "ENTRY_ORIGINS_ALL126.json", entries)
            report = {"identity": IDENTITY, "owner": OWNER, "incumbent_commit": INCUMBENT_COMMIT,
                      "classification": "EXACT_INCUMBENT_STATE_OBSERVER_NOT_NEW_ECONOMIC_RESULT",
                      "raw126_exact": True, "unresolved_exact": True, "boundary_excluded_exact": True,
                      "source_policy_changed": False, "new_policy_comparisons": 0,
                      "observation_count": len(observations), "entry_count": len(entries),
                      "transitions": dict(Counter(r["successor_transition"] for r in observations)),
                      "context_fit_sha256": fit_sha, "source_inputs": data_pins,
                      "files": {"NATIVE_ORIGINS_ALL.json.gz": all_pin, "ENTRY_ORIGINS_ALL126.json": entry_pin}}
            save_new(args.output_dir, "OBSERVER_RECEIPT.json", report)
            print(json.dumps({"identity": IDENTITY, "raw126_exact": True, "entry_count": len(entries),
                              "receipt": str(args.output_dir / "OBSERVER_RECEIPT.json")}))
    except Exception as exc:
        save_new(args.output_dir, "HOLD.json", {"identity": IDENTITY, "error_type": type(exc).__name__,
                 "error": str(exc), "source_run_started": started, "no_blind_retry": True})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-ack", required=True)
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--incumbent-input-dir", required=True, type=Path,
                        help="read-only export of pinned incumbent ROWS.json.gz and SUMMARY.json")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="must not exist; parent must already exist")
    run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
