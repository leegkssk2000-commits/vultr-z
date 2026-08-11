from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

SCHEMA = "zel.production_paper_account_state.v1"
POLICY_SCHEMA = "zel.production_paper_account_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_paper_account_v1.json")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _float(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"ACCOUNT_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"ACCOUNT_NUMERIC_NONFINITE:{name}")
    return out


def _policy_value(policy: Mapping[str, Any], key: str) -> Any:
    value = policy.get(key)
    if value is not None:
        return value
    env_map = policy.get("required_env_when_null")
    env_name = env_map.get(key) if isinstance(env_map, Mapping) else None
    if not env_name:
        raise RuntimeError(f"ACCOUNT_POLICY_VALUE_UNBOUND:{key}")
    value = os.environ.get(str(env_name))
    if value is None or not str(value).strip():
        raise RuntimeError(f"ACCOUNT_POLICY_ENV_UNBOUND:{key}:{env_name}")
    return value


def validate_policy(policy: Mapping[str, Any]) -> tuple[float, ZoneInfo]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("ACCOUNT_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("ACCOUNT_POLICY_NON_PAPER_FORBIDDEN")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("ACCOUNT_POLICY_LIVE_AUTHORITY_FORBIDDEN")
    initial = _float(_policy_value(policy, "initial_equity_usdt"), "initial_equity_usdt")
    if initial <= 0:
        raise RuntimeError("ACCOUNT_INITIAL_EQUITY_NONPOSITIVE")
    tz_name = str(_policy_value(policy, "risk_day_timezone"))
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:
        raise RuntimeError(f"ACCOUNT_RISK_DAY_TZ_INVALID:{tz_name}") from exc
    return initial, tz


def _snapshot_total_pnl(snapshot: Mapping[str, Any] | None) -> tuple[float, str]:
    if snapshot is None:
        return 0.0, "FLAT"
    canonical = snapshot.get("canonical") if isinstance(snapshot.get("canonical"), Mapping) else snapshot
    if not isinstance(canonical, Mapping):
        raise RuntimeError("ACCOUNT_SNAPSHOT_INVALID")
    pnl = canonical.get("pnl")
    position = canonical.get("position")
    if not isinstance(pnl, Mapping) or not isinstance(position, Mapping):
        raise RuntimeError("ACCOUNT_SNAPSHOT_FIELDS_MISSING")
    total = _float(pnl.get("total"), "snapshot.pnl.total")
    state = str(position.get("state") or "").upper()
    if state not in {"FLAT", "LONG", "SHORT"}:
        raise RuntimeError("ACCOUNT_POSITION_STATE_INVALID")
    return total, state


def build_account_state(
    *,
    policy: Mapping[str, Any],
    snapshot: Mapping[str, Any] | None,
    prior: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    initial, tz = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if now <= 0:
        raise RuntimeError("ACCOUNT_NOW_INVALID")
    total_pnl, position_state = _snapshot_total_pnl(snapshot)
    equity = initial + total_pnl
    if equity <= 0:
        raise RuntimeError("ACCOUNT_EQUITY_DEPLETED")

    current_day = datetime.fromtimestamp(now / 1000.0, tz=tz).date().isoformat()
    prior = dict(prior) if isinstance(prior, Mapping) else {}
    prior_initial = prior.get("initial_equity_usdt")
    if prior_initial is not None and abs(_float(prior_initial, "prior.initial_equity_usdt") - initial) > 1e-9:
        raise RuntimeError("ACCOUNT_INITIAL_EQUITY_CHANGED")

    prior_peak = _float(prior.get("peak_equity_usdt", initial), "prior.peak_equity_usdt")
    peak = max(initial, prior_peak, equity)
    if str(prior.get("risk_day") or "") == current_day:
        day_start = _float(prior.get("day_start_equity_usdt", equity), "prior.day_start_equity_usdt")
    else:
        day_start = equity
    if day_start <= 0 or peak <= 0:
        raise RuntimeError("ACCOUNT_REFERENCE_EQUITY_INVALID")

    dd_day = max(0.0, (day_start - equity) / day_start * 100.0)
    dd_total = max(0.0, (peak - equity) / peak * 100.0)
    # New exposure is only allowed when FLAT. While a simulated position is open,
    # available balance is deliberately zero so no second open can be sized even
    # if an upstream duplicate signal bypasses the position gate.
    available = equity if position_state == "FLAT" else 0.0

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_PAPER_ACCOUNT_STATE",
        "mode": "PAPER",
        "updated_at_ms": now,
        "risk_day": current_day,
        "risk_day_timezone": str(tz.key),
        "initial_equity_usdt": initial,
        "equity_usdt": equity,
        "available_balance_usdt": available,
        "peak_equity_usdt": peak,
        "day_start_equity_usdt": day_start,
        "dd_day_pct": dd_day,
        "dd_total_pct": dd_total,
        "position_state": position_state,
        "pnl_total_usdt": total_pnl,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"ACCOUNT_JSON_NOT_OBJECT:{path}")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL canonical PAPER account-state producer")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    args = parser.parse_args(argv)
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    snapshot_path = args.snapshot or Path(str(policy.get("canonical_snapshot_path")))
    state_path = args.state or Path(str(policy.get("account_state_path")))
    prior = read_json_if_exists(state_path)
    snapshot = read_json_if_exists(snapshot_path)
    result = build_account_state(policy=policy, snapshot=snapshot, prior=prior)
    _atomic_json_write(state_path, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
