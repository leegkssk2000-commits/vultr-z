#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "SHORT_EXECUTION_HARNESS_V1" in source:
        raise RuntimeError("RUNNER_ALREADY_SHORT_PATCHED")
    if "ENTRY_LINEAGE_REASONS:" not in source:
        raise RuntimeError("ENTRY_CHAIN_PATCH_REQUIRED")

    source = replace_once(
        source,
        '''def lineage_allows_add(strategy_id: str, position: dict[str, Any]) -> bool:
    allowed = ENTRY_LINEAGE_REASONS.get(strategy_id)
    if allowed is None:
        return True
    return (
        str(position.get("entry_strategy_id") or "") == strategy_id
        and str(position.get("entry_event") or "") in allowed
    )


''',
        '''SHORT_EXECUTION_HARNESS_V1 = True
SHORT_ACTIVE_ACTIONS = frozenset({"enter", "add", "reduce", "exit", "close"})


def lineage_allows_add(strategy_id: str, position: dict[str, Any]) -> bool:
    entry_strategy_id = str(position.get("entry_strategy_id") or "")
    entry_event = str(position.get("entry_event") or "")
    if str(position.get("side") or "") == "short":
        return entry_strategy_id == strategy_id and bool(entry_event)
    allowed = ENTRY_LINEAGE_REASONS.get(strategy_id)
    if allowed is None:
        return True
    return entry_strategy_id == strategy_id and entry_event in allowed


''',
        "SHORT_LINEAGE_HELPERS",
    )

    source = replace_once(
        source,
        '''    allowed_intents = {str(item) for item in contract.get("allowed_intents", [])}
    fee_rate = float(cost["fee_bps_per_side"]) / 10000.0
''',
        '''    allowed_intents = {str(item) for item in contract.get("allowed_intents", [])}
    short_execution_enabled = bool(contract.get("short_execution_enabled", False))
    short_target_strategy_ids = {
        str(item) for item in contract.get("short_target_strategy_ids", []) if str(item)
    }
    fee_rate = float(cost["fee_bps_per_side"]) / 10000.0
''',
        "SHORT_CONTRACT_FLAGS",
    )

    source = replace_once(
        source,
        '''    invalid_signal_count = 0
    orphan_add_block_count = 0
    strategy_call_count = 0
    intent_histogram: Counter[str] = Counter()
''',
        '''    invalid_signal_count = 0
    orphan_add_block_count = 0
    short_enter_signal_count = 0
    short_add_signal_count = 0
    short_reduce_signal_count = 0
    short_exit_signal_count = 0
    short_invalid_geometry_count = 0
    short_orphan_add_block_count = 0
    strategy_call_count = 0
    intent_histogram: Counter[str] = Counter()
''',
        "SHORT_COUNTERS",
    )

    source = replace_once(
        source,
        '''        fill = max(float(raw_price) * (1.0 - slip_rate), 1e-12)
        gross = quantity * (fill / float(position["avg_entry"]) - 1.0)
''',
        '''        position_side = str(position.get("side") or "long")
        if position_side == "short":
            fill = max(float(raw_price) * (1.0 + slip_rate), 1e-12)
            gross = quantity * (float(position["avg_entry"]) / fill - 1.0)
        else:
            fill = max(float(raw_price) * (1.0 - slip_rate), 1e-12)
            gross = quantity * (fill / float(position["avg_entry"]) - 1.0)
''',
        "SIDE_AWARE_CLOSE_MATH",
    )

    source = replace_once(
        source,
        '''        nonlocal realized, total_cost, current_trade, invalid_signal_count, orphan_add_block_count
        kind = action["kind"]
        target_qty = max(float(action.get("target_qty") or 0.0), 0.0)
        signal = action.get("legacy") if isinstance(action.get("legacy"), dict) else {}
        entry_event = str(action.get("entry_event") or signal.get("why") or "")
        if kind == "add" and not lineage_allows_add(strategy_id, position):
            orphan_add_block_count += 1
            return
        if kind in {"enter", "add"}:
            quantity = min(target_qty, max(max_qty - float(position["qty"]), 0.0))
            fill = max(open_price * (1.0 + slip_rate), 1e-12)
            stop = float(signal.get("sl") or 0.0)
            tp = float(signal.get("tp") or 0.0)
            if quantity <= 0 or not (0 < stop < fill < tp):
                invalid_signal_count += 1
                return
            fee = quantity * fee_rate
            realized -= fee
            total_cost += fee
            risk_pct = quantity * (fill - stop) / fill * 100.0
            old_qty = float(position["qty"])
''',
        '''        nonlocal realized, total_cost, current_trade, invalid_signal_count, orphan_add_block_count, short_invalid_geometry_count, short_orphan_add_block_count
        kind = action["kind"]
        action_side = str(action.get("side") or "long").lower()
        target_qty = max(float(action.get("target_qty") or 0.0), 0.0)
        signal = action.get("legacy") if isinstance(action.get("legacy"), dict) else {}
        entry_event = str(action.get("entry_event") or signal.get("why") or "")
        if action_side not in {"long", "short"}:
            invalid_signal_count += 1
            return
        if kind == "add" and not lineage_allows_add(strategy_id, position):
            orphan_add_block_count += 1
            if action_side == "short":
                short_orphan_add_block_count += 1
            return
        if kind in {"enter", "add"}:
            old_qty = float(position["qty"])
            if old_qty > 0 and str(position.get("side") or "") != action_side:
                invalid_signal_count += 1
                return
            quantity = min(target_qty, max(max_qty - old_qty, 0.0))
            fill = max(
                open_price * (1.0 - slip_rate if action_side == "short" else 1.0 + slip_rate),
                1e-12,
            )
            stop = float(signal.get("sl") or 0.0)
            tp = float(signal.get("tp") or 0.0)
            geometry_ok = (
                0 < tp < fill < stop
                if action_side == "short"
                else 0 < stop < fill < tp
            )
            if quantity <= 0 or not geometry_ok:
                invalid_signal_count += 1
                if action_side == "short":
                    short_invalid_geometry_count += 1
                return
            fee = quantity * fee_rate
            realized -= fee
            total_cost += fee
            risk_pct = quantity * (
                (stop - fill) / fill if action_side == "short" else (fill - stop) / fill
            ) * 100.0
''',
        "SIDE_AWARE_EXECUTION_HEADER",
    )

    source = replace_once(
        source,
        '''                position.update({
                    "side": "long",
                    "qty": quantity,
                    "avg_entry": fill,
                    "stop": stop,
                    "tp": tp,
                    "add_count": 0,
                    "last_add_price": fill,
                    "entry_strategy_id": strategy_id,
                    "entry_event": entry_event,
                })
                current_trade = {
                    "entry_index": bar_index - evaluation_start,
                    "entry_strategy_id": strategy_id,
                    "entry_event": entry_event,
''',
        '''                position.update({
                    "side": action_side,
                    "qty": quantity,
                    "avg_entry": fill,
                    "stop": stop,
                    "tp": tp,
                    "add_count": 0,
                    "last_add_price": fill,
                    "entry_strategy_id": strategy_id,
                    "entry_event": entry_event,
                })
                current_trade = {
                    "side": action_side,
                    "entry_index": bar_index - evaluation_start,
                    "entry_strategy_id": strategy_id,
                    "entry_event": entry_event,
''',
        "SIDE_AWARE_POSITION_OPEN",
    )

    source = replace_once(
        source,
        '''                new_qty = old_qty + quantity
                position["avg_entry"] = (float(position["avg_entry"]) * old_qty + fill * quantity) / new_qty
                position["qty"] = new_qty
                position["stop"] = max(float(position["stop"]), stop)
                position["tp"] = max(float(position["tp"]), tp)
                position["add_count"] = int(position["add_count"]) + 1
''',
        '''                new_qty = old_qty + quantity
                new_avg = (float(position["avg_entry"]) * old_qty + fill * quantity) / new_qty
                if action_side == "short":
                    new_stop = min(float(position["stop"]), stop)
                    new_tp = min(float(position["tp"]), tp)
                    if not (0 < new_tp < new_avg < new_stop):
                        invalid_signal_count += 1
                        short_invalid_geometry_count += 1
                        return
                else:
                    new_stop = max(float(position["stop"]), stop)
                    new_tp = max(float(position["tp"]), tp)
                position["avg_entry"] = new_avg
                position["qty"] = new_qty
                position["stop"] = new_stop
                position["tp"] = new_tp
                position["add_count"] = int(position["add_count"]) + 1
''',
        "SIDE_AWARE_ADD_GEOMETRY",
    )

    source = replace_once(
        source,
        '''        elif kind == "reduce" and position["qty"] > 0:
            close_qty(target_qty if target_qty > 0 else float(position["qty"]), open_price, bar_index, "signal_reduce")
        elif kind == "exit" and position["qty"] > 0:
            close_qty(float(position["qty"]), open_price, bar_index, "signal_exit")
''',
        '''        elif (
            kind == "reduce"
            and position["qty"] > 0
            and str(position.get("side") or "") == action_side
        ):
            close_qty(
                target_qty if target_qty > 0 else float(position["qty"]),
                open_price,
                bar_index,
                "signal_reduce",
            )
        elif (
            kind == "exit"
            and position["qty"] > 0
            and str(position.get("side") or "") == action_side
        ):
            close_qty(float(position["qty"]), open_price, bar_index, "signal_exit")
''',
        "SIDE_AWARE_REDUCE_EXIT",
    )

    source = replace_once(
        source,
        '''            if current_trade is not None:
                avg = max(float(position["avg_entry"]), 1e-12)
                current_trade["mfe_pct"] = max(float(current_trade["mfe_pct"]), (high_price / avg - 1.0) * 100.0)
                current_trade["mae_pct"] = min(float(current_trade["mae_pct"]), (low_price / avg - 1.0) * 100.0)
            stop_hit = low_price <= float(position["stop"])
            tp_hit = high_price >= float(position["tp"])
            if stop_hit:
                raw_exit = min(open_price, float(position["stop"]))
                close_qty(float(position["qty"]), raw_exit, index, "stop_collision" if tp_hit else "stop")
            elif tp_hit:
                raw_exit = max(open_price, float(position["tp"]))
                close_qty(float(position["qty"]), raw_exit, index, "take_profit")
''',
        '''            position_side = str(position.get("side") or "long")
            if current_trade is not None:
                avg = max(float(position["avg_entry"]), 1e-12)
                if position_side == "short":
                    current_trade["mfe_pct"] = max(
                        float(current_trade["mfe_pct"]),
                        (avg / max(low_price, 1e-12) - 1.0) * 100.0,
                    )
                    current_trade["mae_pct"] = min(
                        float(current_trade["mae_pct"]),
                        (avg / max(high_price, 1e-12) - 1.0) * 100.0,
                    )
                else:
                    current_trade["mfe_pct"] = max(
                        float(current_trade["mfe_pct"]),
                        (high_price / avg - 1.0) * 100.0,
                    )
                    current_trade["mae_pct"] = min(
                        float(current_trade["mae_pct"]),
                        (low_price / avg - 1.0) * 100.0,
                    )
            if position_side == "short":
                stop_hit = high_price >= float(position["stop"])
                tp_hit = low_price <= float(position["tp"])
                if stop_hit:
                    raw_exit = max(open_price, float(position["stop"]))
                    close_qty(
                        float(position["qty"]),
                        raw_exit,
                        index,
                        "stop_collision" if tp_hit else "stop",
                    )
                elif tp_hit:
                    raw_exit = min(open_price, float(position["tp"]))
                    close_qty(float(position["qty"]), raw_exit, index, "take_profit")
            else:
                stop_hit = low_price <= float(position["stop"])
                tp_hit = high_price >= float(position["tp"])
                if stop_hit:
                    raw_exit = min(open_price, float(position["stop"]))
                    close_qty(
                        float(position["qty"]),
                        raw_exit,
                        index,
                        "stop_collision" if tp_hit else "stop",
                    )
                elif tp_hit:
                    raw_exit = max(open_price, float(position["tp"]))
                    close_qty(float(position["qty"]), raw_exit, index, "take_profit")
''',
        "SIDE_AWARE_INTRABAR",
    )

    source = replace_once(
        source,
        '''        unrealized = 0.0
        if position["qty"] > 0:
            unrealized = float(position["qty"]) * (close_price / float(position["avg_entry"]) - 1.0)
''',
        '''        unrealized = 0.0
        if position["qty"] > 0:
            if str(position.get("side") or "") == "short":
                unrealized = float(position["qty"]) * (
                    float(position["avg_entry"]) / max(close_price, 1e-12) - 1.0
                )
            else:
                unrealized = float(position["qty"]) * (
                    close_price / float(position["avg_entry"]) - 1.0
                )
''',
        "SIDE_AWARE_UNREALIZED",
    )

    source = replace_once(
        source,
        '''        legacy = legacy_signal(fields)
        if str(legacy.get("side") or "").lower() == "short" and str(legacy.get("action") or "").lower() in {"enter", "add"}:
            short_shadow_signal_count += 1
        if not fields["ok"] or intent in {"hold", "block"}:
            continue
        signal_count += 1
        legacy_action = str(legacy.get("action") or "").lower()
        target_qty = float(fields.get("target_qty") or legacy.get("size") or 0.0)
        if intent == "enter_long":
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
        elif intent == "reduce" and position["qty"] > 0:
            execute_index = index + exit_delay
            if execute_index < len(rows) and not any(item["kind"] == "reduce" for item in pending):
                pending.append({"kind": "reduce", "execute_index": execute_index, "target_qty": target_qty, "legacy": legacy})
                reduce_signal_count += 1
        elif intent == "exit_long" and position["qty"] > 0:
            execute_index = index + exit_delay
            if execute_index < len(rows) and not any(item["kind"] == "exit" for item in pending):
                pending.append({"kind": "exit", "execute_index": execute_index, "target_qty": float(position["qty"]), "legacy": legacy})
                exit_signal_count += 1
''',
        '''        legacy = legacy_signal(fields)
        legacy_side = str(legacy.get("side") or "").lower()
        legacy_action = str(legacy.get("action") or "").lower()
        if legacy_side == "short" and legacy_action in SHORT_ACTIVE_ACTIONS:
            short_shadow_signal_count += 1
        short_execute = (
            short_execution_enabled
            and strategy_id in short_target_strategy_ids
            and bool(fields["ok"])
            and intent == "hold"
            and legacy_side == "short"
            and legacy_action in SHORT_ACTIVE_ACTIONS
        )
        if not fields["ok"] or intent == "block":
            continue
        if intent == "hold" and not short_execute:
            continue
        signal_count += 1
        target_qty = float(fields.get("target_qty") or legacy.get("size") or 0.0)

        if short_execute:
            short_kind = "exit" if legacy_action in {"exit", "close"} else legacy_action
            execute_index = index + (
                entry_delay if short_kind in {"enter", "add"} else exit_delay
            )
            if execute_index >= len(rows):
                continue
            if short_kind == "enter":
                if position["qty"] > 0 or any(item["kind"] == "enter" for item in pending):
                    continue
                pending.append({
                    "kind": "enter",
                    "side": "short",
                    "execute_index": execute_index,
                    "target_qty": target_qty,
                    "legacy": legacy,
                    "strategy_id": strategy_id,
                    "entry_event": str(legacy.get("why") or fields.get("reason") or ""),
                })
                short_enter_signal_count += 1
            elif short_kind == "add":
                if (
                    position["qty"] <= 0
                    or str(position.get("side") or "") != "short"
                    or not lineage_allows_add(strategy_id, position)
                ):
                    orphan_add_block_count += 1
                    short_orphan_add_block_count += 1
                    continue
                if any(item["kind"] == "add" for item in pending):
                    continue
                pending.append({
                    "kind": "add",
                    "side": "short",
                    "execute_index": execute_index,
                    "target_qty": target_qty,
                    "legacy": legacy,
                    "strategy_id": strategy_id,
                    "entry_event": str(legacy.get("why") or fields.get("reason") or ""),
                })
                short_add_signal_count += 1
            elif (
                short_kind == "reduce"
                and position["qty"] > 0
                and str(position.get("side") or "") == "short"
                and not any(item["kind"] == "reduce" for item in pending)
            ):
                pending.append({
                    "kind": "reduce",
                    "side": "short",
                    "execute_index": execute_index,
                    "target_qty": target_qty,
                    "legacy": legacy,
                })
                short_reduce_signal_count += 1
            elif (
                short_kind == "exit"
                and position["qty"] > 0
                and str(position.get("side") or "") == "short"
                and not any(item["kind"] == "exit" for item in pending)
            ):
                pending.append({
                    "kind": "exit",
                    "side": "short",
                    "execute_index": execute_index,
                    "target_qty": float(position["qty"]),
                    "legacy": legacy,
                })
                short_exit_signal_count += 1
            continue

        if intent == "enter_long":
            kind = "add" if legacy_action == "add" else "enter"
            if kind == "enter" and (
                position["qty"] > 0 or any(item["kind"] == "enter" for item in pending)
            ):
                continue
            if kind == "add":
                if (
                    position["qty"] <= 0
                    or str(position.get("side") or "") != "long"
                    or not lineage_allows_add(strategy_id, position)
                ):
                    orphan_add_block_count += 1
                    continue
                if any(item["kind"] == "add" for item in pending):
                    continue
            execute_index = index + entry_delay
            if execute_index < len(rows):
                pending.append({
                    "kind": kind,
                    "side": "long",
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
        elif (
            intent == "reduce"
            and position["qty"] > 0
            and str(position.get("side") or "") == "long"
        ):
            execute_index = index + exit_delay
            if execute_index < len(rows) and not any(
                item["kind"] == "reduce" for item in pending
            ):
                pending.append({
                    "kind": "reduce",
                    "side": "long",
                    "execute_index": execute_index,
                    "target_qty": target_qty,
                    "legacy": legacy,
                })
                reduce_signal_count += 1
        elif (
            intent == "exit_long"
            and position["qty"] > 0
            and str(position.get("side") or "") == "long"
        ):
            execute_index = index + exit_delay
            if execute_index < len(rows) and not any(
                item["kind"] == "exit" for item in pending
            ):
                pending.append({
                    "kind": "exit",
                    "side": "long",
                    "execute_index": execute_index,
                    "target_qty": float(position["qty"]),
                    "legacy": legacy,
                })
                exit_signal_count += 1
''',
        "DUAL_SIDE_SIGNAL_INTERPRETER",
    )

    source = replace_once(
        source,
        '''        "short_shadow_signal_count": short_shadow_signal_count,
        "invalid_signal_count": invalid_signal_count,
        "orphan_add_block_count": orphan_add_block_count,
        "trade_count": len(trades),
''',
        '''        "short_shadow_signal_count": short_shadow_signal_count,
        "short_enter_signal_count": short_enter_signal_count,
        "short_add_signal_count": short_add_signal_count,
        "short_reduce_signal_count": short_reduce_signal_count,
        "short_exit_signal_count": short_exit_signal_count,
        "short_invalid_geometry_count": short_invalid_geometry_count,
        "short_orphan_add_block_count": short_orphan_add_block_count,
        "short_closed_trade_count": sum(
            1 for trade in trades if str(trade.get("side") or "") == "short"
        ),
        "invalid_signal_count": invalid_signal_count,
        "orphan_add_block_count": orphan_add_block_count,
        "trade_count": len(trades),
''',
        "SHORT_RESULT_FIELDS",
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
        "w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        delete=False,
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    py_compile.compile(str(output_path), doraise=True)

    print("STATE=PASS_SHORT_EXECUTION_PATCH_BUILD")
    print("PATCHED_RUNNER=" + str(output_path))
    print("PRODUCTION_ADAPTER_MUTATION_ALLOWED=false")
    print("SHORT_EXECUTION_DEFAULT_ENABLED=false")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
