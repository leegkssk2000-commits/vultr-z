from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
V2_PATH = ROOT / "backend/tools/r7a4d_strategy11_gemini_direct_video_v2.py"
VERSION = "R7A4D_STRATEGY11_GEMINI_22_SECOND_CAUSAL_V1"
ALLOWED = {
    "TIME_STOP_24", "TIME_STOP_48", "PARTIAL075_30", "PARTIAL100_30",
    "STOP085", "FEATURE_GATE", "SYMBOL_WHITELIST", "REGIME_WHITELIST", "NO_CHANGE"
}


def load_v2() -> Any:
    name = "r7a4d_strategy11_gemini_direct_video_v2_for_second_causal"
    spec = importlib.util.spec_from_file_location(name, V2_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("V2_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v2 = load_v2()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def parse_response(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if isinstance(value, list):
        value = {"reviews": value}
    if not isinstance(value, dict):
        raise RuntimeError("GEMINI_RESPONSE_NOT_OBJECT")
    return value


def compact_row(row: Mapping[str, Any]) -> dict[str, Any]:
    variants = []
    for item in row.get("variants", []):
        if not isinstance(item, Mapping):
            continue
        loss = item.get("loss_metrics", {}) if isinstance(item.get("loss_metrics"), Mapping) else {}
        stress = item.get("stress_2x_p95_plus_one", {}) if isinstance(item.get("stress_2x_p95_plus_one"), Mapping) else {}
        stress_loss = stress.get("loss_metrics", {}) if isinstance(stress.get("loss_metrics"), Mapping) else {}
        check = item.get("adaptive_research_check", {}) if isinstance(item.get("adaptive_research_check"), Mapping) else {}
        variants.append({
            "variant_id": item.get("variant_id"), "trades": item.get("trade_count"),
            "wr": item.get("win_rate_pct"), "net": item.get("net_return_pct_sum"),
            "pf": item.get("net_profit_factor"), "payoff": item.get("payoff_ratio"),
            "dd": item.get("max_drawdown_pct"), "avg_loss_R": loss.get("avg_loss_R"),
            "worst_R": loss.get("worst_net_loss_R"), "stress_worst_R": stress_loss.get("worst_net_loss_R"),
            "positive_windows_pct": item.get("positive_fresh_windows_pct"),
            "research_pass": check.get("research_pass"),
        })
    return {
        "strategy_id": row.get("strategy_id"), "classification": row.get("classification"),
        "tested_candidate_ids": row.get("tested_candidate_ids", []), "variants": variants,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", required=True)
    ap.add_argument("--profiles", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    final = load(Path(args.final))
    registry = load(Path(args.registry))
    profiles_dir = Path(args.profiles)
    rows = [compact_row(row) for row in final.get("rows", []) if isinstance(row, Mapping)]
    profiles = {}
    for path in sorted(profiles_dir.glob("*.json")):
        payload = load(path)
        alias = payload.get("strategy_alias") or path.stem
        profiles[str(alias)] = payload
    sources = [dict(row) for row in registry.get("sources", []) if isinstance(row, Mapping)]
    channels = {str(row.get("channel")) for row in sources if row.get("channel")}
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    if len(sources) < 4 or len(channels) < 4:
        raise RuntimeError("SOURCE_DIVERSITY_LOW")
    schema = {
        "status": "PASS|HOLD", "reviews": [{
            "strategy_id": "...", "decision": "NEW_AXIS|W1_CAUSAL_WAIT",
            "new_single_cause_axis": "TIME_STOP_24|TIME_STOP_48|PARTIAL075_30|PARTIAL100_30|STOP085|FEATURE_GATE|SYMBOL_WHITELIST|REGIME_WHITELIST|NO_CHANGE",
            "why_distinct_from_BE_and_TRAIL": "...", "numeric_evidence": ["..."],
            "bounded_values": ["..."], "winner_contamination_risk": "LOW|MEDIUM|HIGH",
            "falsification_test": "...", "priority": 1
        }], "active_new_axis_queue": [{"strategy_id": "...", "axis": "...", "priority": 1}]
    }
    prompt = (
        "You are the second causal-review layer for 22 quantitative strategies. The first review tested BE075 and trailing and all 22 produced no L085 candidate. "
        "Do not repeat BE or trailing. Use the attached public videos only as external hypotheses and the supplied anonymized numeric evidence as the internal authority. "
        "For every strategy choose either one genuinely distinct single-cause axis from the allowed list or W1_CAUSAL_WAIT. "
        "FEATURE_GATE/SYMBOL_WHITELIST/REGIME_WHITELIST require explicit internal numeric evidence; otherwise choose W1_CAUSAL_WAIT. "
        "Select at most three strategies globally for active_new_axis_queue. No performance claim, no multi-axis change, no parameter mining. Return strict JSON only.\n\n"
        f"ROWS={json.dumps(rows, ensure_ascii=False, sort_keys=True)}\n"
        f"PROFILES={json.dumps(profiles, ensure_ascii=False, sort_keys=True)[:180000]}\n"
        f"SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )
    models = v2.list_models(key)
    model, text = v2.call_direct_video(key, models, prompt, sources)
    response = parse_response(text)
    reviews = []
    seen = set()
    for row in response.get("reviews", []):
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("strategy_id") or "")
        axis = str(row.get("new_single_cause_axis") or "NO_CHANGE")
        if sid not in {x["strategy_id"] for x in rows} or axis not in ALLOWED or sid in seen:
            continue
        seen.add(sid)
        reviews.append(dict(row))
    by_sid = {str(row.get("strategy_id")): row for row in reviews}
    queue = []
    for item in response.get("active_new_axis_queue", []):
        if not isinstance(item, Mapping):
            continue
        sid = str(item.get("strategy_id") or "")
        axis = str(item.get("axis") or "")
        review = by_sid.get(sid)
        if review is None or axis not in ALLOWED - {"NO_CHANGE"} or review.get("decision") != "NEW_AXIS":
            continue
        queue.append({"strategy_id": sid, "axis": axis, "priority": int(item.get("priority") or 999)})
    queue = sorted(queue, key=lambda x: x["priority"])[:3]
    result = {
        "schema_version": "1.0", "version": VERSION, "state": "PASS",
        "strategy_count": len(rows), "review_count": len(reviews),
        "active_new_axis_queue": queue, "active_candidate_limit": 3,
        "w1_causal_wait_count": sum(1 for row in reviews if row.get("decision") != "NEW_AXIS"),
        "GEMINI_USED": True, "free_only": True, "actual_model": model,
        "public_urls": [row["url"] for row in sources], "independent_channel_count": len(channels),
        "input_sha256": sha({"rows": rows, "profiles": profiles}),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "reviews": reviews, "promotion_authority": False, "execution_allowed": False,
        "canonical_mutated": False, "registry_mutated": False, "protected_mutations": 0,
        "order_authority": "BLOCKED", "blockers": [],
        "next": "CREATE_MAX3_ISOLATED_NEW_AXIS_REPLAY" if queue else "W1_CAUSAL_WAIT_ALL22",
    }
    dump(out / "summary.json", result)
    dump(out / "raw_response.json", response)
    print(json.dumps({"state": result["state"], "queue": queue, "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
