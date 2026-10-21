"""Thin Work C adapter to the frozen Scalp7 source, fills and cost metrics.

This module does not acquire economic ownership, reserve experiment budget,
check shared-heavy capacity, submit orders, or dispatch Actions. Only the
existing economic owner may invoke the CLI after its existing checks. Work C
uses replay_candidate with synthetic frames only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild import scalp7_source_data_v2 as source

OWNER = "CLOUD_WORK_COORDINATOR_ISSUE1358_V1"
DAY_MS = 86_400_000


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_shared_freeze() -> dict[str, Any]:
    spec = json.loads((HERE / "SPEC.json").read_text())
    for rel, expected in spec["dependency_sha256"].items():
        if sha(ROOT / rel) != expected:
            raise ValueError("FROZEN_DEPENDENCY_CHANGED:" + rel)
    return spec


def load_candidate(name: str, *, verify: bool = True) -> tuple[Any, dict[str, Any]]:
    if not name or Path(name).name != name:
        raise ValueError("CANDIDATE_DIRECTORY_NAME_REQUIRED")
    directory = HERE / name
    if not directory.resolve().is_relative_to(HERE.resolve()):
        raise ValueError("CANDIDATE_OUTSIDE_WORK_C")
    spec = json.loads((directory / "SPEC.json").read_text())
    if verify:
        handoff = json.loads((directory / "HANDOFF.json").read_text())
        pins = handoff.get("hashes", handoff)
        for filename, key in (("adapter.py", "adapter_sha256"), ("SPEC.json", "spec_sha256")):
            if sha(directory / filename) != pins.get(key):
                raise ValueError("CANDIDATE_HASH_MISMATCH:" + filename)
    handle = importlib.util.spec_from_file_location("work_c_" + name, directory / "adapter.py")
    module = importlib.util.module_from_spec(handle)
    sys.modules[handle.name] = module
    handle.loader.exec_module(module)
    if spec["identity"] != module.IDENTITY:
        raise ValueError("CANDIDATE_IDENTITY_MISMATCH")
    if int(spec.get("timeframe_min", module.TIMEFRAME_MIN)) != int(module.TIMEFRAME_MIN):
        raise ValueError("CANDIDATE_TIMEFRAME_MISMATCH")
    if module.TIMEFRAME_MIN not in (15, 30):
        raise ValueError("NATIVE_EXECUTION_REQUIRES_15M_OR_30M")
    return module, spec


def _validate_windows(windows: list[dict[str, Any]]) -> None:
    if not windows:
        raise ValueError("WINDOWS_REQUIRED")
    last = -1
    labels = set()
    for window in windows:
        start, end = int(window["start_ms"]), int(window["end_ms"])
        if start < last or end <= start or window["label"] in labels:
            raise ValueError("WINDOWS_OVERLAP_UNORDERED_OR_INVALID")
        if window["partition"] not in ("rolling", "validation"):
            raise ValueError("WINDOW_PARTITION_INVALID")
        labels.add(window["label"])
        last = end


def replay_candidate(module: Any, frames: dict[str, Any], costs: dict[str, float],
                     windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reuse native execution; independent windows retain native gap ownership.

    Callers may supply synthetic data. No source loading happens in this method.
    Whole-history signal generation is permitted only for causal candidate
    generators, tested for prefix invariance in each candidate's fixtures.
    """
    _validate_windows(windows)
    signals = module.generate_signals(frames)
    for signal in signals:
        if signal["identity"] != module.IDENTITY or signal["timeframe_min"] != module.TIMEFRAME_MIN:
            raise ValueError("CANDIDATE_SIGNAL_IDENTITY_OR_TF_DRIFT")
        feature_available = signal.get("meta", {}).get("feature_available_ts_ms")
        if feature_available is not None and int(feature_available) > int(signal["signal_ts_ms"]):
            raise ValueError("SIGNAL_BEFORE_FEATURE_AVAILABILITY")
    trades, unresolved, excluded, receipts = [], [], [], []
    for window in windows:
        start, end = int(window["start_ms"]), int(window["end_ms"])
        chosen = [s for s in signals if start <= int(s["signal_ts_ms"]) < end]
        # History remains a causal prefix; no bars after this independent window.
        sliced = {symbol: frame[frame["close_ts_ms"] <= end].reset_index(drop=True)
                  for symbol, frame in frames.items()}
        out = execution.replay(chosen, sliced, costs, identity=module.IDENTITY,
                               exit_update=module.exit_update,
                               entry_update=getattr(module, "entry_update", None))
        kept, boundary_counts = metrics.partition_rows(out["trades"], start, end)
        kept_keys = {(r["symbol"], r["signal_ts_ms"]) for r in kept}
        for row in out["trades"]:
            row.update(window_label=window["label"], partition=window["partition"])
            if (row["symbol"], row["signal_ts_ms"]) in kept_keys:
                trades.append(row)
            else:
                row["exclusion"] = "OUTCOME_AT_OR_AFTER_INDEPENDENT_WINDOW_END"
                excluded.append(row)
        for row in out["unresolved"]:
            row.update(window_label=window["label"], partition=window["partition"],
                       window_end_ms=end)
            unresolved.append(row)
        receipts.append({"window": window, "signal_count": out["signal_count"],
                         "closed_trade_count": len(kept), "unresolved_count": len(out["unresolved"]),
                         "boundary_exclusions": boundary_counts, "rejections": out["rejections"],
                         "cost1x": metrics.summarize(kept, start, end),
                         "cost2x": metrics.summarize(kept, start, end, 2)})
    summaries = {}
    for partition in ("validation", "rolling"):
        ws = [w for w in windows if w["partition"] == partition]
        if not ws:
            continue
        if any(int(a["end_ms"]) != int(b["start_ms"]) for a, b in zip(ws, ws[1:])):
            raise ValueError("PARTITION_CALENDAR_NOT_CONTIGUOUS")
        start, end = int(ws[0]["start_ms"]), int(ws[-1]["end_ms"])
        rows = [t for t in trades if t["partition"] == partition]
        summaries[partition] = {
            "calendar_days": (end - start) / DAY_MS,
            "start_ms": start, "end_ms": end,
            "cost1x": metrics.summarize(rows, start, end),
            "cost2x": metrics.summarize(rows, start, end, 2),
            "by_side": {str(side): {
                "cost1x": metrics.summarize([r for r in rows if r["side"] == side], start, end),
                "cost2x": metrics.summarize([r for r in rows if r["side"] == side], start, end, 2)
            } for side in (1, -1)},
            "entry_count_semantics": "complete-trade entries only; unresolved separate; no portfolio claim",
        }
    return {"schema": "zel.work_c.native_candidate_handoff_result.v1",
            "identity": module.IDENTITY, "trades": trades, "unresolved": unresolved,
            "boundary_excluded": excluded, "window_receipts": receipts,
            "partitions": summaries, "research_only": True, "fresh_oos": False,
            "promotion": False, "order_authority": "BLOCKED", "live_authority": "BLOCKED",
            "economics": "native frozen reference-cost scenario; not account NAV or historical fills",
            "cost2x": "same fills; double debit only; no second strategy replay"}


