from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from backend.contracts.zel_event_sourced_shadow_v1 import canonical_sha
from backend.runtime.zel_shadow_event_journal_v1 import (
    SqliteShadowEventJournal,
    build_event,
)

VERSION = "ZEL_EVENT_SOURCED_EXACT25_PRODUCER_V1"
DEFAULT_PRODUCER = Path("/home/z/z/tools/q4r3_exact25_dedicated_shadow_producer.py")
DEFAULT_PRODUCER_BLOB_SHA = "42cb8d5c92ace00a11531b46548efdc9f872c9b7"
HOLD_ACTIONS = {"", "hold", "none", "flat"}


class ProducerAdapterError(RuntimeError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ProducerAdapterError(f"{code}:{detail}" if detail else code)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(value), handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def git_blob_sha(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)], text=True, capture_output=True, timeout=20
    )
    if result.returncode != 0:
        _fail("PRODUCER_GIT_HASH_FAILED", result.stderr.strip()[:500])
    value = result.stdout.strip().lower()
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        _fail("PRODUCER_GIT_BLOB_INVALID", value)
    return value


def load_producer(path: Path, expected_blob_sha: str) -> ModuleType:
    if not path.is_file():
        _fail("PRODUCER_SOURCE_MISSING", str(path))
    actual = git_blob_sha(path)
    if actual != expected_blob_sha.lower():
        _fail("PRODUCER_SOURCE_BLOB_MISMATCH", f"expected={expected_blob_sha}:actual={actual}")
    spec = importlib.util.spec_from_file_location("zel_wrapped_exact25_producer", path)
    if spec is None or spec.loader is None:
        _fail("PRODUCER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized_skill(result: Mapping[str, Any]) -> list[str]:
    raw = result.get("skill") or result.get("skill_id") or ""
    if isinstance(raw, list):
        values = raw
    else:
        values = [raw]
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() not in {"none", "hold", "null", "na", "n/a"}:
            output.append(text)
    return sorted(set(output))


def scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def frame_snapshot(frame: Any) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for _, row in frame.tail(2).iterrows():
        rows.append({key: scalar(row.get(key)) for key in ("timestamp_ms", "open", "high", "low", "close", "volume")})
    return {"rows": rows}


def identity_for_position(position: Mapping[str, Any], result: Mapping[str, Any], frame: Any) -> dict[str, Any]:
    position_id = str(position["position_id"])
    market_snapshot = {
        "frame": frame_snapshot(frame),
        "entry_features": dict(position.get("entry_features") or {}),
    }
    risk_snapshot = {
        "entry_price": position.get("entry_price"),
        "stop_price": position.get("stop_price"),
        "take_profit_price": position.get("take_profit_price"),
        "qty": position.get("qty"),
        "initial_risk_usdt": position.get("initial_risk_usdt"),
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }
    method = str(result.get("method_id") or result.get("method") or "UNRESOLVED").strip()
    team = str(result.get("team_id") or result.get("team") or "UNRESOLVED").strip()
    source_sha = str(position["owner_sha256"]).lower()
    return {
        "decision_id": "zel.shadow.decision." + hashlib.sha256(position_id.encode("utf-8")).hexdigest()[:32],
        "position_id": position_id,
        "strategy_id": str(position["strategy_id"]),
        "strategy_source_sha256": source_sha,
        "method_id": method or "UNRESOLVED",
        "skill_set": normalized_skill(result),
        "team_id": team or "UNRESOLVED",
        "symbol": str(position["symbol"]),
        "side": str(position["side"]).upper(),
        "market_snapshot_sha256": canonical_sha(market_snapshot),
        "risk_snapshot_sha256": canonical_sha(risk_snapshot),
        "source_ids": [
            "runtime:q4r3_exact25_dedicated_shadow_producer",
            f"strategy_sha256:{source_sha}",
        ],
    }


def candidate_identity(
    strategy_id: str,
    owner_sha: str,
    symbol: str,
    result: Mapping[str, Any],
    frame: Any,
) -> dict[str, Any] | None:
    side = str(result.get("side") or "").upper()
    if side not in {"LONG", "SHORT"}:
        return None
    timestamp = str(frame.iloc[-1].get("timestamp"))
    position_id = "zel.shadow.candidate." + hashlib.sha256(
        f"{strategy_id}|{symbol}|{timestamp}|{side}".encode("utf-8")
    ).hexdigest()[:32]
    placeholder = {
        "position_id": position_id,
        "strategy_id": strategy_id,
        "owner_sha256": owner_sha,
        "symbol": symbol,
        "side": side.lower(),
        "entry_features": {},
        "entry_price": result.get("entry"),
        "stop_price": result.get("sl"),
        "take_profit_price": result.get("tp"),
        "qty": 0.0,
        "initial_risk_usdt": 0.0,
    }
    return identity_for_position(placeholder, result, frame)


class EventSourcedProducerHooks:
    def __init__(
        self,
        module: ModuleType,
        journal: SqliteShadowEventJournal,
        status_path: Path,
        producer_blob_sha: str,
    ) -> None:
        self.module = module
        self.journal = journal
        self.status_path = status_path
        self.producer_blob_sha = producer_blob_sha
        self.pending_close: dict[str, dict[str, Any]] = {}
        self.unresolved_signal_count = 0
        self.original_make_position = module.make_position
        self.original_apply_add = module.apply_add
        self.original_apply_partial_reduce = module.apply_partial_reduce
        self.original_close_position = module.close_position
        self.original_append_jsonl_once = module.append_jsonl_once
        self.original_atomic_json = module.atomic_json

    def _emit(
        self,
        identity: Mapping[str, Any],
        event_type: str,
        event_ts: str,
        payload: Mapping[str, Any],
        *,
        skill_set: list[str] | None = None,
    ) -> dict[str, Any]:
        event_identity = copy.deepcopy(dict(identity))
        if skill_set is not None:
            event_identity["skill_set"] = list(skill_set)
        raw = build_event(event_identity, event_type, event_ts, payload, self.journal)
        return self.journal.append(raw)

    def _ensure_open_confirmed(self, position: Mapping[str, Any], event_ts: str) -> None:
        identity = position.get("_zel_event_identity")
        if not isinstance(identity, Mapping):
            _fail("POSITION_EVENT_IDENTITY_MISSING", str(position.get("position_id")))
        context = self.journal.next_context(str(position["position_id"]))
        if context is None:
            _fail("POSITION_EVENT_CHAIN_MISSING", str(position["position_id"]))
        if context["last_event_type"] == "shadow_open_requested":
            self._emit(identity, "shadow_open_confirmed", event_ts, {"state_persisted": True})

    def make_position(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        strategy_id = str(args[0] if args else kwargs["strategy_id"])
        owner_sha = str(args[1] if len(args) > 1 else kwargs["owner_sha"])
        symbol = str(args[2] if len(args) > 2 else kwargs["symbol"])
        result = args[4] if len(args) > 4 else kwargs["result"]
        frame = args[5] if len(args) > 5 else kwargs["frame"]
        position = self.original_make_position(*args, **kwargs)
        action = str(result.get("action") or "").lower() if isinstance(result, Mapping) else ""
        event_ts = str(frame.iloc[-1].get("timestamp"))
        if position is None:
            if action not in HOLD_ACTIONS and isinstance(result, Mapping):
                identity = candidate_identity(strategy_id, owner_sha, symbol, result, frame)
                if identity is None:
                    self.unresolved_signal_count += 1
                else:
                    self._emit(identity, "strategy_signal_emitted", event_ts, {"action": action, "admitted": False})
                    self._emit(identity, "held", event_ts, {"reason": "INVALID_ENTRY_CONTRACT"})
            self.write_status()
            return None

        identity = identity_for_position(position, result, frame)
        position["_zel_event_identity"] = identity
        position["_zel_open_confirm_pending"] = True
        self._emit(identity, "strategy_signal_emitted", event_ts, {
            "action": action,
            "entry_reason": str(position.get("entry_reason") or ""),
            "confidence": position.get("entry_confidence"),
        })
        self._emit(identity, "admission_decided", event_ts, {
            "admitted": True,
            "valid_entry_contract": True,
            "capital_allowed": False,
        })
        self._emit(identity, "shadow_open_requested", event_ts, {
            "entry_price": position.get("entry_price"),
            "stop_price": position.get("stop_price"),
            "take_profit_price": position.get("take_profit_price"),
            "qty": position.get("qty"),
        })
        self.write_status()
        return position

    def atomic_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        self.original_atomic_json(path, payload)
        if payload.get("schema") != "q4r3_exact25_dedicated_shadow_producer_state_v1":
            return
        changed = False
        for position in (payload.get("positions") or {}).values():
            if not isinstance(position, dict) or position.get("_zel_open_confirm_pending") is not True:
                continue
            self._ensure_open_confirmed(position, str(position.get("entry_ts")))
            position["_zel_open_confirm_pending"] = False
            changed = True
        if changed:
            self.original_atomic_json(path, payload)
        self.write_status()

    def _managed(self, position: Mapping[str, Any], result: Mapping[str, Any], applied: bool, action: str) -> bool:
        if not applied:
            return False
        event_ts = str(result.get("event_ts") or self.module.now_iso())
        self._ensure_open_confirmed(position, event_ts)
        identity = position["_zel_event_identity"]
        skills = normalized_skill(result)
        if skills:
            self._emit(identity, "skill_triggered", event_ts, {"action": action}, skill_set=skills)
        self._emit(identity, "shadow_managed", event_ts, {
            "action": action,
            "qty": position.get("qty"),
            "add_count": position.get("add_count"),
            "partial_count": position.get("partial_count"),
        }, skill_set=skills)
        self.write_status()
        return True

    def apply_add(self, position: dict[str, Any], result: Mapping[str, Any], *args: Any, **kwargs: Any) -> bool:
        return self._managed(position, result, self.original_apply_add(position, result, *args, **kwargs), "add")

    def apply_partial_reduce(self, position: dict[str, Any], result: Mapping[str, Any], *args: Any, **kwargs: Any) -> bool:
        return self._managed(position, result, self.original_apply_partial_reduce(position, result, *args, **kwargs), "partial_reduce")

    def close_position(
        self,
        position: Mapping[str, Any],
        exit_price: float,
        exit_ts: str,
        reason: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._ensure_open_confirmed(position, exit_ts)
        identity = dict(position["_zel_event_identity"])
        self._emit(identity, "shadow_close_requested", exit_ts, {
            "exit_price": exit_price,
            "reason": reason,
        })
        row = self.original_close_position(position, exit_price, exit_ts, reason, *args, **kwargs)
        row.update({
            "decision_id": identity["decision_id"],
            "method_id": identity["method_id"],
            "team_id": identity["team_id"],
            "skill_set": identity["skill_set"],
            "market_snapshot_sha256": identity["market_snapshot_sha256"],
            "risk_snapshot_sha256": identity["risk_snapshot_sha256"],
            "source_ids": identity["source_ids"],
            "event_source_version": VERSION,
        })
        self.pending_close[str(row["event_id"])] = {
            "identity": identity,
            "event_ts": exit_ts,
            "row_sha256": canonical_sha(row),
        }
        return row

    def append_jsonl_once(self, path: Path, row: Mapping[str, Any]) -> bool:
        appended = self.original_append_jsonl_once(path, row)
        if row.get("schema") != "q4r3_exact25_dedicated_shadow_close_v1":
            return appended
        key = str(row.get("event_id") or "")
        pending = self.pending_close.get(key)
        if pending is None:
            identity = {
                "decision_id": row.get("decision_id"),
                "position_id": row.get("position_id"),
                "strategy_id": row.get("strategy_id"),
                "strategy_source_sha256": row.get("owner_sha256"),
                "method_id": row.get("method_id"),
                "skill_set": row.get("skill_set") or [],
                "team_id": row.get("team_id"),
                "symbol": row.get("symbol"),
                "side": str(row.get("side") or "").upper(),
                "market_snapshot_sha256": row.get("market_snapshot_sha256"),
                "risk_snapshot_sha256": row.get("risk_snapshot_sha256"),
                "source_ids": row.get("source_ids") or [],
            }
            if any(value in (None, "") for key2, value in identity.items() if key2 != "skill_set"):
                _fail("CLOSE_EVENT_IDENTITY_MISSING", key)
            pending = {
                "identity": identity,
                "event_ts": str(row.get("exit_ts")),
                "row_sha256": canonical_sha(row),
            }
        identity = pending["identity"]
        event_ts = pending["event_ts"]
        context = self.journal.next_context(str(identity["position_id"]))
        if context and context["last_event_type"] == "shadow_close_requested":
            self._emit(identity, "shadow_closed", event_ts, {
                "close_row_sha256": pending["row_sha256"],
                "realized_R": row.get("realized_R"),
                "exit_reason": row.get("exit_reason"),
            })
        context = self.journal.next_context(str(identity["position_id"]))
        if context and context["last_event_type"] == "shadow_closed":
            self._emit(identity, "formal_ledger_joined", event_ts, {
                "ledger_path": str(path),
                "close_row_sha256": pending["row_sha256"],
                "append_was_new": appended,
            })
        self.pending_close.pop(key, None)
        self.write_status()
        return appended

    def write_status(self) -> None:
        coverage = self.journal.coverage()
        projection = self.journal.sync_projection()
        status = {
            "schema_version": "zel.event_sourced_exact25_producer.status.v1",
            "version": VERSION,
            "producer_blob_sha": self.producer_blob_sha,
            "event_database": str(self.journal.database_path),
            "event_projection": str(self.journal.projection_path),
            "event_count": projection["event_count"],
            "projection_sha256": projection["projection_sha256"],
            "unresolved_signal_count": self.unresolved_signal_count,
            "coverage": coverage,
            "polling_is_proof_authority": False,
            "runtime_binding_allowed": False,
            "paper_allowed": False,
            "live_allowed": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }
        atomic_json(self.status_path, status)

    def install(self) -> None:
        self.module.make_position = self.make_position
        self.module.apply_add = self.apply_add
        self.module.apply_partial_reduce = self.apply_partial_reduce
        self.module.close_position = self.close_position
        self.module.append_jsonl_once = self.append_jsonl_once
        self.module.atomic_json = self.atomic_json
        self.write_status()


def parse_wrapper_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--producer-source", type=Path, default=DEFAULT_PRODUCER)
    parser.add_argument("--producer-blob-sha", default=DEFAULT_PRODUCER_BLOB_SHA)
    parser.add_argument("--event-db", type=Path, required=True)
    parser.add_argument("--event-jsonl", type=Path, required=True)
    parser.add_argument("--event-status", type=Path, required=True)
    return parser.parse_known_args(argv)


def main() -> int:
    if os.environ.get("ZEL_EVENT_SOURCED_SHADOW") != "1":
        _fail("EVENT_SOURCED_SHADOW_ENV_REQUIRED")
    wrapper, producer_args = parse_wrapper_args(sys.argv[1:])
    module = load_producer(wrapper.producer_source.resolve(), wrapper.producer_blob_sha)
    journal = SqliteShadowEventJournal(wrapper.event_db, wrapper.event_jsonl)
    hooks = EventSourcedProducerHooks(module, journal, wrapper.event_status, wrapper.producer_blob_sha)
    hooks.install()
    sys.argv = [str(wrapper.producer_source)] + producer_args
    try:
        module.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
