"""Three new finite economics; cached P; no old experiment or live execution."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild import scalp7_campaign_v2 as campaign
from backend.research.rebuild import scalp7_execution_v2 as engine
from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild import scalp7_source_components_v1 as component
from backend.research.rebuild import scalp7_source_data_v2 as source
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild import economic7_campaign_registry_v1 as registry

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "research/campaigns/scalp7_20260916/source_ab_v1"
RUNTIME = Path("/home/z/z/runtime/scalp7_source_ab_20260916")
SCOPE = "SCALP7_SOURCE_COMPONENT_AB_AFTER_PR1338_V1"
OWNER = "CHAT_SOURCE_AB_FINITE_OWNER"


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def verify_freeze() -> dict[str, Any]:
    frozen = read(OUT / "FREEZE.json")
    for name, expected in frozen["hashes"].items():
        if campaign.sha(ROOT / name) != expected:
            raise ValueError("SOURCE_AB_FROZEN_HASH_DRIFT:" + name)
    campaign.verify_freeze()
    return frozen


def rolling(rows, windows):
    ends = {w["label"]: w["end_ms"] for w in windows}
    return [
        r
        for r in rows
        if r["partition"] == "rolling"
        and int(r["outcome_available_ts_ms"]) < ends[r["window_label"]]
    ]


def summarize(rows, windows):
    use = rolling(rows, windows)
    rw = [w for w in windows if w["partition"] == "rolling"]
    return dict(
        cost1x=metrics.summarize(use, rw[0]["start_ms"], rw[-1]["end_ms"]),
        cost2x=metrics.summarize(use, rw[0]["start_ms"], rw[-1]["end_ms"], 2),
        windows1x=metrics.rolling_summary(use, rw),
        windows2x=metrics.rolling_summary(use, rw, 2),
    )


def attribution(parent_rows, child_rows, windows):
    def key(r):
        return (r["symbol"], r["signal_ts_ms"], r["window_label"])

    p = {key(r): r for r in rolling(parent_rows, windows)}
    c = {key(r): r for r in rolling(child_rows, windows)}
    common = p.keys() & c.keys()
    prior_profit = sum(max(r["net_bps"], 0) for r in p.values())
    retained = sum(
        max(0, min(p[k]["net_bps"], c[k]["net_bps"]))
        for k in common
        if p[k]["net_bps"] > 0
    )
    return dict(
        common_T=len(common),
        lost_parent_T=len(p.keys() - c.keys()),
        added_T=len(c.keys() - p.keys()),
        common_delta_net=sum(c[k]["net_bps"] - p[k]["net_bps"] for k in common),
        lost_parent_net=sum(p[k]["net_bps"] for k in p.keys() - c.keys()),
        added_net=sum(c[k]["net_bps"] for k in c.keys() - p.keys()),
        parent_winner_profit_retained=retained / prior_profit if prior_profit else None,
        reasons=dict(Counter(r["reason"] for r in c.values())),
        components=dict(
            Counter(r["signal"]["meta"].get("component", "P") for r in c.values())
        ),
    )


def prepare(frozen):
    frames = source.load_candles(
        campaign.SOURCE_ROOT, 30, cache_dir=campaign.RUNTIME / "candle_cache"
    )
    expected = read(ROOT / "research/campaigns/scalp7_20260915/SOURCE_DATA_V2_30M.json")
    for symbol, frame in frames.items():
        pin = expected["symbols"][symbol]
        if (
            len(frame) != pin["bars"]
            or frame.segment_id.nunique() != pin["segments"]
            or frame.attrs != pin["attrs"]
        ):
            raise ValueError("SOURCE_AB_COHORT_DRIFT")
    bound, fits = context.bind_context(
        frames, context.cross_features(frames), frozen["windows"]
    )
    if fits != read(campaign.REPORT / "ROLLING_CONTEXT_FITS_V2.json"):
        raise ValueError("SOURCE_AB_CONTEXT_DRIFT")
    return bound


def run():
    frozen = verify_freeze()
    report_file = OUT / "RESULTS.json"
    if report_file.exists():
        return verify_saved()
    pinfo = read(ROOT / frozen["parent_evidence_path"])
    payload = json.loads(gzip.decompress((ROOT / pinfo["ledger_path"]).read_bytes()))
    prows = payload["trades"]
    windows = frozen["windows"]
    frames = prepare(frozen)
    costs = read(campaign.COST_PATH)["costs_bps"]
    RUNTIME.mkdir(parents=True, exist_ok=True)
    ledger = registry.CampaignLedger(RUNTIME / "candidate_registry.sqlite3")
    ledger.create_scope(SCOPE, OWNER, 3, 3, frozen)
    report = dict(
        scope=SCOPE,
        parent_cached=True,
        parent_economic_reruns=0,
        history="INSPECTED_HISTORY_NEW_COMPOSITION_NOT_FRESH",
        comparisons={"P": summarize(prows, windows)},
        authority=dict(order="BLOCKED", live="BLOCKED", promotion=False),
    )
    for variant, identity in component.IDENTITIES.items():
        claim = registry.CandidateIdentity(
            candidate_id=identity,
            strategy_id="squeeze_break",
            baseline_id=component.parent.SQUEEZE_PARENT,
            changed_axis=variant,
            rule_sha256=component.SPEC_SHA256,
            data_sha256=frozen["data_sha256"],
            cost_sha256=frozen["cost_sha256"],
            window_sha256=campaign.digest(windows),
        )
        reserved = ledger.reserve(SCOPE, OWNER, claim)
        dest = OUT / f"{variant}.trades.json.gz"
        receipt = OUT / f"{variant}.json"
        if not reserved["new"]:
            if reserved["state"] == "COMPLETED" and receipt.exists():
                saved = read(receipt)
                if campaign.sha(dest) != saved["ledger_sha256"]:
                    raise ValueError("SAVED_COMPONENT_HASH_DRIFT")
                report["comparisons"][variant] = saved
                continue
            raise ValueError("NO_REPEAT_OF_STARTED_COMPONENT:" + variant)
        signals = component.generate_signals(frames, costs, variant)
        originals = {
            (s["symbol"], s["signal_ts_ms"])
            for s in signals
            if s["meta"]["component"] == "UNCHANGED_PARENT_EVENT"
        }
        if any((r["symbol"], r["signal_ts_ms"]) not in originals for r in prows):
            raise ValueError("PARENT_SIGNAL_PARITY_FAILED")
        if not ledger.start(claim.key, OWNER):
            raise ValueError("COMPONENT_START_CONFLICT")
        print("START", variant, "signals", len(signals), flush=True)
        trades, unresolved, receipts = [], [], []
        try:
            for w in windows:
                begin, end = w["start_ms"], w["end_ms"]
                use = [s for s in signals if begin <= s["signal_ts_ms"] < end]
                slices = {
                    sym: f[
                        (f.open_ts_ms >= begin - 200 * 1_800_000)
                        & (f.close_ts_ms <= end)
                    ].reset_index(drop=True)
                    for sym, f in frames.items()
                }
                result = engine.replay(
                    use,
                    slices,
                    costs,
                    identity=identity,
                    exit_update=component.exit_update,
                    entry_update=component.entry_update,
                )
                for r in result["trades"]:
                    r.update(window_label=w["label"], partition=w["partition"])
                for r in result["unresolved"]:
                    r.update(window_label=w["label"], window_end_ms=end)
                trades.extend(result["trades"])
                unresolved.extend(result["unresolved"])
                receipts.append(
                    dict(
                        window=w,
                        signal_count=len(use),
                        rejections=result["rejections"],
                        unresolved_count=len(result["unresolved"]),
                    )
                )
            data = dict(trades=trades, unresolved=unresolved, window_receipts=receipts)
            raw = gzip.compress(
                json.dumps(data, sort_keys=True, allow_nan=False).encode(), mtime=0
            )
            with dest.open("xb") as handle:
                handle.write(raw)
            saved = dict(
                identity=identity,
                **summarize(trades, windows),
                attribution=attribution(prows, trades, windows),
                unresolved_count=len(unresolved),
                ledger_path=str(dest.relative_to(ROOT)),
                ledger_sha256=campaign.sha(dest),
            )
            campaign.write_json(receipt, saved)
            ledger.finish(
                claim.key,
                OWNER,
                "COMPLETED",
                dict(path=str(receipt), sha=campaign.sha(receipt)),
            )
            report["comparisons"][variant] = saved
            m = saved["cost1x"]
            print(
                "DONE",
                variant,
                {k: m[k] for k in ("T", "WR_pct", "Net_bps", "PF", "DD_bps")},
                flush=True,
            )
        except Exception as exc:
            ledger.finish(claim.key, OWNER, "FAILED", dict(error=str(exc)))
            raise
    report["registry"] = ledger.status(SCOPE)
    nets = {k: r["cost1x"]["Net_bps"] for k, r in report["comparisons"].items()}
    report["interaction_delta_net_bps"] = (
        nets["PAB"] - nets["PA"] - nets["PB"] + nets["P"]
    )
    campaign.write_json(report_file, report)
    return verify_saved()


def verify_saved():
    verify_freeze()
    report = read(OUT / "RESULTS.json")
    if set(report["comparisons"]) != {"P", "PA", "PB", "PAB"}:
        raise ValueError("COMPONENT_COHORT_INCOMPLETE")
    windows = read(OUT / "FREEZE.json")["windows"]
    for key in ("PA", "PB", "PAB"):
        saved = report["comparisons"][key]
        path = ROOT / saved["ledger_path"]
        if campaign.sha(path) != saved["ledger_sha256"]:
            raise ValueError("COMPONENT_LEDGER_HASH_DRIFT")
        data = json.loads(gzip.decompress(path.read_bytes()))
        for row in data["trades"]:
            name = row["symbol"]
            gross = (row["exit_prices"][name] / row["entry_prices"][name] - 1) * 10_000
            if (
                abs(gross - row["gross_bps"]) > 1e-8
                or abs(gross - row["cost_bps"] - row["net_bps"]) > 1e-8
            ):
                raise ValueError("INDEPENDENT_CASHFLOW_ARITHMETIC_FAILURE")
        actual = summarize(data["trades"], windows)
        if any(actual[k] != saved[k] for k in actual):
            raise ValueError("COMPONENT_METRIC_DRIFT")
    return {
        "state": "PASS_SAVED_SOURCE_AB",
        "new_economic_executions": 3,
        "parent_replays": 0,
        "verification_economic_replays": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "verify"))
    args = parser.parse_args()
    print(json.dumps(run() if args.action == "run" else verify_saved()), flush=True)
