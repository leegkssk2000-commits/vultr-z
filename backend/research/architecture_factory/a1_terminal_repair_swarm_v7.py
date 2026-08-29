#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_alpha_primitive_miner_v1 as miner
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as econ
from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as factory
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
V6_RECEIPT = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v6_latest.json"
DEFAULT_MODEL = "gpt-5-mini"
MAX_PLANS = 4
MENU_LIMIT = 24
COST_BPS = econ.COST_BPS

SUPPORTED_PRIMITIVES = {
    "P_HIGHVOL_MOM_LONG": "abs(ret1) >= 1.5 * retstd20 and ret1 > 0 and ema20 > ema50",
    "P_HIGHVOL_MOM_SHORT": "abs(ret1) >= 1.5 * retstd20 and ret1 < 0 and ema20 < ema50",
    "P_BREAKOUT50_LONG": "close > lag(hh50,1) and ema20 > ema50 and vol_ratio20 >= 1.1",
    "P_TREND_CONT_LONG": "ema20 > ema50 and ema50 > ema100 and ret1 > 0 and vol_ratio20 >= 1.0",
    "P_TREND_CONT_SHORT": "ema20 < ema50 and ema50 < ema100 and ret1 < 0 and vol_ratio20 >= 1.0",
    "P_TREND_PULL_LONG": "ema20 > ema50 and lag(close,1) <= lag(ema20,1) and close > ema20",
    "P_TREND_PULL_SHORT": "ema20 < ema50 and lag(close,1) >= lag(ema20,1) and close < ema20",
    "P_VOL_SHOCK_CONT_LONG": "vol_ratio20 >= 2.0 and ret1 > 0",
    "P_BREAKOUT20_LONG": "close > lag(hh20,1) and vol_ratio20 >= 1.2",
    "P_LONDONUS_BREAK_LONG": "hour() >= 6 and hour() < 18 and close > lag(hh20,1) and vol_ratio20 >= 1.2",
}

SHARED_FEATURES = [
    {"name": "ret1", "formula": "ret(1)"},
    {"name": "retstd20", "formula": "std(ret1,20)"},
    {"name": "ema20", "formula": "ema(close,20)"},
    {"name": "ema50", "formula": "ema(close,50)"},
    {"name": "ema100", "formula": "ema(close,100)"},
    {"name": "vol_ratio20", "formula": "vol_ratio(20)"},
    {"name": "hh20", "formula": "highest(high,20)"},
    {"name": "hh50", "formula": "highest(high,50)"},
]

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plans": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_PLANS,
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "maxLength": 100},
                    "primitive_keys": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 3,
                        "items": {"type": "string", "maxLength": 120},
                    },
                    "combine_mode": {"type": "string", "enum": ["SINGLE", "ANY", "ALL", "MAJORITY"]},
                    "economic_rationale": {"type": "string", "maxLength": 260},
                    "falsification": {"type": "string", "maxLength": 260},
                },
                "required": ["candidate_id", "primitive_keys", "combine_mode", "economic_rationale", "falsification"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["plans"],
    "additionalProperties": False,
}


def _side(primitive_id: str) -> str:
    if primitive_id.endswith("_LONG"):
        return "long"
    if primitive_id.endswith("_SHORT"):
        return "short"
    raise ValueError(f"PRIMITIVE_SIDE_UNKNOWN:{primitive_id}")


def _menu_row(row: Mapping[str, Any]) -> dict[str, Any]:
    pid = str(row.get("primitive_id") or "")
    interval = str(row.get("interval") or "")
    horizon = int(row.get("horizon_bars") or 0)
    return {
        "primitive_key": f"{pid}|{interval}|{horizon}",
        "primitive_id": pid,
        "side": _side(pid),
        "interval": interval,
        "horizon_bars": horizon,
        "events": int(row.get("events") or 0),
        "net_expectancy_bps": row.get("net_expectancy_bps"),
        "profit_factor": row.get("profit_factor"),
        "win_rate": row.get("win_rate"),
        "drawdown_bps": row.get("drawdown_bps"),
        "net_bps_per_calendar_day": row.get("net_bps_per_calendar_day"),
        "cost_bps_per_trade": row.get("cost_bps_per_trade"),
    }


