"""Single-writer virtual BBO Shadow; native conditions and independent R runner.
No broker/network/Paper/Live/account NAV authority. Real observation clocks only.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import fcntl
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import signal as process_signal
import sys
import time
from forward_asof_quote import observe
import virtual_shadow_ledger as ledger

GMMA = "TREND_GUPPY_GMMA_LONG_4H_V1"
TSMOM = "MOMENTUM_MOP_TSMOM_LONG_4H_V1"
K117 = "K117_PRICE_ONLY_30M_NATIVE"
RULES = (TSMOM, GMMA, K117)
FOUR, HALF_HOUR = 14_400_000, 1_800_000
SIGNAL_4H = Path("/home/z/z/runtime/gmma_tsmom_orderless_quote_20261026_v2/STATUS.json")
SIGNAL_K117 = Path("/home/z/z/runtime/k117_priceonly_orderless_20261025_extended_v1/STATUS.json")
K117_NATIVE = Path("/home/z/worktrees/zel-k117-priceonly-contract-20261025/research/campaigns/scalp7_20261022/parallel_fastfinish_v1/work_e")
SHADOW = "zel.three_existing_survivors.rr_observer.v1"
RUNNER = "OBSERVE_2R_ARM_NEXT_QUOTE_PLUS_0P5R_FLOOR_NO_HARD_TP"

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def native_events(gmma_status, k117_status, rejected=None):
    """Per-event clocks only; never substitute the latest checkpoint time."""
    if (gmma_status.get("order_calls") != 0 or gmma_status.get("virtual_fills") != 0
            or gmma_status.get("formal_shadow") is not False
            or k117_status.get("order_calls") != 0 or k117_status.get("virtual_fills") != 0):
        raise RuntimeError("SOURCE_OBSERVER_AUTHORITY_CHANGED")
    result = []
    rows = [(row, False) for row in gmma_status.get("signals", [])]
    rows += [(row, True) for row in k117_status.get("signals", [])]
    for row, is_k117 in rows:
        if (row.get("status") != "SIGNAL" if is_k117 else row.get("state") != "SIGNAL_ONLY_NO_ORDER_NO_FILL"):
            continue
        rule = K117 if is_k117 else row.get("rule_id")
        if rule not in RULES:
            continue
        uid, decision = digest(row), row.get("decision_ts_ms")
        close = row.get("close_ts_ms") if is_k117 else row.get("closed_native_4h_ts_ms")
        if type(decision) is not int or type(close) is not int or close <= 0 or decision < close:
            if rejected is not None:
                rejected.append({"uid": uid, "reason": "SOURCE_EVENT_DECISION_CLOCK_UNVERIFIED", "rule_id": rule, "symbol": row.get("symbol")})
            continue
        event = {"rule_id": rule, "symbol": row["symbol"], "decision_ms": decision,
                 "signal_close_ts_ms": close, "original_signal_digest": uid,
                 "native_signal": deepcopy(row.get("signal")),
                 "native_signal_bar": deepcopy((row.get("native_exit_input") or {}).get("bar")),
                 "source_event": deepcopy(row),
                 "max_hold_ms": HALF_HOUR * 50 if is_k117 else FOUR * (24 if rule == TSMOM else 48)}
        if is_k117:
            event["signal_stop_px"] = float((row.get("signal") or {}).get("stop_price") or 0)
            event["unsupported_side"] = (row.get("signal") or {}).get("side") not in (1, "long", "LONG")
        else:
            distance = row.get("native_safety_stop_distance_price")
            if distance is None:
                distance = float(row.get("native_stop_distance_reference_bps") or 0) * float(row.get("native_signal_close_reference_price") or 0) / 10000
            event["risk_distance_price"] = float(distance)
        result.append(event)
    return sorted(result, key=lambda e: (e["decision_ms"], RULES.index(e["rule_id"]), e["symbol"]))

def valid_quote(q, after_ms):
    try:
        bid, ask = float(q["best_bid"]), float(q["best_ask"])
        return (q.get("state") == "OBSERVED_REAL_POST_DECISION_BOOK_ONLY_NO_FILL"
                and q.get("source_quote_clock_kind") == "BUCKET_END"
                and math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask
                and type(q["observed_at_ms"]) is int
                and after_ms < int(q["source_bucket_start_ms"]) < int(q["source_quote_ts_ms"]) <= q["observed_at_ms"]
                and q["observed_at_ms"] - int(q["source_quote_ts_ms"]) <= 15000)
    except (KeyError, ValueError, TypeError, OverflowError):
        return False

def quote_entry(event, q):
    if not valid_quote(q, event["decision_ms"]):
        return None
    price = float(q["best_ask"])
    stop = float(event["signal_stop_px"]) if event["rule_id"] == K117 else price - float(event.get("risk_distance_price") or 0)
    risk = price - stop
    if not math.isfinite(risk) or not 0 < stop < price or not 0 < risk < price:
        return None
    ts, read = int(q["source_quote_ts_ms"]), int(q["observed_at_ms"])
    return {**deepcopy(event), "entry_quote_ts_ms": ts, "quote_read_at_ms": read,
            "quote_received_at_ms": q.get("source_quote_received_at_ms"), "source_quote_clock_kind": "BUCKET_END",
            "entry_ask_price": price, "native_or_reference_stop_price": stop, "initial_risk_price": risk,
            "last_quote_ts_ms": ts, "last_quote_read_at_ms": read, "base_stop_price": stop,
            "native_active_stop_price": stop, "active_floor_stop_price": stop, "floor_pending_after_ts_ms": None,
            "best_observed_R": (float(q["best_bid"]) - price) / risk, "last_observed_R": (float(q["best_bid"]) - price) / risk,
            "cost_assumption_roundtrip_bps": 40, "quote_entry_sha256": q["source_quote_sha256"],
            "entry_quote_evidence": deepcopy(q), "native_pending": {}, "native_mfe_snapshots": {},
            "real_broker_fill": False, "original_next_open_fill_verified": False, "formal_shadow": False}

def terminal_evidence(position, quote, reason):
    bid, entry, risk = float(quote["best_bid"]), position["entry_ask_price"], position["initial_risk_price"]
    net = 10000 * (bid / entry - 1) - 40
    return {"type": "VIRTUAL_OBSERVED_BBO_BID_NOT_BROKER_FILL", "symbol": position["symbol"],
            "rule_id": position["rule_id"], "virtual_id": position.get("virtual_id"),
            "terminal_quote_ts_ms": int(quote["source_quote_ts_ms"]), "terminal_received_at_ms": quote.get("source_quote_received_at_ms"),
            "read_at_ms": quote["observed_at_ms"], "source_quote_clock_kind": "BUCKET_END",
            "terminal_bid_price": bid, "observational_net_bps_at_40bp": net,
            "observational_net_R": net / (10000 * risk / entry), "reason": reason,
            "intrabar_stop_witness_complete": False, "native_exit_rule_parity": False,
            "real_trade": False, "order_calls": 0, "source_quote_sha256": quote["source_quote_sha256"],
            "source_quote_evidence": deepcopy(quote)}

def sample_position(position, q, *, track="runner"):
    """Original native stop/exit plus runner-only 2R/0.5R next-quote floor."""
    if not valid_quote(q, position["last_quote_ts_ms"]) or q["observed_at_ms"] <= position["last_quote_read_at_ms"]:
        return position, None
    p = deepcopy(position)
    ts, read, bid = int(q["source_quote_ts_ms"]), q["observed_at_ms"], float(q["best_bid"])
    p["last_quote_ts_ms"], p["last_quote_read_at_ms"] = ts, read
    p["last_quote_sha256"] = q["source_quote_sha256"]
    measured = (bid - p["entry_ask_price"]) / p["initial_risk_price"]
    p["best_observed_R"], p["last_observed_R"] = max(p["best_observed_R"], measured), measured
    interval = HALF_HOUR if p["rule_id"] == K117 else FOUR
    closing = ((ts - 1) // interval + 1) * interval
    p["native_mfe_snapshots"][str(closing)] = {"through_ts_ms": ts, "mfe_R": p["best_observed_R"]}
    pending = p.get("native_pending", {})
    stop_event = pending.get("stop_event")
    if stop_event and q["source_bucket_start_ms"] > stop_event["decision_ts_ms"]:
        p["native_active_stop_price"] = max(p["native_active_stop_price"], stop_event["next_stop_price"])
        del pending["stop_event"]
    p["active_floor_stop_price"] = max(p["active_floor_stop_price"], p["native_active_stop_price"])
    if track == "runner" and p["floor_pending_after_ts_ms"] is not None and q["source_bucket_start_ms"] > p["floor_pending_after_ts_ms"]:
        p["active_floor_stop_price"] = max(p["active_floor_stop_price"], p["entry_ask_price"] + .5 * p["initial_risk_price"])
        p["floor_pending_after_ts_ms"] = None
    terminal = "OBSERVED_BID_TOUCH_STOP" if bid <= p["active_floor_stop_price"] else None
    exit_event = pending.get("exit_event")
    if terminal is None and exit_event and q["source_bucket_start_ms"] > exit_event["decision_ts_ms"]:
        terminal = "NATIVE_CONDITION_DELAYED_BID:" + exit_event["reason"]
    if terminal:
        return p, terminal_evidence(p, q, terminal)
    if (track == "runner" and measured >= 2 and p["floor_pending_after_ts_ms"] is None
            and p["active_floor_stop_price"] < p["entry_ask_price"] + .5 * p["initial_risk_price"]):
        p["floor_pending_after_ts_ms"] = read
    return p, None

def new_state(started):
    state = {"schema": SHADOW, "state": "RUNNING_WAIT_FIRST_FUTURE_SIGNAL", "started_at_ms": started,
             "virtual_started_at_ms": started, "updated_at_ms": started, "rules": list(RULES),
             "quote_symbols": ["BTC-USDT", "ETH-USDT"], "runner_idea": RUNNER,
             "same_symbol_max_positions": 1, "model_cost_bps": 40, "real_broker_fills": 0,
             "order_calls": 0, "formal_shadow": False, "native_strategy_changed": False,
             "g5_credit": 0, "account_NAV": None, "closed_quote_marks": [], "positions": {},
             "seen_signals": [], "pending": {}, "blocked": [], "faults": [], "last_consumed_decision_id": {},
             "profitability_validation": "NOT_VERIFIED", "source_hidden_price_path": True}
    ledger.initialize(state)
    return state

def resume_state(old, now):
    state = deepcopy(old)
    if state.get("schema") != SHADOW or state.get("rules") != list(RULES) or state.get("runner_idea") != RUNNER:
        raise RuntimeError("RR_CHECKPOINT_AUTHORITY_OR_FREEZE_CHANGED")
    if not state.get("virtual_shadow_schema"):
        ledger.initialize(state, upgrade=True)
        state["virtual_started_at_ms"] = now
        state["upgrade_from_quote_only_sha256"] = digest(old)
    else:
        ledger.verify(state)
    state.setdefault("faults", [])
    state.setdefault("last_consumed_decision_id", {})
    if now < state.get("updated_at_ms", 0):
        raise RuntimeError("RESTART_CLOCK_ROLLBACK")
    for symbol, position in list(state["positions"].items()):
        for track, item in list(position["tracks"].items()):
            if now - item["last_quote_read_at_ms"] > 30000:
                ledger.censor(state, symbol, "UNOBSERVED_QUOTE_PATH_ON_RESTART_NO_RETRO_CLOSE", track=track, at_ms=now)
    state.update(stopped=False, state="RUNNING_RESUMED_PROSPECTIVE_VIRTUAL_SHADOW", restarted_at_ms=now,
                 updated_at_ms=now, profitability_validation="NOT_VERIFIED")
    return state

def block(state, uid, reason, *, event=None, at_ms=None, **details):
    if uid not in state["seen_signals"]:
        if event is not None:
            ledger.ack_signal(state, event, accepted=False, reason=reason, at_ms=at_ms,
                              evidence_sha256=digest({"event": event, "observed_at_ms": at_ms, "reason": reason}))
        state["blocked"].append({"uid": uid, "reason": reason, "observed_at_ms": at_ms, **details})
        state["seen_signals"].append(uid)
    state["pending"].pop(uid, None)

def sample_track(state, symbol, track, now, quote_reader):
    item = state["positions"][symbol]["tracks"][track]
    after = max([item["last_quote_ts_ms"]] + [x["decision_ts_ms"] for x in item["native_pending"].values()])
    if after >= now:
        return
    quote = quote_reader(symbol, decision_ts_ms=after, read_at_ms=now)
    updated, terminal = sample_position(item, quote, track=track)
    state["positions"][symbol]["tracks"][track] = updated
    if terminal:
        ledger.exit_at_bid(state, terminal, track=track)
        return
    partial = updated.get("native_pending", {}).get("partial_event")
    if partial and valid_quote(quote, partial["decision_ts_ms"]):
        evidence = terminal_evidence(updated, quote, partial["reason"])
        evidence.update(partial_fraction=partial["partial_fraction"], partial_decision_ts_ms=partial["decision_ts_ms"])
        ledger.partial_at_bid(state, evidence, track=track)
        state["positions"][symbol]["tracks"][track]["native_pending"].pop("partial_event")


def poll_once(state, source4, source117, now, *, quote_reader=observe, native_exit_fn=None, k117_dependencies=None):
    """Mutate a transaction candidate; caller discards it on any exception."""
    rejected = []
    signals = native_events(source4, source117, rejected)
    for row in rejected:
        block(state, row["uid"], row["reason"], symbol=row["symbol"], rule_id=row["rule_id"])
    for event in signals:
        uid = event["original_signal_digest"]
        if uid in state["seen_signals"] or uid in state["pending"]:
            continue
        if event["decision_ms"] < state["virtual_started_at_ms"]:
            block(state, uid, "PRE_VIRTUAL_START_NOT_FRESH", event=event, at_ms=now)
            continue
        if event["decision_ms"] > now:
            raise RuntimeError("FUTURE_SOURCE_DECISION")
        state["pending"][uid] = event
        state["last_consumed_decision_id"][event["rule_id"] + ":" + event["symbol"]] = uid
    for uid, event in list(state["pending"].items()):
        symbol = event["symbol"]
        if event.get("unsupported_side"):
            block(state, uid, "UNSUPPORTED_K117_SIDE_LONG_ONLY", event=event, at_ms=now, symbol=symbol)
        elif symbol not in ("BTC-USDT", "ETH-USDT"):
            block(state, uid, "HOLD_NO_EXISTING_WS_QUOTE_FOR_SYMBOL", event=event, at_ms=now, symbol=symbol)
        elif now - event["decision_ms"] > 120000:
            block(state, uid, "NO_TIMELY_POST_SIGNAL_QUOTE", event=event, at_ms=now)
        elif symbol in state["positions"]:
            block(state, uid, "SAME_SYMBOL_POSITION_ALREADY_OCCUPIED", event=event, at_ms=now)
        else:
            quote = quote_reader(symbol, decision_ts_ms=event["decision_ms"], read_at_ms=now)
            position = quote_entry(event, quote)
            if position is not None:
                ledger.enter(state, position)
                state["seen_signals"].append(uid)
                del state["pending"][uid]
    for symbol, position in list(state["positions"].items()):
        for track, item in list(position["tracks"].items()):
            if now - item["last_quote_read_at_ms"] > 30000:
                ledger.censor(state, symbol, "UNOBSERVED_QUOTE_PATH_GAP_NO_RETRO_CLOSE", track=track, at_ms=now)
    # An already active stop can use the current observed bid before a new
    # completed-bar ambiguity is considered. New native stops remain pending.
    for symbol in list(state["positions"]):
        for track in list(state["positions"][symbol]["tracks"]):
            sample_track(state, symbol, track, now, quote_reader)
    for symbol in list(state["positions"]):
        for track in list(state["positions"][symbol]["tracks"]):
            item = state["positions"][symbol]["tracks"][track]
            if item["rule_id"] == K117:
                # Pending native admission still supplies source-only exit bars.
                # Prefer the native decision when both paths persisted this bar.
                combined = { (row.get("symbol"), row.get("close_ts_ms")): row
                             for row in source117.get("source_only_decisions", []) + source117.get("decisions", []) }
                rows = sorted(combined.values(), key=lambda row: row.get("close_ts_ms", 0))
            else:
                rows = source4.get("decisions", [])
            for row in rows:
                close = row.get("close_ts_ms", row.get("closed_native_4h_ts_ms", 0))
                if row.get("symbol") != symbol or close <= item["signal_close_ts_ms"]:
                    continue
                if item["rule_id"] != K117 and row.get("rule_id") != item["rule_id"]:
                    continue
                if close <= item.get("native_exit_state", {}).get("last_close_ts_ms", 0):
                    continue
                if native_exit_fn is None:
                    raise RuntimeError("NATIVE_EXIT_CALLBACK_NOT_CONNECTED")
                item["native_observed_mfe_snapshot"] = item["native_mfe_snapshots"].get(str(close))
                action = native_exit_fn(item, row, k117_dependencies=k117_dependencies)
                if action["censor_reason"]:
                    ledger.censor(state, symbol, action["censor_reason"], track=track, at_ms=now)
                    break
                item["native_exit_state"] = action["state"]
                for key in ("stop_event", "partial_event", "exit_event"):
                    if action[key] is not None:
                        item["native_pending"][key] = action[key]
                if action["exit_event"]:
                    break
            if symbol not in state["positions"] or track not in state["positions"][symbol]["tracks"]:
                continue
            sample_track(state, symbol, track, now, quote_reader)
    ledger.verify(state)
    state["state"] = "RUNNING_VIRTUAL_POSITIONS" if state["positions"] else "RUNNING_WAIT_FIRST_OR_NEXT_FUTURE_SIGNAL"

def persist(out, state, store=None):
    if state.get("order_calls") != 0 or state.get("real_broker_fills") != 0 or state.get("formal_shadow") is not False:
        raise RuntimeError("RR_ORDERLESS_AUTHORITY_CHANGED")
    if store is not None:
        store.commit(state)
    with (out / "STATUS.tmp").open("w") as target:
        target.write(json.dumps(state, indent=2, sort_keys=True, allow_nan=False) + "\n")
        target.flush()
        os.fsync(target.fileno())
    os.replace(out / "STATUS.tmp", out / "STATUS.json")
    fd = os.open(out, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def producer_alive(status, now):
    """A declared polling contract and an actual live PID, not a stale JSON flag."""
    pid, stamp, poll = status.get("pid"), status.get("updated_at_ms"), status.get("producer_poll_seconds")
    return (type(pid) is int and pid > 0 and Path("/proc", str(pid)).is_dir()
            and type(stamp) is int and type(poll) is int and 30 <= poll <= 300
            and 0 <= now - stamp <= (2 * poll + 15) * 1000
            and status.get("stopped") is not True)

def k117_ready(status, now):
    allowed = {"ACTIVE_DEVELOPMENT_OBSERVATION_NO_ORDER", "RESUMED_DEVELOPMENT_OBSERVATION_NO_ORDER",
               "VIRTUAL_SOURCE_ONLY_NATIVE_PENDING_OR_CAUSAL_HOLD", "WAIT_FIRST_PROSPECTIVE_CLOSED_30M"}
    return (producer_alive(status, now) and status.get("phase") in allowed
            and status.get("virtual_ack_health") == "VERIFIED_READ_ONLY_SQLITE_SNAPSHOT"
            and bool(status.get("virtual_signal_export"))
            and not status["virtual_signal_export"].get("native_causal_hold"))

def pin_contract(state, code_pins, native_pins, expected_previous=None):
    if state.get("k117_native_pins") not in (None, native_pins):
        raise RuntimeError("K117_NATIVE_CONTRACT_CHANGED_ON_RESTART")
    previous = state.get("code_sha256")
    if previous not in (None, code_pins):
        if (expected_previous != digest(previous) or state.get("virtual_events")
                or state.get("virtual_entry_T") or state.get("positions") or state.get("pending")):
            raise RuntimeError("VIRTUAL_OBSERVATION_CONTRACT_CHANGED_ON_RESTART")
        state.setdefault("empty_code_migrations", []).append({"previous": previous,
            "next": code_pins, "observed_at_ms": int(time.time()*1000), "reason": "EXPLICIT_PINNED_EMPTY_LEDGER_CODE_UPGRADE"})
    state["code_sha256"], state["k117_native_pins"] = code_pins, native_pins

def record_readiness(state, now, source4=None, source117=None):
    health = {"readiness": state["shadow_readiness"], "error": state.get("last_source_error"),
              "quote_states": {k: v.get("state") for k, v in state.get("quote_health", {}).items()},
              "sources": {name: None if value is None else
                          {k: value.get(k) for k in ("phase", "reason", "source_hold_reason", "virtual_ack_health")}
                          for name, value in (("four_hour", source4), ("k117", source117))}}
    signature = digest(health)
    history = state.setdefault("readiness_transitions", [])
    if not history or history[-1]["health_sha256"] != signature:
        history.append({**health, "observed_at_ms": now, "health_sha256": signature,
                        "source_status_sha256": deepcopy(state.get("source_status_sha256", {}))})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-observational-rr-only", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-seconds", type=int, default=604800)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--expected-empty-code-contract-sha256")
    parser.add_argument("--k117-native-dir", type=Path, default=K117_NATIVE)
    args = parser.parse_args()
    if not args.enable_observational_rr_only:
        print("DEFAULT_OFF:NO_ORDER_VIRTUAL_SHADOW")
        return 0
    if not (60 <= args.max_seconds <= 604800 and 3 <= args.poll_seconds <= 60):
        raise SystemExit("BOUNDED_RR_ONLY")
    args.out.mkdir(parents=True, exist_ok=args.resume_existing)
    lock = (args.out / "writer.lock").open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def boundary(event, details):
        if event in ("socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
            raise RuntimeError("NETWORK_ORDER_SUBPROCESS_BLOCKED")
    sys.addaudithook(boundary)
    safe = {key: value for key, value in os.environ.items() if key in ("PATH", "LANG", "LC_ALL", "TZ", "PYTHONDONTWRITEBYTECODE")}
    os.environ.clear()
    os.environ.update(safe)
    from native_exit_observer import evaluate_native_exit
    sys.path.insert(0, str(args.k117_native_dir))
    k117 = importlib.import_module("k117_adapter")
    dependencies = k117.dependencies()
    stop = False
    def request_stop(*_):
        nonlocal stop
        stop = True
    process_signal.signal(process_signal.SIGTERM, request_stop)
    process_signal.signal(process_signal.SIGINT, request_stop)
    store = ledger.Store(args.out / "VIRTUAL_LEDGER.sqlite3")
    started = int(time.time() * 1000)
    previous = store.load()
    if previous is None and args.resume_existing and (args.out / "STATUS.json").exists():
        previous = json.loads((args.out / "STATUS.json").read_bytes())
    state = resume_state(previous, started) if previous is not None else new_state(started)
    state["pid"] = os.getpid()
    code_pins = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                            [Path(__file__), Path(ledger.__file__), Path(__file__).with_name("native_exit_observer.py"),
                             Path(__file__).with_name("forward_asof_quote.py"), Path(__file__).with_name("benchmark.py")]}
    native_pins = k117.pins()
    pin_contract(state, code_pins, native_pins, args.expected_empty_code_contract_sha256)
    state["shadow_readiness"] = "STARTING"
    persist(args.out, state, store)
    until = time.monotonic() + args.max_seconds
    try:
        while not stop and time.monotonic() < until:
            now = int(time.time() * 1000)
            candidate = deepcopy(state)
            try:
                raw4, raw117 = SIGNAL_4H.read_bytes(), SIGNAL_K117.read_bytes()
                source4, source117 = json.loads(raw4), json.loads(raw117)
                poll_once(candidate, source4, source117, now,
                          native_exit_fn=evaluate_native_exit, k117_dependencies=dependencies)
                candidate["source_status_sha256"] = {str(SIGNAL_4H): hashlib.sha256(raw4).hexdigest(), str(SIGNAL_K117): hashlib.sha256(raw117).hexdigest()}
                # Health is not a signal. Include the full bucket preceding a
                # <=15s-old quote; observe() still enforces that freshness cap.
                candidate["quote_health"] = {symbol: observe(symbol, decision_ts_ms=now-30000, read_at_ms=now) for symbol in ("BTC-USDT", "ETH-USDT")}
                candidate["source_producer_readiness"] = {
                    "four_hour": producer_alive(source4, now) and source4.get("phase", "").startswith("ACTIVE_") and bool(source4.get("native_exit_contract")),
                    "k117": k117_ready(source117, now),
                }
                quotes_ready = all(q.get("state") == "OBSERVED_REAL_POST_DECISION_BOOK_ONLY_NO_FILL" for q in candidate["quote_health"].values())
                candidate["shadow_readiness"] = ("PASS_RUNNING" if quotes_ready and all(candidate["source_producer_readiness"].values())
                                                 else "HOLD_SOURCE_PRODUCER" if quotes_ready else "HOLD_QUOTE_SOURCE")
                candidate.pop("last_source_error", None)
                record_readiness(candidate, now, source4, source117)
            except (OSError, RuntimeError, TypeError, KeyError, ValueError) as exc:
                candidate = deepcopy(state)
                error = type(exc).__name__ + ":" + str(exc)
                if candidate.get("last_source_error") != error:
                    candidate["faults"].append({"observed_at_ms": now, "reason": error})
                candidate.update(last_source_error=error, state="HOLD_SOURCE_CLOCK_OR_AUTHORITY", shadow_readiness="HOLD_SOURCE")
                record_readiness(candidate, now)
                for symbol in list(candidate["positions"]):
                    for track, item in list(candidate["positions"][symbol]["tracks"].items()):
                        if now - item["last_quote_read_at_ms"] > 30000:
                            ledger.censor(candidate, symbol, "SOURCE_FAILURE_UNOBSERVED_QUOTE_PATH", track=track, at_ms=now)
            candidate["updated_at_ms"] = now
            persist(args.out, candidate, store)
            state = candidate
            time.sleep(args.poll_seconds)
    finally:
        try:
            # A status-file write can fail after a successful DB commit.
            # Reload the authoritative transaction before attempting shutdown IO.
            state = store.load() or state
            state.update(stopped=True, shadow_readiness="STOPPED", updated_at_ms=int(time.time()*1000))
            persist(args.out, state, store)
        finally:
            store.close()
            lock.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
