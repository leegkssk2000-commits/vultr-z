from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

VERSION = "STRATEGY11_POST_PORTFOLIO_AUTONOMY_AUDIT_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "automatic_live_enable": False,
}

CAPABILITIES: dict[str, dict[str, tuple[str, ...]]] = {
    "ADAPTIVE_EXECUTION": {
        "intent_idempotency": ("intent_id", "client_order_id", "idempot", "duplicate_order"),
        "fill_state_machine": ("partial_fill", "filled_qty", "sent", "ack", "fill_state"),
        "liquidity_capacity": ("liquidity", "capacity", "spread", "orderbook", "market_depth"),
        "execution_cost": ("slippage", "fee", "funding", "latency", "cost_envelope"),
        "risk_sizing": ("exposure", "liq_buffer", "position_size", "risk_budget", "leverage"),
        "stop_ownership": ("stop_owner", "stop_ownership", "protective_stop", "reduce_only"),
    },
    "SELF_HEALING_OPERATIONS": {
        "health_heartbeat": ("heartbeat", "stale", "health_check", "liveness"),
        "state_ledger_parity": ("ledger", "pnl", "state_parity", "source_parity", "reconcile"),
        "single_writer": ("single_writer", "writer_owner", "owner_lock", "duplicate_writer"),
        "rollback_restore": ("rollback", "snapshot", "restore", "golden"),
        "service_recovery": ("systemd", "restart", "timer", "service_failed", "failover"),
        "incident_dedup": ("fingerprint", "dedup", "error_budget", "severity"),
    },
    "CHAMPION_CHALLENGER": {
        "incumbent_identity": ("incumbent", "champion", "incumbent_candidate_sha"),
        "challenger_shadow": ("challenger", "shadow_only", "promotion_authority"),
        "bounded_epoch": ("generation_count", "search_ledger", "epoch", "experiment_budget"),
        "promotion_gate": ("promotion_gate", "pareto", "retention", "oos", "sealed"),
        "automatic_rollback_request": ("retain_incumbent", "rollback", "previous_verified_incumbent"),
        "drift_calibration": ("drift", "calibration", "psi", "brier", "ece"),
    },
    "MARKET_DIGITAL_TWIN": {
        "market_path_scenarios": ("scenario", "regime", "shock", "market_path"),
        "execution_microstructure": ("partial_fill", "slippage", "latency", "spread", "orderbook"),
        "funding_cost": ("funding", "fee", "cost_profile"),
        "liquidity_failure": ("liquidity_shock", "api_gap", "outage", "stale_feed"),
        "portfolio_joint_risk": ("joint_dd", "correlation", "liquidation", "exposure"),
        "deterministic_lineage": ("seed", "scenario_sha", "source_sha", "deterministic"),
    },
    "HUMAN_GOVERNED_CAPITAL": {
        "policy_manifest": ("policy_sha", "approval_manifest", "governance_policy"),
        "capital_limits": ("max_capital", "max_exposure", "max_leverage", "dd_limit"),
        "universe_limits": ("allowed_exchange", "allowed_symbols", "symbol_allowlist"),
        "approval_lifecycle": ("user_approval", "approved_by", "approval_expiry", "revocation"),
        "canary_ladder": ("canary", "stage_gate", "capital_step", "rollback_stage"),
        "kill_switch": ("kill_switch", "emergency_stop", "block_new_entries"),
        "ai_no_authority": ("order_authority", "execution_allowed", "promotion_authority"),
    },
}

