#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


ENTRY_LINEAGE_BLOCK = '''ENTRY_LINEAGE_REASONS: dict[str, frozenset[str]] = {
    "break_and_continue": frozenset({"bnc_long"}),
    "rbreaker_like": frozenset({"rbr_breakout_long", "rbr_reversal_long"}),
    "squeeze_break": frozenset({"squeeze_break_long"}),
    "trend_ma_macd": frozenset({"trend_ma_macd_long_entry"}),
    "vwap_revert": frozenset({"vwap_revert_long_entry"}),
}


def lineage_allows_add(strategy_id: str, position: dict[str, Any]) -> bool:
    allowed = ENTRY_LINEAGE_REASONS.get(strategy_id)
    if allowed is None:
        return True
    return (
        str(position.get("entry_strategy_id") or "") == strategy_id
        and str(position.get("entry_event") or "") in allowed
    )


def select_segment_with_preroll(
    frame: pd.DataFrame,
    start: int,
    stop: int,
    evaluation_bars: int,
    preroll_bars: int,
) -> pd.DataFrame:
    if start < 0 or stop <= start or stop > len(frame):
        raise ValueError(f"SEGMENT_RANGE_INVALID:{start}:{stop}:{len(frame)}")
    if stop - start != evaluation_bars:
        raise ValueError(f"EVALUATION_BAR_COUNT_INVALID:{stop - start}")
    context_start = max(0, start - max(preroll_bars, 0))
    sample = frame.iloc[context_start:stop].copy().reset_index(drop=True)
    evaluation_start_index = start - context_start
    if len(sample) - evaluation_start_index != evaluation_bars:
        raise ValueError("EVALUATION_WINDOW_ALIGNMENT_INVALID")
    sample.attrs["evaluation_start_index"] = evaluation_start_index
    sample.attrs["indicator_preroll_bars"] = evaluation_start_index
    sample.attrs["evaluation_bars"] = evaluation_bars
    return sample


'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "ENTRY_LINEAGE_REASONS:" in source:
        raise RuntimeError("RUNNER_ALREADY_PATCHED")

    source = replace_once(
        source,
        "def build_context(\n",
        ENTRY_LINEAGE_BLOCK + "def build_context(\n",
        "INSERT_LINEAGE_HELPERS",
    )

    source = replace_once(
        source,
        '''        "last_add_price": float(position.get("last_add_price") or 0.0),
        "risk_action": "hold",
''',
        '''        "last_add_price": float(position.get("last_add_price") or 0.0),
        "entry_strategy_id": str(position.get("entry_strategy_id") or ""),
        "entry_event": str(position.get("entry_event") or ""),
        "risk_action": "hold",
''',
        "CONTEXT_LINEAGE_PAYLOAD",
    )

    source = replace_once(
        source,
        '''        position=AttrBox(side=payload["position_side"], qty=payload["position_qty"], avg_entry=payload["avg_entry"]),
''',
        '''        position=AttrBox(
            side=payload["position_side"],
            qty=payload["position_qty"],
            avg_entry=payload["avg_entry"],
            add_count=payload["add_count"],
            last_add_price=payload["last_add_price"],
            entry_strategy_id=payload["entry_strategy_id"],
            entry_event=payload["entry_event"],
        ),
''',
        "CONTEXT_POSITION_LINEAGE",
    )

    source = replace_once(
        source,
        '''    rows = segment.copy().reset_index(drop=True)
    public_columns = [column for column in rows.columns if not str(column).startswith("__")]
    row_records = rows[public_columns].to_dict(orient="records")
    timestamps = rows["__timestamp"].astype(float).tolist()
    instance = owner()
''',
        '''    evaluation_start = int(segment.attrs.get("evaluation_start_index", 0))
    declared_evaluation_bars = int(segment.attrs.get("evaluation_bars", len(segment) - evaluation_start))
    rows = segment.copy().reset_index(drop=True)
    evaluation_bars = len(rows) - evaluation_start
    if evaluation_start < 0 or evaluation_start >= len(rows) or evaluation_bars != declared_evaluation_bars:
        raise ValueError(
            f"EVALUATION_WINDOW_INVALID:{evaluation_start}:{evaluation_bars}:{declared_evaluation_bars}"
        )
    public_columns = [column for column in rows.columns if not str(column).startswith("__")]
    row_records = rows[public_columns].to_dict(orient="records")
    timestamps = rows["__timestamp"].astype(float).tolist()
    instance = owner()
