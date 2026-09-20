"""Four approved paired economic-development identities; sole Work owner; saved-only CI.

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
from backend.research.rebuild import scalp7_source_binding_repair_v2 as binding

ROOT = base.ROOT
OUT = ROOT / "research/campaigns/scalp7_20260920/economic_development_v1"
RUNTIME = Path("/home/z/z/runtime/scalp7_economic_v1_20260920")
SCOPE = "G4_SCALP7_MATERIAL20_ECONOMIC_DEVELOPMENT_AFTER_PR1340_V1"
OWNER = "WORK_ROOT_SINGLE_ECONOMIC_OWNER"
SELECTION = OUT / "BATCH_SELECTION.json"
EXPECTED = {
    "SQ0": (
        "scalp7_squeeze_30m_context_15m_exec_control_v1",
        "scalp7_economic_squeeze_v1",
    ),
    "SQ2": (
        "scalp7_squeeze_30m_context_15m_high2_replacement_v1",
        "scalp7_economic_squeeze_v1",
    ),
    "R15": ("scalp7_rider_gmma_pullback_15m_exit15_v1", "scalp7_economic_rider_v1"),
    "R30": ("scalp7_rider_gmma_pullback_15m_exit30_v1", "scalp7_economic_rider_v1"),
}


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
    if set(candidates) != {"SQ0", "SQ2", "R15", "R30"}:
        raise ValueError("ECONOMIC_SELECTED_ALIASES_ONLY")
    if selection["max_candidates"] != 4 or selection["max_full_executions"] != 4:
        raise ValueError("ECONOMIC_FOUR_TOTAL_BUDGET")
    if selection["max_hypotheses"] != 2 or selection["scope_key"] != SCOPE:
        raise ValueError("ECONOMIC_SCOPE_BUDGET")
    if len({s["identity"] for s in candidates.values()}) != 4:
        raise ValueError("ECONOMIC_DUPLICATE_IDENTITY")
    if any(
        (candidates[a]["identity"], candidates[a]["module"]) != EXPECTED[a]
        for a in candidates
    ):
        raise ValueError("ECONOMIC_APPROVED_IDENTITIES_ONLY")
    if any(s["tf"] != 15 for s in candidates.values()):
        raise ValueError("ECONOMIC_EXECUTION_TIMEFRAME_15M")


def verify_batch() -> dict[str, Any]:
    selection = read(SELECTION)
    validate_selection(selection)
    freezes = {alias: verify_freeze(alias) for alias in selection["candidates"]}
    if len({x["frozen_at_utc"] for x in freezes.values()}) != 1:
        raise ValueError("ECONOMIC_ALL_FOUR_MUST_FREEZE_TOGETHER")
    return freezes


def freeze_all() -> dict[str, Any]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "root_execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _freeze_all_locked()


def _freeze_all_locked() -> dict[str, Any]:
    selection = read(SELECTION)
    validate_selection(selection)
    existing = [OUT / "freezes" / (a + ".json") for a in selection["candidates"]]
    if any(p.exists() for p in existing):
        return verify_batch()
    for spec in selection["candidates"].values():
        gate = read(ROOT / spec["eligibility_path"])
        module_path = ROOT / "backend/research/rebuild" / (spec["module"] + ".py")
        if gate["state"] != "READY_FOR_ECONOMIC_DIAGNOSTIC" or gate[
            "module_sha256"
        ] != base.sha(module_path):
            raise ValueError("ECONOMIC_ALL_SOURCE_CASE_GATES_REQUIRED")
    frozen_at = datetime.now(timezone.utc).isoformat()
    for alias in selection["candidates"]:
        _freeze_one(alias, frozen_at)
    return verify_batch()


def dependency_paths(selection: dict[str, Any]) -> set[str]:
    return {
        *selection["shared_dependency_paths"],
        str(SELECTION.relative_to(ROOT)),
        "backend/research/rebuild/scalp7_economic_runner_v1.py",
        "backend/research/rebuild/scalp7_source_binding_repair_v2.py",
        "backend/research/rebuild/scalp7_fidelity_runner_v1.py",
        *[
            p
            for c in selection["candidates"].values()
            for p in [
                c["eligibility_path"],
                "backend/research/rebuild/" + c["module"] + ".py",
                *c["verified_case_and_review_paths"],
            ]
        ],
    }


def verify_freeze(alias: str) -> dict[str, Any]:
    original = base.verify_freeze()
    selection = read(SELECTION)
    validate_selection(selection)
    frozen = read(OUT / "freezes" / (alias + ".json"))
    spec = selection["candidates"][alias]
    if set(frozen["hashes"]) != dependency_paths(selection):
        raise ValueError("ECONOMIC_FROZEN_DEPENDENCY_MEMBERSHIP")
    for path, expected_hash in frozen["hashes"].items():
        if base.sha(ROOT / path) != expected_hash:
            raise ValueError("ECONOMIC_FROZEN_HASH_DRIFT:" + path)
    mod = base.module(spec["module"])
    expected = {
        "scope": SCOPE,
        "owner": OWNER,
        "alias": alias,
        "candidate": spec,
        "base_master_sha": selection["base_master_sha"],
        "rule_spec": mod.SPEC,
        "rule_sha256": mod.SPEC_SHA256,
        "data_sha256": base.digest(original["data_hashes"]),
        "cost_sha256": original["cost_sha256"],
        "windows": original["windows"],
        "window_sha256": base.digest(original["windows"]),
        "execution_sha256": base.sha(
            ROOT / "backend/research/rebuild/scalp7_execution_v2.py"
        ),
        "fresh_T": 0,
        "order": "BLOCKED",
        "live": "BLOCKED",
        "promotion": False,
    }
    for key, value in expected.items():
        if base.digest(frozen[key]) != base.digest(value):
            raise ValueError("ECONOMIC_FROZEN_SEMANTIC_DRIFT:" + key)
    return frozen


def _freeze_one(alias: str, frozen_at: str) -> dict[str, Any]:
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
    dependencies = sorted(dependency_paths(selection))
    for p in spec["verified_case_and_review_paths"]:
        if not (ROOT / p).is_file():
            raise ValueError("SOURCE_CASE_REVIEW_REQUIRED:" + p)
    value = {
        "scope": SCOPE,
        "owner": OWNER,
        "alias": alias,
        "candidate": spec,
        "frozen_at_utc": frozen_at,
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


def prepare(
    tf: int, windows: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if tf != 15:
        raise ValueError("ECONOMIC_15M_EXECUTION_REQUIRED")
    from backend.research.rebuild import scalp7_fidelity_runner_v1 as prior

    return prior.prepare(15, windows), prior.prepare(30, windows)


def candidate_claim(frozen: dict[str, Any]) -> registry.CandidateIdentity:
    spec = frozen["candidate"]
    return registry.CandidateIdentity(
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


def run(alias: str) -> dict[str, Any]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "root_execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run_locked(alias)


def _run_locked(alias: str) -> dict[str, Any]:
    frozen = verify_batch()[alias]
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
    claim = candidate_claim(frozen)
    reserved = ledger.reserve(SCOPE, OWNER, claim)
    if not reserved["new"]:
        if reserved["state"] == "COMPLETED" and dest.exists():
            terminal = json.loads(reserved["result_json"])
            if terminal["sha256"] != base.sha(dest):
                raise ValueError("ECONOMIC_COMPLETED_RECEIPT_DRIFT")
            return verify_saved(alias)
        raise ValueError("NO_REPEAT_OF_RESERVED_OR_STARTED_IDENTITY:" + alias)
    started = False
    try:
        if dest.exists():
            raise ValueError("ECONOMIC_ORPHAN_RECEIPT_REQUIRES_RECONCILIATION")
        frames, context_frames = prepare(spec["tf"], frozen["windows"])
        costs = read(base.COST_PATH)["costs_bps"]
        mod = base.module(spec["module"])
        work = mod.prepare_frames(frames, context_frames, costs=costs)
        signals = mod.generate_signals(work, costs=costs, identity=spec["identity"])
        if any(s["identity"] != spec["identity"] for s in signals):
            raise ValueError("ECONOMIC_GENERATED_IDENTITY_MISMATCH")
        signals = binding.bind_segments(signals, work)
        packed_write(OUT / "results" / (alias + ".signals.json.gz"), signals)
        if not ledger.start(claim.key, OWNER):
            raise ValueError("ECONOMIC_START_CONFLICT")
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
            "parent_signals_reconstructed_no_economic_replay": False,
            "fresh_T": 0,
            "order": "BLOCKED",
            "live": "BLOCKED",
            "promotion": False,
        }
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
    if (
        info["alias"] != alias
        or info["candidate"] != frozen["candidate"]
        or info["identity_key"] != candidate_claim(frozen).key
        or info["fresh_T"] != 0
        or info["order"] != "BLOCKED"
        or info["live"] != "BLOCKED"
        or info["promotion"] is not False
    ):
        raise ValueError("ECONOMIC_SAVED_IDENTITY_OR_AUTHORITY")
    if base.sha(ROOT / info["freeze_path"]) != info["freeze_sha256"]:
        raise ValueError("ECONOMIC_FREEZE_RECEIPT_DRIFT")
    for path_key, sha_key in (
        ("ledger_path", "ledger_sha256"),
        ("signal_path", "signals_sha256"),
    ):
        if path_key in info and base.sha(ROOT / info[path_key]) != info[sha_key]:
            raise ValueError("ECONOMIC_SAVED_PAYLOAD_DRIFT:" + path_key)
    data = unpack(ROOT / info["ledger_path"])
    signals = unpack(ROOT / info["signal_path"])
    all_signals = (
        signals
        + [r["signal"] for r in data["trades"]]
        + [r["position"]["signal"] for r in data["unresolved"]]
    )
    if any(
        x["identity"] != frozen["candidate"]["identity"] or x["timeframe_min"] != 15
        for x in all_signals
    ):
        raise ValueError("ECONOMIC_SAVED_SIGNAL_IDENTITY")
    for r in data["trades"]:
        if r["identity"] != frozen["candidate"]["identity"] or not (
            r["signal_ts_ms"]
            <= r["entry_ts_ms"]
            <= r["exit_ts_ms"]
            <= r["outcome_available_ts_ms"]
        ):
            raise ValueError("ECONOMIC_SAVED_ROW_IDENTITY_OR_CAUSALITY")
        symbol, side = r["symbol"], r["side"]
        entry, exit_price = r["entry_prices"][symbol], r["exit_prices"][symbol]
        events = r["partial_cashflows"]
        terminal = r["terminal_fraction_original_notional"]
        if side not in (-1, 1) or not all(
            math.isfinite(v) and v > 0 for v in (entry, exit_price)
        ):
            raise ValueError("ECONOMIC_CASHFLOW_PRICE")
        if not math.isfinite(terminal) or not 0 <= terminal <= 1:
            raise ValueError("ECONOMIC_CASHFLOW_WEIGHT")
        for event in events:
            fraction, price = event["fraction_original_notional"], event["fill_price"]
            if (
                not math.isfinite(fraction)
                or not 0 < fraction < 1
                or not math.isfinite(price)
                or price <= 0
            ):
                raise ValueError("ECONOMIC_CASHFLOW_EVENT")
            if (
                not r["entry_ts_ms"]
                <= event["fill_interval_start_ms"]
                < event["fill_interval_end_ms"]
                <= event["observed_at_ms"]
                <= r["outcome_available_ts_ms"]
            ):
                raise ValueError("ECONOMIC_CASHFLOW_TIME")
        if (
            abs(terminal + sum(e["fraction_original_notional"] for e in events) - 1)
            > 1e-12
        ):
            raise ValueError("ECONOMIC_CASHFLOW_WEIGHT")
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
            raise ValueError("ECONOMIC_CASHFLOW_ARITHMETIC")
    if summarize(data["trades"], frozen["windows"]) != info["summary"]:
        raise ValueError("ECONOMIC_SAVED_SUMMARY_DRIFT")
    if (
        len(data["unresolved"]) != info["unresolved_count"]
        or data["window_receipts"] != info["window_receipts"]
    ):
        raise ValueError("ECONOMIC_UNRESOLVED_OR_RECEIPT_DRIFT")
    return {
        "alias": alias,
        "state": "PASS_SAVED_ECONOMIC_NO_ECONOMIC_REPLAY",
        "raw_T": len(data["trades"]),
        "unresolved": len(data["unresolved"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "run", "verify"))
    parser.add_argument("alias", nargs="?", choices=("SQ0", "SQ2", "R15", "R30"))
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_all()
    elif args.alias is None:
        parser.error("run/verify requires an approved alias")
    else:
        result = {"run": run, "verify": verify_saved}[args.command](args.alias)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