ALLOWED_SUFFIXES = {".py", ".json", ".yml", ".yaml", ".sh"}
ROOTS = ("backend", "engine", "strategies", "ops", "scripts", ".github/workflows")
EXCLUDED_PARTS = {
    ".git", "node_modules", "dist", "build", "runtime", "runtime_results", "backups", "backup",
    "__pycache__", "docs", "document", "artifacts",
}
EXCLUDED_FILES = {
    "strategy11_post_portfolio_autonomy_audit_v1.py",
    "strategy11-post-portfolio-autonomy-audit-v1.yml",
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def iter_source_files(root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for rel_root in ROOTS:
        base = root / rel_root
        if not base.exists():
            continue
        if base.is_file():
            candidates = [base]
        else:
            candidates = base.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            rel = path.relative_to(root)
            if path.name in EXCLUDED_FILES:
                continue
            lowered_parts = {part.lower() for part in rel.parts}
            if lowered_parts & EXCLUDED_PARTS:
                continue
            if rel in seen:
                continue
            seen.add(rel)
            yield path


def executable_shape(path: Path, text: str) -> dict[str, Any]:
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return {"kind": "python_parse_error", "callables": 0, "classes": 0, "top_level_calls": 0}
        callables = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
        classes = sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
        top_level_calls = sum(
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            for node in tree.body
        )
        return {"kind": "python", "callables": callables, "classes": classes, "top_level_calls": top_level_calls}
    if path.suffix in {".yml", ".yaml"}:
        return {"kind": "workflow_or_yaml", "callables": int("jobs:" in text and ("run:" in text or "uses:" in text))}
    if path.suffix == ".sh":
        return {"kind": "shell", "callables": int("#!/" in text or "set -" in text)}
    return {"kind": "json", "callables": 0}


def evidence_strength(path: Path, text: str, terms: tuple[str, ...]) -> tuple[int, list[str]]:
    lowered = text.lower()
    hits = sorted({term for term in terms if term.lower() in lowered})
    shape = executable_shape(path, text)
    executable = shape.get("kind") in {"python", "workflow_or_yaml", "shell"} and int(shape.get("callables", 0)) > 0
    score = len(hits) + (2 if executable else 0)
    return score, hits


def audit(root: Path, head_sha: str) -> dict[str, Any]:
    files = []
    for path in iter_source_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix()
        files.append({
            "path": rel,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "text": text,
            "shape": executable_shape(path, text),
        })

    capability_rows = []
    implementation_queue = []
    for capability, subcaps in CAPABILITIES.items():
        subcap_rows = []
        for subcap, terms in subcaps.items():
            candidates = []
            for row in files:
                score, hits = evidence_strength(root / row["path"], row["text"], terms)
                if score < 3 or not hits:
                    continue
                candidates.append({
                    "path": row["path"],
                    "sha256": row["sha256"],
                    "score": score,
                    "term_hits": hits,
                    "shape": row["shape"],
                })
            candidates.sort(key=lambda value: (-value["score"], value["path"]))
            strong = [item for item in candidates if item["shape"].get("kind") in {"python", "workflow_or_yaml", "shell"}]
            subcap_rows.append({
                "subcapability": subcap,
                "required_terms": list(terms),
                "status": "EXECUTABLE_EVIDENCE" if strong else ("CONFIG_ONLY_EVIDENCE" if candidates else "MISSING"),
                "evidence": candidates[:8],
            })
        executable_count = sum(row["status"] == "EXECUTABLE_EVIDENCE" for row in subcap_rows)
        required_count = len(subcap_rows)
        if executable_count == required_count:
            status = "IMPLEMENTED_EVIDENCE"
        elif executable_count > 0:
            status = "PARTIAL_EVIDENCE"
        else:
            status = "MISSING_EXECUTABLE_EVIDENCE"
        missing = [row["subcapability"] for row in subcap_rows if row["status"] != "EXECUTABLE_EVIDENCE"]
        capability_rows.append({
            "capability": capability,
            "status": status,
            "executable_subcapability_count": executable_count,
            "required_subcapability_count": required_count,
            "missing_or_config_only": missing,
            "subcapabilities": subcap_rows,
        })
        if missing:
            implementation_queue.append({
                "stage": capability,
                "missing_or_config_only": missing,
                "next_minimum_child": f"{capability}_STRICT_CONTRACT_AND_FIXTURE_V1",
                "runtime_activation_allowed": False,
            })

    result = {
        "schema_version": "strategy11.post_portfolio_autonomy_audit.v1",
        "version": VERSION,
        "state": "PASS_POST_PORTFOLIO_AUTONOMY_AUDIT",
        "repository_head_sha": head_sha,
        "scanned_file_count": len(files),
        "capability_count": len(capability_rows),
        "capabilities": capability_rows,
        "implementation_queue": implementation_queue,
        "next_stage": implementation_queue[0]["stage"] if implementation_queue else "HUMAN_GOVERNED_ARCHITECTURE_READY",
        "audit_limitations": [
            "Static executable evidence does not prove runtime binding or production correctness.",
            "Configuration or documentation alone never satisfies an executable subcapability.",
            "All future stages remain fixture/read-only until W1/W2/W3, new sealed, Shadow and Paper gates pass.",
        ],
        **SAFETY,
    }
    result["audit_sha"] = stable_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root.resolve(), args.head_sha)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "summary.json", result)
    atomic_json(args.out / "capability_evidence.json", {"capabilities": result["capabilities"]})
    atomic_json(args.out / "implementation_queue.json", {"implementation_queue": result["implementation_queue"]})
    print(result["state"], result["scanned_file_count"], result["next_stage"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
