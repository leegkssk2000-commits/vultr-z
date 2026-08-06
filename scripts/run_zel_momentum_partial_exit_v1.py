#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, gzip, hashlib, importlib.util, io, json, math, sys, zipfile
from pathlib import Path
from statistics import fmean
from typing import Any

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
MAX_HOLD = 12


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_engine(root: Path):
    path = root / "scripts/run_zel_momentum_feature_contribution_v1.py"
    spec = importlib.util.spec_from_file_location("zel_feature_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("feature runner unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def member(z: zipfile.ZipFile, suffix: str) -> str:
    hits = [n for n in z.namelist() if n.endswith(suffix) and not n.endswith("/")]
    if len(hits) != 1:
        raise ValueError((suffix, hits))
    return hits[0]


def read_source(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with zipfile.ZipFile(path) as z:
        receipt = json.loads(z.read(member(z, "breakeven_receipt.json")))
        raw = z.read(member(z, "breakeven_trades.csv.gz"))
    rows = []
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gz:
        for r in csv.DictReader(io.TextIOWrapper(gz, encoding="utf-8", newline="")):
            if r["trigger_r"] not in {"", "None", "null"}:
                continue
            rows.append({
                "trade_id": r["trade_id"], "symbol": r["symbol"],
                "signal_ts": int(r["signal_ts"]), "entry_ts": int(r["entry_ts"]), "exit_ts": int(r["exit_ts"]),
                "entry_price": float(r["entry_price"]), "entry_reference": float(r["entry_reference"]),
                "stop_price": float(r["original_stop_price"]), "target_price": float(r["target_price"]),
                "planned_risk": float(r["planned_risk"]), "gross_R": float(r["gross_R"]),
                "cost_R": float(r["cost_R"]), "net_R": float(r["net_R"]), "exit_reason": r["exit_reason"],
                "source_intent_sha256": r["source_intent_sha256"],
                "strategy_source_sha256": r["strategy_source_sha256"],
                "feature_schema_sha256": r["feature_schema_sha256"], "config_sha256": r["config_sha256"],
            })
    return receipt, sorted(rows, key=lambda x: (x["entry_ts"], x["symbol"], x["trade_id"]))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda x: (x["exit_ts"], x["symbol"], x["trade_id"]))
    vals = [float(x["net_R"]) for x in ordered]
    wins, losses = [x for x in vals if x > 0], [x for x in vals if x < 0]
    eq = peak = dd = 0.0
    for x in vals:
        eq += x; peak = max(peak, eq); dd = max(dd, peak - eq)
    aw, al = (fmean(wins) if wins else 0.0), (fmean(losses) if losses else 0.0)
    return {
        "trades": len(rows), "win_rate_pct": len(wins) / len(rows) * 100 if rows else 0.0,
        "net_R": sum(vals), "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "payoff": aw / abs(al) if al < 0 else None, "expectancy_R": fmean(vals) if vals else 0.0,
        "avg_win_R": aw, "avg_loss_R": al, "max_drawdown_R": dd,
        "partial_fills": sum(bool(x["partial_filled"]) for x in rows),
        "partial_then_target": sum(x["exit_reason"] == "PARTIAL_THEN_TARGET" for x in rows),
        "partial_then_stop": sum(x["exit_reason"] in {"PARTIAL_THEN_STOP", "PARTIAL_THEN_STOP_FIRST"} for x in rows),
        "partial_then_timeout": sum(x["exit_reason"] == "PARTIAL_THEN_TIMEOUT" for x in rows),
    }


def overlaps(rows: list[dict[str, Any]]) -> int:
    total = 0
    for sym in SYMBOLS:
        last = -1
        for r in sorted((x for x in rows if x["symbol"] == sym), key=lambda x: (x["entry_ts"], x["trade_id"])):
            total += r["entry_ts"] <= last
            last = max(last, r["exit_ts"])
    return total


def simulate(source: list[dict[str, Any]], bars: dict[str, list[Any]], indexes: dict[str, dict[int, int]],
             fraction: float | None, trigger_r: float, cost_pct: float) -> list[dict[str, Any]]:
    out = []
    label = "DISABLED" if fraction is None else f"{fraction:g}"
    for s in source:
        base = {
            "trade_id": hashlib.sha256(f"PARTIAL_{label}|{s['trade_id']}".encode()).hexdigest(),
            "source_trade_id": s["trade_id"], "partial_fraction": fraction, "partial_trigger_r": trigger_r,
            "symbol": s["symbol"], "signal_ts": s["signal_ts"], "entry_ts": s["entry_ts"],
            "entry_price": s["entry_price"], "entry_reference": s["entry_reference"],
            "original_stop_price": s["stop_price"], "target_price": s["target_price"],
            "planned_risk": s["planned_risk"], "source_intent_sha256": s["source_intent_sha256"],
            "strategy_source_sha256": s["strategy_source_sha256"],
            "feature_schema_sha256": s["feature_schema_sha256"], "config_sha256": s["config_sha256"],
        }
        partial_target = s["entry_reference"] + trigger_r * s["planned_risk"]
        if fraction is None:
            out.append(base | {
                "partial_ts": None, "exit_ts": s["exit_ts"], "partial_target_price": partial_target,
                "partial_filled": False, "remaining_fraction": 1.0, "partial_gross_R": 0.0,
                "final_leg_gross_R": s["gross_R"], "gross_R": s["gross_R"], "cost_R": s["cost_R"],
                "net_R": s["net_R"], "exit_reason": s["exit_reason"],
            })
            continue
        seq = bars[s["symbol"]]; start = indexes[s["symbol"]].get(s["entry_ts"])
        if start is None or start + MAX_HOLD > len(seq):
            raise ValueError(f"missing horizon {s['symbol']}/{s['entry_ts']}")
        filled = False; partial_ts = None; remaining = 1.0; partial_gross = 0.0
        exit_i = start + MAX_HOLD - 1; final_price = seq[exit_i].close; reason = "TIMEOUT"
        for i in range(start, start + MAX_HOLD):
            bar = seq[i]; stop = bar.low <= s["stop_price"]; target = bar.high >= s["target_price"]
            p_hit = (not filled) and bar.high >= partial_target
            if stop:
                final_price = s["stop_price"]; exit_i = i
                reason = ("PARTIAL_THEN_STOP_FIRST" if target else "PARTIAL_THEN_STOP") if filled else ("STOP_FIRST" if target or p_hit else "STOP")
                break
            if p_hit:
                filled = True; partial_ts = bar.ts; remaining = 1.0 - fraction
                partial_gross = fraction * ((partial_target - s["entry_price"]) / s["planned_risk"])
            if target:
                final_price = s["target_price"]; exit_i = i; reason = "PARTIAL_THEN_TARGET" if filled else "TARGET"; break
        else:
            reason = "PARTIAL_THEN_TIMEOUT" if filled else "TIMEOUT"
        final_leg = remaining * ((final_price - s["entry_price"]) / s["planned_risk"])
        gross = partial_gross + final_leg
        cost = (s["entry_price"] * (cost_pct / 100.0)) / s["planned_risk"]
        out.append(base | {
            "partial_ts": partial_ts, "exit_ts": seq[exit_i].ts, "partial_target_price": partial_target,
            "partial_filled": filled, "remaining_fraction": remaining, "partial_gross_R": partial_gross,
            "final_leg_gross_R": final_leg, "gross_R": gross, "cost_R": cost, "net_R": gross - cost,
            "exit_reason": reason,
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", type=Path, required=True); p.add_argument("--source-artifact", type=Path, required=True)
    p.add_argument("--repo-root", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); a.repo_root = a.repo_root.resolve(); a.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(a.repo_root))
    from backend.research import zel_feature_strategy_ssot_v1 as strategy
    engine = load_engine(a.repo_root)
    plan_path = a.repo_root / "backend/research/zel_momentum_partial_exit_plan_v1.json"
    disp_path = a.repo_root / "backend/research/zel_momentum_breakeven_disposition_v1.json"
    manifest_path, cost_path = a.inputs / "materialized_manifest.json", a.inputs / "cost_binding.json"
    plan, disp = json.loads(plan_path.read_text()), json.loads(disp_path.read_text())
    manifest, cost_cfg = json.loads(manifest_path.read_text()), json.loads(cost_path.read_text())
    if plan.get("state") != "PASS_PARTIAL_EXIT_PLAN_SEALED_RESEARCH_ONLY" or disp.get("state") != "FAIL_BREAKEVEN_NO_SURVIVOR":
        raise SystemExit("partial route not sealed")
    if sha(a.source_artifact) != disp["source_artifact_sha256"] or manifest.get("state") != "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("lineage mismatch")
    receipt, source = read_source(a.source_artifact)
    if receipt.get("receipt_sha256") != plan["source_receipt_sha256"] or len(source) != int(plan["frozen_entry_count"]):
        raise SystemExit("source receipt/count mismatch")
    if len({x["trade_id"] for x in source}) != len(source):
        raise SystemExit("duplicate source trade")
    bars = {s: engine.read_bars(a.inputs / "market/5m/research" / f"{s}.csv.gz", strategy.Bar, strategy.FIVE_MIN_MS) for s in SYMBOLS}
    indexes = {s: {b.ts: i for i, b in enumerate(v)} for s, v in bars.items()}
    results, ledgers = [], {}
    for raw in plan["partial_exit_fraction_candidates"]:
        fraction = None if raw is None else float(raw); vid = "PARTIAL_DISABLED" if fraction is None else f"PARTIAL_FRACTION_{fraction:g}"
        rows = simulate(source, bars, indexes, fraction, float(plan["partial_trigger_r"]), float(cost_cfg["all_in_cost_pct"]))
        m = summarize(rows) | {"variant_id": vid, "partial_fraction": raw, "partial_trigger_r": float(plan["partial_trigger_r"]),
                               "entry_retention_pct": len(rows) / len(source) * 100.0, "same_symbol_overlap_conflicts": overlaps(rows),
                               "duplicates": len(rows) - len({x["trade_id"] for x in rows})}
        results.append(m); ledgers[vid] = rows
    base = next(x for x in results if x["partial_fraction"] is None); src = disp["best_control"]
    for key in ("trades", "net_R", "win_rate_pct", "profit_factor", "payoff", "expectancy_R", "max_drawdown_R"):
        if key == "trades":
            assert int(base[key]) == int(src[key])
        elif not math.isclose(float(base[key]), float(src[key]), rel_tol=1e-9, abs_tol=1e-9):
            raise AssertionError((key, base[key], src[key]))
    gates = plan["hard_gates"]; survivors = []
    for r in results:
        r["hard_gate"] = {
            "trades": int(r["trades"]) == int(gates["trades_eq"]),
            "entry_retention": math.isclose(float(r["entry_retention_pct"]), float(gates["entry_retention_pct_eq"]), abs_tol=1e-12),
            "net_R": float(r["net_R"]) > float(gates["net_R_gt"]),
            "profit_factor": r["profit_factor"] is not None and float(r["profit_factor"]) >= float(gates["profit_factor_gte"]),
            "expectancy_R": float(r["expectancy_R"]) > float(gates["expectancy_R_gt"]),
            "payoff": r["payoff"] is not None and float(r["payoff"]) >= float(gates["payoff_gte"]),
            "max_drawdown": float(r["max_drawdown_R"]) < float(gates["max_drawdown_R_lt_source"]),
        }
        r["hard_gate_pass"] = all(r["hard_gate"].values())
        if r["hard_gate_pass"]: survivors.append(r["variant_id"])
    ranking = [x["variant_id"] for x in sorted(results, key=lambda x: (float(x["net_R"]), float(x["profit_factor"] or 0), -float(x["max_drawdown_R"])), reverse=True)]
    integrity = {"errors": 0, "duplicates": sum(int(x["duplicates"]) for x in results), "source_entry_rows": len(source),
                 "base_metric_parity": True, "protected_mutations": 0, "execution_authority": "NONE", "order_authority": "BLOCKED"}
    if integrity["duplicates"]: raise SystemExit("duplicate output")
    state = "PASS_PARTIAL_EXIT_COUNTERFACTUAL_SURVIVOR_FOUND_SEQUENCE_REQUIRED" if survivors else "PASS_PARTIAL_EXIT_COUNTERFACTUAL_NO_SURVIVOR"
    next_gate = plan["next_if_survivor"] if survivors else plan["next_if_no_survivor"]
    output = {"schema_version": "zel.momentum.partial_exit_receipt.v1", "state": state, "strategy_id": plan["strategy_id"],
              "single_causal_axis": plan["single_causal_axis"], "source_variant_id": plan["source_variant_id"],
              "source_artifact_sha256": sha(a.source_artifact), "source_receipt_sha256": receipt["receipt_sha256"],
              "references": {"plan_sha256": sha(plan_path), "disposition_sha256": sha(disp_path),
                             "materialized_manifest_sha256": sha(manifest_path), "cost_binding_sha256": sha(cost_path)},
              "results": results, "research_ranking": ranking, "hard_gate_survivors": survivors, "integrity": integrity,
              "selection_authority": False, "promotion_authority": False, "next_gate": next_gate,
              "action": "hold" if survivors else "route_change"}
    output["receipt_sha256"] = canonical(output)
    (a.output / "partial_exit_receipt.json").write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    fields = ["trade_id", "source_trade_id", "partial_fraction", "partial_trigger_r", "symbol", "signal_ts", "entry_ts", "partial_ts", "exit_ts", "entry_price", "entry_reference", "original_stop_price", "partial_target_price", "target_price", "planned_risk", "partial_filled", "remaining_fraction", "partial_gross_R", "final_leg_gross_R", "gross_R", "cost_R", "net_R", "exit_reason", "source_intent_sha256", "strategy_source_sha256", "feature_schema_sha256", "config_sha256"]
    with gzip.open(a.output / "partial_exit_trades.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for vid in ranking: w.writerows(ledgers[vid])
    print(json.dumps({"state": state, "survivors": survivors, "top3": ranking[:3], "next_gate": next_gate, "receipt": output["receipt_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
