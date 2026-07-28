from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
V31_PATH = ROOT / "backend/tools/r7a4d_strategy11_gemini_active_research_v3_1.py"
REPAIR_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_repair_v1.py"
VERSION = "R7A4D_STRATEGY11_GEMINI_22_PREWORK_V1"
PRIMARY = {"alpha_combo", "turtle_trend", "ema_ribbon_scalp"}
STRATEGIES = (
    "anchor_vwap_trend", "bb_revert", "break_and_continue", "fvg_revert",
    "grid_rebalance", "keltner_trend", "liquidity_sweep", "mfi_rsi_div",
    "obv_trend", "pivot_reversal", "range_fade", "rbreaker_like",
    "rsi_swing_fail", "scalp_snap", "session_bias", "squeeze_break",
    "sr_levels", "supertrend_pullback", "trend_ma_macd", "trend_rider",
    "vol_spike_fade", "vwap_revert",
)
CANDIDATE_LIBRARY = {
    "BE_075": {"axis": "BREAKEVEN", "description": "move stop to cost-aware breakeven after +0.75R"},
    "PARTIAL30_R075": {"axis": "PARTIAL30", "description": "realize 30% at +0.75R and protect remainder"},
    "TRAIL_R100_ATR150": {"axis": "MFE_TRAILING", "description": "activate 1.5 ATR trailing only after +1.0R"},
    "TIME_STOP_24": {"axis": "TIME_STOP", "description": "close at next open after 24 bars"},
    "TIME_STOP_48": {"axis": "TIME_STOP", "description": "close at next open after 48 bars"},
}


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v31 = load_module("s11_gemini_22_v31", V31_PATH)
repair = load_module("s11_gemini_22_repair", REPAIR_PATH)
p = repair.p
exact = repair.exact
base = repair.base


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def registry_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = strict_json(path)
    rows = [dict(row) for row in payload.get("entries", []) if isinstance(row, Mapping)]
    result = {str(row.get("strategy_id")): row for row in rows}
    if set(STRATEGIES) - set(result):
        raise RuntimeError("REGISTRY_22_INCOMPLETE")
    return result


def find_summary(evidence_root: Path, strategy_id: str) -> Path:
    matches = sorted(evidence_root.glob(f"batch-*/{strategy_id}/summary.json"))
    if len(matches) != 1:
        raise RuntimeError(f"EVIDENCE_SUMMARY_MATCH:{strategy_id}:{len(matches)}")
    return matches[0]


def recursive_strategy_rows(value: Any, strategy_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        if str(value.get("strategy_id") or "") == strategy_id:
            rows.append(dict(value))
        for item in value.values():
            rows.extend(recursive_strategy_rows(item, strategy_id))
    elif isinstance(value, list):
        for item in value:
            rows.extend(recursive_strategy_rows(item, strategy_id))
    return rows


def source_structure(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    identifiers: set[str] = set()
    calls: set[str] = set()
    comparisons: list[str] = []
    return_actions: set[str] = set()
    numeric_constants: list[float] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
        elif isinstance(node, ast.Compare):
            comparisons.extend(type(op).__name__ for op in node.ops)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            value = float(node.value)
            if math.isfinite(value) and abs(value) <= 1_000_000:
                numeric_constants.append(value)
        elif isinstance(node, ast.Dict):
            keys = [key.value if isinstance(key, ast.Constant) else None for key in node.keys]
            if "action" in keys:
                index = keys.index("action")
                value = node.values[index]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return_actions.add(value.value)
    indicator_tokens = sorted(
        token for token in identifiers
        if any(part in token.lower() for part in (
            "ema", "sma", "rsi", "mfi", "macd", "atr", "vwap", "boll", "keltner",
            "volume", "obv", "pivot", "support", "resistance", "trend", "squeeze",
            "break", "range", "liquidity", "supertrend", "fvg",
        ))
    )
    fingerprint_tokens = sorted(set(indicator_tokens) | set(calls) | set(comparisons) | set(return_actions))
    return {
        "source_sha256": sha256(path),
        "line_count": len(source.splitlines()),
        "function_count": sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree)),
        "class_count": sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree)),
        "indicator_tokens": indicator_tokens[:80],
        "call_tokens": sorted(calls)[:80],
        "comparison_ops": sorted(set(comparisons)),
        "return_actions": sorted(return_actions),
        "numeric_constant_count": len(numeric_constants),
        "numeric_constant_sample": sorted(set(numeric_constants))[:40],
        "fingerprint_tokens": fingerprint_tokens,
        "raw_code_sent": False,
    }


