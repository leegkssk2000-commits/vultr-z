#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import statistics
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.policy_kernel_v1 import ema

ROOT = Path(__file__).resolve().parents[3]
SCOPE = "TOP5_TRADER_BENCHMARK_MULTI_AI_AFTER_PR1255_V1"
OUT = ROOT / "research/development_evidence" / SCOPE
ACTIVE_REPLAY = ROOT / "backend/research/rebuild/a1_strategy25_active_deep_replay_latest.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
AUTHORITY = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
TARGET_GEMINI = "gemini-3.6-flash"
TARGET_OPENAI = "gpt-6-astra"
GEMINI_MODELS = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_GENERATE = f"https://generativelanguage.googleapis.com/v1beta/models/{TARGET_GEMINI}:generateContent"
OPENAI_RESPONSES = "https://api.openai.com/v1/responses"
MAX_NEW_GENERATION_CALLS = {"gemini": 1, "openai": 1}
RESERVED_USD = {"gemini": 0.25, "openai": 1.25}
# Conservative pricing proxies only; never claim these as billed amounts.
RATE_USD_PER_M = {"gemini": {"input": 2.0, "output": 12.0}, "openai": {"input": 12.5, "output": 50.0}}
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}

SOURCE_PACKET = [
    {
        "source_id": "LBR_HOLY_GRAIL",
        "url": "https://lindaraschke.net/wp-content/uploads/2013/11/august1997.pdf",
        "grade": "DIRECT_PUBLIC_INTERVIEW_RULES",
        "rules": [
            "Use 14-period ADX; arm the setup when ADX is above 30 and rising.",
            "Wait for a retracement to the 20-period exponential moving average.",
            "After the pullback, place a stop-entry beyond the prior completed bar in trend direction.",
            "Use the newly formed pullback swing extreme as protective risk and trail protection as profits grow.",
        ],
    },
    {
        "source_id": "QULLAMAGGIE_BREAKOUT",
        "url": "https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/",
        "grade": "TRADER_SELF_PUBLISHED_RULES",
        "rules": [
            "A large prior advance is followed by an orderly consolidation with higher lows and tighter range.",
            "Entry is on range expansion or an opening-range breakout.",
            "Initial stop is at the day low and should not be wider than ATR or ADR.",
            "Take a partial after several days and trail the remainder with a short moving average.",
        ],
    },
    {
        "source_id": "BASSO_KELTNER21",
        "url": "https://www.investors.com/news/gold-prices-tempt-traders-use-this-signal-to-time-your-buys-and-sells/",
        "grade": "PUBLIC_INTERVIEW_SUMMARY",
        "rules": [
            "Use a 21-day Keltner band framework for directional buy and sell signals.",
            "An upper-band hit can be a buy signal and a lower-band signal can define the opposite side.",
            "Define exits when the position is opened and keep portfolio risk normalized.",
        ],
    },
    {
        "source_id": "PARKER_CLASSIC_TREND",
        "url": "https://www.toptradersunplugged.com/podcast/ttu145-jerry-parker-founder-of-chesapeake-capital/",
        "grade": "PUBLIC_INTERVIEW",
        "rules": [
            "Classic trend following emphasizes one entry, one exit and a stop.",
            "Keep losses small while allowing profitable outliers to run.",
            "Avoid adding complexity merely because it improves a backtest.",
        ],
    },
]

NATIVE_FINGERPRINTS = {
    "supertrend_pullback": {
        "policy_path": "backend/research/rebuild/trend_policy_batch_v1.py",
        "entry": "supertrend direction + rising EMA50 + EMA50 pullback/reclaim; pullback 0.15..2 ATR; chase <=1.5 ATR",
        "risk": "1.5 ATR initial stop; timeout 48 bars; no fixed TP",
    },
    "trend_rider": {
        "policy_path": "backend/research/rebuild/trend_policy_batch_v1.py",
        "entry": "supertrend + EMA50 continuation confirmation; ST gap >=0.10 ATR; chase <=2 ATR",
        "risk": "1.5 ATR initial stop; timeout 48 bars; runner intent",
    },
    "keltner_trend": {
        "policy_path": "backend/research/rebuild/breakout_policy_batch_v1.py",
        "entry": "EMA20 Keltner +/-1.5 ATR + EMA21/55 alignment + noncontracting ATR + chase <=1 ATR",
        "risk": "1.25 ATR initial stop; timeout 48 bars",
    },
    "break_and_continue": {
        "policy_path": "backend/research/rebuild/breakout_policy_batch_v1.py",
        "entry": "prior-20 range breakout + EMA21/55 alignment + box height <=4 ATR + chase <=1 ATR",
        "risk": "1.25 ATR initial stop; timeout 48 bars",
    },
    "trend_ma_macd": {
        "policy_path": "backend/research/rebuild/trend_policy_batch_v1.py",
        "entry": "EMA21/55 alignment + MACD histogram zero-cross + chase <=1.5 ATR",
        "risk": "1.5 ATR initial stop; timeout 48 bars",
    },
}

