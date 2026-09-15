"""Single-owner bounded Scalp7 campaign. Freeze, execute once, verify saved outputs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "research/campaigns/scalp7_20260915/broad_rebuild_v2"
RUNTIME = Path("/home/z/z/runtime/scalp7_broad_v2_20260915")
SOURCE_ROOT = Path("/home/z/z/runtime/economic7_campaign_20260915")
COST_PATH = ROOT / (
    "research/campaigns/scalp7_20260915/cost_snapshot_v2/"
    "SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
)
SCOPE = "SCALP7_15M30M_BROAD_REBUILD_MATERIAL_FUSION_AFTER_PR1337_V2"
OWNER = "WORK_ROOT_SINGLE_ECONOMIC_OWNER"
START = int(datetime(2025, 9, 15, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 9, 15, tzinfo=timezone.utc).timestamp() * 1000)


def module(name: str) -> Any:
    return importlib.import_module("backend.research.rebuild." + name)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("IMMUTABLE_ARTIFACT_CONFLICT:" + str(path))
        return
    path.write_bytes(raw)


def candidates() -> list[dict[str, Any]]:
    positive = module("scalp7_positive_lanes_v2")
    parent = module("scalp7_parent_controls_v2")
    mr = module("scalp7_mr_formation_v2")
    material = module("scalp7_materials_program_v2")
    result = []
    for identity in positive.IDENTITIES:
        result.append(
            {
                "identity": identity,
                "module": "scalp7_positive_lanes_v2",
                "tf": 30,
                "lane": (
                    "keltner_holygrail" if "keltner" in identity else "squeeze_break"
                ),
                "kind": "parent" if "parent" in identity else "frozen_chat_child",
                "parent": (
                    positive.KELTNER_PARENT
                    if "keltner" in identity
                    else positive.SQUEEZE_PARENT
                ),
            }
        )
    for lane, identity in parent.IDENTITIES.items():
        result.append(
            {
                "identity": identity,
                "module": "scalp7_parent_controls_v2",
                "tf": parent.TIMEFRAMES[lane],
                "lane": lane,
                "kind": "parent",
                "parent": identity,
            }
        )
    for name in ("rider", "break", "supertrend"):
        mod_name = "scalp7_" + name + "_architecture_v2"
        child = module(mod_name)
        result.append(
            {
                "identity": child.IDENTITY,
                "module": mod_name,
                "tf": child.TIMEFRAME_MIN,
                "lane": child.LANE,
                "kind": "architecture_child",
                "parent": parent.IDENTITIES[child.LANE],
            }
        )
    for identity in mr.IDENTITIES:
        result.append(
            {
                "identity": identity,
                "module": "scalp7_mr_formation_v2",
                "tf": 30,
                "lane": "cross_sectional_mean_reversion",
                "kind": (
                    "parent" if identity == mr.PARENT_IDENTITY else "frozen_mr_child"
                ),
                "parent": mr.PARENT_IDENTITY,
            }
        )
    for identity in material.IDENTITIES:
        name = identity.split("_30m_")[0]
        result.append(
            {
                "identity": identity,
                "module": "scalp7_materials_program_v2",
                "tf": 30,
                "lane": name,
                "kind": (
                    "material_control" if "control" in identity else "material_round1"
                ),
                "parent": name + "_30m_control_v2",
            }
        )
    return result


def freeze() -> dict[str, Any]:
    contract_path = REPORT / "CAMPAIGN_PREREGISTERED_V2.json"
    if contract_path.exists():
        return verify_freeze()
    context = module("scalp7_rolling_context_v2")
    catalog = candidates()
    names = {row["module"] for row in catalog} | {
        "scalp7_execution_v2",
        "scalp7_rolling_context_v2",
        "scalp7_metrics_v2",
        "scalp7_source_data_v2",
        "scalp7_campaign_v2",
        "economic7_campaign_registry_v1",
        "scalp7_portfolio_v2",
    }
    code_hashes = {
        "backend/research/rebuild/"
        + name
        + ".py": sha(ROOT / "backend/research/rebuild" / (name + ".py"))
        for name in sorted(names)
    }
    receipt_paths = [
        ROOT / "research/campaigns/scalp7_20260915" / name
        for name in ("SOURCE_DATA_V2_15M.json", "SOURCE_DATA_V2_30M.json")
    ]
    receipt_paths.extend(
        path
        for path in (
            ROOT / "research/campaigns/scalp7_20260915/source_time_v2"
        ).iterdir()
        if path.is_file()
    )
    receipt_paths.extend(path for path in COST_PATH.parent.iterdir() if path.is_file())
    dependency_paths = [
        "backend/research/rebuild/benchmark25_donor_state_machine_v2.py",
        "backend/research/rebuild/benchmark25_donor_state_machine_v2.json",
        "research/campaigns/scalp7_20260915/broad_v2/supertrend/PARENT_CONTROLS_FREEZE_V2.json",
        "research/campaigns/scalp7_20260915/SCALP7_MR_FORMATION_V2_PREREG.json",
    ]
    receipt_paths.extend(ROOT / name for name in dependency_paths)
    data_hashes = {str(path.relative_to(ROOT)): sha(path) for path in receipt_paths}
    contract = {
        "schema": "zel.scalp7.broad_rebuild_preregistered.v2",
        "scope_key": SCOPE,
        "owner": OWNER,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_master_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "candidates": catalog,
        "max_candidate_count": len(catalog),
        "max_historical_executions": len(catalog),
        "executions_per_identity": 1,
        "code_hashes": code_hashes,
        "data_hashes": data_hashes,
        "cost_path": str(COST_PATH.relative_to(ROOT)),
        "cost_sha256": sha(COST_PATH),
        "cost_stress": "same frozen fills and entry admission; debit1x/2x only, no second replay",
        "raw_history_start_ms": START,
        "raw_history_end_ms": END,
        "windows": context.windows(START, END),
        "training": "first90days context only; eachwindow prior90day quantiles; no train PnL",
        "signal_state": "continuous causal opportunity stream; window execution flat; autonomous MR shadow-position/excursion state remains continuous and may suppress boundary opportunities",
        "data_gap_policy": "missing4minutes retained; unresolvedpositions block restofwindow; nextindependentwindow startsflat",
        "rolling_interpretation": "chronological parameter OOS; strategy formation after inspected history; not genuine fresh",
        "primary_identities": [
            "scalp7_keltner_hg_parent_utc30m_v2",
            "scalp7_rider_15m_impulse_pullback_reclaim_v2",
            "scalp7_break_15m_anchored_retest_reclaim_v2",
            "scalp7_supertrend_native_impulse_pullback_30m_v2",
            "scalp7_squeeze_panic_cost4_parent_utc30m_v2",
            "mr_cross_sectional_v1_30m_causal_control_v2",
            "scalp7_micro_observed_tick_15m_v2",
        ],
        "material_round_budget": 3,
        "material_rounds_frozen_now": 1,
        "fusion": "BLOCKED_UNTIL_TWO_INDEPENDENT_FRESH_VERIFIED_B_AND_COSINE_LT_0P85",
        "forbidden_repeats": [
            "plain ADX/DMI",
            "plain Aroon",
            "plain KAMA/ER",
            "plain CMO",
            "generic strong close",
            "Keltner3bar no progress scratch",
            "Squeeze samehour longestduration owner",
            "PR1336 Keltner pre1R EMA20 loss",
            "PR1336 Squeeze failedrelease EMA34 momentum",
        ],
        "ssot": {
            "issue": 1334,
            "comments": [5685542390, 5685670313, 5685816128],
            "prs": [1331, 1332, 1333, 1335, 1337],
        },
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    write_json(contract_path, contract)
    return contract


def verify_freeze() -> dict[str, Any]:
    path = REPORT / "CAMPAIGN_PREREGISTERED_V2.json"
    contract = json.loads(path.read_text())
    for group in ("code_hashes", "data_hashes"):
        for name, expected in contract[group].items():
            if sha(ROOT / name) != expected:
                raise ValueError("FROZEN_SOURCE_CHANGED:" + name)
    if sha(COST_PATH) != contract["cost_sha256"]:
        raise ValueError("FROZEN_COST_CHANGED")
    return contract


def _signals(
    spec: dict[str, Any], frames: dict[str, pd.DataFrame], costs: dict[str, float]
) -> list[dict[str, Any]]:
    mod = module(spec["module"])
    name = spec["module"]
    if name == "scalp7_positive_lanes_v2":
        return mod.generate_signals(frames, costs=costs, identities=(spec["identity"],))
    if name in (
        "scalp7_parent_controls_v2",
        "scalp7_mr_formation_v2",
        "scalp7_materials_program_v2",
    ):
        return mod.generate_signals(frames, identity=spec["identity"])
    return mod.generate_signals(frames)


def run() -> dict[str, Any]:
    contract = verify_freeze()
    registry = module("economic7_campaign_registry_v1")
    engine = module("scalp7_execution_v2")
    metrics = module("scalp7_metrics_v2")
    source = module("scalp7_source_data_v2")
    context = module("scalp7_rolling_context_v2")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    ledger = registry.CampaignLedger(RUNTIME / "campaign.sqlite3")
    ledger.create_scope(
        SCOPE, OWNER, len(contract["candidates"]), len(contract["candidates"]), contract
    )
    frames = {
        tf: source.load_candles(SOURCE_ROOT, tf, cache_dir=RUNTIME / "candle_cache")
        for tf in (15, 30)
    }
    for tf, by_symbol in frames.items():
        expected = json.loads(
            (
                ROOT
                / "research/campaigns/scalp7_20260915"
                / f"SOURCE_DATA_V2_{tf}M.json"
            ).read_text()
        )
        if set(by_symbol) != set(expected["symbols"]):
            raise ValueError("SOURCE_COHORT_DRIFT")
        for symbol, frame in by_symbol.items():
            pinned = expected["symbols"][symbol]
            if (
                len(frame) != pinned["bars"]
                or frame["segment_id"].nunique() != pinned["segments"]
            ):
                raise ValueError("SOURCE_COVERAGE_DRIFT")
            if frame.attrs != pinned["attrs"]:
                raise ValueError("SOURCE_ATTRIBUTE_BINDING_DRIFT")
    features = context.cross_features(frames[30])
    fits = []
    for tf in (15, 30):
        frames[tf], fits = context.bind_context(
            frames[tf], features, contract["windows"]
        )
    write_json(REPORT / "ROLLING_CONTEXT_FITS_V2.json", fits)
    costs = json.loads(COST_PATH.read_text())["costs_bps"]
    report: dict[str, Any] = {
        "scope_key": SCOPE,
        "freeze_sha256": sha(REPORT / "CAMPAIGN_PREREGISTERED_V2.json"),
        "rows": {},
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    for spec in contract["candidates"]:
        identity = spec["identity"]
        evidence_path = REPORT / "results" / (identity + ".json")
        output_path = REPORT / "results" / (identity + ".trades.json.gz")
        claim = registry.CandidateIdentity(
            candidate_id=identity,
            strategy_id=spec["lane"],
            baseline_id=spec["parent"],
            changed_axis=spec["kind"] + ":" + identity,
            rule_sha256=digest({"code": contract["code_hashes"], "identity": spec}),
            data_sha256=digest(contract["data_hashes"]),
            cost_sha256=contract["cost_sha256"],
            window_sha256=digest(contract["windows"]),
        )
        reserved = ledger.reserve(SCOPE, OWNER, claim)
        if not reserved["new"]:
            if reserved["state"] == "COMPLETED" and evidence_path.exists():
                saved = json.loads(reserved["result_json"])
                if sha(evidence_path) != saved["evidence_sha256"]:
                    raise ValueError("SAVED_EVIDENCE_HASH_MISMATCH:" + identity)
                evidence = json.loads(evidence_path.read_text())
                if sha(ROOT / evidence["ledger_path"]) != saved["ledger_sha256"]:
                    raise ValueError("SAVED_LEDGER_HASH_MISMATCH:" + identity)
                report["rows"][identity] = evidence
                print("REUSE_SAVED", identity, flush=True)
                continue
            raise ValueError("NO_AUTOMATIC_RERUN:" + identity + ":" + reserved["state"])
        # Freeze claim precedes all new economics; feature-only signal generation
        # is not a completed economic execution.
        mod = module(spec["module"])
        work = frames[int(spec["tf"])]
        if spec["module"] == "scalp7_materials_program_v2":
            work = mod.prepare_frames(work)
        signals = _signals(spec, work, costs)
        if not ledger.start(claim.key, OWNER):
            raise ValueError("EXECUTION_CLAIM_NOT_STARTED")
        print("START", identity, "signals", len(signals), flush=True)
        all_rows: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        receipts = []
        try:
            for window in contract["windows"]:
                start, end = int(window["start_ms"]), int(window["end_ms"])
                chosen = [s for s in signals if start <= int(s["signal_ts_ms"]) < end]
                prefix_start = start - 200 * int(spec["tf"]) * 60_000
                sliced = {
                    symbol: frame[
                        (frame["open_ts_ms"] >= prefix_start)
                        & (frame["close_ts_ms"] <= end)
                    ].reset_index(drop=True)
                    for symbol, frame in work.items()
                }
                out = engine.replay(
                    chosen,
                    sliced,
                    costs,
                    identity=identity,
                    exit_update=mod.exit_update,
                    entry_update=getattr(mod, "entry_update", None),
                )
                for row in out["trades"]:
                    row["window_label"] = window["label"]
                    row["partition"] = window["partition"]
                for position in out["unresolved"]:
                    position["window_label"] = window["label"]
                    position["window_end_ms"] = end
                all_rows.extend(out["trades"])
                unresolved.extend(out["unresolved"])
                receipts.append(
                    {
                        "window": window,
                        "signal_count": out["signal_count"],
                        "unresolved_count": len(out["unresolved"]),
                        "rejections": out["rejections"],
                        "cost1x": metrics.summarize(out["trades"], start, end),
                        "cost2x": metrics.summarize(out["trades"], start, end, 2),
                    }
                )
            rolling_windows = [
                w for w in contract["windows"] if w["partition"] == "rolling"
            ]
            rolling_rows = [r for r in all_rows if r["partition"] == "rolling"]
            # Exclude exact window end outcomes, not merely the final campaign end.
            ends = {w["label"]: w["end_ms"] for w in contract["windows"]}
            rolling_rows = [
                r
                for r in rolling_rows
                if r["outcome_available_ts_ms"] < ends[r["window_label"]]
            ]
            evidence = {
                "candidate": spec,
                "identity_key": claim.key,
                "module_sha256": contract["code_hashes"][
                    "backend/research/rebuild/" + spec["module"] + ".py"
                ],
                "window_receipts": receipts,
                "rolling1x": metrics.summarize(
                    rolling_rows, rolling_windows[0]["start_ms"], END
                ),
                "rolling2x": metrics.summarize(
                    rolling_rows, rolling_windows[0]["start_ms"], END, 2
                ),
                "rolling_windows1x": metrics.rolling_summary(
                    rolling_rows, rolling_windows
                ),
                "rolling_windows2x": metrics.rolling_summary(
                    rolling_rows, rolling_windows, 2
                ),
                "unresolved_count": len(unresolved),
                "fresh_T": 0,
                "promotion": False,
                "state": "ROLLING_DIAGNOSTIC_FRESH_REQUIRED",
                "interpretation": contract["rolling_interpretation"],
            }
            payload = {
                "trades": all_rows,
                "unresolved": unresolved,
                "window_receipts": receipts,
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            raw = gzip.compress(
                json.dumps(payload, sort_keys=True, allow_nan=False).encode(), mtime=0
            )
            if output_path.exists():
                raise ValueError("OUTPUT_ALREADY_EXISTS")
            output_path.write_bytes(raw)
            evidence["ledger_path"] = str(output_path.relative_to(ROOT))
            evidence["ledger_sha256"] = sha(output_path)
            write_json(evidence_path, evidence)
            ledger.finish(
                claim.key,
                OWNER,
                "COMPLETED",
                {
                    "evidence_path": str(evidence_path.relative_to(ROOT)),
                    "evidence_sha256": sha(evidence_path),
                    "ledger_sha256": sha(output_path),
                },
            )
            report["rows"][identity] = evidence
            m = evidence["rolling1x"]
            print(
                "DONE",
                identity,
                json.dumps(
                    {k: m[k] for k in ("T", "WR_pct", "Net_bps", "PF", "DD_bps")}
                ),
                flush=True,
            )
        except Exception as exc:
            ledger.finish(
                claim.key,
                OWNER,
                "FAILED",
                {"error": type(exc).__name__, "message": str(exc)},
            )
            raise
    report["registry"] = ledger.status(SCOPE)
    write_json(REPORT / "CAMPAIGN_RESULTS_V2.json", report)
    return report


def verify_saved() -> dict[str, Any]:
    contract = verify_freeze()
    report = json.loads((REPORT / "CAMPAIGN_RESULTS_V2.json").read_text())
    if set(report["rows"]) != {row["identity"] for row in contract["candidates"]}:
        raise ValueError("RESULT_COHORT_MISMATCH")
    if report["freeze_sha256"] != sha(REPORT / "CAMPAIGN_PREREGISTERED_V2.json"):
        raise ValueError("RESULT_FREEZE_BINDING_MISMATCH")
    for identity, receipt in report["rows"].items():
        individual = json.loads((REPORT / "results" / (identity + ".json")).read_text())
        if individual != receipt:
            raise ValueError("INDIVIDUAL_RESULT_MISMATCH:" + identity)
        if sha(ROOT / receipt["ledger_path"]) != receipt["ledger_sha256"]:
            raise ValueError("LEDGER_HASH_MISMATCH:" + identity)
    return {"state": "PASS", "identities": len(report["rows"]), "economic_replays": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "verify"))
    args = parser.parse_args()
    result = (
        freeze()
        if args.action == "freeze"
        else run() if args.action == "run" else verify_saved()
    )
    print(
        json.dumps({"action": args.action, "state": result.get("state", "COMPLETE")}),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
