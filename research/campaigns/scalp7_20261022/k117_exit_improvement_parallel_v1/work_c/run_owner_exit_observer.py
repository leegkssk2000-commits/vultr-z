"""Owner-only, one passive trace of the frozen K117 baseline.

No new policy, carry-cost replay, market download, claim or budget mutation.
--bind-only validates saved bytes and builds the exact callable without loading
price frames or running it. --owner-ack is acknowledgement, not an authority
grant: A must first review its current claim, budget and shared-slot ownership.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
OWNER = "CLOUD_WORK_COORDINATOR_ISSUE1358_V1"
SCOPE = "K117_PASSIVE_EXIT_OBSERVER_C_V1"
BASELINE = "scalp7_k126_veto_objective_completed_fresh_touch_v1"
BASELINE_COMMIT = "8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8"
STAGE = Path("/home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1")
SOURCE_STAGE = Path("/home/z/z/runtime/k126_pullback_structure_failure_20261021_v1")
PRIOR_C = Path("/home/z/z/runtime/k126_c_veto_consume_20261022_v1/work_c_exact")
CACHE = Path("/home/z/z/runtime/k_winner_handoff_20261021T1230Z")
ORDER = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
PINS = {
    "SUMMARY.json": "c2dfcdbec704fb7ab020c2d4d53293fd03dab5820672e0ac6fb4f9aa6094e5ae",
    "EXECUTION_FREEZE.json": "918d00133ddb1b498bd93353a48f6e8a75f2da83b4062e3430db52b99b57ef0a",
    "objective_lifetime.py": "40659bc91044cca35ea6fc0aad383487b59ac16ec8aeb74639f8f5663e131bb7",
    "run_compare.py": "6072afe404b0341c20975430ca51fcd32f89be8405a6432aa020d53b0dd81538",
    "ARITHMETIC_AUDIT.json": "a9832e7fab8b07f2918e82a26fdfa52840a448e8ecfe737a1495d85a4e8a1f2c",
}
ROWS_PLAIN_SHA = "7cba96a0627dbec42459f344a6e8e7dd70d97f87d71dfb573e10975153d7d0a7"
ROWS_GZIP_SHA = "ab48ec1bd90479ae95fb432838a30e9e23b060c3002c70f14dd09b6a869ca4e9"
CACHE_MANIFEST_SHA = "c62e037500dd5b6ccaeb309c250be7bf47d053b4d3527cdbda60bbaafbb05bf9"
PRIOR_HELPER_SHA = "cafe68dd24ce28da96ea8098192b15f00bfc0c25dc5093ac0bc4e55185319254"
STATE_CODE_SHA = "73e0ae811349e8ca41cc0555691a88c57df0d744ccc652f5a37861511ebe5fc7"
SOURCE_FUNCTION_SHA = "9cab68472492d27a0a990cdce73e51ecd8009866f2ba12fc3a29b02381094252"
FULL_CSV_SHA = {
    "BTC-USDT": "36a7133d89effa8691ecaed2df208d3e983debfc3e59c86fdea878fcfb5ad057",
    "ETH-USDT": "3312811ed98595c087e934a2b845b98ace2b86d5077b615607135a78b1ea2d3a",
    "SOL-USDT": "1db7ae0eabafd70222daad51607f3838a388233ac94c5d08d7682786132b6cee",
    "XRP-USDT": "6f8749856144fe313fc1c4715e39f22e0520a23a4a4367c70dd702c2ece3a771",
    "LINK-USDT": "2f1478ff2611891c8564737af4d591183d5863e6c9cecb0808eea3e5103078bf",
    "DOGE-USDT": "5571b70d9058bd7bfa0ff5e6ced74bc4b2cb05f909dccff0b11020fb7f7d17b8",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected):
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError("K117_PIN_CHANGED:" + str(path))
    return raw


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_saved(directory):
    docs = {name: checked(directory / name, pin) for name, pin in PINS.items()}
    if (directory / "ROWS.json").exists():
        raw = checked(directory / "ROWS.json", ROWS_PLAIN_SHA)
    else:
        raw = gzip.decompress(checked(directory / "ROWS.json.gz", ROWS_GZIP_SHA))
        if sha(raw) != ROWS_PLAIN_SHA:
            raise ValueError("K117_DECOMPRESSED_ROWS_CHANGED")
    saved, summary, freeze = json.loads(raw), json.loads(docs["SUMMARY.json"]), json.loads(docs["EXECUTION_FREEZE.json"])
    if summary["candidate"] != BASELINE or freeze["candidate"] != BASELINE:
        raise ValueError("K117_IDENTITY_NOT_BOUND")
    if summary["rows_sha256"] != ROWS_PLAIN_SHA:
        raise ValueError("K117_SUMMARY_ROWS_NOT_BOUND")
    if len(saved["raw_trades"]) != 117 or len(saved["trades"]) != 117:
        raise ValueError("K117_COUNT_CHANGED")
    if len({key(r) for r in saved["raw_trades"]}) != 117:
        raise ValueError("K117_DUPLICATE_SAVED_ENTRIES")
    return saved, summary, freeze


def key(row):
    return str(row["symbol"]), int(row["side"]), int(row["signal_ts_ms"])


def require_order(source_symbols, frames=None):
    if tuple(source_symbols) != ORDER or (frames is not None and tuple(frames) != ORDER):
        raise ValueError("K117_ORIGINAL_SYMBOL_ORDER_CHANGED")


def verify_parity(result, events, saved, expected_count=117):
    """Full ordered row dictionaries and all native state-event ledgers, no scoring."""
    for result_key, saved_key in (("trades", "raw_trades"), ("unresolved", "unresolved"),
                                  ("boundary_excluded", "boundary_excluded")):
        actual = [r for r in result[result_key] if r["partition"] == "rolling"]
        if actual != saved[saved_key]:
            raise ValueError("K117_PASSIVE_PARITY_FAILED:" + result_key)
    if result["traces"] != saved["native_traces"]:
        raise ValueError("K117_PASSIVE_PARITY_FAILED:native_traces")
    if events != saved["objective_expiry_events"]:
        raise ValueError("K117_PASSIVE_PARITY_FAILED:objective_expiry_events")
    if len(saved["raw_trades"]) != expected_count:
        raise ValueError("K117_PASSIVE_COUNT_CHANGED")


def observe_once(baseline, frames, costs, windows, saved, passive, expected_count=117):
    """Build passive trace once and invoke only K117, never an economic challenger."""
    if baseline.events:
        raise ValueError("K117_CALLABLE_ALREADY_USED_NO_REPLAY")
    if passive.build(baseline, enabled=False, observations=[]) is not baseline:
        raise ValueError("PASSIVE_DISABLED_NOT_IDENTICAL")
    sessions = []
    wrapped = passive.build(baseline, enabled=True, observations=sessions)
    result = wrapped(frames, costs, windows)
    verify_parity(result, baseline.events, saved, expected_count)
    entries = passive.join_all117(sessions, saved["raw_trades"])
    if len(entries) != expected_count:
        raise ValueError("K117_TRACE_ENTRY_COVERAGE_INCOMPLETE")
    return sessions, entries


def bind_runtime(input_dir):
    """Only saved rows, module bytes and callable construction. No frame load/run."""
    saved, summary, freeze = load_saved(input_dir)
    prior_path = ROOT / "research/campaigns/scalp7_20261021/k126_loss_repair_parallel_v1/work_c/run_owner_observer.py"
    checked(prior_path, PRIOR_HELPER_SHA)
    prior = load_module("_k117_pinned_common_guard", prior_path)
    # Verify the full execution freeze, including unused historical bookkeeping
    # files, without invoking any writer/queue/claim functions from those files.
    for name, pin in freeze["code_sha256"].items():
        checked(Path(name), pin)
    for path, pin in prior.RUNTIME_PINS.items():
        checked(path, pin)
    checked(PRIOR_C / "state_lifetime_adapter.py", STATE_CODE_SHA)
    checked(STAGE / "objective_lifetime.py", PINS["objective_lifetime.py"])
    sys.path[:0] = [str(SOURCE_STAGE), str(PRIOR_C), str(STAGE)]
    structure = load_module("_k117_frozen_structure", SOURCE_STAGE / "structural_failure.py")
    h = structure.h
    for path, pin in prior.REPO_PINS.items():
        checked(h.REPO / path, pin)
    h.timeout.verify_dependencies()
    objective = load_module("_k117_frozen_objective", STAGE / "objective_lifetime.py")
    incumbent = structure.ExitComparison(True).build()
    source_text = inspect.getsource(h.k._fresh_touch_successor)
    if sha(source_text.encode()) != SOURCE_FUNCTION_SHA:
        raise ValueError("K117_NATIVE_FUNCTION_CHANGED")
    if objective.build(incumbent, source_text=source_text, enabled=False) is not incumbent:
        raise ValueError("K117_BUILD_DISABLED_NOT_IDENTICAL")
    baseline = objective.build(incumbent, source_text=source_text, enabled=True)
    if baseline.candidate_identity != BASELINE or baseline.events:
        raise ValueError("K117_BUILD_IDENTITY_OR_EVENTS_CHANGED")
    cache_manifest = json.loads(checked(CACHE / "INPUT_CACHE.json", CACHE_MANIFEST_SHA))
    binding = json.loads(checked(h.BASE / "CHRONO_SOURCE_BINDING.json", prior.BINDING_SHA))
    for symbol in ORDER:
        if binding[symbol]["full_csv_sha256"] != FULL_CSV_SHA[symbol]:
            raise ValueError("K117_SOURCE_BINDING_CHANGED:" + symbol)
    from backend.research.rebuild import scalp7_source_data_v2 as source
    require_order(source.SYMBOLS)
    if set(cache_manifest["symbols"]) != set(ORDER):
        raise ValueError("K117_CACHE_SYMBOL_SET_CHANGED")
    return prior, structure, baseline, saved, summary, cache_manifest


def run(args):
    if args.bind_only:
        if args.run_once or args.output_dir is not None:
            raise ValueError("BIND_ONLY_CANNOT_START_OR_WRITE")
        prior, structure, baseline, saved, summary, manifest = bind_runtime(args.baseline_input_dir)
        sys.path.insert(0, str(HERE))
        import passive_exit_observer as passive
        if passive.build(baseline, enabled=False, observations=[]) is not baseline:
            raise ValueError("PASSIVE_DISABLED_NOT_IDENTICAL")
        passive.build(baseline, enabled=True, observations=[])
        print(json.dumps({"scope": SCOPE, "status": "PINNED_K117_BUILD_ONLY_PASS",
                          "baseline_commit": BASELINE_COMMIT, "raw_rows": len(saved["raw_trades"]),
                          "prices_loaded": False, "callable_invocations": 0,
                          "output_files_written": 0, "new_policy_comparisons": 0}))
        return
    if args.owner_ack != OWNER or not args.run_once or args.output_dir is None:
        raise ValueError("A_OWNER_ACK_AND_EXPLICIT_RUN_ONCE_REQUIRED")
    prior, structure, baseline, saved, summary, manifest = bind_runtime(args.baseline_input_dir)
    h = structure.h
    output = args.output_dir.resolve()
    protected = (STAGE, SOURCE_STAGE, PRIOR_C, CACHE, h.BASE, h.REPO, ROOT)
    if any(output.is_relative_to(p.resolve()) for p in protected):
        raise ValueError("ISOLATED_ADD_ONLY_OUTPUT_REQUIRED")
    output.mkdir(parents=False, exist_ok=False)
    started = False
    try:
        sys.path.insert(0, str(prior.GUARD_STAGE))
        cap = load_module("_k117_existing_capacity", prior.GUARD_STAGE / "guard_exact_allocation_once.py")
        cap.S = output
        cap.original.S = output
        cap.original.REQUESTS = 0
        # Only live_capacity/local_busy are called. Never main/update/queue.
        with prior.existing_lock(h.BASE / "paired.lock"):
            capacity = prior.require_capacity(cap)
            from backend.research.rebuild import scalp7_rolling_context_v2 as context
            import pandas as pd
            frames, frame_receipts = {}, {}
            for symbol in ORDER:
                item = manifest["symbols"][symbol]
                path = (CACHE / item["path"]).resolve()
                if not path.is_relative_to(CACHE.resolve()):
                    raise ValueError("K117_CACHE_PATH_ESCAPE")
                raw = checked(path, item["sha256"])
                frame = pd.read_csv(io.BytesIO(raw), compression="gzip", float_precision="round_trip")
                csv_sha = sha(frame.to_csv(index=False).encode())
                if len(frame) != 17519 or csv_sha != FULL_CSV_SHA[symbol]:
                    raise ValueError("K117_FULL_FRAME_CHANGED:" + symbol)
                frames[symbol] = frame
                frame_receipts[symbol] = {"rows": len(frame), "cache_sha256": sha(raw), "full_csv_sha256": csv_sha}
            require_order(ORDER, frames)
            checked(CACHE / "INPUT_CACHE.json", CACHE_MANIFEST_SHA)
            windows = json.loads((h.REPO / "research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json").read_bytes())["windows"]
            costs = json.loads((h.REPO / "research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json").read_bytes())["costs_bps"]
            capacity = prior.require_capacity(cap)
            prior.save_new(output, "STARTED.json", {"scope": SCOPE, "owner": OWNER,
                "at_utc": datetime.now(timezone.utc).isoformat(), "baseline_commit": BASELINE_COMMIT,
                "source_inputs": frame_receipts, "source_order": ORDER,
                "cache_manifest_sha256": CACHE_MANIFEST_SHA, "rows_plain_sha256": ROWS_PLAIN_SHA,
                "capacity_evidence": capacity, "new_policy_comparisons": 0, "no_blind_retry": True})
            started = True
            # Preserve full 365-day context, native segments/gaps and source order.
            bound, fits = context.bind_context(frames, context.cross_features(frames), windows)
            fit_sha = sha(json.dumps(fits, sort_keys=True, separators=(",", ":")).encode())
            if fit_sha != prior.CONTEXT_SHA or fit_sha != summary["context_fit_sha256"]:
                raise ValueError("K117_CONTEXT_FIT_CHANGED")
            sys.path.insert(0, str(HERE))
            import passive_exit_observer as passive
            sessions, entries = observe_once(baseline, bound, costs, windows, saved, passive)
            all_pin = prior.save_new(output, "EXIT_TRACE_ALL_CALLS.json.gz", sessions, compressed=True)
            entry_pin = prior.save_new(output, "EXIT_TRACE_ALL117.json.gz", entries, compressed=True)
            receipt = {"scope": SCOPE, "owner": OWNER, "baseline_identity": BASELINE,
                "baseline_commit": BASELINE_COMMIT, "classification": "PASSIVE_EXACT_K117_NOT_NEW_ECONOMIC_RESULT",
                "raw117_exact": True, "unresolved_exact": True, "boundary_exact": True,
                "native_traces_exact": True, "objective_expiry_events_exact": True,
                "trace_calls": len(sessions), "trace_entries": len(entries),
                "baseline_stored_metrics": summary["child"],
                "carry_adjusted_metrics_source": "PINNED_SAVED_SUMMARY_NOT_RECOMPUTED_OR_NEW_ECONOMICS",
                "carry_reference_replays": 0, "new_policy_comparisons": 0, "actual_orders": 0,
                "context_fit_sha256": fit_sha, "source_inputs": frame_receipts,
                "files": {"EXIT_TRACE_ALL_CALLS.json.gz": all_pin, "EXIT_TRACE_ALL117.json.gz": entry_pin}}
            prior.save_new(output, "PASSIVE_EXIT_OBSERVER_RECEIPT.json", receipt)
            print(json.dumps({"scope": SCOPE, "raw117_exact": True, "trace_entries": len(entries),
                              "receipt": str(output / "PASSIVE_EXIT_OBSERVER_RECEIPT.json")}))
    except Exception as exc:
        prior.save_new(output, "HOLD.json", {"scope": SCOPE, "error_type": type(exc).__name__,
            "error": str(exc), "source_run_started": started, "no_blind_retry": True})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-input-dir", type=Path, default=STAGE)
    parser.add_argument("--bind-only", action="store_true")
    parser.add_argument("--owner-ack")
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
