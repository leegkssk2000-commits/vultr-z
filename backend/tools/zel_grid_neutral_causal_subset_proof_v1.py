from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_GRID_NEUTRAL_CAUSAL_SUBSET_PROOF_V1"
SCHEMA = "zel.grid_neutral.causal_subset_proof.receipt.v1"
STRATEGY_ID = "grid_rebalance"
NEUTRAL = "neutral"
EXPECTED_GRID_TRADES = 580
EXPECTED_NEUTRAL_TRADES = 248
EXPECTED_WINDOWS = {"1m_w1": 133, "1m_w2": 66, "1m_w3": 49}
TIMESTAMP_KEY = re.compile(r"(?i)(?:^|_)(?:ts|time|timestamp|at)$|(?:_ts|_time|_timestamp|_at)$")
REGIME_KEY = re.compile(r"(?i)regime")


def stable_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def normalize_ts(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return None
        if numeric > 10_000_000_000_000:
            return numeric / 1_000_000.0
        if numeric > 10_000_000_000:
            return numeric / 1000.0
        return numeric
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            numeric = float(text)
        except ValueError:
            numeric = None
        if numeric is not None:
            return normalize_ts(numeric)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(f"ROW_OBJECT_REQUIRED:{line_number}")
            rows.append(value)
    return rows


def strategy_id(row: Mapping[str, Any]) -> str:
    return str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "")


def regime_value(row: Mapping[str, Any]) -> str:
    return str(row.get("regime") or row.get("market_regime") or "unknown")


def entry_ts(row: Mapping[str, Any]) -> float | None:
    return normalize_ts(row.get("entry_ts") or row.get("entry_time"))


def event_id(row: Mapping[str, Any]) -> str:
    return str(row.get("event_id") or row.get("trade_id") or "").strip()


