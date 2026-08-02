from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_GRID_NEUTRAL_CAUSAL_EVIDENCE_PROBE_V1"
SCHEMA = "zel.grid_neutral.causal_evidence_probe.receipt.v1"
STRATEGY_ID = "grid_rebalance"
TIMESTAMP_KEY = re.compile(r"(?i)(^|[._])(ts|time|timestamp|captured_at|observed_at|feature_at|signal_at)$")
CONTEXT_KEY = re.compile(r"(?i)(regime|feature|signal|context|capture|observe|bar|candle)")


def stable_sha(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_timestamp(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return numeric if 0 < numeric < 10_000_000_000 else None
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            return normalize_timestamp(float(raw))
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def walk_values(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, child
            yield from walk_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value[:1000]):
            child_path = f"{path}[{index}]"
            yield child_path, child
            yield from walk_values(child, child_path)


def timestamp_candidates(row: Mapping[str, Any]) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for path, value in walk_values(row):
        normalized_path = re.sub(r"\[\d+\]", "[]", path)
        tail = normalized_path.rsplit(".", 1)[-1]
        is_timestamp_name = bool(TIMESTAMP_KEY.search(tail) or tail.lower().endswith(("_ts", "_time", "_timestamp")))
        is_contextual = bool(CONTEXT_KEY.search(normalized_path))
        if not is_timestamp_name or not is_contextual:
            continue
        timestamp = normalize_timestamp(value)
        if timestamp is not None:
            candidates.append((normalized_path, timestamp))
    return candidates


def event_id(row: Mapping[str, Any]) -> str:
    return str(row.get("event_id") or row.get("trade_id") or "").strip()


def read_grid_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "") == STRATEGY_ID:
                rows.append(row)
    return rows


def ledger_proof(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"state": "HOLD_GRID_TRADES_MISSING", "path": str(path)}
    rows = read_grid_rows(path)
    neutral = [row for row in rows if str(row.get("regime") or row.get("market_regime") or "") == "neutral"]
    all_ids = [event_id(row) for row in rows]
    neutral_ids = [event_id(row) for row in neutral]
    all_id_set = set(all_ids)
    neutral_id_set = set(neutral_ids)
    nonempty = all(bool(value) for value in all_ids)
    unique_all = len(all_id_set) == len(all_ids)
    unique_neutral = len(neutral_id_set) == len(neutral_ids)
    subset = neutral_id_set.issubset(all_id_set)

    path_stats: dict[str, Counter[str]] = {}
    neutral_with_pre_entry = 0
    neutral_with_exact_entry = 0
    neutral_with_post_entry_only = 0
    neutral_without_candidate = 0
    candidate_path_counts: Counter[str] = Counter()
    candidate_path_pre_entry_counts: Counter[str] = Counter()
    for row in neutral:
        entry = normalize_timestamp(row.get("entry_ts") or row.get("entry_time"))
        candidates = timestamp_candidates(row)
        valid_pre = []
        exact = []
        post = []
        for candidate_path, timestamp in candidates:
            candidate_path_counts[candidate_path] += 1
            if entry is None:
                continue
            if timestamp < entry:
                valid_pre.append(candidate_path)
                candidate_path_pre_entry_counts[candidate_path] += 1
            elif abs(timestamp - entry) <= 1e-9:
                exact.append(candidate_path)
                candidate_path_pre_entry_counts[candidate_path] += 1
            else:
                post.append(candidate_path)
        if valid_pre:
            neutral_with_pre_entry += 1
        elif exact:
            neutral_with_exact_entry += 1
        elif post:
            neutral_with_post_entry_only += 1
        else:
            neutral_without_candidate += 1

    subset_pass = (
        len(rows) == 580
        and len(neutral) == 248
        and nonempty
        and unique_all
        and unique_neutral
        and subset
    )
    explicit_timestamp_pass = (
        neutral_with_pre_entry + neutral_with_exact_entry == len(neutral)
        and neutral_with_post_entry_only == 0
        and neutral_without_candidate == 0
    )
    return {
        "state": "PASS_GRID_NEUTRAL_EXACT_EVENT_SUBSET" if subset_pass else "HOLD_GRID_NEUTRAL_EVENT_SUBSET_INCOMPLETE",
        "trade_count": len(rows),
        "neutral_trade_count": len(neutral),
        "event_id_nonempty": nonempty,
        "all_event_ids_unique": unique_all,
        "neutral_event_ids_unique": unique_neutral,
        "neutral_event_ids_subset_of_all": subset,
        "event_id_set_sha256": stable_sha(sorted(all_ids)),
        "neutral_event_id_set_sha256": stable_sha(sorted(neutral_ids)),
        "neutral_with_pre_entry_context_timestamp": neutral_with_pre_entry,
        "neutral_with_entry_equal_context_timestamp": neutral_with_exact_entry,
        "neutral_with_post_entry_context_only": neutral_with_post_entry_only,
        "neutral_without_context_timestamp": neutral_without_candidate,
        "explicit_context_timestamp_proof": explicit_timestamp_pass,
        "timestamp_candidate_path_counts": dict(candidate_path_counts.most_common(40)),
        "timestamp_pre_or_equal_entry_path_counts": dict(candidate_path_pre_entry_counts.most_common(40)),
        "raw_event_ids_published": False,
        "raw_trade_rows_published": False,
    }


def node_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id.lower())
        elif isinstance(child, ast.Attribute):
            names.add(child.attr.lower())
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value.strip().lower()
            if len(value) <= 80:
                names.add(value)
    return names


