from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as v1
from backend.research.rebuild.a1_exact25_hardening_evidence_adapter_v1 import load_verified_hardening_evidence
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions
from backend.research.rebuild.a1_exact25_survivor_gate_v1 import attach_survivor_gate, stable_sha

ROOT = Path(__file__).resolve().parents[3]
RESOURCE_RULE_PATH = ROOT / "backend/research/rebuild/a1_exact25_resource_budget_v1.json"
PUBLIC_KLINE_FETCH_LIMIT = 1000
INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000,
}

v1.policy_functions = policy_functions

_base_request_json = v1.request_json


def request_json_with_transient_retry(url: str, params: dict[str, object]):
    """Retry only BingX's explicit transient 100410 response; all other defects fail closed."""
    for attempt in range(3):
        try:
            return _base_request_json(url, params)
        except RuntimeError as exc:
            if "BINGX_API_ERROR:100410:" not in str(exc) or attempt >= 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("UNREACHABLE_TRANSIENT_RETRY")


v1.request_json = request_json_with_transient_retry


def _output_path(argv: list[str]) -> Path:
    for i, arg in enumerate(argv):
        if arg == "--out" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--out="):
            return Path(arg.split("=", 1)[1])
    return Path("a1_exact25_receipt.json")


def _finite_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite_json(v) for v in value]
    return value


def _parse_utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def _resource_data_block_rule() -> dict[str, Any]:
    value = json.loads(RESOURCE_RULE_PATH.read_text(encoding="utf-8"))
    if value.get("state") != "FROZEN_RESEARCH_RESOURCE_ALLOCATION_RULE":
        raise RuntimeError("RESOURCE_BUDGET_NOT_FROZEN")
    return dict((value.get("budget") or {}).get("data_blocked") or {})


