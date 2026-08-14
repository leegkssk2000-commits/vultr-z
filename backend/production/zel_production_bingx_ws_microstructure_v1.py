from __future__ import annotations

import argparse
import base64
import fcntl
import gzip
import hashlib
import json
import math
import os
import socket
import ssl
import struct
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Mapping

POLICY_SCHEMA = "zel.production_bingx_ws_microstructure_policy.v1"
ROW_SCHEMA = "zel.production_bingx_ws_microstructure_row.v1"
HEARTBEAT_SCHEMA = "zel.production_bingx_ws_microstructure_heartbeat.v1"
DEFAULT_POLICY = Path("config/zel_production_bingx_ws_microstructure_v1.json")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("WS_MICRO_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("WS_MICRO_NON_PAPER_FORBIDDEN")
    if policy.get("role") != "PROSPECTIVE_PUBLIC_MICROSTRUCTURE_HISTORY_COLLECTOR_NOT_STRATEGY":
        raise RuntimeError("WS_MICRO_ROLE_DRIFT")
    if policy.get("websocket_url") != "wss://open-api-swap.bingx.com/swap-market":
        raise RuntimeError("WS_MICRO_ENDPOINT_INVALID")
    symbols = policy.get("symbols")
    if not isinstance(symbols, list) or not symbols or any(str(s) not in {"BTC-USDT", "ETH-USDT"} for s in symbols):
        raise RuntimeError("WS_MICRO_SYMBOLS_INVALID")
    if int(policy.get("depth_level") or 0) != 20 or policy.get("depth_interval") != "200ms":
        raise RuntimeError("WS_MICRO_DEPTH_CONTRACT_INVALID")
    if policy.get("kline_interval") != "1m":
        raise RuntimeError("WS_MICRO_KLINE_CONTRACT_INVALID")
    if int(policy.get("bucket_ms") or 0) < 1000:
        raise RuntimeError("WS_MICRO_BUCKET_INVALID")
    if int(policy.get("heartbeat_interval_ms") or 0) < 1000:
        raise RuntimeError("WS_MICRO_HEARTBEAT_INVALID")
    if int(policy.get("reconnect_after_sec") or 0) <= 0:
        raise RuntimeError("WS_MICRO_RECONNECT_INVALID")
    for key in ("history_path", "heartbeat_path", "log_path", "pid_path", "lock_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"WS_MICRO_PATH_MISSING:{key}")
    if policy.get("history_gate_decision") != "UNSET_BY_COLLECTOR" or policy.get("economic_signal_enabled") is not False:
        raise RuntimeError("WS_MICRO_RESEARCH_BOUNDARY_INVALID")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("WS_MICRO_SELECTION_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("WS_MICRO_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED" or policy.get("exchange_order_submitted") is not False:
        raise RuntimeError("WS_MICRO_LIVE_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("WS_MICRO_MUTATION_FORBIDDEN")
    return dict(policy)


def _finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"WS_MICRO_NUMERIC_INVALID:{label}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"WS_MICRO_NUMERIC_NONFINITE:{label}")
    return out


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(value), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _recv_exact(sock: ssl.SSLSocket, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise ConnectionError("WS_MICRO_SOCKET_EOF")
        out.extend(chunk)
    return bytes(out)


def _client_frame(payload: bytes, opcode: int = 1) -> bytes:
    first = 0x80 | (opcode & 0x0F)
    length = len(payload)
    mask = os.urandom(4)
    if length < 126:
        head = bytes([first, 0x80 | length])
    elif length < 65536:
        head = bytes([first, 0x80 | 126]) + struct.pack("!H", length)
    else:
        head = bytes([first, 0x80 | 127]) + struct.pack("!Q", length)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return head + mask + masked


def _server_frame(sock: ssl.SSLSocket) -> tuple[bool, int, bytes]:
    first, second = _recv_exact(sock, 2)
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    mask = _recv_exact(sock, 4) if masked else None
    payload = _recv_exact(sock, length)
    if mask:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return fin, opcode, payload


class BingXPublicWs:
    def __init__(self, endpoint: str, timeout: float = 15.0):
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "wss" or parsed.hostname != "open-api-swap.bingx.com" or parsed.path != "/swap-market":
            raise RuntimeError("WS_MICRO_ENDPOINT_PARSE_INVALID")
        self.host = parsed.hostname
        self.path = parsed.path
        self.timeout = timeout
        self.sock: ssl.SSLSocket | None = None

    def connect(self) -> None:
        raw = socket.create_connection((self.host, 443), timeout=self.timeout)
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(raw, server_hostname=self.host)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: ZEL-PAPER-MICROSTRUCTURE/1.0\r\n\r\n"
        )
        sock.sendall(request.encode())
        response = bytearray()
        while b"\r\n\r\n" not in response and len(response) < 16384:
            response.extend(sock.recv(4096))
        status = bytes(response).split(b"\r\n", 1)[0].decode("latin1", "replace")
        if " 101 " not in f" {status} ":
            sock.close()
            raise RuntimeError(f"WS_MICRO_HANDSHAKE_FAILED:{status[:160]}")
        sock.settimeout(self.timeout)
        self.sock = sock

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.sendall(_client_frame(b"", opcode=8))
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def send_text(self, text: str) -> None:
        if self.sock is None:
            raise RuntimeError("WS_MICRO_NOT_CONNECTED")
        self.sock.sendall(_client_frame(text.encode("utf-8"), opcode=1))

    def subscribe(self, channel: str) -> None:
        self.send_text(json.dumps({"id": str(uuid.uuid4()), "reqType": "sub", "dataType": channel}, separators=(",", ":")))

    def recv_text(self) -> str:
        if self.sock is None:
            raise RuntimeError("WS_MICRO_NOT_CONNECTED")
        fragments = bytearray()
        message_opcode: int | None = None
        while True:
            fin, opcode, payload = _server_frame(self.sock)
            if opcode == 8:
                raise ConnectionError("WS_MICRO_SERVER_CLOSE")
            if opcode == 9:
                self.sock.sendall(_client_frame(payload, opcode=10))
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                fragments = bytearray(payload)
                message_opcode = opcode
            elif opcode == 0 and message_opcode is not None:
                fragments.extend(payload)
            else:
                continue
            if not fin:
                continue
            raw = bytes(fragments)
            if message_opcode == 2:
                try:
                    raw = gzip.decompress(raw)
                except OSError as exc:
                    raise RuntimeError("WS_MICRO_GZIP_DECOMPRESS_FAILED") from exc
            return raw.decode("utf-8", "replace")


class Aggregator:
    def __init__(self, policy: Mapping[str, Any]):
        self.policy = validate_policy(policy)
        self.bucket_ms = int(self.policy["bucket_ms"])
        self.symbols = [str(x) for x in self.policy["symbols"]]
        self.buckets: dict[tuple[str, int], dict[str, Any]] = {}
        self.last_depth: dict[str, dict[str, float]] = {}
        self.totals = {
            "messages_total": 0,
            "depth_messages_total": 0,
            "trade_messages_total": 0,
            "kline_messages_total": 0,
            "parse_errors_total": 0,
            "rows_written_total": 0,
            "reconnects_total": 0,
        }

    def _bucket(self, symbol: str, event_ms: int) -> dict[str, Any]:
        b = event_ms - (event_ms % self.bucket_ms)
        key = (symbol, b)
        if key not in self.buckets:
            self.buckets[key] = {
                "symbol": symbol,
                "bucket_start_ms": b,
                "bucket_end_ms": b + self.bucket_ms,
                "depth_messages": 0,
                "trade_messages": 0,
                "kline_messages": 0,
                "source_event_first_ms": None,
                "source_event_last_ms": None,
                "spread_bps_min": None,
                "spread_bps_max": None,
                "spread_bps_sum": 0.0,
                "imbalance_top20_min": None,
                "imbalance_top20_max": None,
                "imbalance_top20_sum": 0.0,
                "imbalance_top20_first": None,
                "imbalance_top20_last": None,
                "bid_qty_top20_first": None,
                "bid_qty_top20_last": None,
                "ask_qty_top20_first": None,
                "ask_qty_top20_last": None,
                "best_bid_last": None,
                "best_ask_last": None,
                "mid_last": None,
                "last_depth_digest": None,
                "trade_qty": 0.0,
                "trade_quote_notional": 0.0,
                "aggressive_buy_qty": 0.0,
                "aggressive_sell_qty": 0.0,
                "last_trade_price": None,
                "kline": None,
            }
        return self.buckets[key]

    @staticmethod
    def _touch_time(row: dict[str, Any], event_ms: int) -> None:
        first = row["source_event_first_ms"]
        last = row["source_event_last_ms"]
        row["source_event_first_ms"] = event_ms if first is None else min(first, event_ms)
        row["source_event_last_ms"] = event_ms if last is None else max(last, event_ms)

    @staticmethod
    def _book_side(values: Any, label: str) -> list[tuple[float, float]]:
        if not isinstance(values, list) or not values:
            raise RuntimeError(f"WS_MICRO_{label.upper()}_EMPTY")
        out: list[tuple[float, float]] = []
        for raw in values[:20]:
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                raise RuntimeError(f"WS_MICRO_{label.upper()}_SCHEMA_INVALID")
            price = _finite(raw[0], f"{label}_price")
            qty = _finite(raw[1], f"{label}_qty")
            if price <= 0 or qty < 0:
                raise RuntimeError(f"WS_MICRO_{label.upper()}_VALUE_INVALID")
            out.append((price, qty))
        return out

    def on_depth(self, symbol: str, data: Mapping[str, Any], event_ms: int) -> None:
        bids = self._book_side(data.get("bids"), "bids")
        asks = self._book_side(data.get("asks"), "asks")
        best_bid, best_ask = bids[0][0], asks[0][0]
        if best_ask < best_bid:
            raise RuntimeError("WS_MICRO_CROSSED_BOOK")
        mid = (best_bid + best_ask) / 2.0
        spread_bps = (best_ask - best_bid) / mid * 10000.0
        bid_qty = sum(q for _, q in bids[:20])
        ask_qty = sum(q for _, q in asks[:20])
        total = bid_qty + ask_qty
        imbalance = (bid_qty - ask_qty) / total if total > 0 else 0.0
        canonical = json.dumps({"b": bids, "a": asks}, separators=(",", ":"), sort_keys=True).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        row = self._bucket(symbol, event_ms)
        self._touch_time(row, event_ms)
        row["depth_messages"] += 1
        row["spread_bps_min"] = spread_bps if row["spread_bps_min"] is None else min(row["spread_bps_min"], spread_bps)
        row["spread_bps_max"] = spread_bps if row["spread_bps_max"] is None else max(row["spread_bps_max"], spread_bps)
        row["spread_bps_sum"] += spread_bps
        row["imbalance_top20_min"] = imbalance if row["imbalance_top20_min"] is None else min(row["imbalance_top20_min"], imbalance)
        row["imbalance_top20_max"] = imbalance if row["imbalance_top20_max"] is None else max(row["imbalance_top20_max"], imbalance)
        row["imbalance_top20_sum"] += imbalance
        if row["imbalance_top20_first"] is None:
            row["imbalance_top20_first"] = imbalance
            row["bid_qty_top20_first"] = bid_qty
            row["ask_qty_top20_first"] = ask_qty
        row["imbalance_top20_last"] = imbalance
        row["bid_qty_top20_last"] = bid_qty
        row["ask_qty_top20_last"] = ask_qty
        row["best_bid_last"] = best_bid
        row["best_ask_last"] = best_ask
        row["mid_last"] = mid
        row["last_depth_digest"] = digest
        self.last_depth[symbol] = {"bid_qty": bid_qty, "ask_qty": ask_qty, "imbalance": imbalance, "mid": mid}
        self.totals["depth_messages_total"] += 1

    def on_trade(self, symbol: str, data: Mapping[str, Any], event_ms: int) -> None:
        price = _finite(data.get("p"), "trade_price")
        qty = _finite(data.get("q"), "trade_qty")
        if price <= 0 or qty < 0:
            raise RuntimeError("WS_MICRO_TRADE_VALUE_INVALID")
        row = self._bucket(symbol, event_ms)
        self._touch_time(row, event_ms)
        row["trade_messages"] += 1
        row["trade_qty"] += qty
        row["trade_quote_notional"] += price * qty
        if bool(data.get("m")):
            row["aggressive_sell_qty"] += qty
        else:
            row["aggressive_buy_qty"] += qty
        row["last_trade_price"] = price
        self.totals["trade_messages_total"] += 1

    def on_kline(self, symbol: str, data: Mapping[str, Any], event_ms: int) -> None:
        k = data.get("K")
        if not isinstance(k, Mapping):
            raise RuntimeError("WS_MICRO_KLINE_SCHEMA_INVALID")
        row = self._bucket(symbol, event_ms)
        self._touch_time(row, event_ms)
        row["kline_messages"] += 1
        row["kline"] = {
            "start_ms": int(_finite(k.get("t"), "kline_t")),
            "close_ms": int(_finite(k.get("T"), "kline_T")),
            "open": _finite(k.get("o"), "kline_o"),
            "high": _finite(k.get("h"), "kline_h"),
            "low": _finite(k.get("l"), "kline_l"),
            "close": _finite(k.get("c"), "kline_c"),
            "volume": _finite(k.get("v"), "kline_v"),
        }
        self.totals["kline_messages_total"] += 1

    def consume(self, message: Mapping[str, Any], received_ms: int) -> None:
        self.totals["messages_total"] += 1
        dtype = str(message.get("dataType") or "")
        data = message.get("data")
        if not dtype or not isinstance(data, Mapping):
            return
        symbol = dtype.split("@", 1)[0]
        if symbol not in self.symbols:
            return
        event_ms = int(data.get("T") or received_ms)
        try:
            if "@depth" in dtype:
                self.on_depth(symbol, data, event_ms)
            elif dtype.endswith("@trade"):
                self.on_trade(symbol, data, event_ms)
            elif "@kline_" in dtype:
                self.on_kline(symbol, data, event_ms)
        except Exception:
            self.totals["parse_errors_total"] += 1
            raise

    def flush_ready(self, history_path: Path, now_ms: int, force: bool = False) -> int:
        ready_keys = [key for key, row in self.buckets.items() if force or int(row["bucket_end_ms"]) <= now_ms]
        ready_keys.sort(key=lambda x: (x[1], x[0]))
        if not ready_keys:
            return 0
        history_path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with history_path.open("a", encoding="utf-8") as handle:
            for key in ready_keys:
                row = self.buckets.pop(key)
                depth_n = int(row["depth_messages"])
                trade_total = float(row["aggressive_buy_qty"]) + float(row["aggressive_sell_qty"])
                out = {
                    "schema_version": ROW_SCHEMA,
                    "provider": "BINGX_PUBLIC_USDT_PERPETUAL_WS",
                    "symbol": row["symbol"],
                    "bucket_start_ms": row["bucket_start_ms"],
                    "bucket_end_ms": row["bucket_end_ms"],
                    "source_event_first_ms": row["source_event_first_ms"],
                    "source_event_last_ms": row["source_event_last_ms"],
                    "depth_messages": depth_n,
                    "trade_messages": row["trade_messages"],
                    "kline_messages": row["kline_messages"],
                    "spread_bps_min": row["spread_bps_min"],
                    "spread_bps_max": row["spread_bps_max"],
                    "spread_bps_mean": (row["spread_bps_sum"] / depth_n) if depth_n else None,
                    "imbalance_top20_min": row["imbalance_top20_min"],
                    "imbalance_top20_max": row["imbalance_top20_max"],
                    "imbalance_top20_mean": (row["imbalance_top20_sum"] / depth_n) if depth_n else None,
                    "imbalance_top20_first": row["imbalance_top20_first"],
                    "imbalance_top20_last": row["imbalance_top20_last"],
                    "imbalance_top20_delta": (row["imbalance_top20_last"] - row["imbalance_top20_first"]) if depth_n else None,
                    "bid_qty_top20_first": row["bid_qty_top20_first"],
                    "bid_qty_top20_last": row["bid_qty_top20_last"],
                    "ask_qty_top20_first": row["ask_qty_top20_first"],
                    "ask_qty_top20_last": row["ask_qty_top20_last"],
                    "best_bid_last": row["best_bid_last"],
                    "best_ask_last": row["best_ask_last"],
                    "mid_last": row["mid_last"],
                    "last_depth_digest": row["last_depth_digest"],
                    "trade_qty": row["trade_qty"],
                    "trade_quote_notional": row["trade_quote_notional"],
                    "aggressive_buy_qty": row["aggressive_buy_qty"],
                    "aggressive_sell_qty": row["aggressive_sell_qty"],
                    "trade_imbalance": ((row["aggressive_buy_qty"] - row["aggressive_sell_qty"]) / trade_total) if trade_total > 0 else None,
                    "last_trade_price": row["last_trade_price"],
                    "kline": row["kline"],
                    "history_gate_decision": "UNSET_BY_COLLECTOR",
                    "economic_signal_enabled": False,
                    "selection_authority": False,
                    "promotion_authority": False,
                    "execution_authority": "NONE",
                    "order_authority": "BLOCKED",
                    "live_trade_authority": "BLOCKED",
                    "exchange_order_submitted": False,
                }
                handle.write(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                written += 1
            handle.flush()
            os.fsync(handle.fileno())
        self.totals["rows_written_total"] += written
        return written


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _heartbeat(policy: Mapping[str, Any], agg: Aggregator, *, connected: bool, started_ms: int, connection_started_ms: int | None, last_message_ms: int | None, last_error: str | None) -> dict[str, Any]:
    now = int(time.time() * 1000)
    source_path = Path(__file__)
    policy_path = DEFAULT_POLICY
    return {
        "schema_version": HEARTBEAT_SCHEMA,
        "state": "PASS_BINGX_WS_MICROSTRUCTURE_ACCUMULATING" if connected and agg.totals["depth_messages_total"] > 0 else "HOLD_BINGX_WS_MICROSTRUCTURE_CONNECTING",
        "role": "PROSPECTIVE_PUBLIC_MICROSTRUCTURE_HISTORY_COLLECTOR_NOT_STRATEGY",
        "pid": os.getpid(),
        "started_at_ms": started_ms,
        "updated_at_ms": now,
        "uptime_ms": now - started_ms,
        "connected": connected,
        "connection_started_ms": connection_started_ms,
        "last_message_ms": last_message_ms,
        "last_message_age_ms": (now - last_message_ms) if last_message_ms else None,
        "last_error": last_error,
        "symbols": list(policy["symbols"]),
        "bucket_ms": int(policy["bucket_ms"]),
        "source_sha256": _sha(source_path),
        "policy_sha256": _sha(policy_path) if policy_path.is_file() else None,
        **agg.totals,
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


def run(policy: Mapping[str, Any], *, max_seconds: int = 0) -> int:
    cfg = validate_policy(policy)
    history_path = Path(str(cfg["history_path"]))
    heartbeat_path = Path(str(cfg["heartbeat_path"]))
    pid_path = Path(str(cfg["pid_path"]))
    lock_path = Path(str(cfg["lock_path"]))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    lock = lock_path.open("r+", encoding="utf-8")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"state": "PASS_BINGX_WS_MICROSTRUCTURE_ALREADY_RUNNING", "execution_authority": "NONE", "order_authority": "BLOCKED"}, sort_keys=True))
        return 0
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    started_ms = int(time.time() * 1000)
    agg = Aggregator(cfg)
    heartbeat_interval = int(cfg["heartbeat_interval_ms"])
    reconnect_after_sec = int(cfg["reconnect_after_sec"])
    backoff = int(cfg["reconnect_backoff_sec"])
    last_hb_ms = 0
    last_message_ms: int | None = None
    last_error: str | None = None
    connection_started_ms: int | None = None
    deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
    ws: BingXPublicWs | None = None
    try:
        while deadline is None or time.monotonic() < deadline:
            connected = False
            try:
                ws = BingXPublicWs(str(cfg["websocket_url"]), timeout=15.0)
                ws.connect()
                connected = True
                connection_started_ms = int(time.time() * 1000)
                last_error = None
                for symbol in cfg["symbols"]:
                    ws.subscribe(f"{symbol}@depth{int(cfg['depth_level'])}@{cfg['depth_interval']}")
                    ws.subscribe(f"{symbol}@trade")
                    ws.subscribe(f"{symbol}@kline_{cfg['kline_interval']}")
                while deadline is None or time.monotonic() < deadline:
                    if connection_started_ms and int(time.time() * 1000) - connection_started_ms >= reconnect_after_sec * 1000:
                        raise ConnectionError("WS_MICRO_PLANNED_RECONNECT")
                    try:
                        text = ws.recv_text()
                    except socket.timeout:
                        now = int(time.time() * 1000)
                        if now - last_hb_ms >= heartbeat_interval:
                            _atomic_json(heartbeat_path, _heartbeat(cfg, agg, connected=connected, started_ms=started_ms, connection_started_ms=connection_started_ms, last_message_ms=last_message_ms, last_error=last_error))
                            last_hb_ms = now
                        continue
                    received_ms = int(time.time() * 1000)
                    last_message_ms = received_ms
                    if text == "Ping":
                        ws.send_text("Pong")
                        continue
                    try:
                        message = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(message, Mapping):
                        try:
                            agg.consume(message, received_ms)
                        except Exception as exc:
                            last_error = f"{type(exc).__name__}:{exc}"[:300]
                    agg.flush_ready(history_path, received_ms)
                    if received_ms - last_hb_ms >= heartbeat_interval:
                        _atomic_json(heartbeat_path, _heartbeat(cfg, agg, connected=connected, started_ms=started_ms, connection_started_ms=connection_started_ms, last_message_ms=last_message_ms, last_error=last_error))
                        last_hb_ms = received_ms
            except Exception as exc:
                connected = False
                last_error = f"{type(exc).__name__}:{exc}"[:300]
                agg.totals["reconnects_total"] += 1
                _atomic_json(heartbeat_path, _heartbeat(cfg, agg, connected=False, started_ms=started_ms, connection_started_ms=connection_started_ms, last_message_ms=last_message_ms, last_error=last_error))
                if deadline is not None and time.monotonic() >= deadline:
                    break
                time.sleep(backoff)
            finally:
                if ws is not None:
                    ws.close()
                    ws = None
        agg.flush_ready(history_path, int(time.time() * 1000), force=True)
        _atomic_json(heartbeat_path, _heartbeat(cfg, agg, connected=False, started_ms=started_ms, connection_started_ms=connection_started_ms, last_message_ms=last_message_ms, last_error=last_error))
        return 0
    finally:
        try:
            if pid_path.is_file() and pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_path.unlink()
        except Exception:
            pass
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect prospective public BingX high-frequency microstructure history")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--max-seconds", type=int, default=0)
    ns = ap.parse_args(argv)
    policy = json.loads(ns.policy.read_text(encoding="utf-8"))
    return run(policy, max_seconds=max(0, ns.max_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