def function_order_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    rows: list[dict[str, Any]] = []
    for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        regime_lines: list[int] = []
        strategy_lines: list[int] = []
        trade_record_lines: list[int] = []
        entry_lines: list[int] = []
        for node in ast.walk(function):
            names = node_names(node)
            line = int(getattr(node, "lineno", 0) or 0)
            if not line:
                continue
            if any("regime" in name for name in names):
                regime_lines.append(line)
            if isinstance(node, ast.Call) and any(token in name for name in names for token in ("decide", "strategy", "signal")):
                strategy_lines.append(line)
            if isinstance(node, ast.Call) and any(token in name for name in names for token in ("append", "trade", "close_position", "open_position")):
                trade_record_lines.append(line)
            if any(token in name for name in names for token in ("entry_ts", "entry_time", "entry_features")):
                entry_lines.append(line)
        if not regime_lines:
            continue
        regime_first = min(regime_lines)
        strategy_after = [line for line in strategy_lines if line >= regime_first]
        record_after = [line for line in trade_record_lines if strategy_after and line >= min(strategy_after)]
        rows.append({
            "function_name_sha256": hashlib.sha256(function.name.encode()).hexdigest(),
            "function_first_line": int(function.lineno),
            "regime_line_min": regime_first,
            "strategy_call_line_min_after_regime": min(strategy_after) if strategy_after else None,
            "trade_record_line_min_after_strategy": min(record_after) if record_after else None,
            "entry_evidence_line_min": min(entry_lines) if entry_lines else None,
            "regime_before_strategy_before_trade": bool(strategy_after and record_after),
        })
    return rows


def source_order_proof(paths: list[Path]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    order_pass = False
    for path in paths:
        if not path.is_file():
            continue
        function_rows = function_order_rows(path)
        if any(row["regime_before_strategy_before_trade"] for row in function_rows):
            order_pass = True
        files.append({
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "function_order_candidates": function_rows[:100],
            "raw_code_published": False,
        })
    return {
        "state": "PASS_STATIC_REGIME_BEFORE_STRATEGY_BEFORE_TRADE" if order_pass else "HOLD_STATIC_CAUSAL_ORDER_NOT_PROVED",
        "file_count": len(files),
        "order_proved": order_pass,
        "files": files,
        "raw_code_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--runtime-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    terminal_root = args.terminal_root.resolve()
    runtime_root = args.runtime_root.resolve()
    ledger = ledger_proof(terminal_root / "trades.jsonl.gz")
    report_path = terminal_root / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    source_root = None
    if isinstance(report, Mapping) and isinstance(report.get("source"), Mapping):
        root = report["source"].get("root")
        if isinstance(root, str) and root:
            source_root = Path(root)
    engine_paths = [
        Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"),
        Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v2.py"),
        runtime_root / "backend/tools/zel_historical_oos_exact25_replay_v1.py",
        runtime_root / "backend/tools/zel_historical_oos_exact25_replay_v2.py",
    ]
    if source_root:
        engine_paths.append(source_root / "backend/strategies/grid_rebalance.py")
    source_order = source_order_proof(engine_paths)

    blockers: list[str] = []
    if ledger.get("state") != "PASS_GRID_NEUTRAL_EXACT_EVENT_SUBSET":
        blockers.append("GRID_NEUTRAL_EVENT_SUBSET_NOT_PROVED")
    if ledger.get("explicit_context_timestamp_proof") is not True:
        blockers.append("GRID_REGIME_TIMESTAMP_NOT_EXPLICITLY_PRE_ENTRY")
    if source_order.get("order_proved") is not True:
        blockers.append("GRID_SOURCE_CAUSAL_ORDER_NOT_PROVED")
    passed = not blockers
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_NEUTRAL_CAUSAL_EVIDENCE_COMPLETE" if passed else "HOLD_GRID_NEUTRAL_CAUSAL_EVIDENCE_INCOMPLETE",
        "ledger_subset_proof": ledger,
        "source_order_proof": source_order,
        "blockers": blockers,
        "tmp_fork_stage_allowed": passed,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_code_published": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "STAGE_TMP_GRID_NEUTRAL_SOURCE_FORK" if passed else "RESOLVE_CAUSAL_EVIDENCE_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