def iter_mappings(value: Any, path: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        yield path, value
        for key, child in value.items():
            yield from iter_mappings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_mappings(child, f"{path}[{index}]")


def regime_timestamp_pairs(row: Mapping[str, Any]) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    row_regime = regime_value(row).lower()
    for parent_path, mapping in iter_mappings(row):
        regime_keys = [
            key
            for key, value in mapping.items()
            if REGIME_KEY.search(str(key))
            and not isinstance(value, (Mapping, list))
            and str(value).lower() == row_regime
        ]
        if not regime_keys:
            continue
        for key, value in mapping.items():
            key_text = str(key)
            if TIMESTAMP_KEY.search(key_text) or any(
                token in key_text.lower()
                for token in ("captured_at", "observed_at", "as_of", "feature_ts", "context_ts", "signal_ts", "regime_ts")
            ):
                pairs.append((f"{parent_path}.{key_text}", value))
    return pairs


def timestamp_candidate_stats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    per_path: dict[str, list[tuple[float | None, float | None]]] = defaultdict(list)
    path_presence: Counter[str] = Counter()
    for row in rows:
        seen: set[str] = set()
        e_ts = entry_ts(row)
        for path, value in regime_timestamp_pairs(row):
            if path in seen:
                continue
            seen.add(path)
            path_presence[path] += 1
            per_path[path].append((normalize_ts(value), e_ts))
    output: list[dict[str, Any]] = []
    for path in sorted(path_presence):
        pairs = per_path[path]
        parsed = [(candidate, entry) for candidate, entry in pairs if candidate is not None and entry is not None]
        deltas = [entry - candidate for candidate, entry in parsed]
        output.append(
            {
                "path": path,
                "coverage_count": path_presence[path],
                "parseable_pair_count": len(parsed),
                "strictly_pre_entry_count": sum(candidate < entry for candidate, entry in parsed),
                "equal_entry_count": sum(candidate == entry for candidate, entry in parsed),
                "post_entry_count": sum(candidate > entry for candidate, entry in parsed),
                "min_entry_minus_candidate_sec": min(deltas) if deltas else None,
                "max_entry_minus_candidate_sec": max(deltas) if deltas else None,
            }
        )
    output.sort(
        key=lambda row: (
            row["coverage_count"] != len(rows),
            row["strictly_pre_entry_count"] != len(rows),
            row["path"],
        )
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    all_rows = read_rows(args.trades)
    grid_rows = [row for row in all_rows if strategy_id(row) == STRATEGY_ID]
    neutral_rows = [row for row in grid_rows if regime_value(row) == NEUTRAL]

    grid_ids = [event_id(row) for row in grid_rows]
    neutral_ids = [event_id(row) for row in neutral_rows]
    nonempty_grid_ids = [value for value in grid_ids if value]
    nonempty_neutral_ids = [value for value in neutral_ids if value]
    grid_id_set = set(nonempty_grid_ids)
    neutral_id_set = set(nonempty_neutral_ids)

    window_counts = Counter(str(row.get("window_id") or row.get("window") or "unknown") for row in neutral_rows)
    candidate_stats = timestamp_candidate_stats(neutral_rows)
    selected = next(
        (
            row
            for row in candidate_stats
            if row["coverage_count"] == len(neutral_rows)
            and row["parseable_pair_count"] == len(neutral_rows)
            and row["strictly_pre_entry_count"] == len(neutral_rows)
        ),
        None,
    )

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, actual: Any, expected: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "actual": actual, "expected": expected})

    check("grid_trade_count", len(grid_rows) == EXPECTED_GRID_TRADES, len(grid_rows), EXPECTED_GRID_TRADES)
    check("neutral_trade_count", len(neutral_rows) == EXPECTED_NEUTRAL_TRADES, len(neutral_rows), EXPECTED_NEUTRAL_TRADES)
    check("neutral_window_counts", dict(window_counts) == EXPECTED_WINDOWS, dict(sorted(window_counts.items())), EXPECTED_WINDOWS)
    check("grid_event_id_complete", len(nonempty_grid_ids) == len(grid_rows), len(nonempty_grid_ids), len(grid_rows))
    check("grid_event_id_unique", len(grid_id_set) == len(grid_rows), len(grid_id_set), len(grid_rows))
    check("neutral_event_id_complete", len(nonempty_neutral_ids) == len(neutral_rows), len(nonempty_neutral_ids), len(neutral_rows))
    check("neutral_event_id_unique", len(neutral_id_set) == len(neutral_rows), len(neutral_id_set), len(neutral_rows))
    check("neutral_event_id_exact_subset", neutral_id_set.issubset(grid_id_set), len(neutral_id_set & grid_id_set), len(neutral_id_set))
    check("entry_timestamp_complete", sum(entry_ts(row) is not None for row in neutral_rows) == len(neutral_rows), sum(entry_ts(row) is not None for row in neutral_rows), len(neutral_rows))
    check("regime_timestamp_strictly_pre_entry", selected is not None, selected, "one same-object regime timestamp path covers all neutral rows and is strictly < entry_ts")

    event_subset_pass = all(
        row["passed"]
        for row in checks
        if row["name"]
        in {
            "grid_trade_count",
            "neutral_trade_count",
            "neutral_window_counts",
            "grid_event_id_complete",
            "grid_event_id_unique",
            "neutral_event_id_complete",
            "neutral_event_id_unique",
            "neutral_event_id_exact_subset",
        }
    )
    causal_timestamp_pass = next(
        row["passed"] for row in checks if row["name"] == "regime_timestamp_strictly_pre_entry"
    )
    passed = event_subset_pass and causal_timestamp_pass
    blockers = [row["name"] for row in checks if not row["passed"]]

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_NEUTRAL_CAUSAL_EVENT_SUBSET_PROVED" if passed else "HOLD_GRID_NEUTRAL_CAUSAL_EVENT_SUBSET_INCOMPLETE",
        "strategy_id": STRATEGY_ID,
        "grid_trade_count": len(grid_rows),
        "neutral_trade_count": len(neutral_rows),
        "neutral_window_counts": dict(sorted(window_counts.items())),
        "grid_event_id_set_sha256": stable_sha(sorted(grid_id_set)),
        "neutral_event_id_set_sha256": stable_sha(sorted(neutral_id_set)),
        "event_subset_pass": event_subset_pass,
        "causal_timestamp_pass": causal_timestamp_pass,
        "selected_regime_timestamp_candidate": selected,
        "regime_timestamp_candidates": candidate_stats[:100],
        "checks": checks,
        "blockers": blockers,
        "raw_event_ids_published": False,
        "raw_trade_rows_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "STAGE_TRUE_NEUTRAL_SOURCE_FORK_IN_TMP" if passed else "RESOLVE_CAUSAL_TIMESTAMP_OR_EVENT_ID_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "event_subset_pass": event_subset_pass,
                "causal_timestamp_pass": causal_timestamp_pass,
                "selected": selected,
                "blockers": blockers,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
