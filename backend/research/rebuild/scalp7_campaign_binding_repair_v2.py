"""Explicit bounded recovery of unexecuted or zero-fill source-binding attempts."""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime, timezone
from typing import Any

from backend.research.rebuild import scalp7_campaign_v2 as base

REPORT = base.REPORT
CONTRACT = REPORT / "SOURCE_BINDING_REPAIR_PREREG_V2.json"
REPAIR_SCOPE = base.SCOPE + "::EXACT_SEGMENT_TYPE_BINDING_REPAIR_R1"
PRESERVED = (
    "scalp7_keltner_hg_parent_utc30m_v2",
    "scalp7_keltner_hg_td075_utc30m_v2",
    "scalp7_squeeze_panic_cost4_parent_utc30m_v2",
    "scalp7_squeeze_panic_cost4_be1r_utc30m_v2",
)


def freeze() -> dict[str, Any]:
    original = base.verify_freeze()
    if CONTRACT.exists():
        return verify_contract()
    catalog = [
        spec for spec in original["candidates"] if spec["identity"] not in PRESERVED
    ]
    prior: dict[str, Any] = {}
    for spec in original["candidates"]:
        identity = spec["identity"]
        path = REPORT / "results" / (identity + ".json")
        if not path.exists():
            continue
        evidence = json.loads(path.read_text())
        ledger_path = base.ROOT / evidence["ledger_path"]
        if base.sha(ledger_path) != evidence["ledger_sha256"]:
            raise ValueError("PRIOR_LEDGER_HASH_MISMATCH")
        payload = json.loads(gzip.decompress(ledger_path.read_bytes()))
        fills = len(payload["trades"])
        if identity not in PRESERVED:
            if fills or payload["unresolved"] or evidence["unresolved_count"]:
                raise ValueError("REPAIR_CANNOT_REPEAT_ECONOMIC_FILLS:" + identity)
            reasons = {
                reason
                for w in evidence["window_receipts"]
                for reason in w["rejections"]
            }
            if reasons != {"SIGNAL_SEGMENT_MISMATCH"}:
                raise ValueError("UNRELATED_FAILURE_NOT_AUTHORIZED_BY_REPAIR")
        prior[identity] = {
            "path": str(path.relative_to(base.ROOT)),
            "sha256": base.sha(path),
            "economic_fill_count": fills,
            "ledger_path": evidence["ledger_path"],
            "ledger_sha256": evidence["ledger_sha256"],
            "state": (
                "VALID_PRESERVED_NO_REPLAY"
                if identity in PRESERVED
                else "INVALID_SOURCE_BINDING_ZERO_FILLS_NOT_STRATEGY_PERFORMANCE"
            ),
        }
    hashes = {
        "backend/research/rebuild/"
        + name
        + ".py": base.sha(base.ROOT / "backend/research/rebuild" / (name + ".py"))
        for name in (
            "scalp7_source_binding_repair_v2",
            "scalp7_campaign_binding_repair_v2",
        )
    }
    contract = {
        "scope_key": base.SCOPE,
        "execution_scope": REPAIR_SCOPE,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_freeze_sha256": base.sha(REPORT / "CAMPAIGN_PREREGISTERED_V2.json"),
        "repair_axis": "SOURCE_SEGMENT_ID_REPRESENTATION_ONLY",
        "mechanism": "exact lexical equality required; bind source integer type before frozen engine",
        "economic_rules_changed": False,
        "costs_changed": False,
        "windows_changed": False,
        "preserved_prior": prior,
        "candidates": catalog,
        "max_executions": len(catalog),
        "code_hashes": hashes,
        "new_result_directory": "results_binding_repair",
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    base.write_json(CONTRACT, contract)
    return contract


def verify_contract() -> dict[str, Any]:
    base.verify_freeze()
    value = json.loads(CONTRACT.read_text())
    if value["original_freeze_sha256"] != base.sha(
        REPORT / "CAMPAIGN_PREREGISTERED_V2.json"
    ):
        raise ValueError("ORIGINAL_CONTRACT_DRIFT")
    for name, expected in value["code_hashes"].items():
        if base.sha(base.ROOT / name) != expected:
            raise ValueError("REPAIR_CODE_DRIFT")
    for prior in value["preserved_prior"].values():
        if base.sha(base.ROOT / prior["path"]) != prior["sha256"]:
            raise ValueError("PRESERVED_RESULT_DRIFT")
        if base.sha(base.ROOT / prior["ledger_path"]) != prior["ledger_sha256"]:
            raise ValueError("PRESERVED_LEDGER_DRIFT")
    return value


def run() -> dict[str, Any]:
    contract = verify_contract()
    original = base.verify_freeze()
    registry = base.module("economic7_campaign_registry_v1")
    source = base.module("scalp7_source_data_v2")
    context = base.module("scalp7_rolling_context_v2")
    metrics = base.module("scalp7_metrics_v2")
    adapter = base.module("scalp7_source_binding_repair_v2")
    ledger = registry.CampaignLedger(base.RUNTIME / "campaign.sqlite3")
    ledger.create_scope(
        REPAIR_SCOPE,
        base.OWNER,
        len(contract["candidates"]),
        len(contract["candidates"]),
        contract,
    )
    frames = {
        tf: source.load_candles(
            base.SOURCE_ROOT, tf, cache_dir=base.RUNTIME / "candle_cache"
        )
        for tf in (15, 30)
    }
    for tf, by_symbol in frames.items():
        expected = json.loads(
            (
                base.ROOT
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
                or frame.attrs != pinned["attrs"]
            ):
                raise ValueError("SOURCE_BINDING_DRIFT")
    features = context.cross_features(frames[30])
    for tf in (15, 30):
        frames[tf], fits = context.bind_context(
            frames[tf], features, original["windows"]
        )
    if fits != json.loads((REPORT / "ROLLING_CONTEXT_FITS_V2.json").read_text()):
        raise ValueError("FROZEN_CONTEXT_FIT_DRIFT")
    costs = json.loads(base.COST_PATH.read_text())["costs_bps"]
    report: dict[str, Any] = {
        "scope_key": base.SCOPE,
        "original_freeze_sha256": contract["original_freeze_sha256"],
        "repair_freeze_sha256": base.sha(CONTRACT),
        "rows": {},
        "preserved_positive_no_replay": list(PRESERVED),
        "zero_fill_binding_attempts_not_performance": [
            identity
            for identity, prior in contract["preserved_prior"].items()
            if identity not in PRESERVED and prior["economic_fill_count"] == 0
        ],
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    for identity in PRESERVED:
        prior = contract["preserved_prior"][identity]
        report["rows"][identity] = json.loads((base.ROOT / prior["path"]).read_text())
    for spec in contract["candidates"]:
        identity = spec["identity"]
        path = REPORT / "results_binding_repair" / (identity + ".json")
        payload_path = path.with_suffix(".trades.json.gz")
        claim = registry.CandidateIdentity(
            candidate_id=identity + "__binding_r1",
            strategy_id=spec["lane"],
            baseline_id=spec["parent"],
            changed_axis="EXACT_SOURCE_ID_TYPE_BINDING_R1:" + identity,
            rule_sha256=base.digest(
                {
                    "original": original["code_hashes"],
                    "binding": contract["code_hashes"],
                    "identity": spec,
                }
            ),
            data_sha256=base.digest(original["data_hashes"]),
            cost_sha256=original["cost_sha256"],
            window_sha256=base.digest(original["windows"]),
        )
        reserved = ledger.reserve(REPAIR_SCOPE, base.OWNER, claim)
        if not reserved["new"]:
            if reserved["state"] != "COMPLETED":
                raise ValueError(
                    "NO_AUTOMATIC_REPAIR_RERUN:" + identity + ":" + reserved["state"]
                )
            saved = json.loads(reserved["result_json"])
            if (
                base.sha(path) != saved["evidence_sha256"]
                or base.sha(payload_path) != saved["ledger_sha256"]
            ):
                raise ValueError("SAVED_REPAIR_DRIFT")
            report["rows"][identity] = json.loads(path.read_text())
            continue
        mod = base.module(spec["module"])
        work = frames[int(spec["tf"])]
        if spec["module"] == "scalp7_materials_program_v2":
            work = mod.prepare_frames(work)
        signals = base._signals(spec, work, costs)
        # Source binding is audited for every signal before starting economics.
        adapter.bind_segments(signals, work)
        if not ledger.start(claim.key, base.OWNER):
            raise ValueError("CLAIM_NOT_STARTED")
        print("START_BINDING_R1", identity, "signals", len(signals), flush=True)
        all_rows: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        receipts = []
        try:
            for window in original["windows"]:
                start, end = window["start_ms"], window["end_ms"]
                chosen = [
                    signal
                    for signal in signals
                    if start <= signal["signal_ts_ms"] < end
                ]
                prefix_start = start - 200 * int(spec["tf"]) * 60_000
                sliced = {
                    symbol: frame[
                        (frame["open_ts_ms"] >= prefix_start)
                        & (frame["close_ts_ms"] <= end)
                    ].reset_index(drop=True)
                    for symbol, frame in work.items()
                }
                out = adapter.replay(
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
                        "rejections": out["rejections"],
                        "unresolved_count": len(out["unresolved"]),
                        "cost1x": metrics.summarize(out["trades"], start, end),
                        "cost2x": metrics.summarize(out["trades"], start, end, 2),
                    }
                )
            rolling_windows = [
                window
                for window in original["windows"]
                if window["partition"] == "rolling"
            ]
            ends = {window["label"]: window["end_ms"] for window in original["windows"]}
            rolling_rows = [
                row
                for row in all_rows
                if row["partition"] == "rolling"
                and row["outcome_available_ts_ms"] < ends[row["window_label"]]
            ]
            evidence = {
                "candidate": spec,
                "identity_key": claim.key,
                "module_sha256": original["code_hashes"][
                    "backend/research/rebuild/" + spec["module"] + ".py"
                ],
                "source_binding_repair_sha256": contract["code_hashes"][
                    "backend/research/rebuild/scalp7_source_binding_repair_v2.py"
                ],
                "window_receipts": receipts,
                "rolling1x": metrics.summarize(
                    rolling_rows, rolling_windows[0]["start_ms"], base.END
                ),
                "rolling2x": metrics.summarize(
                    rolling_rows, rolling_windows[0]["start_ms"], base.END, 2
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
                "interpretation": original["rolling_interpretation"],
            }
            payload = {
                "trades": all_rows,
                "unresolved": unresolved,
                "window_receipts": receipts,
            }
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            if payload_path.exists():
                raise ValueError("REPAIR_OUTPUT_ALREADY_EXISTS")
            payload_path.write_bytes(
                gzip.compress(
                    json.dumps(payload, sort_keys=True, allow_nan=False).encode(),
                    mtime=0,
                )
            )
            evidence["ledger_path"] = str(payload_path.relative_to(base.ROOT))
            evidence["ledger_sha256"] = base.sha(payload_path)
            base.write_json(path, evidence)
            ledger.finish(
                claim.key,
                base.OWNER,
                "COMPLETED",
                {
                    "evidence_sha256": base.sha(path),
                    "ledger_sha256": base.sha(payload_path),
                    "evidence_path": str(path.relative_to(base.ROOT)),
                },
            )
            report["rows"][identity] = evidence
            print(
                "DONE_BINDING_R1",
                identity,
                json.dumps(
                    {
                        key: evidence["rolling1x"][key]
                        for key in ("T", "WR_pct", "Net_bps", "PF", "DD_bps")
                    }
                ),
                flush=True,
            )
        except Exception as exc:
            ledger.finish(
                claim.key,
                base.OWNER,
                "FAILED",
                {"error": type(exc).__name__, "message": str(exc)},
            )
            raise
    report["registry"] = ledger.status(REPAIR_SCOPE)
    report["original_registry"] = ledger.status(base.SCOPE)
    base.write_json(REPORT / "CAMPAIGN_FINAL_RESULTS_V2.json", report)
    return report


def verify_saved() -> dict[str, Any]:
    contract = verify_contract()
    report = json.loads((REPORT / "CAMPAIGN_FINAL_RESULTS_V2.json").read_text())
    if report["repair_freeze_sha256"] != base.sha(CONTRACT):
        raise ValueError("REPAIR_FREEZE_BINDING_DRIFT")
    all_specs = base.verify_freeze()["candidates"]
    if set(report["rows"]) != {spec["identity"] for spec in all_specs}:
        raise ValueError("FINAL_COHORT_MISMATCH")
    for identity, receipt in report["rows"].items():
        directory = "results" if identity in PRESERVED else "results_binding_repair"
        path = REPORT / directory / (identity + ".json")
        if json.loads(path.read_text()) != receipt:
            raise ValueError("FINAL_INDIVIDUAL_RECEIPT_MISMATCH")
        if base.sha(base.ROOT / receipt["ledger_path"]) != receipt["ledger_sha256"]:
            raise ValueError("FINAL_LEDGER_DRIFT")
    return {
        "state": "PASS",
        "identities": len(report["rows"]),
        "repair_axis": contract["repair_axis"],
        "economic_replays": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "verify"))
    args = parser.parse_args()
    result = (
        freeze()
        if args.action == "freeze"
        else run() if args.action == "run" else verify_saved()
    )
    print(json.dumps({"state": result.get("state", "COMPLETE")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
