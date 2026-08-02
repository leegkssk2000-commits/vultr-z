from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_GRID_ENTRY_REGIME_FORK_V1"
SCHEMA = "zel.grid.entry_regime_fork.receipt.v1"


def stable_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text(row: Mapping[str, Any], keys: Sequence[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def number(row: Mapping[str, Any], keys: Sequence[str]) -> float:
    for key in keys:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return 0.0


def event_id(row: Mapping[str, Any]) -> str:
    return text(row, ("event_id", "trade_id", "position_id"))


def window_id(row: Mapping[str, Any]) -> str:
    return text(row, ("window_id", "window"), "unknown")


def symbol(row: Mapping[str, Any]) -> str:
    return text(row, ("symbol", "market")).upper()


def timestamp_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return text(row, ("exit_ts", "exit_time", "captured_at")), event_id(row)


def max_drawdown(values: Sequence[float]) -> float:
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    if gross_loss > 0:
        return gross_profit / gross_loss
    if gross_profit > 0:
        return 999.0
    return None


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=timestamp_key)
    values = [
        number(row, ("realized_R", "net_R", "pnl_r", "net_reference_R"))
        for row in ordered
    ]
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    return {
        "trade_count": len(rows),
        "net_R": sum(values),
        "profit_factor": profit_factor(gross_profit, gross_loss),
        "max_drawdown_R": max_drawdown(values),
        "event_id_set_sha256": stable_sha(sorted(event_id(row) for row in rows)),
    }


def delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_pf = base.get("profit_factor")
    candidate_pf = candidate.get("profit_factor")
    return {
        "delta_net_R": float(candidate["net_R"]) - float(base["net_R"]),
        "delta_max_drawdown_R": float(candidate["max_drawdown_R"])
        - float(base["max_drawdown_R"]),
        "delta_profit_factor": (
            float(candidate_pf) - float(base_pf)
            if base_pf is not None and candidate_pf is not None
            else None
        ),
        "retention_pct": int(candidate["trade_count"])
        / max(int(base["trade_count"]), 1)
        * 100.0,
    }


def read_rows(path: Path, strategy_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, Mapping):
                raise RuntimeError(f"ROW_NOT_OBJECT:{line_no}")
            if text(row, ("strategy_id", "strategy", "strategy_name")) == strategy_id:
                rows.append(dict(row))
    return rows


def epoch_ns(pd_module: Any, value: Any) -> int | None:
    try:
        stamp = pd_module.Timestamp(value)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        return int(stamp.value)
    except Exception:
        return None


def resolve_path(root: Path, row: Mapping[str, Any]) -> Path:
    for key in ("path", "file", "csv_path", "relative_path"):
        value = row.get(key)
        if isinstance(value, str) and value:
            path = Path(value)
            return path if path.is_absolute() else root / path
    raise RuntimeError(f"DATA_FILE_PATH_MISSING:{row}")


def pass_candidate(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    min_retention: float,
) -> tuple[bool, list[str]]:
    change = delta(base, candidate)
    blockers: list[str] = []
    if change["retention_pct"] < min_retention:
        blockers.append("RETENTION_BELOW_MIN")
    if change["delta_net_R"] <= 0:
        blockers.append("NET_R_NOT_IMPROVED")
    if change["delta_max_drawdown_R"] < 0:
        blockers.append("MAX_DD_WORSE")
    if change["delta_profit_factor"] is None or change["delta_profit_factor"] < 0:
        blockers.append("PROFIT_FACTOR_WORSE_OR_UNDEFINED")
    return not blockers, blockers


def evaluate(
    policy: Mapping[str, Any],
    *,
    engine_path: Path,
    terminal_root: Path,
    data_root: Path,
) -> dict[str, Any]:
    strategy_id = str(policy["strategy_id"])
    context_path = Path(str(policy["context_source_path"]))
    derive_path = Path(str(policy["derive_source_path"]))
    trades_path = terminal_root / "trades.jsonl.gz"
    terminal_trades_sha256 = file_sha(trades_path)
    expected_terminal_sha = policy.get("expected_terminal_trades_sha256")

    source_checks = {
        "context_sha_match": file_sha(context_path) == policy["context_source_sha256"],
        "derive_sha_match": file_sha(derive_path) == policy["derive_source_sha256"],
        "terminal_trades_sha_pinned": isinstance(expected_terminal_sha, str)
        and len(expected_terminal_sha) == 64,
        "terminal_trades_sha_match": terminal_trades_sha256 == expected_terminal_sha,
    }
    if not source_checks["context_sha_match"] or not source_checks["derive_sha_match"]:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source_checks}")

    engine = load_module(engine_path, "zel_grid_entry_fork_engine")
    context_mod = load_module(context_path, "zel_grid_entry_fork_context")
    derive_mod = load_module(derive_path, "zel_grid_entry_fork_derive")
    compute_context = getattr(context_mod, "compute_context", None)
    derive_regime = getattr(derive_mod, "derive_regime", None)
    if not callable(compute_context) or not callable(derive_regime):
        raise RuntimeError("CONTEXT_CALLABLE_MISSING")

    report = json.loads((terminal_root / "report.json").read_text())
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")

    engine.init_worker(str(Path(source_root_raw)), str(data_root), "1m")
    manifest = engine._WORKER_MANIFEST
    files = list(manifest.get("files") or []) if isinstance(manifest, Mapping) else []
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in files:
        if isinstance(row, Mapping):
            file_map[
                (
                    text(row, ("window_id", "window"), "unknown"),
                    text(row, ("symbol",)).upper(),
                )
            ] = row

    rows = read_rows(trades_path, strategy_id)
    event_digest = stable_sha(sorted(event_id(row) for row in rows))
    identity_checks = {
        "trade_count_match": len(rows) == int(policy["expected_trade_count"]),
        "event_id_set_match": event_digest == policy["expected_event_id_set_sha256"],
    }

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(window_id(row), symbol(row))].append(row)

    labels: dict[str, str] = {}
    facts: dict[str, dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []
    prefix_last_bar_pass = 0
    minimum_prefix_bars: int | None = None
    duplicate_timestamp_count = 0

    for lane, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane)
        if file_row is None:
            unmatched.extend(
                {
                    "event_sha256": stable_sha(event_id(row)),
                    "reason": "LANE_FILE_MISSING",
                    "lane": lane,
                }
                for row in lane_rows
            )
            continue
        frame = engine.frame_from_csv(resolve_path(data_root, file_row))
        index_by_epoch: dict[int, int] = {}
        duplicate_epochs: set[int] = set()
        for index, value in enumerate(frame["timestamp"].tolist()):
            current_epoch = epoch_ns(engine.pd, value)
            if current_epoch is None:
                continue
            if current_epoch in index_by_epoch:
                duplicate_epochs.add(current_epoch)
            index_by_epoch[current_epoch] = index
        duplicate_timestamp_count += len(duplicate_epochs)

        for row in lane_rows:
            current_event_id = event_id(row)
            entry_epoch = epoch_ns(
                engine.pd,
                row.get("entry_ts") or row.get("entry_time"),
            )
            index = index_by_epoch.get(entry_epoch) if entry_epoch is not None else None
            if index is None:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "ENTRY_TIMESTAMP_NOT_FOUND",
                        "lane": lane,
                    }
                )
                continue

            prefix = frame.iloc[
                max(0, index - int(engine.FRAME_LIMIT) + 1) : index + 1
            ].copy()
            minimum_prefix_bars = (
                len(prefix)
                if minimum_prefix_bars is None
                else min(minimum_prefix_bars, len(prefix))
            )
            last_epoch = epoch_ns(engine.pd, prefix["timestamp"].iloc[-1])
            if last_epoch != entry_epoch:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "PREFIX_LAST_BAR_NOT_ENTRY",
                        "lane": lane,
                    }
                )
                continue
            if len(prefix) < 14:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "PREFIX_WARMUP_LT_14",
                        "lane": lane,
                    }
                )
                continue

            prefix_last_bar_pass += 1
            token = f"{lane[0]}:{lane[1]}"
            try:
                context = compute_context(token, prefix, None, None, None)
                regime = str(derive_regime(context) or "missing")
            except Exception as exc:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": f"CONTEXT_ERROR:{type(exc).__name__}",
                        "lane": lane,
                    }
                )
                continue
            if regime not in {"range", "trend_long", "trend_short", "transition"}:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": f"REGIME_INVALID:{regime}",
                        "lane": lane,
                    }
                )
                continue

            labels[current_event_id] = regime
            facts[current_event_id] = {
                "regime": regime,
                "trend_direction": text(context, ("trend_direction",), "missing"),
                "trend_strength": number(context, ("trend_strength",)),
                "entry_epoch_ns": entry_epoch,
                "prefix_bars": len(prefix),
                "window_id": lane[0],
                "symbol": lane[1],
            }

    reconstruction_pass = (
        all(source_checks.values())
        and all(identity_checks.values())
        and len(labels) == len(rows)
        and not unmatched
        and duplicate_timestamp_count == 0
    )

    baseline = metrics(rows)
    selection_window = str(policy["selection_window"])
    base_selection_rows = [row for row in rows if window_id(row) == selection_window]
    base_selection = metrics(base_selection_rows)
    regimes = sorted(set(labels.values()))
    candidates: dict[str, Any] = {}
    eligible: list[str] = []

    for regime in regimes:
        candidate_rows = [row for row in rows if labels.get(event_id(row)) == regime]
        selection_rows = [
            row
            for row in base_selection_rows
            if labels.get(event_id(row)) == regime
        ]
        selection_metrics = metrics(selection_rows)
        selection_pass, selection_blockers = pass_candidate(
            base_selection,
            selection_metrics,
            float(policy["min_retention_pct"]),
        )
        confirmation: dict[str, Any] = {}
        confirmation_pass = True
        for window in policy["confirmation_windows"]:
            base_rows = [row for row in rows if window_id(row) == window]
            selected_rows = [
                row
                for row in base_rows
                if labels.get(event_id(row)) == regime
            ]
            base_metrics = metrics(base_rows)
            candidate_metrics = metrics(selected_rows)
            change = delta(base_metrics, candidate_metrics)
            non_worse_dd = change["delta_max_drawdown_R"] >= 0
            confirmation[str(window)] = {
                "base": base_metrics,
                "candidate": candidate_metrics,
                "delta": change,
                "non_worse_dd": non_worse_dd,
            }
            confirmation_pass = confirmation_pass and non_worse_dd

        candidate = {
            "rule": {"entry_regime_equals": regime},
            "all_windows": metrics(candidate_rows),
            "selection_window": {
                "base": base_selection,
                "candidate": selection_metrics,
                "delta": delta(base_selection, selection_metrics),
                "pass": selection_pass,
                "blockers": selection_blockers,
            },
            "confirmation_windows": confirmation,
            "confirmation_pass": confirmation_pass,
            "eligible": reconstruction_pass and selection_pass and confirmation_pass,
        }
        candidates[regime] = candidate
        if candidate["eligible"]:
            eligible.append(regime)

    selected = None
    if eligible:
        selected = max(
            eligible,
            key=lambda name: (
                candidates[name]["confirmation_windows"]["1m_w3"]["candidate"]["net_R"],
                candidates[name]["selection_window"]["candidate"]["net_R"],
                name,
            ),
        )

    if selected:
        state = "PASS_GRID_ENTRY_REGIME_FORK_CANDIDATE_READY"
    elif not reconstruction_pass:
        state = "HOLD_GRID_ENTRY_REGIME_RECONSTRUCTION_INCOMPLETE"
    else:
        state = "HOLD_GRID_ENTRY_REGIME_NO_POLICY_SURVIVOR"

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": state,
        "strategy_id": strategy_id,
        "source_checks": source_checks,
        "identity_checks": identity_checks,
        "terminal_trades_sha256": terminal_trades_sha256,
        "trade_count": len(rows),
        "event_id_set_sha256": event_digest,
        "reconstructed_count": len(labels),
        "unmatched_count": len(unmatched),
        "unmatched_reason_counts": dict(Counter(item["reason"] for item in unmatched)),
        "duplicate_frame_timestamp_count": duplicate_timestamp_count,
        "prefix_last_bar_at_entry_count": prefix_last_bar_pass,
        "minimum_prefix_bars": minimum_prefix_bars,
        "entry_regime_counts": dict(Counter(labels.values())),
        "baseline": baseline,
        "candidates": candidates,
        "eligible_regimes": eligible,
        "selected_research_fork": selected,
        "selection_authority": False,
        "promotion_authority": False,
        "incumbent_mutated": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "context_facts_published": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "STAGE_SELECTED_RULE_IN_TMP_CHILD_AND_EXACT_REPLAY"
            if selected
            else "RETAIN_INCUMBENT_AND_ROUTE_NEXT_SINGLE_AXIS_HYPOTHESIS"
        ),
    }
    receipt["facts_digest_sha256"] = stable_sha(facts)
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    base = {
        "trade_count": 10,
        "net_R": -4.0,
        "profit_factor": 0.5,
        "max_drawdown_R": -5.0,
    }
    good = {
        "trade_count": 6,
        "net_R": 1.0,
        "profit_factor": 1.2,
        "max_drawdown_R": -2.0,
    }
    passed, blockers = pass_candidate(base, good, 60.0)
    assert passed and not blockers

    loss_free = metrics(
        [
            {"event_id": "a", "realized_R": 1.0},
            {"event_id": "b", "realized_R": 2.0},
        ]
    )
    assert loss_free["profit_factor"] == 999.0, loss_free

    low = dict(good, trade_count=5)
    passed, blockers = pass_candidate(base, low, 60.0)
    assert not passed and "RETENTION_BELOW_MIN" in blockers
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path(
            "/opt/zel/research-runtime/data-b-v2/"
            "zel_historical_oos_exact25_replay_v1.py"
        ),
    )
    parser.add_argument(
        "--terminal-root",
        type=Path,
        default=Path("/var/lib/zel-research/data-b-1m-v2"),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/opt/zel/historical-oos-v1"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.policy:
        parser.error("--policy required")

    policy = json.loads(args.policy.read_text())
    receipt = evaluate(
        policy,
        engine_path=args.engine,
        terminal_root=args.terminal_root,
        data_root=args.data_root,
    )
    encoded = (
        json.dumps(
            receipt,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded)
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