def verified_frames(source_root: Path, tf: int, shared: dict[str, Any]) -> dict[str, Any]:
    # Native loader verifies pinned manifests/daily receipts/time witnesses.
    # No cache write, network call or price download is performed here.
    frames = source.load_candles(source_root, tf)
    expected = json.loads((ROOT / shared["source_contracts"][str(tf)]).read_text())
    if set(frames) != set(expected["symbols"]):
        raise ValueError("SOURCE_COHORT_DRIFT")
    for symbol, frame in frames.items():
        pin = expected["symbols"][symbol]
        if len(frame) != pin["bars"] or frame["segment_id"].nunique() != pin["segments"]:
            raise ValueError("SOURCE_COVERAGE_DRIFT:" + symbol)
        if frame.attrs != pin["attrs"]:
            raise ValueError("SOURCE_ATTRIBUTE_BINDING_DRIFT:" + symbol)
        execution._frame_records(frame, tf)
    return frames


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--check-code", action="store_true", help="verify code pins only; no price read")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--owner-ack", choices=[OWNER])
    args = parser.parse_args(argv)
    shared = verify_shared_freeze()
    module, candidate = load_candidate(args.candidate)
    pins = {"shared_spec_sha256": sha(HERE / "SPEC.json"),
            "shared_adapter_sha256": sha(Path(__file__)),
            "candidate_spec_sha256": sha(HERE / args.candidate / "SPEC.json"),
            "candidate_adapter_sha256": sha(HERE / args.candidate / "adapter.py")}
    if args.check_code:
        print(json.dumps({"state": "CODE_PINS_VALID_NO_PRICE_READ", "identity": module.IDENTITY, **pins}, sort_keys=True))
        return 0
    if args.owner_ack != OWNER or args.source_root is None or args.output is None:
        parser.error("owner execution requires --owner-ack, --source-root and --output; shared-heavy/consumption checks remain external")
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS_NO_AUTOMATIC_REPLAY")
    if not args.output.parent.is_dir():
        raise ValueError("OUTPUT_PARENT_MUST_EXIST")
    frames = verified_frames(args.source_root, module.TIMEFRAME_MIN, shared)
    campaign = json.loads((ROOT / shared["campaign_path"]).read_text())
    snapshot = json.loads((ROOT / shared["cost_path"]).read_text())
    result = replay_candidate(module, frames, snapshot["costs_bps"], campaign["windows"])
    result["provenance"] = {**pins, "owner_ack": args.owner_ack,
                            "owner_checks": "external existing-owner authority/consumption/shared-heavy checks required; ack is not enforcement",
                            "source_root": str(args.source_root.resolve()),
                            "source_inventory_sha256": {symbol: f.attrs.get("source_inventory_sha256") for symbol, f in frames.items()},
                            "dependency_sha256": shared["dependency_sha256"],
                            "candidate_spec": candidate}
    # Exclusive final output; no replacement and no separate local claim/owner.
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"identity": module.IDENTITY, "output": str(args.output), "sha256": sha(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
