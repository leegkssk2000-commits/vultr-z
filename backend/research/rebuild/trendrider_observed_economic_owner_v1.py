"""Offline, serial owner for Issue 1284's already frozen common replay.

No network operations or source acquisition are available here. The root first
pins this code, then supplies an exact-hash OWNER_INPUT_FREEZE.json after source
success. Each economic run/screen has an exclusive durable reservation before
invocation; a failed or interrupted reservation can never be retried. Stages
are separate CLI invocations so A selection and candidate identity receipts
can be committed and independently read back before their next stage.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

SCOPE = "TRENDRIDER_UNIFIED_OBSERVED_WS_SCHEMA_AFTER_PR1283_V1"
OLD_CONTRACT = ("research/development_evidence/"
                "TRENDRIDER_UNIFIED_SHARED_COMMON_REPLAY_AFTER_PR1273_V1/COMMON_REPLAY_CONTRACT.json")
ECONOMIC_CONTRACT_KEYS = ("common_cost", "common_cost_sha256", "execution", "partitions",
                          "policies", "genes", "stage1", "stage2", "stage3",
                          "source_authority_hashes", "runtime", "excluded_terminal_predicates",
                          "gene_provenance", "historical_archives", "formal_credit", "production_grade")
PARTITIONS = {"DEV_A": (64, 532), "DEV_B": (532, 1000)}
POLICIES = ("B_COMMON", "P_COMMON")
OWNER_PATH = "backend/research/rebuild/trendrider_observed_economic_owner_v1.py"
REQUIRED_CODE = (OWNER_PATH, "backend/research/rebuild/trendrider_common_engine_v1.py",
                 "backend/research/rebuild/trendrider_common_genes_v1.py",
                 "backend/research/rebuild/trendrider_common_source_v1.py",
                 "backend/research/rebuild/trendrider_common_source_v6.py",
                 "backend/research/rebuild/trendrider_observed_timestamp_v1.py",
                 "backend/research/rebuild/trendrider_observed_ws_schema_v1.py")
RESERVATION_KEYS = {
    "CONTROL": {f"{p}__{lane}" for p in PARTITIONS for lane in POLICIES},
    "SCREEN_A": {f"G{i}" for i in range(1, 7)},
    "CONFIRM_B": {f"G{i}" for i in range(1, 7)},
    "CHILD_FULL": {f"{p}__{child}" for p in PARTITIONS for child in ("U1", "U2")},
}
LIMITS = {"CONTROL": 4, "SCREEN_A": 6, "CONFIRM_B": 2, "CHILD_FULL": 4}


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       indent=2) + "\n").encode()


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode()).hexdigest()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("OWNER_PATH_OUTSIDE_ROOT")
    return path


def read_hashed(path: Path, expected_sha: str) -> bytes:
    raw = path.read_bytes()
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha)) or sha256(raw).hexdigest() != expected_sha:
        raise ValueError("OWNER_RAW_HASH_MISMATCH:" + path.name)
    return raw


def write_once(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        # The containing directory entry is durable before a run is dispatched.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return sha256(raw).hexdigest()


def _key(row: Mapping[str, Any]) -> tuple[str, int, str]:
    return str(row["symbol"]), int(row["signal_ts"]), str(row["side"])


def _engine():
    from backend.research.rebuild import trendrider_common_engine_v1
    return trendrider_common_engine_v1


def _genes():
    from backend.research.rebuild import trendrider_common_genes_v1
    return trendrider_common_genes_v1


def _semantic_receipt(path: Path, expected_sha: str) -> dict[str, Any]:
    """Read-only semantic revalidation; never opens REST or WS transports."""
    from backend.research.rebuild.trendrider_common_source_v6 import validate_semantic_receipt
    return validate_semantic_receipt(path, expected_sha)


def reserve(root: Path, kind: str, run_id: str, binding: str) -> Path:
    if kind not in RESERVATION_KEYS or run_id not in RESERVATION_KEYS[kind]:
        raise ValueError("OWNER_UNAUTHORIZED_RUN_ID")
    directory = root / "reservations"
    directory.mkdir(parents=True, exist_ok=True)
    # A process lock serializes the count check and exclusive reservation. A
    # crash intentionally leaves the lock in place: there is no retry budget.
    lock = directory / "SERIAL_DISPATCH.lock"
    lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.close(lock_fd)
        if len(list(directory.glob(kind + "__*.json"))) >= LIMITS[kind]:
            raise ValueError("OWNER_BUDGET_EXHAUSTED:" + kind)
        path = directory / (kind + "__" + run_id + ".json")
        write_once(path, {"scope_key": SCOPE, "kind": kind, "run_id": run_id,
                          "input_freeze_sha256": binding, "reserved_at_utc": _utc(),
                          "retry_authorized": False})
        return path
    finally:
        lock.unlink()


def winner_retention(reference: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    """Same-key positive completed winner profit, capped winner by winner."""
    winners = sorted((r for r in reference["campaigns"]
                      if r["status"] == "COMPLETED" and r["net_bps"] > 0),
                     key=lambda r: (-r["net_bps"], _key(r)))
    lookup = {_key(r): r for r in child["campaigns"]}
    def one(rows):
        denominator = math.fsum(float(r["net_bps"]) for r in rows)
        values = []
        for row in rows:
            match = lookup.get(_key(row))
            values.append(max(float(match["net_bps"]), 0.0)
                          if match is not None and match["status"] == "COMPLETED" else 0.0)
        return {"retention": math.fsum(min(v, float(r["net_bps"])) for r, v in zip(rows, values))
                / denominator if denominator > 0 else None,
                "uncapped_retention": math.fsum(values) / denominator if denominator > 0 else None,
                "denominator_bps": denominator, "baseline_winners_T": len(rows)}
    return {"ordinary": one(winners), "top10": one(winners[:max(1, math.ceil(len(winners) * .1))]),
            "definition": "SAME_KEY_COMPLETED_POSITIVE_CHILD_NET_CAPPED_PER_BASELINE_WINNER"}


def path_attribution(reference: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    base, new = ({_key(r): r for r in result["campaigns"]} for result in (reference, child))
    common, removed, added = set(base) & set(new), set(base) - set(new), set(new) - set(base)
    path_fields = ("entry_index", "entry_ts", "entry", "status", "exit_index", "exit_ts",
                   "exit_available_ts", "exit", "exit_reason", "mark_index", "mark_ts",
                   "mark_price", "quantity_normalized", "cost_bps", "net_bps",
                   "terminal_net_bps", "cost2_terminal_net_bps", "mark_path")
    changed = [list(key) for key in sorted(common)
               if any(base[key].get(field) != new[key].get(field) for field in path_fields)]
    matched_delta = math.fsum(new[k]["terminal_net_bps"] - base[k]["terminal_net_bps"] for k in common)
    additional_b = math.fsum(new[k]["terminal_net_bps"] for k in added if new[k]["b_only"])
    additional_p = math.fsum(new[k]["terminal_net_bps"] for k in added if new[k]["p_core"])
    displaced = -math.fsum(base[k]["terminal_net_bps"] for k in removed)
    actual_delta = child["metrics"]["terminal_net_bps"] - reference["metrics"]["terminal_net_bps"]
    bridge = math.fsum((matched_delta, additional_b, additional_p, displaced))
    return {"matched_campaigns_T": len(common), "displaced_reference_T": len(removed),
            "added_B_only_T": sum(new[k]["b_only"] for k in added),
            "recovered_P_core_T": sum(new[k]["p_core"] for k in added),
            "matched_path_changes": changed, "same_key_path_integrity": "FAIL" if changed else "PASS",
            "matched_terminal_delta_bps": matched_delta, "added_B_only_terminal_bps": additional_b,
            "recovered_P_core_terminal_bps": additional_p, "displaced_reference_terminal_effect_bps": displaced,
            "added_completed_winners_T": sum(new[k]["status"] == "COMPLETED" and new[k]["net_bps"] > 0 for k in added),
            "added_completed_losers_T": sum(new[k]["status"] == "COMPLETED" and new[k]["net_bps"] < 0 for k in added),
            "removed_completed_winner_profit_bps": math.fsum(base[k]["net_bps"] for k in removed
                if base[k]["status"] == "COMPLETED" and base[k]["net_bps"] > 0),
            "removed_completed_loss_bps": -math.fsum(base[k]["net_bps"] for k in removed
                if base[k]["status"] == "COMPLETED" and base[k]["net_bps"] < 0),
            "additional_cost_bps": math.fsum(new[k]["cost_bps"] for k in added)
                - math.fsum(base[k]["cost_bps"] for k in removed),
            "terminal_net_delta_bps": actual_delta, "bridge_residual_bps": actual_delta - bridge,
            "displaced_reference_keys": [list(k) for k in sorted(removed)],
            "added_keys": [list(k) for k in sorted(added)]}


def raw_and_executed_overlap(signals: Sequence[Mapping[str, Any]], b: Mapping[str, Any],
                            p: Mapping[str, Any]) -> dict[str, Any]:
    lo, hi = PARTITIONS[b["partition"]]
    subset = [s for s in signals if lo <= s["signal_index"] < hi]
    raw_b = {_key(s) for s in subset if s["b_actionable"]}
    raw_p = {_key(s) for s in subset if s["p_actionable"]}
    actual_b, actual_p = ({_key(c) for c in r["campaigns"]} for r in (b, p))
    return {"raw_B_signals": len(raw_b), "raw_P_signals": len(raw_p),
            "raw_overlap": len(raw_b & raw_p), "raw_P_only": len(raw_p - raw_b),
            "raw_B_only": len(raw_b - raw_p), "actual_overlap": len(actual_b & actual_p),
            "actual_P_only": len(actual_p - actual_b), "actual_B_only": len(actual_b - actual_p),
            "raw_P_subset_B": raw_p <= raw_b,
            "signal_snapshot_sha": digest(subset),
            "feature_intent_lineage": "SIGNALS.json snapshots and each campaign exact SHA bindings"}


def child_gate(p: Mapping[str, Any], b: Mapping[str, Any], child: Mapping[str, Any],
               signals: Sequence[Mapping[str, Any]], gene_ids: Sequence[str]) -> dict[str, Any]:
    retained = winner_retention(p, child)
    attribution = path_attribution(p, child)
    m = child["metrics"]
    lo, hi = PARTITIONS[child["partition"]]
    subset = [s for s in signals if lo <= s["signal_index"] < hi]
    decisions = {_key(s): _genes().union_admission(s, gene_ids) for s in subset}
    p_raw = {_key(s) for s in subset if s["p_actionable"]}
    integrity = (attribution["same_key_path_integrity"] == "PASS"
                 and abs(attribution["bridge_residual_bps"]) < 1e-8
                 and all(decisions[k] == "P_COMMON" for k in p_raw))
    def ge(value, minimum, strict=False):
        return value is not None and (value > minimum if strict else value >= minimum)
    gates = {"integrity": integrity, "positive_terminal_net": ge(m["terminal_net_bps"], 0, True),
             "positive_closed_expectancy": ge(m["expectancy_bps"], 0, True),
             "PF_ge_1": m["PF_infinite"] or ge(m["PF"], 1),
             "payoff_ge_1": m["payoff_infinite"] or ge(m["payoff"], 1),
             "positive_terminal_cost2": ge(m["cost2_terminal_net_bps"], 0, True),
             "P_ordinary_winner_retention_ge_60pct": ge(retained["ordinary"]["retention"], .6),
             "P_top10_winner_retention_ge_60pct": ge(retained["top10"]["retention"], .6)}
    b_only = [s for s in subset if s["b_actionable"] and not s["p_actionable"]]
    return {"partition": child["partition"], "metrics": m, "gates": gates,
            "pass": all(gates.values()), "P_retention": retained,
            "B_retention": winner_retention(b, child), "P_path_attribution": attribution,
            "P_raw_core_signals": len(p_raw), "P_raw_core_rejected": sum(decisions[k] != "P_COMMON" for k in p_raw),
            "B_only_accepted_signals": sum(decisions[_key(s)] == "B_COMMON" for s in b_only),
            "B_only_rejected_signals": sum(decisions[_key(s)] is None for s in b_only),
            "formal_credit": 0, "production_grade": False}


def choose_final(candidates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Frozen Stage 3 Pareto order; no weighted score or post-outcome knobs."""
    def vector(item):
        windows = list(item["windows"].values())
        def worst(field):
            return min(w["metrics"][field] for w in windows)
        return (worst("expectancy_bps"), min(float("inf") if w["metrics"]["PF_infinite"]
                else w["metrics"]["PF"] for w in windows), worst("WR"),
                min(w["metrics"]["loss_tail_10pct_mean_bps"] or 0 for w in windows),
                min(w["P_retention"]["ordinary"]["retention"] for w in windows),
                min(w["P_retention"]["top10"]["retention"] for w in windows),
                -max(w["metrics"]["marked_DD_bps"] for w in windows),
                -max(w["metrics"]["top1_positive_contribution_fraction"] for w in windows))
    passed = {k: v for k, v in candidates.items()
              if set(v["windows"]) == set(PARTITIONS) and all(w["pass"] for w in v["windows"].values())}
    frontier = []
    for key, item in passed.items():
        current = vector(item)
        if not any(all(x >= y for x, y in zip(vector(other), current))
                   and any(x > y for x, y in zip(vector(other), current))
                   for other_key, other in passed.items() if other_key != key):
            frontier.append(key)
    def tie(key):
        item = passed[key]
        axes = set().union(*(_genes().GENES[g]["axes"] for g in item["gene_ids"]))
        return (len(axes), max(w["metrics"]["top1_positive_contribution_fraction"] for w in item["windows"].values()),
                max(w["metrics"]["marked_DD_bps"] for w in item["windows"].values()), key)
    frontier.sort(key=tie)
    selected = frontier[0] if frontier else None
    return {"hard_pass_candidates": list(passed), "pareto_candidates": frontier,
            "selected_candidate": selected,
            "state": "TREND_RIDER_UNIFIED_V1_EARNED_COMMON_REPLAY" if selected
                     else "TREND_RIDER_UNIFIED_NOT_EARNED_COMMON_REPLAY",
            "formal_credit": 0, "production_grade": False}