def duplicate_clusters(structures: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    parent = {sid: sid for sid in structures}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    similarities: list[dict[str, Any]] = []
    ids = sorted(structures)
    for i, left in enumerate(ids):
        a = set(structures[left].get("fingerprint_tokens", []))
        for right in ids[i + 1:]:
            b = set(structures[right].get("fingerprint_tokens", []))
            score = len(a & b) / max(1, len(a | b))
            if score >= 0.70:
                similarities.append({"left": left, "right": right, "jaccard": score})
            if score > 0.85:
                union(left, right)
    groups: dict[str, list[str]] = {}
    for sid in ids:
        groups.setdefault(find(sid), []).append(sid)
    clusters = [rows for rows in groups.values() if len(rows) > 1]
    return {"threshold": 0.85, "clusters": clusters, "similar_pairs": similarities}


def local_candidates(profile: Mapping[str, Any]) -> list[str]:
    cluster = profile.get("trade_cluster") if isinstance(profile.get("trade_cluster"), Mapping) else {}
    favorable = sum(int(value or 0) for value in (cluster.get("favorable_then_loss") or {}).values())
    bars_p90 = metric(cluster.get("bars_held_p90"))
    choices: list[str] = []
    if favorable > 0:
        choices.extend(["BE_075", "TRAIL_R100_ATR150"])
    if bars_p90 >= 24:
        choices.extend(["TIME_STOP_24", "TIME_STOP_48"])
    choices.extend(["PARTIAL30_R075", "TRAIL_R100_ATR150", "TIME_STOP_48"])
    result: list[str] = []
    for item in choices:
        if item not in result:
            result.append(item)
    return result[:2]


def group_prompt(rows: Sequence[Mapping[str, Any]], source_review: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "strategies": [{
            "strategy_alias": "S01",
            "classification": "EXIT_LEAK_REPAIRABLE|STOP_COST_REPAIRABLE|LOW_SAMPLE_WAIT|NO_EVIDENCE_TO_REPAIR|STRUCTURAL_REVIEW",
            "candidate_ids": ["EXACTLY_TWO_FROM_LIBRARY"],
            "evidence": ["metric or structural evidence"],
            "expected_effect": {"Net": "...", "PF": "...", "payoff": "...", "DD": "...", "trade_retention": "..."},
            "winner_contamination_risk": "LOW|MEDIUM|HIGH",
            "falsification_test": "...",
            "priority": 1,
        }],
    }
    return (
        "You are a quantitative strategy pre-repair planner. Compare every anonymized strategy profile in this batch. "
        "Raw source code is not provided; use only local AST structure, immutable evidence metrics, trade excursion clusters, and prior diagnosis. "
        "Select exactly two distinct candidate IDs per strategy from the supplied bounded library. Do not invent parameters, do not combine axes, do not claim improvement, and do not drop low-sample strategies. "
        "The old F1/F2/F3 replay is exploratory only; W1 remains the independent confirmation. Return strict JSON only.\n\n"
        f"SOURCE_REVIEW={json.dumps(v31.v3.sanitize(source_review), ensure_ascii=False, sort_keys=True)}\n"
        f"CANDIDATE_LIBRARY={json.dumps(CANDIDATE_LIBRARY, ensure_ascii=False, sort_keys=True)}\n"
        f"PROFILES={json.dumps(v31.v3.sanitize(list(rows)), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def red_team_prompt(rows: Sequence[Mapping[str, Any]], clusters: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "rows": [{
            "strategy_alias": "S01",
            "approved_candidate_ids": ["two bounded IDs"],
            "priority": 1,
            "reason": "...",
            "required_checks": ["A/B parity", "-0.85R discovery", "2x cost/P95 funding/PLUS_ONE_BAR", "W1 confirmation"],
        }],
        "global_risks": ["..."],
    }
    return (
        "You are the independent red-team for a 22-strategy exploratory replay queue. Preserve all 22 strategies. "
        "Reject only invalid or duplicate candidate IDs, not strategies. Ensure each strategy has two distinct bounded candidates and account for near-duplicate structure clusters. "
        "No candidate is promotion authority. Rank execution priority, with no more than three active strategies at once. Return strict JSON only.\n\n"
        f"PROPOSED_ROWS={json.dumps(v31.v3.sanitize(list(rows)), ensure_ascii=False, sort_keys=True)}\n"
        f"STRUCTURAL_CLUSTERS={json.dumps(v31.v3.sanitize(clusters), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def analyze(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    registry = registry_map(Path(args.registry).resolve())
    prediagnosis = strict_json(Path(args.prediagnosis).resolve())
    source_review = strict_json(Path(args.source_review).resolve())
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")

    aliases = {sid: f"S{index:02d}" for index, sid in enumerate(STRATEGIES, start=1)}
    structures: dict[str, dict[str, Any]] = {}
    profiles: dict[str, dict[str, Any]] = {}
    for sid in STRATEGIES:
        row = registry[sid]
        source_path = ROOT / str(row["canonical_engine"]["implementation_path"])
        structure = source_structure(source_path)
        structures[sid] = structure
        summary_path = find_summary(evidence_root, sid)
        summary = strict_json(summary_path)
        strategy_root = summary_path.parent
        trades = v31.v3.collect_trades([strategy_root], sid)
        cluster = v31.v3.trade_cluster(trades)
        diagnosis_rows = recursive_strategy_rows(prediagnosis, sid)
        profile = {
            "strategy_alias": aliases[sid],
            "strategy_id_local_only": sid,
            "candidate": v31.v3.sanitize(summary.get("candidate", {})),
            "surgery": v31.v3.sanitize(summary.get("surgery", {})),
            "baseline_metrics": v31.v3.sanitize({
                key: summary.get(key)
                for key in (
                    "state", "classification", "trade_count", "win_rate_pct", "net_return_pct_sum",
                    "net_profit_factor", "payoff_ratio", "max_drawdown_pct", "positive_fresh_windows_pct",
                )
            }),
            "trade_cluster": cluster,
            "source_structure": {key: value for key, value in structure.items() if key != "source_sha256"},
            "prediagnosis": v31.v3.sanitize(diagnosis_rows[:4]),
            "local_candidate_fallback": local_candidates({"trade_cluster": cluster}),
            "raw_code_sent": False,
        }
        profiles[sid] = profile
        atomic_json(out / "profiles" / f"{aliases[sid]}.json", profile)

    clusters = duplicate_clusters(structures)
    atomic_json(out / "structural_clusters.json", clusters)
    models = v31.v3.v2.list_models(key)
    if not models:
        raise RuntimeError("NO_FREE_FLASH_MODEL")
    call_audit: list[dict[str, Any]] = []
    proposed: list[dict[str, Any]] = []
    grouped = [STRATEGIES[0:6], STRATEGIES[6:12], STRATEGIES[12:17], STRATEGIES[17:22]]
    for batch_index, strategy_ids in enumerate(grouped, start=1):
        prompt_rows = [profiles[sid] for sid in strategy_ids]
        prompt = group_prompt(prompt_rows, source_review)
        model, text = v31.v3.call_gemini(key, models, [{"text": prompt}], max_tokens=16384)
        response = v31.strict_object_response(text)
        atomic_json(out / "gemini_batches" / f"batch-{batch_index}.json", response)
        observed = {
            str(row.get("strategy_alias")): dict(row)
            for row in response.get("strategies", [])
            if isinstance(row, Mapping)
        }
        for sid in strategy_ids:
            alias = aliases[sid]
            row = observed.get(alias, {})
            ids = [str(value) for value in row.get("candidate_ids", []) if str(value) in CANDIDATE_LIBRARY]
            ids = list(dict.fromkeys(ids))[:2]
            fallback_used = False
            if len(ids) < 2:
                ids = local_candidates(profiles[sid])
                fallback_used = True
            proposed.append({
                "strategy_id": sid,
                "strategy_alias": alias,
                "classification": row.get("classification", "LOW_SAMPLE_WAIT"),
                "candidate_ids": ids,
                "evidence": row.get("evidence", []),
                "expected_effect": row.get("expected_effect", {}),
                "winner_contamination_risk": row.get("winner_contamination_risk", "HIGH"),
                "falsification_test": row.get("falsification_test", "candidate must beat no-change under A/B parity and W1"),
                "priority": int(row.get("priority") or 999),
                "gemini_fallback_local": fallback_used,
            })
        call_audit.append({
            "stage": f"BATCH_{batch_index}", "model": model, "strategy_count": len(strategy_ids),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "status": response.get("status"),
        })

    red_prompt = red_team_prompt(proposed, clusters)
    model, text = v31.v3.call_gemini(key, models, [{"text": red_prompt}], max_tokens=16384)
    red = v31.strict_object_response(text)
    atomic_json(out / "red_team.json", red)
    red_rows = {
        str(row.get("strategy_alias")): dict(row)
        for row in red.get("rows", [])
        if isinstance(row, Mapping)
    }
    final_rows: list[dict[str, Any]] = []
    for row in proposed:
        adjudicated = red_rows.get(row["strategy_alias"], {})
        ids = [str(value) for value in adjudicated.get("approved_candidate_ids", []) if str(value) in CANDIDATE_LIBRARY]
        ids = list(dict.fromkeys(ids))[:2]
        if len(ids) < 2:
            ids = list(row["candidate_ids"])
        final_rows.append({
            **row,
            "candidate_ids": ids,
            "priority": int(adjudicated.get("priority") or row["priority"]),
            "red_team_reason": adjudicated.get("reason"),
            "required_checks": adjudicated.get("required_checks", []),
            "authority": "GEMINI_HYPOTHESIS_EXTERNAL_PLUS_LOCAL_EVIDENCE",
            "promotion_authority": False,
        })
    final_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    call_audit.append({
        "stage": "RED_TEAM", "model": model, "strategy_count": 22,
        "prompt_sha256": hashlib.sha256(red_prompt.encode()).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "status": red.get("status"),
    })
    plan = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS",
        "GEMINI_USED": True,
        "free_only": True,
        "gemini_call_count": len(call_audit),
        "models_used": sorted({row["model"] for row in call_audit}),
        "strategy_count": len(final_rows),
        "candidate_count": sum(len(row["candidate_ids"]) for row in final_rows),
        "candidate_library": CANDIDATE_LIBRARY,
        "rows": final_rows,
        "call_audit": call_audit,
        "source_review_sha256": sha256(Path(args.source_review).resolve()),
        "prediagnosis_sha256": sha256(Path(args.prediagnosis).resolve()),
        "registry_sha256": sha256(Path(args.registry).resolve()),
        "structural_clusters_sha256": stable_sha(clusters),
        "private_code_sent": False,
        "account_data_sent": False,
        "exchange_credentials_sent": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "next": "EXPLORATORY_REPLAY_22_L085",
        "blockers": [],
    }
    atomic_json(out / "plan.json", plan)
    print(json.dumps({"state": plan["state"], "strategies": 22, "candidates": plan["candidate_count"], "calls": plan["gemini_call_count"]}, sort_keys=True))
    return 0