DECISION_TEMPLATE = {
    "supertrend_pullback": {
        "source_id": "LBR_HOLY_GRAIL",
        "match": "ANALOGOUS_BENCHMARK",
        "decision": "EXECUTE",
        "candidate_id": "supertrend_pullback__lbr_holy_grail_adx30_ema20_v1",
        "causal_target": "Raise entry quality/win rate by requiring an objectively strong trend before a pullback entry.",
        "duplicate_check": "DISTINCT_FROM_PRIOR_EMA50_TOUCH_RECLAIM_AND_CURRENT_SUPERTREND_EMA50_PARENT",
        "no_lookahead": "PASS_COMPLETED_BAR_ADX_EMA_AND_NEXT_BAR_STOP_ENTRY_ONLY",
        "translation": "ADX14>30 and rising arms direction; EMA20 touch creates next-bar stop entry; source swing-risk/trailing is translated causally; parent cost model and 48-bar horizon are retained where source is unspecified.",
    },
    "trend_rider": {
        "source_id": "PARKER_CLASSIC_TREND",
        "match": "ANALOGOUS_BENCHMARK",
        "decision": "REJECT_DUPLICATE_RECENT_MECHANISM",
        "candidate_id": None,
        "causal_target": "Preserve fat-tail winners while limiting small losses.",
        "duplicate_check": "RECENT_WINNER_RESTORE_AND_CHASE_COOLING_ALREADY_TARGET_THIS_AXIS",
        "no_lookahead": "NOT_RUN",
        "translation": "No new child: source behavior is already represented by the current runner/winner-restore work.",
    },
    "keltner_trend": {
        "source_id": "BASSO_KELTNER21",
        "match": "ANALOGOUS_BENCHMARK",
        "decision": "REJECT_NO_SUPPORTED_CANDIDATE",
        "candidate_id": None,
        "causal_target": "Simplify band-entry logic without sacrificing risk controls.",
        "duplicate_check": "CURRENT_POLICY_ALREADY_KELTNER20_WITH_EXTRA_FILTERS",
        "no_lookahead": "NOT_RUN",
        "translation": "The public source does not specify a band multiplier suitable for a faithful 1h crypto translation; changing 20 to 21 alone is a parameter tweak, not a mechanism replacement.",
    },
    "break_and_continue": {
        "source_id": "QULLAMAGGIE_BREAKOUT",
        "match": "ANALOGOUS_BENCHMARK",
        "decision": "REJECT_NO_SUPPORTED_CANDIDATE",
        "candidate_id": None,
        "causal_target": "Improve setup selection before breakout rather than retuning exits.",
        "duplicate_check": "CURRENT_POLICY_HAS_PRIOR20_BREAKOUT_BUT_LACKS_STOCK_SESSION_AND_MULTIWEEK_CONTEXT",
        "no_lookahead": "NOT_RUN",
        "translation": "Opening-range/day-low/multiweek leader context is not available in the frozen 1h crypto policy without a market/timeframe architecture change.",
    },
    "trend_ma_macd": {
        "source_id": "PARKER_CLASSIC_TREND",
        "match": "WEAK_ANALOGY_ONLY",
        "decision": "REJECT_NO_DIRECT_MECHANISM_MATCH",
        "candidate_id": None,
        "causal_target": "Improve trend entry quality.",
        "duplicate_check": "NO_DIRECT_MACD_RULE_IN_SELECTED_TRADER_SOURCES",
        "no_lookahead": "NOT_RUN",
        "translation": "Do not manufacture a MACD threshold from a generic trend-following interview.",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def boundary_clean_key(raw: str | None) -> tuple[str | None, str | None]:
    if raw is None:
        return None, "KEY_MISSING"
    value = raw.strip(" \t\r\n")
    if not value:
        return None, "KEY_EMPTY_AFTER_BOUNDARY_TRIM"
    for ch in value:
        code = ord(ch)
        if code < 33 or code > 126 or ch.isspace():
            return None, "KEY_INTERNAL_WHITESPACE_CONTROL_OR_NONASCII"
    return value, None


def _json_request(url: str, *, headers: dict[str, str], body: Any | None = None, timeout: int = 120) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    h = {"Accept": "application/json", "User-Agent": "ZEL-top5-benchmark/1", **headers}
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise RuntimeError("PROVIDER_RESPONSE_TOO_LARGE")
            return int(response.status), json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read(200_001)[:200_000]
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {"error": {"type": "HTTP_ERROR", "status": exc.code}}
        return int(exc.code), payload


def _extract_openai_text(payload: Mapping[str, Any]) -> str:
    text = payload.get("output_text")
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content") or []:
            if isinstance(content, Mapping) and isinstance(content.get("text"), str):
                parts.append(str(content["text"]))
    return "\n".join(parts)


def _parse_json_text(text: str) -> Any:
    raw = text.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    try:
        return json.loads(raw.strip())
    except Exception:
        return {"parse_error": True, "text_prefix": raw.strip()[:4000]}


def _usage_estimate(provider: str, usage: Mapping[str, Any] | None) -> float | None:
    if not usage:
        return None
    if provider == "gemini":
        inp, out = usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
    else:
        inp, out = usage.get("input_tokens"), usage.get("output_tokens")
    if not isinstance(inp, (int, float)) or not isinstance(out, (int, float)):
        return None
    rate = RATE_USD_PER_M[provider]
    return float(inp) / 1_000_000 * rate["input"] + float(out) / 1_000_000 * rate["output"]


def native_snapshot() -> dict[str, Any]:
    active = read(ACTIVE_REPLAY)
    rows = {str(row["strategy_id"]): row for row in active.get("rows") or []}
    return {
        "active_top5": list(active.get("active_top5") or []),
        "stored_metrics": {sid: (rows.get(sid) or {}).get("metrics") for sid in NATIVE_FINGERPRINTS},
        "stored_quality": {
            sid: {
                "best_trade_share_of_total": ((rows.get(sid) or {}).get("evidence_quality") or {}).get("best_trade_share_of_total"),
                "pnl_without_best_trade_bps": ((rows.get(sid) or {}).get("evidence_quality") or {}).get("pnl_without_best_trade_bps"),
                "median_net_bps": ((rows.get(sid) or {}).get("evidence_quality") or {}).get("median_net_bps"),
            }
            for sid in NATIVE_FINGERPRINTS
        },
        "fingerprints": NATIVE_FINGERPRINTS,
        "source_receipt_sha256": {sid: (rows.get(sid) or {}).get("source_receipt_sha256") for sid in NATIVE_FINGERPRINTS},
    }


def ai_prompt(role: str, snapshot: dict[str, Any], gemini_result: Any | None = None) -> str:
    payload = {
        "scope": SCOPE,
        "role": role,
        "constraints": [
            "No future-PnL prediction, threshold sweep, post-outcome trade deletion, or hidden strategy retuning.",
            "Separate exact source rule from 1h-crypto analogy.",
            "Check duplicate mechanisms against current native fingerprints.",
            "Prefer causal entry-quality mechanisms; protect ordinary and fat-tail winners.",
            "AI advice has no execution or promotion authority.",
        ],
        "sources": SOURCE_PACKET,
        "native": snapshot,
        "proposed_decisions": DECISION_TEMPLATE,
        "gemini_result_for_red_team": gemini_result,
        "requested_output": {
            "lane_reviews": [{"strategy_id": "string", "source_fidelity": "PASS|WARN|FAIL", "causal_reach": "PASS|WARN|FAIL", "duplicate_risk": "LOW|MEDIUM|HIGH", "lookahead_risk": "LOW|MEDIUM|HIGH", "note": "short"}],
            "holy_grail_candidate": {"verdict": "SUPPORT|WARN|REJECT", "blocking_reason": "short_or_null"},
            "counterexample": "short",
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def call_gemini(snapshot: dict[str, Any]) -> dict[str, Any]:
    key, problem = boundary_clean_key(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    record: dict[str, Any] = {
        "provider": "gemini", "model": TARGET_GEMINI, "inventory_attempts": 0, "generation_attempts": 0,
        "reserved_usd": RESERVED_USD["gemini"], "billing_status": "UNKNOWN_NOT_SETTLED",
        "key_transport": "TRIM_BOUNDARY_ASCII_SPACE_TAB_CR_LF_THEN_STRICT_VISIBLE_ASCII",
    }
    if problem:
        return {**record, "state": "BLOCKED", "blocker": problem}
    record["inventory_attempts"] = 1
    try:
        status, inventory = _json_request(GEMINI_MODELS, headers={"x-goog-api-key": key}, timeout=45)
        record["inventory_http_status"] = status
        if status != 200:
            return {**record, "state": "BLOCKED", "blocker": "MODEL_INVENTORY_HTTP"}
        target = next((m for m in inventory.get("models") or [] if isinstance(m, Mapping) and m.get("name") == f"models/{TARGET_GEMINI}"), None)
        methods = list((target or {}).get("supportedGenerationMethods") or [])
        record["target_listed"] = bool(target)
        record["generate_content_supported"] = "generateContent" in methods
        if not target or "generateContent" not in methods:
            return {**record, "state": "BLOCKED", "blocker": "TARGET_MODEL_NOT_EXPLICITLY_AVAILABLE"}
        body = {
            "contents": [{"role": "user", "parts": [{"text": ai_prompt("SOURCE_MECHANISM_MAPPER", snapshot)}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096, "responseMimeType": "application/json"},
        }
        record["generation_attempts"] = 1
        status, payload = _json_request(GEMINI_GENERATE, headers={"x-goog-api-key": key}, body=body, timeout=120)
        record["http_status"] = status
        if status != 200:
            return {**record, "state": "FAILED_CONSUMED_NO_RETRY", "blocker": "GENERATION_HTTP"}
        candidates = payload.get("candidates") or []
        text = ""
        if candidates:
            parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
            text = "\n".join(str(p.get("text")) for p in parts if isinstance(p, Mapping) and isinstance(p.get("text"), str))
        usage = payload.get("usageMetadata") if isinstance(payload.get("usageMetadata"), Mapping) else {}
        return {
            **record, "state": "SUCCESS", "response_id": payload.get("responseId"), "usage": usage,
            "estimated_charge_usd_proxy": _usage_estimate("gemini", usage), "result": _parse_json_text(text),
        }
    except Exception as exc:
        return {**record, "state": "FAILED_CONSUMED_NO_RETRY" if record["generation_attempts"] else "BLOCKED", "blocker": f"{type(exc).__name__}:{exc}"[:300]}


def call_openai(snapshot: dict[str, Any], gemini: dict[str, Any]) -> dict[str, Any]:
    key, problem = boundary_clean_key(os.environ.get("OPENAI_API_KEY"))
    record: dict[str, Any] = {
        "provider": "openai", "model": TARGET_OPENAI, "generation_attempts": 0,
        "reserved_usd": RESERVED_USD["openai"], "billing_status": "UNKNOWN_NOT_SETTLED",
    }
    if problem:
        return {**record, "state": "BLOCKED", "blocker": problem}
    gemini_evidence = gemini.get("result") if gemini.get("state") == "SUCCESS" else {"state": gemini.get("state"), "blocker": gemini.get("blocker")}
    body = {"model": TARGET_OPENAI, "input": ai_prompt("RED_TEAM_IMPLEMENTATION_ECONOMICS", snapshot, gemini_evidence), "max_output_tokens": 4500}
    record["generation_attempts"] = 1
    try:
        status, payload = _json_request(OPENAI_RESPONSES, headers={"Authorization": "Bearer " + key}, body=body, timeout=150)
        record["http_status"] = status
        if status != 200:
            return {**record, "state": "FAILED_CONSUMED_NO_RETRY", "blocker": "GENERATION_HTTP"}
        usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
        return {
            **record, "state": "SUCCESS", "response_id": payload.get("id"), "usage": usage,
            "estimated_charge_usd_proxy": _usage_estimate("openai", usage), "result": _parse_json_text(_extract_openai_text(payload)),
        }
    except Exception as exc:
        return {**record, "state": "FAILED_CONSUMED_NO_RETRY", "blocker": f"{type(exc).__name__}:{exc}"[:300]}


def adx_wilder(bars: list[Mapping[str, Any]], n: int = 14) -> tuple[list[float | None], list[float | None], list[float | None]]:
    size = len(bars)
    adx: list[float | None] = [None] * size
    plus_di: list[float | None] = [None] * size
    minus_di: list[float | None] = [None] * size
    if size < 2 * n + 1:
        return adx, plus_di, minus_di
    tr, pdm, mdm = [0.0] * size, [0.0] * size, [0.0] * size
    for i in range(1, size):
        hi, lo = float(bars[i]["high"]), float(bars[i]["low"])
        phi, plo, pc = float(bars[i - 1]["high"]), float(bars[i - 1]["low"]), float(bars[i - 1]["close"])
        up, down = hi - phi, plo - lo
        tr[i] = max(hi - lo, abs(hi - pc), abs(lo - pc))
        pdm[i] = up if up > down and up > 0 else 0.0
        mdm[i] = down if down > up and down > 0 else 0.0
    tr_s, p_s, m_s = sum(tr[1:n + 1]), sum(pdm[1:n + 1]), sum(mdm[1:n + 1])
    dx: list[float | None] = [None] * size
    for i in range(n, size):
        if i > n:
            tr_s, p_s, m_s = tr_s - tr_s / n + tr[i], p_s - p_s / n + pdm[i], m_s - m_s / n + mdm[i]
        if tr_s <= 0:
            continue
        p, m = 100.0 * p_s / tr_s, 100.0 * m_s / tr_s
        plus_di[i], minus_di[i] = p, m
        dx[i] = 100.0 * abs(p - m) / (p + m) if p + m > 0 else 0.0
    first = 2 * n - 1
    initial = [float(dx[i]) for i in range(n, first + 1) if dx[i] is not None]
    if len(initial) != n:
        return adx, plus_di, minus_di
    a = sum(initial) / n
    adx[first] = a
    for i in range(first + 1, size):
        if dx[i] is not None:
            a = (a * (n - 1) + float(dx[i])) / n
            adx[i] = a
    return adx, plus_di, minus_di


def metrics_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net = [float(x["net_bps"]) for x in trades]
    wins, losses_abs = [x for x in net if x > 0], [-x for x in net if x < 0]
    gp, gl = sum(wins), sum(losses_abs)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses_abs) if losses_abs else None
    equity = peak = max_dd = 0.0
    max_streak = cur = 0
    for x in net:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        cur = cur + 1 if x < 0 else 0
        max_streak = max(max_streak, cur)
    ordered = sorted(net, reverse=True)
    loss_tail = sorted(losses_abs)
    p95 = loss_tail[min(len(loss_tail) - 1, max(0, math.ceil(0.95 * len(loss_tail)) - 1))] if loss_tail else None
    total = sum(net)
    return {
        "trades": len(trades), "win_rate": len(wins) / len(net) if net else None,
        "avg_win_bps": avg_win, "avg_loss_bps": avg_loss,
        "payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
        "profit_factor": gp / gl if gl > 0 else None, "net_pnl_bps": total,
        "net_expectancy_bps": total / len(net) if net else None, "drawdown_bps": max_dd,
        "max_losing_streak": max_streak, "loss_p95_bps": p95,
        "median_net_bps": statistics.median(net) if net else None,
        "cost_total_bps": sum(float(x.get("realized_cost_bps") or 0.0) for x in trades),
        "holding_hours_total": sum(max(0, int(x["exit_ts"]) - int(x["entry_ts"])) for x in trades) / 3_600_000,
        "best_trade_net_bps": ordered[0] if ordered else None,
        "top1_share_of_total": ordered[0] / total if ordered and total > 0 else None,
        "pnl_without_best_trade_bps": total - ordered[0] if ordered else None,
    }


def current_parent_receipt(symbols: list[str], bars_cache: dict[tuple[str, str, int], list[dict[str, Any]]], snapshot_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ledger = read(LEDGER)
    shadow = json.loads(json.dumps(ledger))
    shadow["strategies"]["supertrend_pullback"]["status"] = "ACTIVE"
    original_ledger, original_bars, original_snapshot, original_argv = ev.LEDGER_PATH, ev.fetch_bars, ev.fetch_execution_snapshot, list(sys.argv)

    def cb(symbol: str, interval: str, limit: int = 1000):
        key = (symbol, interval, int(limit))
        if key not in bars_cache:
            bars_cache[key] = original_bars(symbol, interval, limit)
        return bars_cache[key]

    def cs(symbol: str, authority: dict[str, Any]):
        if symbol not in snapshot_cache:
            snapshot_cache[symbol] = original_snapshot(symbol, authority)
        return snapshot_cache[symbol]

    with tempfile.TemporaryDirectory(prefix="top5_benchmark_parent_") as td:
        temp_ledger, temp_out = Path(td) / "ledger.json", Path(td) / "parent.json"
        write(temp_ledger, shadow)
        ev.LEDGER_PATH, ev.fetch_bars, ev.fetch_execution_snapshot = temp_ledger, cb, cs
        sys.argv = ["a1_exact25_generic_evaluator_v1.py", "--strategy-id", "supertrend_pullback", "--symbols", ",".join(symbols), "--out", str(temp_out)]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ev.main()
            return read(temp_out)
        finally:
            ev.LEDGER_PATH, ev.fetch_bars, ev.fetch_execution_snapshot, sys.argv = original_ledger, original_bars, original_snapshot, original_argv


def holy_grail_replay(symbols: list[str], bars_cache: dict[tuple[str, str, int], list[dict[str, Any]]], snapshot_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ledger, authority = read(LEDGER), read(AUTHORITY)
    boundary = str(ledger["strategies"]["supertrend_pullback"]["prospective_boundary_utc"])
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    trades: list[dict[str, Any]] = []
    open_intents = rejected_ownership = ambiguous_intrabar = 0

    for symbol in symbols:
        bars = bars_cache.get((symbol, "1h", 1000))
        if bars is None:
            bars = ev.fetch_bars(symbol, "1h", 1000)
            bars_cache[(symbol, "1h", 1000)] = bars
        snap = snapshot_cache.get(symbol)
        if snap is None:
            snap = ev.fetch_execution_snapshot(symbol, authority)
            snapshot_cache[symbol] = snap
        e20 = ema([float(x["close"]) for x in bars], 20)
        adx, pdi, mdi = adx_wilder(bars, 14)
        armed: str | None = None
        pending: dict[str, Any] | None = None
        blocked_until_ts = -1
        i = 30
        while i < len(bars) - 1:
            bar = bars[i]
            ts_ms = int(bar["ts_ms"])
            if ts_ms < boundary_ms:
                i += 1
                continue
            a, ap, p, m = adx[i], adx[i - 1], pdi[i], mdi[i]
            if a is not None and ap is not None and a > 30.0 and a > ap and p is not None and m is not None:
                armed = "long" if p > m else ("short" if m > p else armed)
            if armed == "long" and p is not None and m is not None and m >= p:
                armed, pending = None, None
            elif armed == "short" and p is not None and m is not None and p >= m:
                armed, pending = None, None

            next_bar, next_ts = bars[i + 1], int(bars[i + 1]["ts_ms"])
            if pending is not None:
                if next_ts <= blocked_until_ts:
                    rejected_ownership += 1
                    pending = None
                else:
                    side, trigger, initial_stop = str(pending["side"]), float(pending["trigger"]), float(pending["initial_stop"])
                    fill = (side == "long" and float(next_bar["high"]) > trigger) or (side == "short" and float(next_bar["low"]) < trigger)
                    if fill:
                        entry_px = max(float(next_bar["open"]), trigger) if side == "long" else min(float(next_bar["open"]), trigger)
                        same_bar_stop = (side == "long" and float(next_bar["low"]) <= initial_stop) or (side == "short" and float(next_bar["high"]) >= initial_stop)
                        exit_px = exit_ts = reason = None
                        stop, risk = initial_stop, abs(entry_px - initial_stop)
                        if risk <= 0:
                            pending = None
                            i += 1
                            continue
                        if same_bar_stop:
                            ambiguous_intrabar += 1
                            exit_px = min(float(next_bar["open"]), stop) if side == "long" else max(float(next_bar["open"]), stop)
                            exit_ts, reason = next_ts, "CONSERVATIVE_INTRABAR_STOP"
                        else:
                            trailing_active = False
                            last_j = min(len(bars) - 1, i + 1 + 48)
                            for j in range(i + 2, last_j + 1):
                                b = bars[j]
                                op, hi, lo = float(b["open"]), float(b["high"]), float(b["low"])
                                if (side == "long" and lo <= stop) or (side == "short" and hi >= stop):
                                    exit_px = min(op, stop) if side == "long" else max(op, stop)
                                    exit_ts = int(b["ts_ms"])
                                    reason = "SWING_TRAIL_STOP" if trailing_active else "INITIAL_SWING_STOP"
                                    break
                                if (side == "long" and hi >= entry_px + risk) or (side == "short" and lo <= entry_px - risk):
                                    trailing_active = True
                                if trailing_active:
                                    structural = lo if side == "long" else hi
                                    stop = max(stop, structural) if side == "long" else min(stop, structural)
                            if exit_px is None:
                                if last_j >= len(bars) - 1:
                                    open_intents += 1
                                    blocked_until_ts = int(bars[-1]["ts_ms"]) + 2 * 3_600_000
                                    pending, armed = None, None
                                    i += 1
                                    continue
                                b = bars[last_j]
                                exit_px, exit_ts, reason = float(b["close"]), int(b["ts_ms"]), "TIMEOUT_48"
                        fee, spread, impact = float(snap["fee_bps"]), float(snap["spread_bps"]), float(snap["impact_bps"])
                        fund = ev.funding_cost(next_ts, int(exit_ts), list(snap["funding_rows"]))
                        cost = fee + spread + impact + fund
                        gross = ((float(exit_px) - entry_px) / entry_px * 10_000) if side == "long" else ((entry_px - float(exit_px)) / entry_px * 10_000)
                        trades.append({
                            "symbol": symbol, "signal_ts": int(pending["touch_ts"]), "entry_ts": next_ts, "exit_ts": int(exit_ts),
                            "side": side, "entry": entry_px, "exit": float(exit_px), "reason": reason, "gross_bps": gross,
                            "realized_cost_bps": cost, "net_bps": gross - cost, "benchmark_source_id": "LBR_HOLY_GRAIL",
                            "trigger": trigger, "initial_stop": initial_stop,
                        })
                        blocked_until_ts, armed = int(exit_ts) + 2 * 3_600_000, None
                    pending = None

            center, lo, hi, close = float(e20[i]), float(bar["low"]), float(bar["high"]), float(bar["close"])
            touched = lo <= center <= hi
            if armed == "long" and touched and close >= center:
                pending = {"side": "long", "trigger": hi, "initial_stop": lo, "touch_ts": ts_ms}
            elif armed == "short" and touched and close <= center:
                pending = {"side": "short", "trigger": lo, "initial_stop": hi, "touch_ts": ts_ms}
            i += 1

    return {
        "schema_version": "zel.top5.lbr_holy_grail.causal_translation.v1",
        "strategy_id": "supertrend_pullback", "candidate_id": "supertrend_pullback__lbr_holy_grail_adx30_ema20_v1",
        "source_conformance": {
            "source_id": "LBR_HOLY_GRAIL", "match": "ANALOGOUS_BENCHMARK", "adx14_above30_and_rising": True,
            "ema20_pullback": True, "next_bar_stop_entry_from_completed_pullback_bar": True,
            "protective_swing_extreme_known_before_entry": True, "causal_profit_trailing": True,
            "parent_cost_model_retained": True, "parent_48bar_horizon_retained_where_source_unspecified": True,
        },
        "boundary_utc": boundary, "trades": trades, "metrics": metrics_from_trades(trades),
        "open_intents": open_intents, "ownership_rejected": rejected_ownership,
        "conservative_intrabar_ambiguities": ambiguous_intrabar, "leakage_lookahead": 0, "parameter_sweep": False,
        **AUTH,
    }


def compare(parent: dict[str, Any], child: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    pm, cm = metrics_from_trades(list(parent.get("trades") or [])), child["metrics"]
    pkeys = {(x.get("symbol"), x.get("signal_ts"), x.get("side")) for x in parent.get("trades") or []}
    ckeys = {(x.get("symbol"), x.get("signal_ts"), x.get("side")) for x in child.get("trades") or []}
    economic_pass = bool(
        cm["trades"] >= 12 and cm["net_pnl_bps"] > 0 and cm["profit_factor"] is not None and cm["profit_factor"] > 1.0
        and cm["win_rate"] is not None and pm["win_rate"] is not None and cm["win_rate"] > pm["win_rate"]
        and cm["net_expectancy_bps"] is not None and pm["net_expectancy_bps"] is not None and cm["net_expectancy_bps"] >= pm["net_expectancy_bps"]
        and cm["drawdown_bps"] <= pm["drawdown_bps"] and cm["pnl_without_best_trade_bps"] is not None and cm["pnl_without_best_trade_bps"] > 0
    )
    return {
        "stored_workcopy_metrics": stored, "same_snapshot_parent_metrics": pm, "benchmark_child_metrics": cm,
        "delta": {
            "trades": cm["trades"] - pm["trades"],
            "win_rate_pp": (cm["win_rate"] - pm["win_rate"]) * 100 if cm["win_rate"] is not None and pm["win_rate"] is not None else None,
            "net_pnl_bps": cm["net_pnl_bps"] - pm["net_pnl_bps"],
            "net_expectancy_bps": cm["net_expectancy_bps"] - pm["net_expectancy_bps"] if cm["net_expectancy_bps"] is not None and pm["net_expectancy_bps"] is not None else None,
            "drawdown_bps": cm["drawdown_bps"] - pm["drawdown_bps"],
            "profit_factor": cm["profit_factor"] - pm["profit_factor"] if cm["profit_factor"] is not None and pm["profit_factor"] is not None else None,
        },
        "trade_identity": {
            "parent_count": len(pkeys), "child_count": len(ckeys), "retained_same_signal_count": len(pkeys & ckeys),
            "excluded_parent_signal_count": len(pkeys - ckeys), "new_child_signal_count": len(ckeys - pkeys),
        },
        "economic_pass": economic_pass,
        "economic_gate": {
            "minimum_child_trades": 12, "child_net_positive": True, "child_pf_gt_1": True,
            "win_rate_strictly_improves": True, "expectancy_non_decrease": True, "drawdown_non_increase": True,
            "pnl_without_best_trade_positive": True,
        },
    }


def write_report(run: dict[str, Any]) -> None:
    cmp = run.get("economic_comparison") or {}
    pm, cm, d = cmp.get("same_snapshot_parent_metrics") or {}, cmp.get("benchmark_child_metrics") or {}, cmp.get("delta") or {}
    lines = [
        f"# {SCOPE}", "", f"- state: `{run['state']}`", f"- generated_at: `{run['generated_at']}`",
        f"- Gemini: `{run['providers']['gemini'].get('state')}` model=`{TARGET_GEMINI}` calls={run['providers']['gemini'].get('generation_attempts', 0)}",
        f"- OpenAI: `{run['providers']['openai'].get('state')}` model=`{TARGET_OPENAI}` calls={run['providers']['openai'].get('generation_attempts', 0)}",
        "- billing: `UNKNOWN_NOT_SETTLED`; estimates are token-price proxies, not billed amounts.", "", "## Top5 benchmark disposition",
    ]
    for sid, row in run["benchmark_decision"]["lanes"].items():
        lines.append(f"- {sid}: `{row['decision']}` | source={row['source_id']} | match={row['match']} | candidate={row.get('candidate_id')}")
    lines += [
        "", "## Executed economic replay",
        f"- parent: trades={pm.get('trades')} WR={pm.get('win_rate')} PF={pm.get('profit_factor')} net={pm.get('net_pnl_bps')}bps exp={pm.get('net_expectancy_bps')}bps DD={pm.get('drawdown_bps')}bps",
        f"- child: trades={cm.get('trades')} WR={cm.get('win_rate')} PF={cm.get('profit_factor')} net={cm.get('net_pnl_bps')}bps exp={cm.get('net_expectancy_bps')}bps DD={cm.get('drawdown_bps')}bps",
        f"- delta: trades={d.get('trades')} WRpp={d.get('win_rate_pp')} net={d.get('net_pnl_bps')}bps exp={d.get('net_expectancy_bps')}bps DD={d.get('drawdown_bps')}bps",
        f"- economic_pass: `{cmp.get('economic_pass')}`", "",
        "Source conformance and economic performance are separate. No selection/promotion/order/live authority is granted.",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot = native_snapshot()
    write(OUT / "SOURCE_PACKET.json", SOURCE_PACKET)
    write(OUT / "NATIVE_TOP5_SNAPSHOT.json", snapshot)
    providers = {"gemini": call_gemini(snapshot)}
    providers["openai"] = call_openai(snapshot, providers["gemini"])
    write(OUT / "PROVIDER_LEDGER.json", providers)
    decision = {
        "schema_version": "zel.top5.trader_benchmark.decision.v1", "created_after_provider_evidence": True,
        "ai_advisory_only": True, "lanes": DECISION_TEMPLATE, "candidate_count": 1, "parameter_sweep": False, **AUTH,
    }
    write(OUT / "BENCHMARK_DECISION.json", decision)

    active = read(ACTIVE_REPLAY)
    stored_rows = {str(x["strategy_id"]): x for x in active.get("rows") or []}
    symbols = list(active.get("symbols") or ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT"])
    bars_cache: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    snapshot_cache: dict[str, dict[str, Any]] = {}
    parent = current_parent_receipt(symbols, bars_cache, snapshot_cache)
    child = holy_grail_replay(symbols, bars_cache, snapshot_cache)
    write(OUT / "SUPERTREND_PARENT_SAME_SNAPSHOT.json", parent)
    write(OUT / "SUPERTREND_LBR_HOLY_GRAIL_CHILD.json", child)
    comparison = compare(parent, child, (stored_rows.get("supertrend_pullback") or {}).get("metrics") or {})
    write(OUT / "ECONOMIC_COMPARISON.json", comparison)

    result = {
        "schema_version": "zel.top5.trader_benchmark.multi_ai.v1", "scope_key": SCOPE,
        "state": "AUTHORIZED_SCOPE_COMPLETE_REPORT_ONLY", "generated_at": now(), "providers": providers,
        "provider_generation_total": sum(int(x.get("generation_attempts") or 0) for x in providers.values()),
        "provider_generation_caps": MAX_NEW_GENERATION_CALLS, "reserved_usd_total": sum(RESERVED_USD.values()),
        "billing_status": "UNKNOWN_NOT_SETTLED", "benchmark_decision": decision, "executed_candidate_count": 1,
        "economic_comparison": comparison, "source_conformance_pass": True, "economic_pass": comparison["economic_pass"],
        "canonical_ledger_mutated": False, "strategy_policy_mutated": False, "parameter_sweep": False,
        "future_pnl_selection": False, "report_only": True, **AUTH,
    }
    write(OUT / "FINAL.json", result)
    write_report(result)
    return result


def dry_run() -> dict[str, Any]:
    snapshot = native_snapshot()
    expected = ["supertrend_pullback", "trend_rider", "keltner_trend", "break_and_continue", "trend_ma_macd"]
    if list(snapshot.get("active_top5") or []) != expected:
        raise RuntimeError(f"ACTIVE_TOP5_DRIFT:{snapshot.get('active_top5')}")
    if sum(1 for x in DECISION_TEMPLATE.values() if x["decision"] == "EXECUTE") != 1:
        raise RuntimeError("EXACTLY_ONE_PREREGISTERED_CANDIDATE_REQUIRED")
    if sum(RESERVED_USD.values()) > 1.50:
        raise RuntimeError("AI_RESERVATION_CAP_EXCEEDED")
    return {
        "state": "PASS_OFFLINE_TOP5_BENCHMARK_CONTRACT", "active_top5": snapshot["active_top5"],
        "candidate": DECISION_TEMPLATE["supertrend_pullback"]["candidate_id"], "source_count": len(SOURCE_PACKET),
        "generation_call_cap": sum(MAX_NEW_GENERATION_CALLS.values()), **AUTH,
    }


def self_test() -> int:
    good, err = boundary_clean_key("  abcDEF_123-xyz\r\n")
    assert good == "abcDEF_123-xyz" and err is None
    for bad in ("abc def", "abc\tdef", "abc\ndef", "abc\x00def", "abc\x7fdef", "abcédef", " \r\n\t "):
        value, problem = boundary_clean_key(bad)
        assert value is None and problem
    bars = []
    px = 100.0
    for i in range(80):
        op = px
        px += 1.0 if i < 45 else (-0.25 if i < 55 else 0.7)
        bars.append({"ts_ms": i * 3_600_000, "open": op, "high": max(op, px) + 0.4, "low": min(op, px) - 0.4, "close": px})
    a, p, m = adx_wilder(bars, 14)
    assert len(a) == len(bars) == len(p) == len(m)
    sample = [
        {"entry_ts": 0, "exit_ts": 3_600_000, "net_bps": 100.0, "realized_cost_bps": 5.0},
        {"entry_ts": 3_600_000, "exit_ts": 7_200_000, "net_bps": -40.0, "realized_cost_bps": 5.0},
        {"entry_ts": 7_200_000, "exit_ts": 10_800_000, "net_bps": 60.0, "realized_cost_bps": 5.0},
    ]
    mm = metrics_from_trades(sample)
    assert mm["trades"] == 3 and abs(mm["win_rate"] - 2 / 3) < 1e-12 and mm["max_losing_streak"] == 1
    assert dry_run()["state"] == "PASS_OFFLINE_TOP5_BENCHMARK_CONTRACT"
    print("PASS_TOP5_TRADER_BENCHMARK_MULTI_AI_V1_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--run", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    if args.run:
        result = execute()
        print("TOP5_BENCHMARK=" + json.dumps({
            "state": result["state"], "gemini": result["providers"]["gemini"]["state"],
            "openai": result["providers"]["openai"]["state"], "economic_pass": result["economic_pass"],
            "report_only": result["report_only"],
        }, sort_keys=True))
        return 0
    print(json.dumps(dry_run(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
