"""Work B: isolated development observations using existing Scalp7 components.

No service install, formal Paper activation, economic replay, or order client.
STATE.json is the single atomic commit for signal state and four virtual ledgers.
The CLI drops all credentials before importing the existing market components.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TF = 1_800_000
PUBLIC = "https://open-api.bingx.com"
ENDPOINTS = {"/openApi/swap/v3/quote/klines", "/openApi/swap/v2/quote/depth"}
SOURCE_RETRY_DELAYS = (10, 30, 60)
SAFE_ENV = {
    "PATH", "LANG", "LC_ALL", "TZ", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
}
CAMPAIGN = ROOT / "research/campaigns/scalp7_20260915"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def scrubbed_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key in SAFE_ENV}


def install_audit_boundary() -> dict[str, Any]:
    """Cover urllib use by imported modules too; forbid secret-file reads."""
    evidence: dict[str, Any] = {"public_get_calls": 0, "blocked_calls": 0,
                                "credential_file_reads": 0, "order_calls": 0}

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "urllib.Request":
            url, data, headers, method = args
            parsed = urllib.parse.urlsplit(url)
            query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
            if (method != "GET" or data is not None
                    or parsed.scheme != "https" or parsed.netloc != "open-api.bingx.com"
                    or parsed.path not in ENDPOINTS
                    or parsed.fragment
                    or set(query) - {"symbol", "interval", "timeZone", "startTime",
                                     "endTime", "limit", "timestamp"}
                    or any(k.lower() in ("authorization", "x-bx-apikey", "x-api-key")
                           for k in headers)):
                evidence["blocked_calls"] += 1
                raise ValueError("AUDIT_NON_PUBLIC_GET_BLOCKED")
            evidence["public_get_calls"] += 1
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0]))
            if (path.name == ".env" or path.name.startswith(".env.")
                    or ".ssh" in path.parts or path.suffix in (".pem", ".key")):
                evidence["blocked_calls"] += 1
                raise ValueError("AUDIT_CREDENTIAL_FILE_BLOCKED")
    sys.addaudithook(audit)
    return evidence


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("PUBLIC_FEED_REDIRECT_BLOCKED")


class PublicFeed:
    """Only two existing public quote endpoints; no auth, body, or redirect."""
    def __init__(self) -> None:
        self.receipts: list[dict[str, Any]] = []
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, url: str) -> tuple[int, bytes]:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
        if (parsed.scheme != "https" or parsed.netloc != "open-api.bingx.com"
                or parsed.path not in ENDPOINTS or parsed.fragment
                or set(query) - {"symbol", "interval", "timeZone", "startTime",
                                 "endTime", "limit", "timestamp"}):
            raise ValueError("NON_PUBLIC_QUOTE_REQUEST_BLOCKED")
        request = urllib.request.Request(url, method="GET", headers={
            "Accept": "application/json", "User-Agent": "scalp7-orderless-work-b-v1"})
        started = int(time.time() * 1000)
        item: dict[str, Any] = {"method": "GET", "source": PUBLIC + parsed.path,
                                "requested_at_ms": started, "auth_headers": False}
        try:
            try:
                with self.opener.open(request, timeout=30) as response:
                    status, raw = int(response.status), response.read()
            except urllib.error.HTTPError as exc:
                status, raw = int(exc.code), exc.read()
            item.update(http_status=status, body_sha256=hashlib.sha256(raw).hexdigest())
            # Classification only: retain original response bytes for the collector.
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    item["exchange_code"] = payload.get("code")
            except (ValueError, UnicodeError):
                pass
            return status, raw
        except Exception as exc:
            item["error_type"] = type(exc).__name__
            raise
        finally:
            item["received_at_ms"] = int(time.time() * 1000)
            self.receipts.append(item)


def existing_settings() -> dict[str, Any]:
    """Read only the already frozen costs, clock policy, and past context fit."""
    cost = CAMPAIGN / "cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
    clocks = CAMPAIGN / "broad_rebuild_v2/OBSERVED_PAPER_CONFIG_V3.json"
    fit = CAMPAIGN / "broad_rebuild_v2/FRESH_FORWARD_CONFIG_V2.json"
    old_clock = json.loads(clocks.read_bytes())
    return {
        "costs": json.loads(cost.read_bytes())["costs_bps"],
        "fit": json.loads(fit.read_bytes())["regime_fit"],
        "clock": {key: old_clock[key] for key in
                  ("max_quote_request_ms", "max_pair_skew_ms", "max_quote_gap_ms")},
        "sources": [{"path": str(path.relative_to(ROOT)),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in (cost, clocks, fit)],
        "nav": None, "capital": None, "leverage": None,
        "cost_assumption": "OBSERVED_BID_ASK_MINUS_FROZEN_REFERENCE_RESERVE_NOT_ACTUAL_FEES",
    }


class Shadow:
    def __init__(self, out: Path, source: Path, *, fixture: bool = False,
                 warmup_source: Path | None = None):
        from backend.research.rebuild.economic7_canonical_history_v1 import atomic_json
        from backend.research.rebuild import scalp7_observed_paper_v3 as paper
        from ops import scalp7_orderless_signals_v1 as signals
        self.out, self.source, self.fixture = out, source, fixture
        self.warmup_source = warmup_source
        self.paper, self.signals, self.atomic = paper, signals, atomic_json
        out.mkdir(parents=True, exist_ok=True)
        self.lock = (out / "writer.lock").open("a+b")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise ValueError("SHADOW_OWNER_ALREADY_RUNNING") from exc
        try:
            self._initialize(source, fixture)
        except Exception:
            self.lock.close()
            raise

    def _initialize(self, source: Path, fixture: bool) -> None:
        out, signals, paper = self.out, self.signals, self.paper
        settings = existing_settings()
        self.modules = {version: signals.callbacks(version) for version in signals.VERSIONS}
        self.config = settings
        self.path = out / "STATE.json"
        if self.path.exists():
            self.state = json.loads(self.path.read_bytes())
            signature = self.state.pop("state_sha256")
            if signature != digest(self.state):
                raise ValueError("SHADOW_STATE_HASH_MISMATCH")
            if (self.state["settings_sha256"] != digest(settings)
                    or self.state["fixture"] != fixture
                    or self.state["source_path"] != str(source.resolve())
                    or self.state.get("warmup_source_path") !=
                    (str(self.warmup_source.resolve()) if self.warmup_source else None)):
                raise ValueError("SHADOW_BINDING_CHANGED")
            for name, expected in self.state["code_pins"].items():
                if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                    raise ValueError("SHADOW_CODE_CHANGED")
        else:
            now = int(time.time() * 1000)
            names = ["ops/scalp7_orderless_shadow_v1.py", "ops/scalp7_orderless_signals_v1.py",
                     "backend/research/rebuild/scalp7_positive_lanes_v2.py",
                     "backend/research/rebuild/scalp7_observed_paper_v3.py",
                     "backend/research/rebuild/scalp7_fresh_source_v2.py",
                     "backend/research/rebuild/scalp7_source_data_v2.py",
                     "backend/research/rebuild/scalp7_source_clock_v3.py",
                     "backend/research/rebuild/scalp7_fresh_forward_v2.py",
                     "backend/research/rebuild/scalp7_rolling_context_v2.py",
                     "backend/research/rebuild/economic7_canonical_history_v1.py",
                     "backend/research/rebuild/scalp7_execution_v2.py",
                     "ops/scalp7_dual_native_funnel_v1.py",
                     "ops/scalp7_squeeze_regime_overlay_child_v1.py",
                     "ops/scalp7_squeeze_signal_low_successor_v1.py",
                     "research/campaigns/scalp7_20261013/dual_streak_v1/streak_successor_policies.py"]
            self.state = {
                "schema": "scalp7.orderless.development.v1", "fixture": fixture,
                "started_at_ms": now, "fresh_start_ms": (now // TF + 1) * TF,
                "source_path": str(source.resolve()), "settings_sha256": digest(settings),
                "warmup_source_path": str(self.warmup_source.resolve()) if self.warmup_source else None,
                "warmup_identity_sha256": None, "warmup_cursor_sha256": None,
                "code_pins": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                              for name in names},
                "signals": {}, "accounts": {v: paper.empty_state(digest(settings))
                                             for v in signals.VERSIONS},
                "market": [], "market_keys": {}, "decisions": [],
                "status": {version + ":" + symbol: "UNKNOWN_WAIT_FIRST_CLOSED_BAR"
                           for version in signals.VERSIONS for symbol in settings["costs"]},
                "http_receipts": [], "stopped": False, "order_calls": 0,
                "source_identity_sha256": None,
            }
            self.save()

    def close(self) -> None:
        self.lock.close()

    def save(self) -> None:
        if len(json.dumps(self.state)) > self.paper.MAX_STATE_BYTES:
            raise ValueError("SHADOW_LEDGER_BUDGET_HOLD_NO_DELETION")
        self.atomic(self.path, {**self.state, "state_sha256": digest(self.state)})

    def source_frames(self, now: int) -> tuple[dict[str, Any], dict[str, Any]]:
        from backend.research.rebuild.scalp7_fresh_source_v2 import load_observed_minutes
        from backend.research.rebuild.scalp7_source_data_v2 import aggregate_minutes
        identity = hashlib.sha256((self.source / "IDENTITY.json").read_bytes()).hexdigest()
        before = (self.source / "CURSOR.json").read_bytes()
        minutes = load_observed_minutes(self.source)
        if before != (self.source / "CURSOR.json").read_bytes():
            raise ValueError("SOURCE_SNAPSHOT_CHANGED_RETRY")
        if self.state["source_identity_sha256"] not in (None, identity):
            raise ValueError("SOURCE_IDENTITY_CHANGED")
        self.state["source_identity_sha256"] = identity
        frames, issues = {}, {}
        for symbol, data in minutes.items():
            data = data.loc[data.received_at_ms <= now]
            if data.empty:
                continue
            frame = aggregate_minutes(data, 30, observed=True)
            issues[symbol] = frame.attrs
            if not frame.empty:
                frames[symbol] = frame
        warmup_receipt = None
        if self.warmup_source:
            from backend.research.rebuild.scalp7_fresh_forward_v2 import combine_context
            seed = self.warmup_source
            seed_identity = hashlib.sha256((seed / "IDENTITY.json").read_bytes()).hexdigest()
            seed_cursor = (seed / "CURSOR.json").read_bytes()
            seed_hash = hashlib.sha256(seed_cursor).hexdigest()
            for key, actual in (("warmup_identity_sha256", seed_identity),
                                ("warmup_cursor_sha256", seed_hash)):
                if self.state[key] not in (None, actual):
                    raise ValueError("WARMUP_SOURCE_CHANGED")
            warmup = load_observed_minutes(seed)
            if seed_cursor != (seed / "CURSOR.json").read_bytes():
                raise ValueError("WARMUP_SNAPSHOT_CHANGED")
            source_start = json.loads((self.source / "IDENTITY.json").read_bytes())["start_ms"]
            for symbol, data in warmup.items():
                if (data.received_at_ms > now).any() or (data.timestamp_ms >= source_start).any():
                    raise ValueError("WARMUP_UNAVAILABLE_OR_OVERLAPPING")
                old = aggregate_minutes(data, 30, observed=True)
                if symbol in frames:
                    frames[symbol] = combine_context(old, frames[symbol], 30)
                elif not old.empty:
                    frames[symbol] = old
            self.state["warmup_identity_sha256"] = seed_identity
            self.state["warmup_cursor_sha256"] = seed_hash
            warmup_receipt = {"identity_sha256": seed_identity, "cursor_sha256": seed_hash,
                              "use": "INDICATOR_CONTEXT_ONLY_NO_HISTORICAL_TRADES",
                              "availability": "ACTUAL_HTTP_RECEIPTS_UNMODIFIED"}
        return frames, {"identity_sha256": identity,
                        "cursor_sha256": hashlib.sha256(before).hexdigest(),
                        "warmup": warmup_receipt, "issues": issues}

    def _machine(self, version: str) -> Any:
        return self.paper.ObservedPaper(self.state["accounts"][version],
            {**self.config["clock"], "fresh_start_ms": self.state["fresh_start_ms"]},
            self.config["costs"], self.modules)

    def advance(self, frames: dict[str, Any], *, now: int,
                quotes: dict[str, Any] | None = None, witness: Any = None) -> None:
        """One atomic transition; inputs are verified source snapshots, never commands."""
        if self.state["stopped"]:
            raise ValueError("SHADOW_STOPPED")
        saved = deepcopy(self.state)
        try:
            self._advance(frames, now=now, quotes=quotes or {}, witness=witness)
            self.save()
        except Exception:
            self.state = saved
            raise

    def _advance(self, frames: dict[str, Any], *, now: int,
                 quotes: dict[str, Any], witness: Any) -> None:
        from backend.research.rebuild import scalp7_positive_lanes_v2 as native
        clean = {}
        for symbol, frame in frames.items():
            validated = native._validated(frame)
            if (validated.available_ts_ms > now).any():
                raise ValueError("FUTURE_SOURCE_OBSERVATION")
            clean[symbol] = frame
            for row in frame.to_dict("records"):
                close = int(row["close_ts_ms"])
                if close < self.state["fresh_start_ms"]:
                    continue
                key = symbol + ":" + str(close)
                value = {k: row[k] for k in ("open_ts_ms", "close_ts_ms", "available_ts_ms",
                                             "open", "high", "low", "close", "segment_id")}
                signature = digest(value)
                if key in self.state["market_keys"]:
                    if self.state["market_keys"][key] != signature:
                        raise ValueError("COMMITTED_MARKET_BAR_CHANGED")
                    continue
                self.state["market_keys"][key] = signature
                self.state["market"].append({**value, "symbol": symbol,
                    "source": PUBLIC + "/openApi/swap/v3/quote/klines",
                    "source_ts_ms": close, "received_at_ms": int(row["available_ts_ms"]),
                    "processed_at_ms": now, "witness": witness,
                    "evidence_kind": "FIXTURE" if self.fixture else "ACTUAL_PUBLIC_CLOSED_30M",
                    "formal_fresh_credit": False})
        try:
            bound = self.signals.bind_causal_context(clean, self.config["fit"])
        except (ValueError, KeyError, TypeError):
            bound = clean  # Per-version UNKNOWN; no substituted context labels.
        for version in self.signals.VERSIONS:
            account = self.state["accounts"][version]
            machine = self._machine(version)
            blocked = set(self.config["costs"]) - set(bound)
            for symbol, frame in bound.items():
                if frame.empty or int(frame.iloc[-1].close_ts_ms) < self.state["fresh_start_ms"]:
                    blocked.add(symbol)
                    continue
                if int(frame.iloc[-1].close_ts_ms) != now // TF * TF:
                    blocked.add(symbol)
                    self.state["status"][version + ":" + symbol] = "UNKNOWN_MISSING_LATEST_CLOSED_BAR"
                    continue
                result = self.signals.on_bar(self.state["signals"], version=version,
                    symbol=symbol, frame=frame, cost_bps=self.config["costs"][symbol],
                    asof_ms=now, fit=self.config["fit"])
                if result["status"] == "DUPLICATE":
                    if self.state["status"].get(version + ":" + symbol, "UNKNOWN").startswith("UNKNOWN"):
                        blocked.add(symbol)
                    continue
                self.state["status"][version + ":" + symbol] = result["status"]
                if result["status"] == "UNKNOWN":
                    blocked.add(symbol)
                if result.get("reason") == "UNRESOLVED_PRIOR_ENTRY_DECISION":
                    # A verified newer candle can supersede a never-filled entry.
                    # Reuse the existing decision, with NO quotes/open positions;
                    # missing data and arbitrary timeouts cannot reject an HG event.
                    probe = self.paper.empty_state(account["freeze_sha256"])
                    probe["pending"] = {k: deepcopy(p) for k, p in account["pending"].items()
                                        if p["signal"]["symbol"] == symbol}
                    judge = self.paper.ObservedPaper(probe,
                        {**self.config["clock"], "fresh_start_ms": self.state["fresh_start_ms"]},
                        self.config["costs"], self.modules)
                    judge.step({}, {30: {symbol: clean[symbol]}}, now)
                    for event in probe["events"]:
                        if event["kind"] == "ENTRY_SUPERSEDED_BY_OBSERVED_DECISION_BAR":
                            owner = next(k for k, p in account["pending"].items()
                                         if p["key"] == event["key"])
                            del account["pending"][owner]
                            account["events"].append(event)
                            self.signals.decide_entry(self.state["signals"], version=version,
                                symbol=symbol, accepted=False, decision_ts_ms=now)
                self.state["decisions"].append({"version": version, "symbol": symbol,
                    "received_at_ms": now, "signal_result": result,
                    "quantity": None, "quantity_unit": "UNSIZED_RESEARCH_NOTIONAL",
                    "NAV": None, "cost_assumption": self.config["cost_assumption"]})
                signal = result.get("signal")
                if signal is not None:
                    wrapper = {"signal": signal, "observed_at_ms": now,
                        "decision_bar_close_ms": int(frame.iloc[-1].close_ts_ms),
                        "opportunity_key": digest([version, symbol, signal["signal_open_ts_ms"]]),
                        "execution_eligibility": "CURRENT_DECISION_BAR_REQUIRES_NEW_QUOTE"}
                    wrapper["record_sha256"] = digest(wrapper)
                    machine.admit(wrapper, now)
                    if account["seen"].get(wrapper["opportunity_key"]) == "POSITION_ALREADY_OWNED":
                        self.signals.decide_entry(self.state["signals"], version=version,
                            symbol=symbol, accepted=False, decision_ts_ms=now)
            old_events = len(account["events"])
            held_pending = {k: p for k, p in account["pending"].items()
                            if p["signal"]["symbol"] in blocked}
            for key in held_pending:
                del account["pending"][key]
            for position in account["positions"].values():
                if position["signal"]["symbol"] in blocked:
                    position["status"] = "HOLD_UNRESOLVED_SIGNAL_SOURCE"
            pending = {v["key"]: v["signal"]["symbol"] for v in account["pending"].values()}
            machine.step(quotes, {30: clean}, now, {30: clean})
            account["pending"].update(held_pending)
            for event in account["events"][old_events:]:
                if event["kind"] in ("PAPER_ENTRY", "ENTRY_REJECT", "ENTRY_SUPERSEDED_BY_OBSERVED_DECISION_BAR"):
                    symbol = pending[event["key"]]
                    self.signals.decide_entry(self.state["signals"], version=version,
                        symbol=symbol, accepted=event["kind"] == "PAPER_ENTRY", decision_ts_ms=now)
            # The shared simulator uses bps, not funded capital or exchange quantity.
            for trade in account["trades"]:
                trade.update(evidence_kind="FIXTURE" if self.fixture else "DEVELOPMENT_ORDERLESS_OBSERVED",
                             formal_fresh_credit=False, quantity=None, NAV=None)
            for position in account["positions"].values():
                symbol = position["signal"]["symbol"]
                position["quantity"], position["NAV"] = None, None
                selected = None
                if position["status"] == "OPEN_OBSERVED_PAPER":
                    selected = machine._quotes(position["signal"], quotes, now,
                                               int(position["entry_ts_ms"]) - 1)
                if selected:
                    mark = machine._prices(position["signal"], selected, False)
                    position["unrealized_gross_bps"] = machine._gross(position, mark) * position["remaining"]
                    position["mark_available_ts_ms"] = self.paper._usable(selected[symbol])
        self.state["last_observed_at_ms"] = now

    def stop(self) -> None:
        self.state["stopped"] = True
        self.state["stopped_at_ms"] = int(time.time() * 1000)
        self.save()  # Keep open positions/pending entries; never invent a liquidation.
        self.atomic(self.out / "STATUS.json", self.report())

    def report(self) -> dict[str, Any]:
        return {"schema": self.state["schema"], "fixture": self.fixture,
                "state": "STOPPED" if self.state["stopped"] else
                         "DEVELOPMENT_OBSERVATION" if self.state["market"] else "WAIT_FIRST_CLOSED_BAR",
                "closed_30m_records": len(self.state["market"]),
                "closed_T": sum(len(x["trades"]) for x in self.state["accounts"].values()),
                "open_virtual_positions": sum(len(x["positions"]) for x in self.state["accounts"].values()),
                "version_status": self.state["status"], "NAV": None,
                "order_calls": 0, "formal_fresh_credit": False,
                "state_sha256": digest(self.state), "state_path": str(self.path),
                "persistent_service_started": False}


def transient_source_rejection(exc: Exception, receipts: list[dict[str, Any]]) -> bool:
    """Only the observed exchange retry response, never integrity/auth failures."""
    from backend.research.rebuild.scalp7_source_data_v2 import SourceDataError
    if not isinstance(exc, SourceDataError) or str(exc) != "FRESH_SOURCE_RESPONSE_REJECTED":
        return False
    if not receipts:
        return False
    last = receipts[-1]
    return (last.get("source") == PUBLIC + "/openApi/swap/v3/quote/klines"
            and last.get("http_status") == 200
            and str(last.get("exchange_code")) == "100410")


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    if os.environ.get("ZEL_ORDERLESS_SCRUBBED") != "1":
        env = {**scrubbed_environment(), "ZEL_ORDERLESS_SCRUBBED": "1"}
        os.chdir(ROOT)
        os.execve(sys.executable, [sys.executable, "-m", "ops.scalp7_orderless_shadow_v1", *args_list], env)
    if set(os.environ) - SAFE_ENV - {"ZEL_ORDERLESS_SCRUBBED", "LC_CTYPE"}:
        raise ValueError("UNSCRUBBED_ENVIRONMENT_BLOCKED")
    audit = install_audit_boundary()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--warmup-source", type=Path)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--max-seconds", type=int, default=0)
    args = parser.parse_args(args_list)
    shadow = Shadow(args.out, args.source, warmup_source=args.warmup_source)
    feed = PublicFeed()
    started = time.monotonic()
    consecutive_source_retries = 0
    try:
        if args.stop:
            shadow.stop()
            print(json.dumps(shadow.report(), sort_keys=True), flush=True)
            return 0
        while True:
            try:
                if args.collect:
                    from backend.research.rebuild.scalp7_fresh_source_v2 import collect_once
                    collect_once(args.source, fetch=feed)
                now = int(time.time() * 1000)
                frames, witness = shadow.source_frames(now)
                shadow.advance(frames, now=now, witness=witness)
                names = sorted({p["signal"]["symbol"] for a in shadow.state["accounts"].values()
                                for p in [*a["pending"].values(), *a["positions"].values()]})
                if names:
                    quotes = {name: shadow.paper.quote_request(args.out, name, feed) for name in names}
                    now = int(time.time() * 1000)
                    frames, witness = shadow.source_frames(now)
                    shadow.advance(frames, now=now, quotes=quotes, witness=witness)
                shadow.state["http_receipts"].extend(feed.receipts)
                feed.receipts.clear()
                shadow.state["last_process_isolation"] = {
                    **audit, "environment_allowlist_only": True,
                    "exchange_client_imported": False,
                    "network_interface": "PUBLIC_GET_ALLOWLIST_NO_REDIRECT_NO_AUTH",
                }
                shadow.save()
                shadow.atomic(args.out / "STATUS.json", shadow.report())
                print(json.dumps(shadow.report(), sort_keys=True), flush=True)
                consecutive_source_retries = 0
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                retryable = args.collect and transient_source_rejection(exc, feed.receipts)
                shadow.state["http_receipts"].extend(feed.receipts)
                feed.receipts.clear()
                shadow.state["last_error"] = {"type": type(exc).__name__, "reason": str(exc),
                                               "at_ms": int(time.time() * 1000)}
                shadow.state["last_process_isolation"] = {**audit, "environment_allowlist_only": True}
                delay = (SOURCE_RETRY_DELAYS[consecutive_source_retries]
                         if consecutive_source_retries < len(SOURCE_RETRY_DELAYS) else None)
                remaining = args.max_seconds - (time.monotonic() - started)
                retry = retryable and args.max_seconds > 0 and delay is not None and remaining > delay
                if retryable:
                    shadow.state.setdefault("source_retry_events", []).append({
                        **shadow.state["last_error"], "attempt": consecutive_source_retries + 1,
                        "delay_seconds": delay if retry else None,
                        "disposition": "WAIT_SOURCE_RETRY" if retry else "HOLD_RETRY_BUDGET",
                    })
                shadow.save()
                status = {**shadow.report(), "state": "WAIT_SOURCE_RETRY" if retry else "HOLD",
                          "last_error": shadow.state["last_error"]}
                shadow.atomic(args.out / "STATUS.json", status)
                print(json.dumps(status, sort_keys=True), flush=True)
                if retry:
                    consecutive_source_retries += 1
                    time.sleep(delay)
                    if time.monotonic() - started < args.max_seconds:
                        continue  # No signal/quote/ledger advancement on the failed response.
                    shadow.atomic(args.out / "STATUS.json", {**status, "state": "HOLD"})
                return 2
            if not args.max_seconds or time.monotonic() - started >= args.max_seconds:
                return 0
            time.sleep(min(10, 60 - time.time() % 60))
    finally:
        shadow.close()


if __name__ == "__main__":
    raise SystemExit(main())