def apply_candidate(base_exit: Any, candidate_id: str) -> Any:
    if candidate_id == "BE_075":
        return replace(base_exit, exit_id=f"{base_exit.exit_id}_BE075", breakeven_r=0.75)
    if candidate_id == "PARTIAL30_R075":
        return replace(base_exit, exit_id=f"{base_exit.exit_id}_P30R075", partial_r=0.75, partial_fraction=0.30)
    if candidate_id == "TRAIL_R100_ATR150":
        return replace(base_exit, exit_id=f"{base_exit.exit_id}_TR100A150", trail_activate_r=1.0, trail_atr_mult=1.5)
    if candidate_id == "TIME_STOP_24":
        return replace(base_exit, exit_id=f"{base_exit.exit_id}_TS24", time_stop_bars=24)
    if candidate_id == "TIME_STOP_48":
        return replace(base_exit, exit_id=f"{base_exit.exit_id}_TS48", time_stop_bars=48)
    raise RuntimeError(f"UNKNOWN_CANDIDATE:{candidate_id}")


def worst(row: Mapping[str, Any], stress: bool = False) -> float:
    loss = row.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {}) if stress else row.get("loss_metrics", {})
    return metric(loss.get("normal_worst_net_loss_R", loss.get("worst_net_loss_R")), -math.inf)