def source_quality_gate(receipt: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Verify post-boundary cadence and recency using only the frozen resource SSOT.

    `source_ready` in the scheduler proves that policy/source adapters exist; it
    does not prove that the runtime receipt contains the expected closed bars.
    This gate closes that distinction without changing strategy economics.
    """
    source = receipt.get("source") if isinstance(receipt.get("source"), dict) else {}
    interval = str(source.get("interval") or "")
    tf_ms = INTERVAL_MS.get(interval)
    boundary_raw = str(receipt.get("boundary_utc") or "")
    rows = [x for x in (source.get("symbols") or []) if isinstance(x, dict)]
    defects: list[str] = []
    checks: list[dict[str, Any]] = []
    if tf_ms is None:
        defects.append(f"SOURCE_INTERVAL_UNSUPPORTED:{interval or '<missing>'}")
    if not boundary_raw:
        defects.append("SOURCE_BOUNDARY_MISSING")
    if not rows:
        defects.append("SOURCE_SYMBOL_ROWS_MISSING")
    if defects:
        return {"state": "FAIL", "defects": defects, "checks": checks, "ssot": str(RESOURCE_RULE_PATH.relative_to(ROOT))}

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current_ms = int(current.timestamp() * 1000)
    boundary_ms = _parse_utc_ms(boundary_raw)
    expected_total = max(0, int(math.floor(max(0, current_ms - boundary_ms) / tf_ms)))
    expected_visible = min(expected_total, PUBLIC_KLINE_FETCH_LIMIT)
    db = _resource_data_block_rule()
    minimum_before_check = int(db["minimum_wallclock_equivalent_bars_before_check"])
    maximum_missing = float(db["maximum_missing_bar_fraction"])

    if expected_total < minimum_before_check:
        return {
            "state": "PENDING",
            "defects": [],
            "checks": [],
            "expected_total_bars": expected_total,
            "expected_visible_bars": expected_visible,
            "minimum_before_check": minimum_before_check,
            "ssot": str(RESOURCE_RULE_PATH.relative_to(ROOT)),
        }

    latest_closed_open_ms = (current_ms // tf_ms) * tf_ms - tf_ms
    for row in rows:
        symbol = str(row.get("symbol") or "<unknown>")
        observed = int(row.get("bars_post_boundary") or 0)
        first_ts = row.get("first_post_boundary_ts")
        last_ts = row.get("last_post_boundary_ts")
        missing_fraction = max(0.0, (expected_visible - observed) / max(1, expected_visible))
        if missing_fraction > maximum_missing:
            defects.append(
                f"SOURCE_CADENCE_MISSING:{symbol}:expected_visible={expected_visible}:observed={observed}:missing_fraction={missing_fraction:.6f}"
            )
        lag_bars: int | None = None
        lag_fraction: float | None = None
        if observed <= 0 or last_ts is None:
            defects.append(f"SOURCE_RECENCY_MISSING:{symbol}:observed={observed}")
        else:
            last_ms = int(last_ts)
            if last_ms > current_ms + tf_ms:
                defects.append(f"SOURCE_TIMESTAMP_FUTURE:{symbol}:last={last_ms}:now={current_ms}")
            lag_bars = max(0, int((latest_closed_open_ms - last_ms) // tf_ms))
            lag_fraction = lag_bars / max(1, expected_visible)
            if lag_fraction > maximum_missing:
                defects.append(
                    f"SOURCE_RECENCY_STALE:{symbol}:lag_bars={lag_bars}:lag_fraction={lag_fraction:.6f}"
                )
        if first_ts is not None and int(first_ts) < boundary_ms - tf_ms:
            defects.append(f"SOURCE_PREBOUNDARY_LEAK:{symbol}:first={int(first_ts)}:boundary={boundary_ms}")
        checks.append({
            "symbol": symbol,
            "observed_bars": observed,
            "expected_visible_bars": expected_visible,
            "missing_fraction": missing_fraction,
            "last_post_boundary_ts": last_ts,
            "lag_bars": lag_bars,
            "lag_fraction": lag_fraction,
        })

    return {
        "state": "FAIL" if defects else "PASS",
        "defects": defects,
        "checks": checks,
        "expected_total_bars": expected_total,
        "expected_visible_bars": expected_visible,
        "api_visibility_cap_bars": PUBLIC_KLINE_FETCH_LIMIT,
        "maximum_missing_fraction": maximum_missing,
        "ssot": str(RESOURCE_RULE_PATH.relative_to(ROOT)),
    }


def main() -> None:
    # Preserve v1 economics exactly. V2 adds only source-integrity and survivor
    # evidence attachment; neither path changes entries, exits, costs, or PnL.
    v1.main()
    out_path = _output_path(sys.argv[1:])
    receipt = _finite_json(json.loads(out_path.read_text(encoding="utf-8")))
    receipt["source_quality_gate"] = source_quality_gate(receipt)
    if receipt["source_quality_gate"]["state"] == "FAIL":
        receipt["state"] = "A1_DATA_BLOCKED"
        receipt["terminal_reason"] = "SOURCE_QUALITY_GATE_FAIL:" + ";".join(receipt["source_quality_gate"]["defects"][:8])

    hardening_evidence = load_verified_hardening_evidence(receipt)
    receipt = attach_survivor_gate(receipt, hardening_evidence=hardening_evidence)

    # Keep the legacy/public field required by downstream ledgers, but derive it
    # strictly from the attached H4 gate. Missing H4 remains PENDING; nothing is
    # inferred or auto-passed.
    receipt["negative_control_state"] = str(
        receipt.get("negative_control_gate") or "PENDING_H4_NEGATIVE_CONTROL_SUPERIORITY"
    )
    receipt["receipt_sha256"] = stable_sha(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )

    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False, default=str), encoding="utf-8")
    print(json.dumps({
        "state": receipt.get("state"),
        "strategy_id": receipt.get("strategy_id"),
        "completed_trades": receipt.get("completed_trades"),
        "source_quality_state": (receipt.get("source_quality_gate") or {}).get("state"),
        "negative_control_state": receipt.get("negative_control_state"),
        "survivor_gate_state": (receipt.get("survivor_gate") or {}).get("state"),
        "survivor_gate_passed": (receipt.get("survivor_gate") or {}).get("passed"),
        "receipt_sha256": receipt.get("receipt_sha256"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
