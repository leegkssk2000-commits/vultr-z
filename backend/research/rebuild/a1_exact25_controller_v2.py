from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.research.rebuild import a1_exact25_controller_v1 as v1

RULE_PATH = ROOT / "backend/research/rebuild/a1_exact25_resource_budget_v1.json"
LEDGER_PATH = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"


def load_rule() -> dict[str, Any]:
    value = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    if value.get("state") != "FROZEN_RESEARCH_RESOURCE_ALLOCATION_RULE":
        raise RuntimeError("RESOURCE_BUDGET_NOT_FROZEN")
    return value


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _source_symbols(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    source = receipt.get("source") or {}
    rows = source.get("symbols") if isinstance(source, dict) else None
    return [x for x in (rows or []) if isinstance(x, dict)]


def _timeframe_ms(receipt: dict[str, Any], symbols: list[dict[str, Any]]) -> int | None:
    source = receipt.get("source") or {}
    interval = str(source.get("interval") or "") if isinstance(source, dict) else ""
    table = {
        "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
        "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000,
    }
    if interval in table:
        return table[interval]
    estimates: list[float] = []
    for row in symbols:
        n = int(row.get("bars_post_boundary") or 0)
        first = row.get("first_post_boundary_ts")
        last = row.get("last_post_boundary_ts")
        if n >= 2 and first is not None and last is not None and int(last) > int(first):
            estimates.append((int(last) - int(first)) / (n - 1))
    if not estimates:
        return None
    estimates.sort()
    return int(estimates[len(estimates) // 2])


def resource_disposition(receipt: dict[str, Any], *, now: datetime | None = None) -> tuple[str | None, str | None]:
    rule = load_rule()
    budget = rule["budget"]
    symbols = _source_symbols(receipt)
    if len(symbols) < int(budget["minimum_symbols_required"]):
        return "A1_DATA_BLOCKED", f"SOURCE_SYMBOL_COVERAGE_LT_REQUIRED:{len(symbols)}"

    bars = [int(x.get("bars_post_boundary") or 0) for x in symbols]
    min_bars = min(bars) if bars else 0
    total_bars = sum(bars)
    intents = int(receipt.get("intent_count") or 0)
    trades = int(receipt.get("completed_trades") or 0)

    boundary_raw = receipt.get("boundary_utc")
    if boundary_raw is None and isinstance(receipt.get("activation"), dict):
        boundary_raw = receipt["activation"].get("prospective_boundary_utc")
    timeframe_ms = _timeframe_ms(receipt, symbols)
    if boundary_raw and timeframe_ms and timeframe_ms > 0:
        current = now or datetime.now(timezone.utc)
        elapsed_ms = max(0.0, (current - parse_utc(str(boundary_raw))).total_seconds() * 1000.0)
        expected_bars = max(0, int(math.floor(elapsed_ms / timeframe_ms)))
        db = budget["data_blocked"]
        if expected_bars >= int(db["minimum_wallclock_equivalent_bars_before_check"]):
            missing_fraction = max(0.0, (expected_bars - min_bars) / max(1, expected_bars))
            if missing_fraction > float(db["maximum_missing_bar_fraction"]):
                return "A1_DATA_BLOCKED", (
                    f"SOURCE_CADENCE_MISSING:expected={expected_bars}:min_observed={min_bars}:"
                    f"missing_fraction={missing_fraction:.6f}"
                )

    min_zero = int(budget["minimum_elapsed_bars_per_symbol_for_zero_intent"])
    max_sparse = int(budget["maximum_elapsed_bars_per_symbol_for_inadequate_completed_trades"])
    min_trades = int(budget["minimum_completed_trades_to_avoid_sparse_resource_disposition_at_max_budget"])
    if intents == 0 and min_bars >= min_zero:
        return "A1_SPARSE_EVENT_FUTILITY", f"ZERO_INTENT_RESOURCE_BUDGET_EXHAUSTED:min_bars={min_bars}:total_bars={total_bars}"
    if min_bars >= max_sparse and trades < min_trades:
        return "A1_SPARSE_EVENT_FUTILITY", (
            f"INADEQUATE_COMPLETED_TRADES_AT_MAX_RESOURCE_BUDGET:min_bars={min_bars}:"
            f"intents={intents}:trades={trades}:required={min_trades}"
        )
    return None, None


def terminal_disposition(receipt: dict[str, Any], hardening: dict[str, Any]) -> tuple[str | None, str | None]:
    disposition, reason = v1.terminal_disposition(receipt, hardening)
    if disposition is not None or reason == "IMPLEMENTATION_INTEGRITY_REQUIRES_REPAIR":
        return disposition, reason
    return resource_disposition(receipt)


def validate_ledger_contract(ledger: dict[str, Any]) -> None:
    order = ledger.get("strategy_order") or []
    strategies = ledger.get("strategies") or {}
    if len(order) != 25 or len(set(order)) != 25:
        raise RuntimeError("EXACT25_IDENTITY_CONTRACT_BROKEN")
    if set(order) != set(strategies):
        raise RuntimeError("EXACT25_IDENTITY_SKIP_OR_EXTRA")
    active = [sid for sid, row in strategies.items() if isinstance(row, dict) and row.get("status") == "ACTIVE"]
    active_id = ledger.get("active_strategy_id")
    if active_id is None:
        if active:
            raise RuntimeError("ACTIVE_ID_NULL_WITH_ACTIVE_STRATEGY")
    elif active != [active_id]:
        raise RuntimeError(f"ONE_HEAVY_CONTRACT_BROKEN:{active}:{active_id}")
    if ledger.get("one_heavy_evaluator_at_a_time") is not True:
        raise RuntimeError("ONE_HEAVY_FLAG_REQUIRED")


def main() -> None:
    validate_ledger_contract(json.loads(LEDGER_PATH.read_text(encoding="utf-8")))
    v1.terminal_disposition = terminal_disposition
    v1.main()


if __name__ == "__main__":
    main()