def research_check(row: Mapping[str, Any], incumbent: Mapping[str, Any]) -> dict[str, Any]:
    deltas = {
        "net": metric(row.get("net_return_pct_sum")) - metric(incumbent.get("net_return_pct_sum")),
        "pf": metric(row.get("net_profit_factor")) - metric(incumbent.get("net_profit_factor")),
        "payoff": metric(row.get("payoff_ratio")) - metric(incumbent.get("payoff_ratio")),
        "dd": metric(row.get("max_drawdown_pct")) - metric(incumbent.get("max_drawdown_pct")),
    }
    improved = sum(deltas[key] > 0.0 for key in ("net", "pf", "payoff"))
    retention = metric(row.get("trade_count")) / max(1.0, metric(incumbent.get("trade_count"), 1.0)) * 100.0
    avg_loss_ok = metric(row.get("loss_metrics", {}).get("avg_loss_R"), -math.inf) >= metric(incumbent.get("loss_metrics", {}).get("avg_loss_R"), -math.inf)
    passes = (
        row.get("parity", {}).get("state") == "PASS"
        and int(row.get("parity", {}).get("duplicate_trade_count") or 0) == 0
        and worst(row) >= -0.85
        and worst(row, True) >= -0.90
        and metric(row.get("max_drawdown_pct"), math.inf) <= metric(incumbent.get("max_drawdown_pct"), math.inf) + 0.25
        and retention >= 75.0
        and metric(row.get("positive_fresh_windows_pct")) >= 66.67
        and avg_loss_ok
        and improved >= 1
        and deltas["net"] >= -0.25
        and deltas["pf"] >= -0.05
        and deltas["payoff"] >= -0.10
    )
    return {
        "loss_ladder_stage": "L085_DISCOVERY",
        "normal_worst_net_loss_R": worst(row),
        "stress_worst_net_loss_R": worst(row, True),
        "trade_retention_pct": retention,
        "average_loss_nonworse": avg_loss_ok,
        "improved_primary_metrics": improved,
        "deltas": deltas,
        "research_pass": passes,
        "promotion_authority": False,
    }