class Owner:
    def __init__(self, repo_root: str | Path, evidence_root: str | Path,
                 freeze_manifest: str | Path, freeze_sha: str):
        self.repo = Path(repo_root).resolve()
        self.root = Path(evidence_root).resolve()
        self.freeze_sha = freeze_sha
        self.freeze = json.loads(read_hashed(Path(freeze_manifest), freeze_sha))
        if self.freeze.get("scope_key") != SCOPE:
            raise ValueError("OWNER_SCOPE_MISMATCH")
        if not self.root.is_relative_to(self.repo / "research/development_evidence") or self.root.name != SCOPE:
            raise ValueError("OWNER_EVIDENCE_SCOPE_MISMATCH")
        code = self.freeze["code_files"]
        if not set(REQUIRED_CODE) <= set(code):
            raise ValueError("OWNER_CODE_PIN_INCOMPLETE")
        for relative, expected in code.items():
            read_hashed(_safe(self.repo, relative), expected)
        contract_ref = self.freeze["contract"]
        self.contract = json.loads(read_hashed(_safe(self.repo, contract_ref["path"]), contract_ref["sha256"]))
        old_ref = self.freeze["prior_contract"]
        if old_ref["path"] != OLD_CONTRACT:
            raise ValueError("OWNER_PRIOR_CONTRACT_IDENTITY")
        old = json.loads(read_hashed(_safe(self.repo, OLD_CONTRACT), old_ref["sha256"]))
        if any(k not in self.contract or k not in old
               or canonical(self.contract[k]) != canonical(old[k])
               for k in ECONOMIC_CONTRACT_KEYS):
            raise ValueError("OWNER_FROZEN_ECONOMIC_SEMANTICS_CHANGED")
        authority = old["source_authority_hashes"]
        if any(code.get(path) != expected for path, expected in authority.items()):
            raise ValueError("OWNER_SOURCE_AUTHORITY_PIN_INCOMPLETE")
        for partition, bounds in PARTITIONS.items():
            p = self.contract["partitions"][partition]
            if (p["start_index"], p["end_exclusive"]) != bounds:
                raise ValueError("OWNER_PARTITION_DRIFT")
        calibration_ref = self.freeze["calibration_receipt"]
        calibration_path = _safe(self.repo, calibration_ref["path"])
        if calibration_path != self.root / "calibration/OBSERVED_WS_REST_TIMESTAMP_RECEIPT.json":
            raise ValueError("OWNER_CALIBRATION_RECEIPT_IDENTITY")
        # The semantic validator checks raw REST and WS witness bindings before
        # normalized historical data is ever decoded by this owner.
        self.calibration = _semantic_receipt(calibration_path, calibration_ref["sha256"])
        lane_transforms = {
            "OBJECT_TIME_OPEN": "IDENTITY_NATIVE_OBJECT_TIME_MS",
            "ARRAY_OPEN_CLOSE": "IDENTITY_NATIVE_ARRAY_OPEN_MS",
        }
        lane_close_rules = {
            "OBJECT_TIME_OPEN": "OPEN_PLUS_HOUR_MINUS_1_MS",
            "ARRAY_OPEN_CLOSE": "IDENTITY_NATIVE_ARRAY_CLOSE_MS",
        }
        if (self.calibration.get("schema") != "trendrider.observed.ws.rest.timestamp.receipt.v1"
                or self.calibration.get("state") != "PASS"
                or self.calibration.get("supported_canonical_lane") not in lane_transforms
                or self.calibration.get("canonical_open_transform") != lane_transforms.get(
                    self.calibration.get("supported_canonical_lane"))
                or self.calibration.get("open_ts_rule") != "native_T"
                or self.calibration.get("close_ts_rule") != "open_ts + 1h"
                or self.calibration.get("provider_native_close_claim") is not False
                or self.calibration.get("outcome_independent") is not True
                or self.calibration.get("hour_ms") != 3_600_000
                or self.calibration.get("timestamp_adjustment_ms") != 0):
            raise ValueError("OWNER_CALIBRATION_NOT_REST_WS_PASS")
        authorization_ref = self.freeze["source_authorization"]
        self.source_authorization = json.loads(read_hashed(
            _safe(self.repo, authorization_ref["path"]), authorization_ref["sha256"]))
        from backend.research.rebuild.trendrider_common_source_v1 import canonical_bytes as source_canonical_bytes
        expected_authorization = {
            "schema": "trendrider.common.source.authorization.v6", "scope_key": SCOPE,
            "state": "AUTHORIZED_SOURCE_ONCE",
            "contract_sha256": contract_ref["sha256"],
            "timestamp_semantic_receipt_sha256": calibration_ref["sha256"],
            "dataset_fetch_attempts": 1, "max_pages_per_symbol": 3, "max_http_requests": 6,
            "retry_authorized": False,
        }
        expected_authorization["receipt_sha256"] = sha256(
            source_canonical_bytes(expected_authorization)).hexdigest()
        if canonical(self.source_authorization) != canonical(expected_authorization):
            raise ValueError("OWNER_SOURCE_AUTHORIZATION_BINDING")
        data_ref = self.freeze["data_freeze"]
        data_path = _safe(self.repo, data_ref["path"])
        if data_path != self.root / "source_data/DATA_FREEZE_V6.json":
            raise ValueError("OWNER_DATA_FREEZE_V6_REQUIRED")
        self.data_freeze = json.loads(read_hashed(data_path, data_ref["sha256"]))
        if (self.data_freeze.get("schema") != "trendrider.common.source.freeze.v6"
                or self.data_freeze.get("timestamp_semantic_receipt_sha256") != calibration_ref["sha256"]
                or self.data_freeze.get("source_authorization_sha256") != authorization_ref["sha256"]):
            raise ValueError("OWNER_SOURCE_CALIBRATION_BINDING")
        if any(self.data_freeze.get(key) != self.calibration.get(key) for key in (
                "supported_canonical_lane", "canonical_open_transform", "open_ts_rule", "close_ts_rule")):
            raise ValueError("OWNER_SOURCE_CANONICAL_LANE_DRIFT")
        # This field describes legacy historical-bar serialization only. The
        # interval boundary above is not a claim of a provider native close.
        if self.data_freeze.get("canonical_close_rule") != lane_close_rules.get(
                self.calibration.get("supported_canonical_lane")):
            raise ValueError("OWNER_SOURCE_LEGACY_CLOSE_SERIALIZATION_DRIFT")
        if (self.data_freeze.get("provider_native_close_claim") is not False
                or self.data_freeze.get("canonical_close_metadata_role") != "LEGACY_SOURCE_SERIALIZATION_ONLY"
                or self.data_freeze.get("economic_close_delta_ms") != 3_600_000
                or self.data_freeze.get("canonical_timestamp_offset_ms") != 0):
            raise ValueError("OWNER_SOURCE_INTERVAL_BOUNDARY_DRIFT")
        if self.data_freeze.get("dataset_sha256") != sha256(source_canonical_bytes(self.data_freeze["normalized"])).hexdigest():
            raise ValueError("OWNER_DATASET_HASH_DRIFT")
        if self.data_freeze.get("state") != "FROZEN_COMMON_HISTORICAL_DEV":
            raise ValueError("OWNER_SOURCE_NOT_FROZEN")
        self.bars = {}
        normalized = self.freeze["normalized_files"]
        if set(normalized) != {"BTC-USDT", "ETH-USDT"}:
            raise ValueError("OWNER_SYMBOL_DRIFT")
        for symbol, ref in normalized.items():
            recorded = self.data_freeze["normalized"][symbol]
            path = _safe(self.repo, ref["path"])
            if recorded["sha256"] != ref["sha256"] or path != _safe(data_path.parent, recorded["path"]):
                raise ValueError("OWNER_NORMALIZED_SOURCE_BINDING")
            self.bars[symbol] = json.loads(read_hashed(path, ref["sha256"]))
        _engine().validate_bars(self.bars)
        expected_clock = list(range(1784448000000, 1788048000000, 3_600_000))
        for rows in self.bars.values():
            if [int(r["ts_ms"]) for r in rows] != expected_clock:
                raise ValueError("OWNER_EXACT_DATA_CLOCK")
        self.cost = self.contract["common_cost"]
        if _engine().validate_cost(self.cost) != 14 or self.cost["exact_2x_round_trip_bps"] != 28:
            raise ValueError("OWNER_COST_DRIFT")
        if digest(self.cost) != self.contract["common_cost_sha256"]:
            raise ValueError("OWNER_COST_HASH_DRIFT")
        self.policy_shas = {lane: self.contract["policies"][lane]["sha256"] for lane in POLICIES}

    def save(self, relative: str, value: Any) -> dict[str, Any]:
        result_sha = write_once(_safe(self.root, relative), value)
        receipt = {"scope_key": SCOPE, "path": relative, "sha256": result_sha,
                   "input_freeze_sha256": self.freeze_sha, "written_at_utc": _utc()}
        write_once(_safe(self.root, "output_receipts/" + relative.replace("/", "__")), receipt)
        return value

    def load(self, relative: str) -> Any:
        receipt = json.loads(_safe(self.root, "output_receipts/" + relative.replace("/", "__")).read_bytes())
        if receipt["input_freeze_sha256"] != self.freeze_sha or receipt["path"] != relative:
            raise ValueError("OWNER_OUTPUT_BINDING")
        return json.loads(read_hashed(_safe(self.root, relative), receipt["sha256"]))

    def run(self, kind: str, run_id: str, output: str, function: Callable[[], Any]) -> Any:
        self.root.mkdir(parents=True, exist_ok=True)
        execution_lock = self.root / "EXECUTION.lock"
        fd = os.open(execution_lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.close(fd)
        try:
            reservation = reserve(self.root, kind, run_id, self.freeze_sha)
            try:
                result = function()
                self.save(output, result)
                write_once(self.root / "completions" / reservation.name,
                           {"kind": kind, "run_id": run_id, "state": "COMPLETED",
                            "output_path": output, "output_sha256": sha256(_safe(self.root, output).read_bytes()).hexdigest(),
                            "input_freeze_sha256": self.freeze_sha, "completed_at_utc": _utc()})
                return result
            except Exception as exc:
                write_once(self.root / "failures" / reservation.name,
                           {"kind": kind, "run_id": run_id, "state": "FAILED_BUDGET_CONSUMED",
                            "error_type": type(exc).__name__, "reason": str(exc), "retry_authorized": False})
                raise
        finally:
            execution_lock.unlink()

    def barrier(self, receipt_path: str | Path | None, stage: str, relative: str) -> Mapping[str, Any]:
        if receipt_path is None:
            raise ValueError("OWNER_REMOTE_FREEZE_BARRIER_REQUIRED")
        receipt = json.loads(Path(receipt_path).read_bytes())
        if (receipt.get("stage") != stage or receipt.get("readback_verified") is not True
                or receipt.get("input_freeze_sha256") != self.freeze_sha
                or not re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("verified_commit_sha")))):
            raise ValueError("OWNER_REMOTE_FREEZE_BARRIER_INVALID")
        expected = receipt.get("files", {}).get(relative)
        read_hashed(_safe(self.root, relative), expected)
        return receipt

    def stage0(self) -> dict[str, Any]:
        if list((self.root / "reservations").glob("*.json")):
            raise ValueError("OWNER_STAGE0_ALREADY_STARTED_NO_RETRY")
        signals = _engine().build_signals(self.bars, self.cost, self.policy_shas)
        self.save("SIGNALS.json", signals)
        results = {}
        for partition, (lo, hi) in PARTITIONS.items():
            for lane in POLICIES:
                name = f"{partition}__{lane}"
                results[name] = self.run("CONTROL", name, f"controls/{name}.json",
                    lambda p=partition, start=lo, end=hi, l=lane:
                    _engine().replay(signals, self.bars, p, start, end, l, self.cost))
        # DEV_B outcomes are saved above but deliberately absent from stdout
        # and from the DEV_A selection input. They are not used to select A.
        summary = {"state": "FOUR_CONTROLS_COMPLETE", "control_runs": 4,
                   "DEV_A": {lane: results[f"DEV_A__{lane}"]["metrics"] for lane in POLICIES},
                   "DEV_A_overlap": raw_and_executed_overlap(signals, results["DEV_A__B_COMMON"], results["DEV_A__P_COMMON"]),
                   "DEV_B_outcomes_disclosed": False}
        return self.save("STAGE0_RECEIPT.json", summary)

    def stage1a(self) -> dict[str, Any]:
        if self.load("STAGE0_RECEIPT.json")["control_runs"] != 4:
            raise ValueError("OWNER_CONTROLS_INCOMPLETE")
        signals = self.load("SIGNALS.json")
        saved_b = self.load("controls/DEV_A__B_COMMON.json")
        reports = []
        for gene_id in _genes().GENES:
            short = gene_id.split("_", 1)[0]
            reports.append(self.run("SCREEN_A", short, f"screens_A/{gene_id}.json",
                lambda g=gene_id: _genes().screen(saved_b, signals, "DEV_A", g)))
        selection = _genes().select_a(reports)
        return self.save("SELECTION_A.json", selection)

    def stage1b(self, remote_receipt: str | Path | None) -> dict[str, Any]:
        self.barrier(remote_receipt, "A_SELECTION", "SELECTION_A.json")
        selection = self.load("SELECTION_A.json")
        if not selection["ordered_survivors"]:
            raise ValueError("OWNER_NO_A_SURVIVORS_NO_B_CONFIRMATION")
        signals = self.load("SIGNALS.json")
        saved_b = self.load("controls/DEV_B__B_COMMON.json")
        reports = []
        for gene_id in selection["ordered_survivors"]:
            short = gene_id.split("_", 1)[0]
            reports.append(self.run("CONFIRM_B", short, f"confirmations_B/{gene_id}.json",
                lambda g=gene_id: _genes().screen(saved_b, signals, "DEV_B", g)))
        confirmation = _genes().confirm_b(selection, reports)
        self.save("CONFIRMATION_B.json", confirmation)
        candidates = {}
        if confirmation["confirmed_A_order"]:
            candidates["U1"] = {"gene_ids": [confirmation["best_gene"]], "operator": "AND"}
        if confirmation["U2_orthogonal"]:
            candidates["U2"] = {"gene_ids": confirmation["confirmed_A_order"], "operator": "AND"}
        return self.save("CANDIDATE_IDENTITIES.json", {"candidates": candidates,
            "confirmation_B_receipt": confirmation["receipt_sha"], "selection_A_receipt": selection["receipt_sha"],
            "input_freeze_sha256": self.freeze_sha, "barrier_next": "REMOTE_COMMIT_AND_READBACK_BEFORE_FIRST_CHILD_FULL"})

    def stage2(self, remote_receipt: str | Path | None) -> dict[str, Any]:
        self.barrier(remote_receipt, "CANDIDATE_IDENTITIES", "CANDIDATE_IDENTITIES.json")
        identities = self.load("CANDIDATE_IDENTITIES.json")
        candidates = identities["candidates"]
        if not candidates:
            raise ValueError("OWNER_NO_CONFIRMED_CANDIDATE_NO_FULL")
        signals = self.load("SIGNALS.json")
        reports = {}
        for candidate_id, definition in candidates.items():
            windows = {}
            gene_ids = definition["gene_ids"]
            for partition, (lo, hi) in PARTITIONS.items():
                name = f"{partition}__{candidate_id}"
                child = self.run("CHILD_FULL", name, f"children/{name}.json",
                    lambda p=partition, start=lo, end=hi, gs=gene_ids:
                    _engine().replay(signals, self.bars, p, start, end,
                        lambda snap: _genes().union_admission(snap, gs), self.cost))
                windows[partition] = child_gate(self.load(f"controls/{partition}__P_COMMON.json"),
                    self.load(f"controls/{partition}__B_COMMON.json"), child, signals, gene_ids)
            reports[candidate_id] = {"gene_ids": gene_ids, "windows": windows}
        return self.save("CHILD_REPORTS.json", reports)

    def budget(self) -> dict[str, Any]:
        paths = list((self.root / "reservations").glob("*.json"))
        reservations = [json.loads(p.read_bytes()) for p in paths]
        counts = Counter(r["kind"] for r in reservations)
        completed = {p.name for p in (self.root / "completions").glob("*.json")}
        failed = {p.name for p in (self.root / "failures").glob("*.json")}
        uncompleted = {p.name for p in paths} - completed - failed
        return {"control_runs": counts["CONTROL"], "DEV_A_screens": counts["SCREEN_A"],
                "DEV_B_confirmations": counts["CONFIRM_B"], "child_FULL_runs": counts["CHILD_FULL"],
                "canonical_candidates": len({r["run_id"].rsplit("__", 1)[1] for r in reservations if r["kind"] == "CHILD_FULL"}),
                "completed_runs": len(completed), "failed_runs": len(failed),
                "reserved_incomplete_runs": len(uncompleted),
                "reserved_incomplete_ids": sorted(uncompleted),
                "retries": 0, "sweep": 0, "paid_AI": 0, "live": 0, "orders": 0, "deploy": 0}

    def final(self) -> dict[str, Any]:
        if list((self.root / "failures").glob("*.json")):
            raise ValueError("OWNER_FAILED_EXECUTION_REQUIRES_EXPLICIT_BLOCKED_REPORT")
        if self.budget()["reserved_incomplete_runs"]:
            raise ValueError("OWNER_INCOMPLETE_EXECUTION_REQUIRES_EXPLICIT_BLOCKED_REPORT")
        selection = self.load("SELECTION_A.json")
        result = {"scope_key": SCOPE, "input_freeze_sha256": self.freeze_sha,
                  "source_dataset_sha256": self.data_freeze["dataset_sha256"],
                  "calibration_receipt": self.freeze["calibration_receipt"],
                  "data_normalized_sha256": {s: r["sha256"] for s, r in self.freeze["normalized_files"].items()},
                  "cost_sha256": self.contract["common_cost_sha256"], "policy_shas": self.policy_shas,
                  "formal_credit": 0, "production_grade": False, "budget": self.budget()}
        if not selection["ordered_survivors"]:
            result.update(state="NO_CAUSAL_UNIFIED_GENE_COMMON_REPLAY", selected_candidate=None,
                          unified_state="TREND_RIDER_UNIFIED_NOT_EARNED_COMMON_REPLAY", child_economics="NOT_RUN")
        else:
            identities = self.load("CANDIDATE_IDENTITIES.json")
            if not identities["candidates"]:
                result.update(state="NO_CAUSAL_UNIFIED_GENE_COMMON_REPLAY", selected_candidate=None,
                              unified_state="TREND_RIDER_UNIFIED_NOT_EARNED_COMMON_REPLAY", child_economics="NOT_RUN")
            else:
                reports = self.load("CHILD_REPORTS.json")
                if set(reports) != set(identities["candidates"]):
                    raise ValueError("OWNER_CHILD_REPORT_IDENTITIES_MISMATCH")
                result.update(choose_final(reports))
                result["child_economics"] = "COMPLETED"
                if result["selected_candidate"]:
                    result["unified_exact_seal"] = {"candidate_id": result["selected_candidate"],
                        "definition": identities["candidates"][result["selected_candidate"]],
                        "code_files": self.freeze["code_files"], "contract": self.freeze["contract"],
                        "data_freeze": self.freeze["data_freeze"], "normalized_files": self.freeze["normalized_files"],
                        "calibration_receipt": self.freeze["calibration_receipt"],
                        "cost_sha256": self.contract["common_cost_sha256"], "policy_shas": self.policy_shas,
                        "selection_A_receipt": selection["receipt_sha"],
                        "confirmation_B_receipt": identities["confirmation_B_receipt"]}
        signals = self.load("SIGNALS.json")
        result["controls"] = {}
        result["overlap"] = {}
        for partition in PARTITIONS:
            controls = {lane: self.load(f"controls/{partition}__{lane}.json") for lane in POLICIES}
            result["controls"][partition] = {lane: saved["metrics"] for lane, saved in controls.items()}
            result["overlap"][partition] = raw_and_executed_overlap(signals, controls["B_COMMON"], controls["P_COMMON"])
        result["G5A_handoff_eligible"] = result["selected_candidate"] is not None
        result["G5A_handoff"] = ("ROOT_MUST_SEAL_NEW_FUTURE_BOUNDARY_AFTER_SPRINT; G5A_AND_G5B_TIME_SEPARATED"
                                  if result["selected_candidate"] else "NONE")
        result["G6_authority"] = "BLOCKED_BEFORE_G5B_TERMINAL_PASS"
        result["receipt_sha"] = digest(result)
        return self.save("FINAL_ECONOMIC_RECEIPT.json", result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("stage0", "stage1a", "stage1b", "stage2", "final"))
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--freeze-manifest", required=True)
    parser.add_argument("--freeze-sha", required=True)
    parser.add_argument("--remote-receipt")
    args = parser.parse_args()
    owner = Owner(args.repo_root, args.evidence_root, args.freeze_manifest, args.freeze_sha)
    method = getattr(owner, args.stage)
    result = method(args.remote_receipt) if args.stage in ("stage1b", "stage2") else method()
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