def _build_menu(mined: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for raw in mined.get("usable") or []:
        if not isinstance(raw, Mapping):
            continue
        pid = str(raw.get("primitive_id") or "")
        if pid not in SUPPORTED_PRIMITIVES or str(raw.get("interval") or "") != "4h":
            continue
        row = _menu_row(raw)
        key = row["primitive_key"]
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    rows.sort(key=lambda x: (-(float(x.get("profit_factor") or 0.0)), -(int(x.get("events") or 0)), -(float(x.get("net_expectancy_bps") or 0.0))))
    return rows[:MENU_LIMIT]


def _v6_context() -> dict[str, Any]:
    if not V6_RECEIPT.is_file():
        return {"available": False}
    try:
        r = json.loads(V6_RECEIPT.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}:{str(exc)[:160]}"}
    dev = r.get("development_economics") if isinstance(r.get("development_economics"), Mapping) else {}
    return {
        "available": True,
        "ledger_done_count": int(r.get("ledger_done_count") or 0),
        "terminal_count": int(r.get("terminal_count") or 0),
        "v6_machine_replayable_count": int(r.get("machine_replayable_count") or 0),
        "v6_economic_pass_count": int(r.get("development_economic_pass_count") or 0),
        "v6_spec_reject_count": int(dev.get("spec_reject_count") or 0),
        "v6_receipt_sha256": r.get("receipt_sha256"),
    }


def _planner_prompt(menu: list[dict[str, Any]], context: Mapping[str, Any]) -> str:
    return (
        "You are the economic plan selector. The free-form DSL path failed, so you are NOT allowed to write formulas, thresholds, exits, or new indicators. "
        "Choose only exact primitive_keys from MENU. The compiler will copy fixed formulas and horizons verbatim. "
        "Return up to 4 plans. Include at least 2 SINGLE plans when possible; at most 2 composite plans. "
        "For a composite, every primitive_key MUST share identical side, interval, and horizon_bars. "
        "SINGLE requires exactly one key. MAJORITY requires exactly three keys. ANY/ALL require two or three keys. "
        "Optimize for cost-adjusted economic robustness: PF, event count, net expectancy, calendar-day net, and lower drawdown; do not simply maximize one metric. "
        f"All menu economics already include fixed round-trip cost={COST_BPS} bps and are development-only, not promotion evidence. "
        "No parameter invention and no outcome-conditioned threshold changes are permitted. JSON only.\n"
        + "CONTEXT=" + factory.canonical(context) + "\nMENU=" + factory.canonical(menu)
    )


def _extract_usage(payload: Mapping[str, Any]) -> dict[str, int]:
    raw = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    out = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = raw.get(key)
        if isinstance(value, (int, float)):
            out[key] = int(value)
    return out


def _call_planner(prompt: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    if not key:
        raise RuntimeError("OPENAI_API_KEY_MISSING")
    body = {
        "model": model,
        "store": False,
        "instructions": "Return only the constrained economic plan JSON. Never write executable formulas or prose outside JSON.",
        "input": prompt,
        "max_output_tokens": 2200,
        "reasoning": {"effort": "minimal"},
        "text": {"format": {"type": "json_schema", "name": "a1_v7_constrained_economic_planner", "strict": True, "schema": PLAN_SCHEMA}},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=factory.canonical(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        raise RuntimeError(f"OPENAI_V7_HTTP_{exc.code}:{detail}") from exc
    if str(payload.get("status") or "").lower() == "incomplete":
        reason = ((payload.get("incomplete_details") or {}).get("reason") if isinstance(payload.get("incomplete_details"), Mapping) else "unknown")
        raise RuntimeError(f"OPENAI_V7_INCOMPLETE:{reason}")
    text = factory.extract_openai_text(payload)
    parsed = json.loads(text)
    lineage = {
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "model": model,
        "response_status": payload.get("status"),
        **_extract_usage(payload),
    }
    return model, parsed, lineage


def _validate_plans(raw: Mapping[str, Any], menu: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key = {str(x["primitive_key"]): x for x in menu}
    accepted = []
    rejected = []
    seen = set()
    for idx, plan in enumerate(raw.get("plans") or []):
        if not isinstance(plan, Mapping):
            rejected.append({"index": idx, "reason": "PLAN_NOT_OBJECT"}); continue
        keys = [str(x) for x in (plan.get("primitive_keys") or [])]
        mode = str(plan.get("combine_mode") or "")
        cid = str(plan.get("candidate_id") or f"v7_plan_{idx+1}")
        reason = None
        if not keys or any(k not in by_key for k in keys): reason = "KEY_NOT_IN_MENU"
        elif len(set(keys)) != len(keys): reason = "DUPLICATE_KEYS"
        elif mode == "SINGLE" and len(keys) != 1: reason = "SINGLE_REQUIRES_ONE_KEY"
        elif mode == "MAJORITY" and len(keys) != 3: reason = "MAJORITY_REQUIRES_THREE_KEYS"
        elif mode in {"ANY", "ALL"} and len(keys) not in {2, 3}: reason = "COMPOSITE_REQUIRES_TWO_OR_THREE_KEYS"
        elif mode not in {"SINGLE", "ANY", "ALL", "MAJORITY"}: reason = "COMBINE_MODE_INVALID"
        else:
            rows = [by_key[k] for k in keys]
            signatures = {(x["side"], x["interval"], x["horizon_bars"]) for x in rows}
            if len(signatures) != 1: reason = "COMPOSITE_SIGNATURE_MISMATCH"
        fp = tuple(sorted(keys)) + (mode,)
        if reason is None and fp in seen: reason = "DUPLICATE_PLAN"
        if reason:
            rejected.append({"candidate_id": cid, "primitive_keys": keys, "combine_mode": mode, "reason": reason}); continue
        seen.add(fp)
        accepted.append({
            "candidate_id": re.sub(r"[^A-Za-z0-9_.-]+", "_", cid)[:100],
            "primitive_keys": keys,
            "combine_mode": mode,
            "economic_rationale": str(plan.get("economic_rationale") or "")[:260],
            "falsification": str(plan.get("falsification") or "")[:260],
        })
    return accepted, rejected


def _entry_from_signals(names: list[str], mode: str) -> str:
    if mode == "SINGLE":
        return f"{names[0]} > 0.5"
    if mode == "ANY":
        return " or ".join(f"{x} > 0.5" for x in names)
    if mode == "ALL":
        return " and ".join(f"{x} > 0.5" for x in names)
    if mode == "MAJORITY":
        return " + ".join(names) + " >= 2.0"
    raise ValueError(f"COMBINE_MODE_INVALID:{mode}")


def _compile_plan(plan: Mapping[str, Any], menu: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {str(x["primitive_key"]): x for x in menu}
    rows = [by_key[str(k)] for k in plan.get("primitive_keys") or []]
    if not rows:
        raise ValueError("PLAN_EMPTY")
    side = str(rows[0]["side"]); interval = str(rows[0]["interval"]); horizon = int(rows[0]["horizon_bars"])
    features = [dict(x) for x in SHARED_FEATURES]
    signal_names = []
    for idx, row in enumerate(rows, 1):
        pid = str(row["primitive_id"])
        formula = SUPPORTED_PRIMITIVES.get(pid)
        if not formula:
            raise ValueError(f"PRIMITIVE_COMPILER_MISSING:{pid}")
        name = f"primitive_signal_{idx}"
        features.append({"name": name, "formula": formula})
        signal_names.append(name)
    mode = str(plan.get("combine_mode") or "")
    spec = {
        "bar_interval": interval,
        "features": features,
        "entry_rule": _entry_from_signals(signal_names, mode),
        "side_rule": side,
        "exit_rule": "time_stop",
        "max_hold_bars": horizon + 1,
        "entry_timing": "next_bar_open",
        "cost_model": f"fixed_round_trip_{COST_BPS:g}bps",
        "development_data_rule": "strictly_pre_GEN1_boundary; fixed primitive formulas; non-overlap executable replay",
        "parameter_provenance": "AI selects only frozen primitive keys; compiler copies primitive thresholds and horizon without tuning; max_hold=horizon+1 matches next-open to h-bar-close convention",
    }
    return {
        "candidate_id": str(plan.get("candidate_id") or "v7_plan"),
        "strategy_id": "NEW",
        "provider": "openai_constrained_planner_v7",
        "mode": "NEW_ARCHITECTURE",
        "required_sources": ["ohlcv", "volume"],
        "primitive_keys": [str(x) for x in plan.get("primitive_keys") or []],
        "combine_mode": mode,
        "economic_rationale": plan.get("economic_rationale"),
        "falsification": plan.get("falsification"),
        "executable_spec": spec,
        "machine_replayable": True,
        "compiler": "FROZEN_PRIMITIVE_DSL_COMPILER_V1",
        "selection_authority": False,
        "promotion_authority": False,
    }


def _parity_candidates(menu: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for idx, row in enumerate(menu[:limit], 1):
        plan = {
            "candidate_id": f"v7_parity_{idx}_{row['primitive_id']}_{row['horizon_bars']}",
            "primitive_keys": [row["primitive_key"]],
            "combine_mode": "SINGLE",
            "economic_rationale": "deterministic compiler parity replay",
            "falsification": "fails if executable non-overlap replay does not retain net positive economics after 14bps",
        }
        item = _compile_plan(plan, menu)
        item["provider"] = "deterministic_parity_v7"
        out.append(item)
    return out


def _economic_summary(dev: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in dev.get("rows") or []:
        if not isinstance(row, Mapping): continue
        m = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
        rows.append({
            "candidate_id": row.get("candidate_id"), "state": row.get("state"), "error": row.get("error"),
            "trades": m.get("trades"), "net_expectancy_bps": m.get("net_expectancy_bps"), "profit_factor": m.get("profit_factor"),
            "net_pnl_bps": m.get("net_pnl_bps"), "drawdown_bps": m.get("drawdown_bps"), "net_bps_per_calendar_day": m.get("net_bps_per_calendar_day"),
        })
    return rows


def run(output: Path) -> dict[str, Any]:
    mined = miner.mine()
    menu = _build_menu(mined)
    if not menu:
        raise RuntimeError("NO_SUPPORTED_COST_POSITIVE_4H_PRIMITIVES")

    parity_candidates = _parity_candidates(menu, 5)
    parity_dev = econ.evaluate_queue(parity_candidates)

    context = _v6_context()
    prompt = _planner_prompt(menu, context)
    model, raw, lineage = _call_planner(prompt)
    accepted, rejected = _validate_plans(raw, menu)
    compiled = [_compile_plan(plan, menu) for plan in accepted]
    ai_dev = econ.evaluate_queue(compiled) if compiled else {
        "economic_pass_count": 0, "spec_reject_count": 0, "candidate_count": 0, "rows": [], "passes": []
    }

    parity_rejects = int(parity_dev.get("spec_reject_count") or 0)
    ai_rejects = int(ai_dev.get("spec_reject_count") or 0)
    result = {
        "schema_version": "zel.a1_terminal_repair_swarm.v7",
        "objective": "CLOSE_AI_TO_EXECUTABLE_ECONOMICS_GAP",
        "source_v6": context,
        "cost_bps_per_trade": COST_BPS,
        "primitive_menu_count": len(menu),
        "primitive_menu": menu,
        "compiler": {
            "state": "FROZEN_PRIMITIVE_DSL_COMPILER_V1",
            "free_form_dsl_from_ai": False,
            "ai_can_invent_thresholds": False,
            "ai_can_invent_exit_logic": False,
            "ai_selects_only_exact_primitive_keys": True,
            "formula_source": "a1_alpha_primitive_miner_v1 fixed definitions",
            "spec_reject_closed": parity_rejects == 0 and ai_rejects == 0,
        },
        "compiler_parity": {
            "candidate_count": len(parity_candidates),
            "development_economics": parity_dev,
            "summary": _economic_summary(parity_dev),
        },
        "ai_planner": {
            "provider": "openai",
            "model": model,
            "strict_schema": True,
            "paid_request_count": 1,
            "lineage": lineage,
            "raw_plan_count": len(raw.get("plans") or []) if isinstance(raw, Mapping) else 0,
            "accepted_plan_count": len(accepted),
            "rejected_plan_count": len(rejected),
            "rejected_plans": rejected,
            "accepted_plans": accepted,
        },
        "ai_candidates": compiled,
        "development_economics": ai_dev,
        "development_economic_pass_count": int(ai_dev.get("economic_pass_count") or 0),
        "compiler_parity_pass_count": int(parity_dev.get("economic_pass_count") or 0),
        "economic_summary": _economic_summary(ai_dev),
        "economic_truth": {
            "development_only": True,
            "prospective": False,
            "promotion_evidence": False,
            "success_requires": "deterministic executable replay Net>0, PF>1, >=12 trades, calendar-day net>0 after fixed 14bps",
            "ai_prose_is_not_success": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "next": "TEMPORAL_OOS_OR_PROSPECTIVE_VALIDATION" if int(ai_dev.get("economic_pass_count") or 0) > 0 else "ECONOMIC_ARCHITECTURE_FAIL_OR_COMPILER_PARITY_DIAGNOSIS",
    }
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def _grammar_self_test(spec: Mapping[str, Any]) -> None:
    rows = []
    for i in range(220):
        px = 100.0 + i * 0.05
        rows.append({"ts": i * 14_400_000, "open": px, "high": px * 1.002, "low": px * 0.998, "close": px * 1.0005, "volume": 1000.0 + (i % 7) * 20.0})
    features: dict[str, list[float | None]] = {}
    for f in spec.get("features") or []:
        name = str(f.get("name") or ""); formula = econ._feature_formula(str(f.get("formula") or ""))
        features[name] = [0.0] * len(rows)
        econ.Expr(rows, features).validate(formula)
    eng = econ.Expr(rows, features)
    eng.validate(str(spec.get("entry_rule") or ""))
    econ._validate_side(str(spec.get("side_rule") or ""), eng)


def self_test() -> int:
    fake_menu = [
        {"primitive_key": "P_HIGHVOL_MOM_LONG|4h|12", "primitive_id": "P_HIGHVOL_MOM_LONG", "side": "long", "interval": "4h", "horizon_bars": 12},
        {"primitive_key": "P_TREND_CONT_LONG|4h|12", "primitive_id": "P_TREND_CONT_LONG", "side": "long", "interval": "4h", "horizon_bars": 12},
        {"primitive_key": "P_BREAKOUT20_LONG|4h|12", "primitive_id": "P_BREAKOUT20_LONG", "side": "long", "interval": "4h", "horizon_bars": 12},
    ]
    raw = {"plans": [{"candidate_id": "x", "primitive_keys": [x["primitive_key"] for x in fake_menu], "combine_mode": "MAJORITY", "economic_rationale": "r", "falsification": "f"}]}
    accepted, rejected = _validate_plans(raw, fake_menu)
    assert len(accepted) == 1 and not rejected
    compiled = _compile_plan(accepted[0], fake_menu)
    assert compiled["executable_spec"]["max_hold_bars"] == 13
    assert compiled["executable_spec"]["side_rule"] == "long"
    assert "primitive_id" not in compiled["executable_spec"]["entry_rule"]
    _grammar_self_test(compiled["executable_spec"])
    bad = {"plans": [{"candidate_id": "bad", "primitive_keys": [fake_menu[0]["primitive_key"]], "combine_mode": "MAJORITY", "economic_rationale": "r", "falsification": "f"}]}
    a2, r2 = _validate_plans(bad, fake_menu)
    assert not a2 and r2[0]["reason"] == "MAJORITY_REQUIRES_THREE_KEYS"
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V7_CONSTRAINED_ECONOMIC_PLANNER_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_terminal_repair_swarm_v7_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "menu": r["primitive_menu_count"],
        "compiler_closed": r["compiler"]["spec_reject_closed"],
        "parity_pass": r["compiler_parity_pass_count"],
        "ai_plans": r["ai_planner"]["accepted_plan_count"],
        "ai_dev_pass": r["development_economic_pass_count"],
        "economic_summary": r["economic_summary"],
        "next": r["next"],
        "receipt": r["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