def replay(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    plan = strict_json(Path(args.plan).resolve())
    plan_rows = {str(row["strategy_id"]): row for row in plan["rows"]}
    requested = [value.strip() for value in args.strategy_ids.split(",") if value.strip()]
    if not requested or any(sid not in STRATEGIES for sid in requested):
        raise RuntimeError("STRATEGY_IDS_INVALID")
    frames, features, funding, manifest = p.load_fresh_data(fresh_root)
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = repair.market_sha_map(manifest)
    registry = base._load_registry(ROOT)
    batch_rows: list[dict[str, Any]] = []
    for sid in requested:
        summary_path = find_summary(evidence_root, sid)
        baseline = strict_json(summary_path)
        candidate = baseline["candidate"]
        gate = exact._gate_from(candidate)
        base_exit = exact._exit_from(candidate)
        surgery = p.surgery_from(baseline.get("surgery"))
        symbols = tuple(str(value) for value in baseline.get("symbols", []))
        registry_row = registry[sid]
        source_sha = str(registry_row["canonical_engine"]["source_sha256"])
        strategy = base._load_canonical_strategy(ROOT, sid, registry_row)
        candidate_ids = list(plan_rows[sid]["candidate_ids"])
        variants = [("INCUMBENT_CONTROL", base_exit)] + [(candidate_id, apply_candidate(base_exit, candidate_id)) for candidate_id in candidate_ids]
        evaluated: list[dict[str, Any]] = []
        strategy_out = out / sid
        for variant_id, exit_spec in variants:
            print(f"REPLAY22_START strategy={sid} variant={variant_id}", flush=True)
            row = repair.evaluate_variant(
                variant_id=variant_id,
                exit_spec=exit_spec,
                strategy=strategy,
                gate=gate,
                surgery=surgery,
                symbols=symbols,
                frames=frames,
                features=features,
                funding=funding,
                quantiles=quantiles,
                manifest=manifest,
                market_shas=market_shas,
                strategy_source_sha=source_sha,
                source_run_id=args.source_run_id,
                source_head_sha=args.source_head_sha,
                cap_r=-0.90,
                out=strategy_out,
            )
            row["strategy_id"] = sid
            evaluated.append(row)
            print(f"REPLAY22_END strategy={sid} variant={variant_id}", flush=True)
        incumbent = evaluated[0]
        eligible: list[dict[str, Any]] = []
        for row in evaluated[1:]:
            row["adaptive_research_check"] = research_check(row, incumbent)
            atomic_json(strategy_out / row["variant_id"] / "summary.json", row)
            if row["adaptive_research_check"]["research_pass"]:
                eligible.append(row)
        winner = max(
            eligible,
            key=lambda row: (
                metric(row.get("net_return_pct_sum")), metric(row.get("net_profit_factor")),
                metric(row.get("payoff_ratio")), -metric(row.get("max_drawdown_pct"), math.inf),
            ),
        ) if eligible else None
        summary = {
            "schema_version": "1.0",
            "version": VERSION,
            "state": "PASS_L085_RESEARCH_CANDIDATE" if winner else "NO_L085_CANDIDATE",
            "strategy_id": sid,
            "plan_priority": plan_rows[sid]["priority"],
            "classification": plan_rows[sid]["classification"],
            "tested_candidate_ids": candidate_ids,
            "winner": winner["variant_id"] if winner else None,
            "loss_ladder_stage": "L085_DISCOVERY",
            "promotion_authority": False,
            "requires_w1_confirmation": True,
            "sealed_holdback_read": False,
            "variants": evaluated,
            "canonical_mutated": False,
            "registry_mutated": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "next": "L080_REFINEMENT" if winner else "SECOND_GEMINI_CAUSAL_REVIEW_OR_W1",
            "blockers": [],
        }
        atomic_json(strategy_out / "summary.json", summary)
        batch_rows.append(summary)
    batch = {
        "schema_version": "1.0", "version": VERSION, "state": "PASS",
        "strategy_count": len(batch_rows), "rows": batch_rows,
        "candidate_count": sum(1 for row in batch_rows if row["winner"]),
        "promotion_authority": False, "protected_mutations": 0, "blockers": [],
    }
    atomic_json(out / "batch_summary.json", batch)
    print(json.dumps({"state": "PASS", "strategies": len(batch_rows), "candidates": batch["candidate_count"]}, sort_keys=True))
    return 0


def aggregate(args: argparse.Namespace) -> int:
    root = Path(args.replay_root).resolve()
    out = Path(args.out).resolve()
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("summary.json")):
        try:
            payload = strict_json(path)
        except Exception:
            continue
        if payload.get("strategy_id") in STRATEGIES and payload.get("state") in {"PASS_L085_RESEARCH_CANDIDATE", "NO_L085_CANDIDATE"}:
            rows.append(payload)
    dedup = {str(row["strategy_id"]): row for row in rows}
    if len(dedup) != 22:
        raise RuntimeError(f"AGGREGATE_STRATEGY_COUNT:{len(dedup)}")
    ordered = sorted(dedup.values(), key=lambda row: (row["winner"] is None, row["plan_priority"], row["strategy_id"]))
    active = [
        {"strategy_id": row["strategy_id"], "winner": row["winner"], "next": "L080_REFINEMENT"}
        for row in ordered if row["winner"]
    ][:3]
    final = {
        "schema_version": "1.0", "version": VERSION,
        "state": "PASS", "strategy_count": 22,
        "l085_candidate_count": sum(1 for row in ordered if row["winner"]),
        "active_candidate_limit": 3, "active_l080_queue": active,
        "rows": ordered,
        "promotion_authority": False,
        "w1_confirmation_required": True,
        "canonical_mutated": False, "registry_mutated": False,
        "protected_mutations": 0, "execution_allowed": False,
        "next": "L080_REFINEMENT_MAX3_AND_SECOND_CAUSAL_REVIEW_REMAINDER",
        "blockers": [],
    }
    atomic_json(out / "final.json", final)
    print(json.dumps({"state": "PASS", "strategies": 22, "l085_candidates": final["l085_candidate_count"], "active": len(active)}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("analyze", "replay", "aggregate"), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--registry")
    parser.add_argument("--evidence-root")
    parser.add_argument("--prediagnosis")
    parser.add_argument("--source-review")
    parser.add_argument("--plan")
    parser.add_argument("--fresh-root")
    parser.add_argument("--strategy-ids")
    parser.add_argument("--source-run-id", default="30252022416")
    parser.add_argument("--source-head-sha", default="64e27d16d7f28b9fae59cf2a875d195f4bca22a1")
    parser.add_argument("--replay-root")
    args = parser.parse_args()
    if args.mode == "analyze":
        return analyze(args)
    if args.mode == "replay":
        return replay(args)
    return aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
