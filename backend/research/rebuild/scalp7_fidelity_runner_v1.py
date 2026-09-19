"""Five reserved source-fidelity identities; sole Work owner; saved-only CI.

The existing 12-month windows are inspected historical diagnostics. No fresh,
account-return, promotion, order or live authority follows from this runner.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import economic7_campaign_registry_v1 as registry
from backend.research.rebuild import scalp7_campaign_v2 as base
from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild import scalp7_source_binding_repair_v2 as binding
from backend.research.rebuild import scalp7_source_data_v2 as source

ROOT = base.ROOT
OUT = ROOT / "research/campaigns/scalp7_20260917/source_fidelity_v1"
RUNTIME = Path("/home/z/z/runtime/scalp7_source_fidelity_20260917")
SCOPE = "SCALP7_AND_MATERIAL20_SOURCE_FIDELITY_REPAIR_AFTER_PR1339_V1"
OWNER = "WORK_ROOT_SINGLE_ECONOMIC_OWNER"
SELECTION = OUT / "BATCH_SELECTION.json"


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def packed_write(path: Path, value: Any) -> None:
    raw = gzip.compress(
        json.dumps(value, sort_keys=True, allow_nan=False).encode(), mtime=0
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)


def unpack(path: Path) -> Any:
    return json.loads(gzip.decompress(path.read_bytes()))


def window_rows(
    rows: list[dict[str, Any]], windows: list[dict[str, Any]], partition: str
) -> list[dict[str, Any]]:
    selected = {w["label"]: w for w in windows if w["partition"] == partition}
    return [
        r
        for r in rows
        if r["window_label"] in selected
        and selected[r["window_label"]]["start_ms"] <= r["signal_ts_ms"]
        and r["outcome_available_ts_ms"] < selected[r["window_label"]]["end_ms"]
    ]


def summarize(
    rows: list[dict[str, Any]], windows: list[dict[str, Any]]
) -> dict[str, Any]:
    output = {}
    for partition in ("validation", "rolling"):
        ww = [w for w in windows if w["partition"] == partition]
        use = window_rows(rows, windows, partition)
        output[partition] = {
            "cost1x": metrics.summarize(use, ww[0]["start_ms"], ww[-1]["end_ms"]),
            "cost2x": metrics.summarize(use, ww[0]["start_ms"], ww[-1]["end_ms"], 2),
            "windows1x": metrics.rolling_summary(use, ww),
            "windows2x": metrics.rolling_summary(use, ww, 2),
        }
        for cost in ("cost1x", "cost2x"):
            m = output[partition][cost]
            m["Gross_bps_T"] = m["Gross_bps"] / m["T"] if m["T"] else None
            m["Cost_bps_T"] = m["Cost_bps"] / m["T"] if m["T"] else None
    return output


def validate_selection(selection: dict[str, Any]) -> None:
    candidates = selection["candidates"]
    if not (len(candidates) == selection["max_candidates"] <= 6):
        raise ValueError("FIDELITY_CANDIDATE_BUDGET")
    if not (0 < selection["max_full_executions"] <= 6):
        raise ValueError("FIDELITY_EXECUTION_BUDGET")
    if len({s["identity"] for s in candidates.values()}) != len(candidates):
        raise ValueError("FIDELITY_DUPLICATE_IDENTITY")


def verify_freeze(alias: str) -> dict[str, Any]:
    base.verify_freeze()
    frozen = read(OUT / "freezes" / (alias + ".json"))
    for path, expected in frozen["hashes"].items():
        if base.sha(ROOT / path) != expected:
            raise ValueError("FIDELITY_FROZEN_HASH_DRIFT:" + path)
    return frozen


def freeze(alias: str) -> dict[str, Any]:
    path = OUT / "freezes" / (alias + ".json")
    if path.exists():
        return verify_freeze(alias)
    original = base.verify_freeze()
    selection = read(SELECTION)
    validate_selection(selection)
    spec = selection["candidates"][alias]
    mod = base.module(spec["module"])
    gate = read(ROOT / spec["eligibility_path"])
    if gate["state"] != "READY_FOR_ECONOMIC_DIAGNOSTIC" or gate[
        "module_sha256"
    ] != base.sha(ROOT / "backend/research/rebuild" / (spec["module"] + ".py")):
        raise ValueError("SOURCE_CASE_CODE_REVIEW_GATE")
    dependencies = [
        spec["eligibility_path"],
        "tests/test_scalp7_fidelity_runner_v1.py",
        "research/campaigns/scalp7_20260917/source_fidelity_v1/audits/RUNNER_INDEPENDENT_REVIEW.json",
        "research/campaigns/scalp7_20260915/broad_rebuild_v2/ROLLING_CONTEXT_FITS_V2.json",
        "backend/research/rebuild/economic7_canonical_history_v1.py",
        "backend/research/rebuild/a1_benchmark25_donor_native_replay_v1.py",
        "backend/research/rebuild/a1_exact25_generic_evaluator_three_lane_v1.py",
        "backend/research/rebuild/benchmark25_donor_native_policy_v1.py",
        "backend/research/rebuild/replay_acceleration_v1.py",
        "backend/research/rebuild/benchmark25_transfer_overlay_v1.py",
        "backend/research/rebuild/policy_kernel_v1.py",
        str(SELECTION.relative_to(ROOT)),
        "backend/research/rebuild/scalp7_fidelity_runner_v1.py",
        "backend/research/rebuild/scalp7_source_binding_repair_v2.py",
        "backend/research/rebuild/" + spec["module"] + ".py",
        *spec["verified_case_and_review_paths"],
    ]
    if spec.get("cached_parent"):
        p = ROOT / spec["cached_parent"]
        info = read(p)
        dependencies.extend([spec["cached_parent"], info["ledger_path"]])
        if base.sha(ROOT / info["ledger_path"]) != info["ledger_sha256"]:
            raise ValueError("CACHED_PARENT_LEDGER_DRIFT")
    for p in spec["verified_case_and_review_paths"]:
        if not (ROOT / p).is_file():
            raise ValueError("SOURCE_CASE_REVIEW_REQUIRED:" + p)
    value = {
        "scope": SCOPE,
        "owner": OWNER,
        "alias": alias,
        "candidate": spec,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_master_sha": selection["base_master_sha"],
        "hashes": {p: base.sha(ROOT / p) for p in dependencies},
        "rule_spec": mod.SPEC,
        "rule_sha256": mod.SPEC_SHA256,
        "data_sha256": base.digest(original["data_hashes"]),
        "cost_sha256": original["cost_sha256"],
        "windows": original["windows"],
        "window_sha256": base.digest(original["windows"]),
        "execution": "UNCHANGED_UTC_NEXT_OPEN_STOP_FIRST_GAPS_UNRESOLVED_V2_WITH_CASHFLOW_OBSERVER",
        "execution_sha256": base.sha(
            ROOT / "backend/research/rebuild/scalp7_execution_v2.py"
        ),
        "initial_capital": "independent flat per identity/window; original notional 1 per symbol; no account curve",
        "history": "ALREADY_INSPECTED_12M_DEV_DIAGNOSTIC_NOT_UNTOUCHED_OOS_OR_FRESH",
        "fresh_T": 0,
        "order": "BLOCKED",
        "live": "BLOCKED",
        "promotion": False,
    }
    base.write_json(path, value)
    return value


def prepare(tf: int, windows: list[dict[str, Any]]) -> dict[str, Any]:
    all_frames = {
        t: source.load_candles(
            base.SOURCE_ROOT, t, cache_dir=base.RUNTIME / "candle_cache"
        )
        for t in sorted({30, tf})
    }
    for t, frames in all_frames.items():
        expected = read(
            ROOT / f"research/campaigns/scalp7_20260915/SOURCE_DATA_V2_{t}M.json"
        )
        if set(frames) != set(expected["symbols"]):
            raise ValueError("FIDELITY_SOURCE_COHORT_DRIFT")
        for symbol, frame in frames.items():
            pin = expected["symbols"][symbol]
            if (
                len(frame) != pin["bars"]
                or frame.segment_id.nunique() != pin["segments"]
                or frame.attrs != pin["attrs"]
            ):
                raise ValueError("FIDELITY_SOURCE_BINDING_DRIFT")
    bound, fits = context.bind_context(
        all_frames[tf], context.cross_features(all_frames[30]), windows
    )
    if fits != read(base.REPORT / "ROLLING_CONTEXT_FITS_V2.json"):
        raise ValueError("FIDELITY_CONTEXT_FIT_DRIFT")
    return bound


def cached_parent_signals(
    spec: dict[str, Any], frames: dict[str, Any], costs: dict[str, float]
) -> list[dict[str, Any]]:
    info = read(ROOT / spec["cached_parent"])
    original = info["candidate"]
    mod = base.module(original["module"])
    work = (
        mod.prepare_frames(frames)
        if original["module"] == "scalp7_materials_program_v2"
        else frames
    )
    signals = binding.bind_segments(base._signals(original, work, costs), work)
    payload = unpack(ROOT / info["ledger_path"])
    rows = payload["trades"] + [
        {
            "symbol": r["position"]["signal"]["symbol"],
            "signal_ts_ms": r["position"]["signal"]["signal_ts_ms"],
            "side": r["position"]["signal"]["side"],
            "signal": r["position"]["signal"],
        }
        for r in payload["unresolved"]
    ]
    by_key = {(s["symbol"], s["signal_ts_ms"], s["side"]): s for s in signals}
    if len(by_key) != len(signals):
        raise ValueError("CACHED_PARENT_DUPLICATE_SIGNAL_KEY")
    for row in rows:
        key = (row["symbol"], row["signal_ts_ms"], row["side"])
        if key not in by_key:
            raise ValueError("CACHED_PARENT_ENTRY_EVENT_MISSING")
        actual, prior = dict(by_key[key]), dict(row["signal"])
        actual["segment_id"] = str(actual["segment_id"])
        prior["segment_id"] = str(prior["segment_id"])
        if actual != prior:
            raise ValueError("CACHED_PARENT_SIGNAL_RECONSTRUCTION_DRIFT")
    return signals


def run(alias: str) -> dict[str, Any]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "root_execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run_locked(alias)


def _run_locked(alias: str) -> dict[str, Any]:
    frozen = verify_freeze(alias)
    spec = frozen["candidate"]
    selection = read(SELECTION)
    validate_selection(selection)
    dest = OUT / "results" / (alias + ".json")
    ledger = registry.CampaignLedger(RUNTIME / "candidate_registry.sqlite3")
    ledger.create_scope(
        SCOPE,
        OWNER,
        selection["max_candidates"],
        selection["max_full_executions"],
        selection,
    )
    claim = registry.CandidateIdentity(
        candidate_id=spec["identity"],
        strategy_id=spec["lane"],
        baseline_id=spec["parent"],
        changed_axis=spec["axis"],
        rule_sha256=base.digest(
            {
                "spec": frozen["rule_sha256"],
                "code": frozen["hashes"],
                "execution": frozen["execution_sha256"],
            }
        ),
        data_sha256=frozen["data_sha256"],
        cost_sha256=frozen["cost_sha256"],
        window_sha256=frozen["window_sha256"],
    )
    reserved = ledger.reserve(SCOPE, OWNER, claim)
    if not reserved["new"]:
        if reserved["state"] == "COMPLETED" and dest.exists():
            terminal = json.loads(reserved["result_json"])
            if terminal["sha256"] != base.sha(dest):
                raise ValueError("FIDELITY_COMPLETED_RECEIPT_DRIFT")
            return verify_saved(alias)
        raise ValueError("NO_REPEAT_OF_RESERVED_OR_STARTED_IDENTITY:" + alias)
    started = False
    try:
        if dest.exists():
            raise ValueError("FIDELITY_ORPHAN_RECEIPT_REQUIRES_RECONCILIATION")
        frames = prepare(spec["tf"], frozen["windows"])
        costs = read(base.COST_PATH)["costs_bps"]
        mod = base.module(spec["module"])
        work = mod.prepare_frames(frames) if hasattr(mod, "prepare_frames") else frames
        signals = mod.generate_signals(work, costs=costs, identity=spec["identity"])
        if any(s["identity"] != spec["identity"] for s in signals):
            raise ValueError("FIDELITY_GENERATED_IDENTITY_MISMATCH")
        signals = binding.bind_segments(signals, work)
        if spec.get("cached_parent"):
            originals = cached_parent_signals(spec, frames, costs)
            packed_write(
                OUT / "results" / (alias + ".parent_signals.json.gz"), originals
            )
        packed_write(OUT / "results" / (alias + ".signals.json.gz"), signals)
        if not ledger.start(claim.key, OWNER):
            raise ValueError("FIDELITY_START_CONFLICT")
        started = True
        print("START_FULL", alias, "signals", len(signals), flush=True)
        trades, unresolved, receipts = [], [], []
        for w in frozen["windows"]:
            start, end = w["start_ms"], w["end_ms"]
            use = [s for s in signals if start <= s["signal_ts_ms"] < end]
            sliced = {
                symbol: f[
                    (f.open_ts_ms >= start - 200 * spec["tf"] * 60_000)
                    & (f.close_ts_ms <= end)
                ].reset_index(drop=True)
                for symbol, f in work.items()
            }
            result = binding.replay(
                use,
                sliced,
                costs,
                identity=spec["identity"],
                exit_update=mod.exit_update,
                entry_update=getattr(mod, "entry_update", None),
            )
            for r in result["trades"]:
                r.update(window_label=w["label"], partition=w["partition"])
            for r in result["unresolved"]:
                r.update(
                    window_label=w["label"], window_end_ms=end, partition=w["partition"]
                )
            trades.extend(result["trades"])
            unresolved.extend(result["unresolved"])
            receipts.append(
                {
                    "window": w,
                    "signal_count": len(use),
                    "rejections": result["rejections"],
                    "unresolved_count": len(result["unresolved"]),
                }
            )
            print("WINDOW_DONE", alias, w["label"], len(result["trades"]), flush=True)
        payload = {
            "trades": trades,
            "unresolved": unresolved,
            "window_receipts": receipts,
        }
        path = OUT / "results" / (alias + ".trades.json.gz")
        packed_write(path, payload)
        value = {
            "alias": alias,
            "candidate": spec,
            "identity_key": claim.key,
            "freeze_path": str((OUT / "freezes" / (alias + ".json")).relative_to(ROOT)),
            "freeze_sha256": base.sha(OUT / "freezes" / (alias + ".json")),
            "ledger_path": str(path.relative_to(ROOT)),
            "ledger_sha256": base.sha(path),
            "summary": summarize(trades, frozen["windows"]),
            "unresolved_count": len(unresolved),
            "window_receipts": receipts,
            "signal_path": str(
                (OUT / "results" / (alias + ".signals.json.gz")).relative_to(ROOT)
            ),
            "signals_sha256": base.sha(OUT / "results" / (alias + ".signals.json.gz")),
            "parent_signals_reconstructed_no_economic_replay": bool(
                spec.get("cached_parent")
            ),
            "fresh_T": 0,
            "order": "BLOCKED",
            "live": "BLOCKED",
            "promotion": False,
        }
        if spec.get("cached_parent"):
            pp = OUT / "results" / (alias + ".parent_signals.json.gz")
            value.update(
                parent_signals_path=str(pp.relative_to(ROOT)),
                parent_signals_sha256=base.sha(pp),
            )
        base.write_json(dest, value)
        verified = verify_saved(alias)
        ledger.finish(
            claim.key,
            OWNER,
            "COMPLETED",
            {"receipt": str(dest), "sha256": base.sha(dest)},
        )
        print("DONE_FULL", alias, value["summary"]["rolling"]["cost1x"], flush=True)
        return verified
    except Exception as exc:
        ledger.finish(
            claim.key, OWNER, "FAILED" if started else "HOLD", {"error": str(exc)}
        )
        raise


def verify_saved(alias: str) -> dict[str, Any]:
    frozen = verify_freeze(alias)
    info = read(OUT / "results" / (alias + ".json"))
    if base.sha(ROOT / info["freeze_path"]) != info["freeze_sha256"]:
        raise ValueError("FIDELITY_FREEZE_RECEIPT_DRIFT")
    for path_key, sha_key in (
        ("ledger_path", "ledger_sha256"),
        ("signal_path", "signals_sha256"),
        ("parent_signals_path", "parent_signals_sha256"),
    ):
        if path_key in info and base.sha(ROOT / info[path_key]) != info[sha_key]:
            raise ValueError("FIDELITY_SAVED_PAYLOAD_DRIFT:" + path_key)
    data = unpack(ROOT / info["ledger_path"])
    for r in data["trades"]:
        symbol, side = r["symbol"], r["side"]
        entry, exit_price = r["entry_prices"][symbol], r["exit_prices"][symbol]
        events = r["partial_cashflows"]
        terminal = r["terminal_fraction_original_notional"]
        if side not in (-1, 1) or not all(
            math.isfinite(v) and v > 0 for v in (entry, exit_price)
        ):
            raise ValueError("FIDELITY_CASHFLOW_PRICE")
        if not math.isfinite(terminal) or not 0 <= terminal <= 1:
            raise ValueError("FIDELITY_CASHFLOW_WEIGHT")
        for event in events:
            fraction, price = event["fraction_original_notional"], event["fill_price"]
            if (
                not math.isfinite(fraction)
                or not 0 < fraction < 1
                or not math.isfinite(price)
                or price <= 0
            ):
                raise ValueError("FIDELITY_CASHFLOW_EVENT")
            if (
                not r["entry_ts_ms"]
                <= event["fill_interval_start_ms"]
                < event["fill_interval_end_ms"]
                <= event["observed_at_ms"]
                <= r["outcome_available_ts_ms"]
            ):
                raise ValueError("FIDELITY_CASHFLOW_TIME")
        if (
            abs(terminal + sum(e["fraction_original_notional"] for e in events) - 1)
            > 1e-12
        ):
            raise ValueError("FIDELITY_CASHFLOW_WEIGHT")
        gross = side * (exit_price / entry - 1) * 10000 * terminal
        gross += sum(
            side
            * (e["fill_price"] / entry - 1)
            * 10000
            * e["fraction_original_notional"]
            for e in events
        )
        if (
            abs(gross - r["gross_bps"]) > 1e-7
            or abs(gross - r["cost_bps"] - r["net_bps"]) > 1e-7
        ):
            raise ValueError("FIDELITY_CASHFLOW_ARITHMETIC")
    if summarize(data["trades"], frozen["windows"]) != info["summary"]:
        raise ValueError("FIDELITY_SAVED_SUMMARY_DRIFT")
    if (
        len(data["unresolved"]) != info["unresolved_count"]
        or data["window_receipts"] != info["window_receipts"]
    ):
        raise ValueError("FIDELITY_UNRESOLVED_OR_RECEIPT_DRIFT")
    return {
        "alias": alias,
        "state": "PASS_SAVED_FIDELITY_NO_ECONOMIC_REPLAY",
        "raw_T": len(data["trades"]),
        "unresolved": len(data["unresolved"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "run", "verify"))
    parser.add_argument("alias")
    args = parser.parse_args()
    fn = {"freeze": freeze, "run": run, "verify": verify_saved}[args.command]
    print(json.dumps(fn(args.alias), sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
