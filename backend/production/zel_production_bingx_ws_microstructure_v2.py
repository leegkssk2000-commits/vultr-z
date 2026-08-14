from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_bingx_ws_microstructure_v1 import Aggregator, BingXPublicWs, _atomic_json

POLICY_SCHEMA = "zel.production_bingx_ws_microstructure_policy.v2"
HEARTBEAT_SCHEMA = "zel.production_bingx_ws_microstructure_heartbeat.v2"
DEFAULT_POLICY = Path("config/zel_production_bingx_ws_microstructure_v2.json")
DEPENDENCY_PATH = Path("backend/production/zel_production_bingx_ws_microstructure_v1.py")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("WS_MICRO_V2_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("WS_MICRO_V2_NON_PAPER_FORBIDDEN")
    if policy.get("role") != "PROSPECTIVE_PUBLIC_MICROSTRUCTURE_HISTORY_COLLECTOR_NOT_STRATEGY":
        raise RuntimeError("WS_MICRO_V2_ROLE_DRIFT")
    if policy.get("websocket_url") != "wss://open-api-swap.bingx.com/swap-market":
        raise RuntimeError("WS_MICRO_V2_ENDPOINT_INVALID")
    if policy.get("symbols") != ["BTC-USDT", "ETH-USDT"]:
        raise RuntimeError("WS_MICRO_V2_SYMBOLS_INVALID")
    streams = policy.get("streams")
    if streams != {
        "depth": "{symbol}@depth20@200ms",
        "trade": "{symbol}@trade",
        "kline": "{symbol}@kline_1m",
    }:
        raise RuntimeError("WS_MICRO_V2_STREAM_CONTRACT_INVALID")
    if int(policy.get("bucket_ms") or 0) != 5000:
        raise RuntimeError("WS_MICRO_V2_BUCKET_INVALID")
    if int(policy.get("flush_lag_ms") or 0) < int(policy.get("bucket_ms") or 0):
        raise RuntimeError("WS_MICRO_V2_FLUSH_LAG_INVALID")
    if int(policy.get("heartbeat_interval_ms") or 0) < 1000:
        raise RuntimeError("WS_MICRO_V2_HEARTBEAT_INVALID")
    if int(policy.get("subscription_pause_ms") or 0) < 100:
        raise RuntimeError("WS_MICRO_V2_SUBSCRIPTION_PAUSE_INVALID")
    for key in ("history_path", "heartbeat_path", "log_path", "pid_path", "lock_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"WS_MICRO_V2_PATH_MISSING:{key}")
    if policy.get("history_gate_decision") != "UNSET_BY_COLLECTOR" or policy.get("economic_signal_enabled") is not False:
        raise RuntimeError("WS_MICRO_V2_RESEARCH_BOUNDARY_INVALID")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("WS_MICRO_V2_SELECTION_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("WS_MICRO_V2_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED" or policy.get("exchange_order_submitted") is not False:
        raise RuntimeError("WS_MICRO_V2_LIVE_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("WS_MICRO_V2_MUTATION_FORBIDDEN")
    return dict(policy)


class Collector:
    def __init__(self, policy: Mapping[str, Any]):
        self.policy = validate_policy(policy)
        # v1 Aggregator accepts the same symbols/bucket fields; authority is still supplied by v2 rows/heartbeat.
        v1_policy = {
            "schema_version": "zel.production_bingx_ws_microstructure_policy.v1",
            "state": "FROZEN_PAPER_PROSPECTIVE_MICROSTRUCTURE_ONLY",
            "mode": "PAPER",
            "role": "PROSPECTIVE_PUBLIC_MICROSTRUCTURE_HISTORY_COLLECTOR_NOT_STRATEGY",
            "websocket_url": self.policy["websocket_url"],
            "symbols": self.policy["symbols"],
            "depth_level": 20,
            "depth_interval": "200ms",
            "kline_interval": "1m",
            "bucket_ms": self.policy["bucket_ms"],
            "heartbeat_interval_ms": self.policy["heartbeat_interval_ms"],
            "stale_heartbeat_ms": self.policy["stale_heartbeat_ms"],
            "reconnect_after_sec": self.policy["reconnect_after_sec"],
            "reconnect_backoff_sec": self.policy["reconnect_backoff_sec"],
            "history_path": self.policy["history_path"],
            "heartbeat_path": self.policy["heartbeat_path"],
            "log_path": self.policy["log_path"],
            "pid_path": self.policy["pid_path"],
            "lock_path": self.policy["lock_path"],
            "history_gate_decision": "UNSET_BY_COLLECTOR",
            "economic_signal_enabled": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "source_code_mutation_allowed": False,
            "self_modification_allowed": False,
        }
        self.agg = Aggregator(v1_policy)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.errors: queue.Queue[str] = queue.Queue()
        self.started_ms = int(time.time() * 1000)
        self.stream_state: dict[str, dict[str, Any]] = {
            name: {
                "connected": False,
                "connection_started_ms": None,
                "last_message_ms": None,
                "messages": 0,
                "reconnects": 0,
                "last_error": None,
            }
            for name in ("depth", "trade", "kline")
        }

    def _channels(self, stream: str) -> list[str]:
        template = str(self.policy["streams"][stream])
        return [template.format(symbol=s) for s in self.policy["symbols"]]

    def _worker(self, stream: str) -> None:
        endpoint = str(self.policy["websocket_url"])
        backoff = int(self.policy["reconnect_backoff_sec"])
        reconnect_after_ms = int(self.policy["reconnect_after_sec"]) * 1000
        pause = int(self.policy["subscription_pause_ms"]) / 1000.0
        while not self.stop.is_set():
            ws: BingXPublicWs | None = None
            try:
                ws = BingXPublicWs(endpoint, timeout=10.0)
                ws.connect()
                with self.lock:
                    state = self.stream_state[stream]
                    state["connected"] = True
                    state["connection_started_ms"] = int(time.time() * 1000)
                    state["last_error"] = None
                for channel in self._channels(stream):
                    ws.subscribe(channel)
                    time.sleep(pause)
                while not self.stop.is_set():
                    with self.lock:
                        started = int(self.stream_state[stream]["connection_started_ms"] or 0)
                    if started and int(time.time() * 1000) - started >= reconnect_after_ms:
                        raise ConnectionError("WS_MICRO_V2_PLANNED_RECONNECT")
                    try:
                        text = ws.recv_text()
                    except TimeoutError:
                        continue
                    except OSError as exc:
                        if getattr(exc, "errno", None) is None and exc.__class__.__name__ == "timeout":
                            continue
                        raise
                    now = int(time.time() * 1000)
                    if text == "Ping":
                        ws.send_text("Pong")
                        continue
                    try:
                        msg = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(msg, Mapping):
                        continue
                    dtype = str(msg.get("dataType") or "")
                    if dtype not in self._channels(stream):
                        continue
                    with self.lock:
                        self.agg.consume(msg, now)
                        state = self.stream_state[stream]
                        state["last_message_ms"] = now
                        state["messages"] = int(state["messages"]) + 1
            except Exception as exc:
                err = f"{type(exc).__name__}:{exc}"[:300]
                with self.lock:
                    state = self.stream_state[stream]
                    state["connected"] = False
                    state["last_error"] = err
                    state["reconnects"] = int(state["reconnects"]) + 1
                self.errors.put(f"{stream}:{err}")
                if not self.stop.wait(backoff):
                    continue
            finally:
                if ws is not None:
                    ws.close()
                with self.lock:
                    self.stream_state[stream]["connected"] = False

    def heartbeat(self) -> dict[str, Any]:
        now = int(time.time() * 1000)
        with self.lock:
            stream_copy = json.loads(json.dumps(self.stream_state))
            totals = dict(self.agg.totals)
        all_fresh = True
        all_seen = True
        for state in stream_copy.values():
            last = state.get("last_message_ms")
            state["last_message_age_ms"] = (now - int(last)) if last else None
            if not last:
                all_seen = False
            elif now - int(last) > int(self.policy["stale_heartbeat_ms"]):
                all_fresh = False
        healthy = all_seen and all_fresh and all(int(stream_copy[s]["messages"]) > 0 for s in ("depth", "trade", "kline"))
        return {
            "schema_version": HEARTBEAT_SCHEMA,
            "state": "PASS_BINGX_WS_MICROSTRUCTURE_V2_ACCUMULATING" if healthy else "HOLD_BINGX_WS_MICROSTRUCTURE_V2_CONNECTING",
            "role": self.policy["role"],
            "pid": os.getpid(),
            "started_at_ms": self.started_ms,
            "updated_at_ms": now,
            "uptime_ms": now - self.started_ms,
            "symbols": list(self.policy["symbols"]),
            "bucket_ms": int(self.policy["bucket_ms"]),
            "streams": stream_copy,
            "source_sha256": _sha(Path(__file__)),
            "dependency_sha256": _sha(DEPENDENCY_PATH),
            "policy_sha256": _sha(DEFAULT_POLICY),
            **totals,
            "history_gate_decision": "UNSET_BY_COLLECTOR",
            "economic_signal_enabled": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "protected_mutations": 0,
        }

    def run(self, max_seconds: int = 0) -> int:
        history = Path(str(self.policy["history_path"]))
        heartbeat_path = Path(str(self.policy["heartbeat_path"]))
        deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
        threads = [threading.Thread(target=self._worker, args=(s,), name=f"bingx-{s}", daemon=True) for s in ("depth", "trade", "kline")]
        for thread in threads:
            thread.start()
        try:
            last_hb = 0
            while deadline is None or time.monotonic() < deadline:
                now = int(time.time() * 1000)
                with self.lock:
                    self.agg.flush_ready(history, now - int(self.policy["flush_lag_ms"]))
                if now - last_hb >= int(self.policy["heartbeat_interval_ms"]):
                    _atomic_json(heartbeat_path, self.heartbeat())
                    last_hb = now
                time.sleep(0.5)
        finally:
            self.stop.set()
            for thread in threads:
                thread.join(timeout=5)
            with self.lock:
                self.agg.flush_ready(history, int(time.time() * 1000), force=True)
            _atomic_json(heartbeat_path, self.heartbeat())
        return 0


def run(policy: Mapping[str, Any], *, max_seconds: int = 0) -> int:
    cfg = validate_policy(policy)
    lock_path = Path(str(cfg["lock_path"])); lock_path.parent.mkdir(parents=True, exist_ok=True); lock_path.touch(exist_ok=True)
    lock = lock_path.open("r+", encoding="utf-8")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"state": "PASS_BINGX_WS_MICROSTRUCTURE_V2_ALREADY_RUNNING", "execution_authority": "NONE", "order_authority": "BLOCKED"}, sort_keys=True))
        return 0
    pid_path = Path(str(cfg["pid_path"])); pid_path.parent.mkdir(parents=True, exist_ok=True); pid_path.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    try:
        return Collector(cfg).run(max_seconds=max_seconds)
    finally:
        try:
            if pid_path.is_file() and pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_path.unlink()
        except Exception:
            pass
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN); lock.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect BingX public microstructure using separated WS stream connections")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--max-seconds", type=int, default=0)
    ns = ap.parse_args(argv)
    policy = json.loads(ns.policy.read_text(encoding="utf-8"))
    return run(policy, max_seconds=max(0, ns.max_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