''',
        "SIMULATION_EVALUATION_WINDOW",
    )

    source = replace_once(
        source,
        '''        "add_count": 0,
        "last_add_price": 0.0,
    }
''',
        '''        "add_count": 0,
        "last_add_price": 0.0,
        "entry_strategy_id": "",
        "entry_event": "",
    }
''',
        "POSITION_LINEAGE_FIELDS",
    )

    source = replace_once(
        source,
        '''    invalid_signal_count = 0
    intent_histogram: Counter[str] = Counter()
''',
        '''    invalid_signal_count = 0
    orphan_add_block_count = 0
    strategy_call_count = 0
    intent_histogram: Counter[str] = Counter()
''',
        "SIMULATION_COUNTERS",
    )

    source = replace_once(
        source,
        '''            position.update({"side": "", "qty": 0.0, "avg_entry": 0.0, "stop": 0.0, "tp": 0.0, "add_count": 0, "last_add_price": 0.0})
''',
        '''            position.update({
                "side": "",
                "qty": 0.0,
                "avg_entry": 0.0,
                "stop": 0.0,
                "tp": 0.0,
                "add_count": 0,
                "last_add_price": 0.0,
                "entry_strategy_id": "",
                "entry_event": "",
            })
''',
        "FULL_CLOSE_LINEAGE_CLEAR",
    )

    source = replace_once(
        source,
        '''            current_trade["exit_index"] = bar_index
''',
        '''            current_trade["exit_index"] = bar_index - evaluation_start
''',
        "RELATIVE_EXIT_INDEX",
    )

    source = replace_once(
        source,
        '''        nonlocal realized, total_cost, current_trade, invalid_signal_count
        kind = action["kind"]
        target_qty = max(float(action.get("target_qty") or 0.0), 0.0)
        signal = action.get("legacy") if isinstance(action.get("legacy"), dict) else {}
        if kind in {"enter", "add"}:
''',
        '''        nonlocal realized, total_cost, current_trade, invalid_signal_count, orphan_add_block_count
        kind = action["kind"]
        target_qty = max(float(action.get("target_qty") or 0.0), 0.0)
        signal = action.get("legacy") if isinstance(action.get("legacy"), dict) else {}
        entry_event = str(action.get("entry_event") or signal.get("why") or "")
        if kind == "add" and not lineage_allows_add(strategy_id, position):
            orphan_add_block_count += 1
            return
        if kind in {"enter", "add"}:
''',
        "EXECUTION_LINEAGE_GUARD",
    )

    source = replace_once(
        source,
        '''                    "add_count": 0,
                    "last_add_price": fill,
                })
                current_trade = {
                    "entry_index": bar_index,
''',
        '''                    "add_count": 0,
                    "last_add_price": fill,
                    "entry_strategy_id": strategy_id,
                    "entry_event": entry_event,
                })
                current_trade = {
                    "entry_index": bar_index - evaluation_start,
                    "entry_strategy_id": strategy_id,
                    "entry_event": entry_event,
''',
        "ENTER_LINEAGE_WRITE",
    )

    source = replace_once(
        source,
        '''        close_price = float(bar["close"])

        due = [action for action in pending if int(action["execute_index"]) == index]
''',
        '''        close_price = float(bar["close"])

        if index < evaluation_start:
            continue

        due = [action for action in pending if int(action["execute_index"]) == index]
''',
        "PREROLL_ACCOUNTING_GUARD",
    )

    source = replace_once(
        source,
        '''        ctx = build_context(strategy_id, row_records[: index + 1], position, regime, cost)
        decision = getattr(instance, method_name)(ctx)
''',
        '''        ctx = build_context(strategy_id, row_records[: index + 1], position, regime, cost)
        strategy_call_count += 1
        decision = getattr(instance, method_name)(ctx)
''',
        "ACTUAL_STRATEGY_CALL_COUNTER",
    )

    source = replace_once(
        source,
        '''        if intent == "enter_long":
            kind = "add" if position["qty"] > 0 and legacy_action == "add" else "enter"
            if kind == "enter" and (position["qty"] > 0 or any(item["kind"] == "enter" for item in pending)):
                continue
            if kind == "add" and (position["qty"] <= 0 or any(item["kind"] == "add" for item in pending)):
                continue
            execute_index = index + entry_delay
            if execute_index < len(rows):
                pending.append({"kind": kind, "execute_index": execute_index, "target_qty": target_qty, "legacy": legacy})
                if kind == "enter":
                    enter_signal_count += 1
                else:
                    add_signal_count += 1
''',
        '''        if intent == "enter_long":
            kind = "add" if legacy_action == "add" else "enter"
            if kind == "enter" and (position["qty"] > 0 or any(item["kind"] == "enter" for item in pending)):
                continue
            if kind == "add":
                if position["qty"] <= 0 or not lineage_allows_add(strategy_id, position):
                    orphan_add_block_count += 1
                    continue
                if any(item["kind"] == "add" for item in pending):
                    continue
            execute_index = index + entry_delay
            if execute_index < len(rows):
                pending.append({
                    "kind": kind,
                    "execute_index": execute_index,
                    "target_qty": target_qty,
                    "legacy": legacy,
                    "strategy_id": strategy_id,
                    "entry_event": str(legacy.get("why") or fields.get("reason") or ""),
                })
                if kind == "enter":
                    enter_signal_count += 1
                else:
                    add_signal_count += 1
''',
        "SIGNAL_LINEAGE_GUARD",
    )

    source = replace_once(
        source,
        '''        "bars": len(rows),
        "strategy_call_count": max(len(rows) - minimum_call_bars, 0),
''',
        '''        "bars": evaluation_bars,
        "context_bars": len(rows),
        "indicator_preroll_bars": evaluation_start,
        "strategy_call_count": strategy_call_count,
''',
        "EVALUATION_RESULT_COUNTS",
    )

    source = replace_once(
        source,
        '''        "invalid_signal_count": invalid_signal_count,
        "trade_count": len(trades),
''',
        '''        "invalid_signal_count": invalid_signal_count,
        "orphan_add_block_count": orphan_add_block_count,
        "trade_count": len(trades),
''',
        "ORPHAN_RESULT_COUNT",
    )

    source = replace_once(
        source,
        '''        "exposure_pct": round(exposure_bars / len(rows) * 100.0, 10),
''',
        '''        "exposure_pct": round(exposure_bars / evaluation_bars * 100.0, 10),
''',
        "EVALUATION_EXPOSURE_DENOMINATOR",
    )

    source = replace_once(
        source,
        '''            start = int(segment["start_row"])
            stop = int(segment["end_row_exclusive"])
            sample = frame.iloc[start:stop].copy().reset_index(drop=True)
            if len(sample) != int(contract["segment_bars"]):
                raise ValueError(f"SEGMENT_BAR_COUNT_INVALID:{len(sample)}")
            segment_frames[segment_id] = sample
''',
        '''            start = int(segment["start_row"])
            stop = int(segment["end_row_exclusive"])
            evaluation_bars = int(contract["segment_bars"])
            preroll_bars = int(contract.get("indicator_preroll_bars", evaluation_bars))
            sample = select_segment_with_preroll(
                frame,
                start,
                stop,
                evaluation_bars,
                preroll_bars,
            )
            segment_frames[segment_id] = sample
''',
        "MAIN_SEGMENT_PREROLL",
    )

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    source = input_path.read_text(encoding="utf-8")
    patched = apply_patch(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    py_compile.compile(str(output_path), doraise=True)

    print("STATE=PASS_ENTRY_CHAIN_PATCH_BUILD")
    print("PATCHED_RUNNER=" + str(output_path))
    print("INDICATOR_PREROLL_BARS=320")
    print("LINEAGE_TARGET_STRATEGY_COUNT=5")
    print("ENTRY_THRESHOLD_RELAXATION_ALLOWED=false")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
