"""Explicit DEV_EVIDENCE_BUILDING adapter. No formal replay or trading authority."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
from zoneinfo import ZoneInfo

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as evaluator
from backend.research.architecture_factory import g5a_stage_candidate_v1 as parent
from backend.research.architecture_factory import g5a_development_data_v1 as data_owner
from backend.research.architecture_factory.g5a_source_admission_v1 import ROOT, AUTH, file_sha, read, require_development, seal
from backend.research.rebuild.a1_rebuilt_bb_revert_evaluator_v1 import expected_funding_boundaries

POLICY = "backend/research/contracts/g5a_development_evidence_probe_v1.json"
TERMINAL = "backend/research/architecture_factory/g5a_stage_candidate_terminal_v1.json"
STAGE = "backend/research/architecture_factory/g5a_stage_admission_latest_v1.json"
OUTPUT = "research/development_evidence/G5A_DEV_STAPC001_001"
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
MONDAY_MS = 4 * DAY_MS
DEV_AUTH = {"formal_credit": 0, "G5A_economic_PASS": False,
            "g5b_entry_authorized": False, "g5b_fresh_boundary_created": False,
            "new_alpha_candidate": False, **AUTH}
STATE_MAP = {
    "DEV_SCREEN_REJECT": "MEASURED_DEVELOPMENT_ONLY_REJECT",
    "DEV_INCONCLUSIVE": "MEASURED_DEVELOPMENT_ONLY_INCONCLUSIVE",
    "DEV_SCREEN_PROMISING_P0_UNRESOLVED": "MEASURED_DEVELOPMENT_ONLY_PROMISING",
    "BLOCKED_DATA_OR_IMPLEMENTATION": "DEVELOPMENT_INPUT_OR_IMPLEMENTATION_BLOCKED",
    "BLOCKED_AUTHORITY": "DEVELOPMENT_AUTHORIZATION_BLOCKED",
}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def verify_seal(value, label):
    if value.get("receipt_sha256") != alpha.sha({k: v for k, v in value.items() if k != "receipt_sha256"}):
        raise RuntimeError(label + "_SEAL")


def authorize(policy, terminal, stage, root=ROOT):
    verify_seal(policy, "POLICY")
    if policy.get("mode") != "DEV_EVIDENCE_BUILDING" or policy.get("authorization") != "EXPLICIT_USER_DEVELOPMENT_ONLY":
        raise RuntimeError("BLOCKED_AUTHORITY")
    if any(policy.get(k) != v for k, v in DEV_AUTH.items()):
        raise RuntimeError("BLOCKED_AUTHORITY")
    if policy.get("outcomes_observed_at_freeze") is not False or policy.get("experiment_budget") != 1:
        raise RuntimeError("BLOCKED_AUTHORITY:EXPERIMENT_FREEZE")
    if policy["enum_mapping"] != STATE_MAP:
        raise RuntimeError("DEVELOPMENT_ENUM_DRIFT")
    verify_seal(terminal, "PARENT_TERMINAL")
    candidate = terminal["candidate"]
    if candidate["candidate_sha256"] != alpha.sha({k: v for k, v in candidate.items() if k != "candidate_sha256"}):
        raise RuntimeError("PARENT_CANDIDATE_IDENTITY")
    if (candidate["candidate_sha256"] != policy["parent_candidate_sha256"] or candidate["candidate_id"] != policy["parent_candidate"]
            or terminal["receipt_sha256"] != policy["parent_terminal_sha256"]
            or terminal["decision"] != "G5A_ALPHA_PROOF_REJECT" or terminal["economic_state"] != "NOT_RUN_PRIOR_GATE_REJECT"):
        raise RuntimeError("PARENT_TERMINAL_IDENTITY")
    dev = require_development(stage, root)
    if dev["receipt_sha256"] != candidate["development_cost_binding_sha256"] or dev["dataset_sha256"] != policy["dataset_sha256"]:
        raise RuntimeError("DEVELOPMENT_DATA_COST_IDENTITY")
    if dev["splits"]["development"] != policy["development_interval_ms"] or alpha.sha(dev["splits"]) != candidate["split_sha256"]:
        raise RuntimeError("DEVELOPMENT_SPLIT_IDENTITY")
    for path, digest in {**policy["immutable_files_sha256"], **policy["code_files_sha256"]}.items():
        if file_sha(root / path) != digest:
            raise RuntimeError("DEVELOPMENT_CODE_CONFIG_IDENTITY:" + path)
    if candidate["implementation_sha256"] != file_sha(root / "backend/research/architecture_factory/g5a_stage_candidate_v1.py"):
        raise RuntimeError("PARENT_IMPLEMENTATION_IDENTITY")
    for fn in (alpha.evaluate_p6, alpha.evaluate_p1, alpha.evaluate_p2):
        if not fn(terminal["bundle"])["passed"]:
            raise RuntimeError("DEVELOPMENT_PREFLIGHT:" + fn.__name__)
    # P0 remains unresolved. Neither require_before_cheap nor freeze_candidate is altered or called.
    return dev, candidate["parameters"]


def prefix_rows(path, count):
    """Decode exactly the chronological prefix; never decode a holdout object.

    Complete-file SHA validation elsewhere is an opaque byte checksum, not a
    read of holdout price values. The evaluator receives this prefix only.
    """
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        if stream.read(1) != "[":
            raise RuntimeError("DEVELOPMENT_ARRAY_REQUIRED")
        for _ in range(count):
            char = stream.read(1)
            while char and (char.isspace() or char == ","):
                char = stream.read(1)
            if char != "{":
                raise RuntimeError("DEVELOPMENT_PREFIX_MISSING")
            buffer = [char]; depth = 1; quoted = escaped = False
            while depth:
                char = stream.read(1)
                if not char:
                    raise RuntimeError("DEVELOPMENT_PREFIX_TRUNCATED")
                buffer.append(char)
                if quoted:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        quoted = False
                elif char == '"':
                    quoted = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
            rows.append(json.loads("".join(buffer)))
    return rows


def load_development(dataset_dir, policy, dev):
    manifest = json.loads((dataset_dir / "development_manifest.json").read_text())
    verify_seal(manifest, "DATA_MANIFEST")
    if (manifest["receipt_sha256"] != policy["manifest_sha256"] or manifest["dataset_sha256"] != policy["dataset_sha256"]
            or alpha.sha(manifest["dataset_files"]) != manifest["dataset_sha256"]
            or manifest["splits"] != dev["splits"] or manifest["outcomes_computed"] is not False):
        raise RuntimeError("DEVELOPMENT_MANIFEST_IDENTITY")
    if set(manifest["symbols"]) != set(policy["symbols"]) or set(dev["cost_by_symbol"]) != set(policy["symbols"]):
        raise RuntimeError("DEVELOPMENT_UNIVERSE_IDENTITY")
    start, end = policy["development_interval_ms"]; interval = policy["interval_ms"]
    count = (end - start) // interval
    rows_by = {}; source_access = {}
    for symbol in policy["symbols"]:
        relative = "ohlcv/" + symbol + ".json"
        path = dataset_dir / relative
        # Hash bytes without interpreting validation/OOS prices; raw archive is not opened.
        if file_sha(path) != manifest["dataset_files"][relative]:
            raise RuntimeError("DEVELOPMENT_SOURCE_BYTES_IDENTITY")
        rows = prefix_rows(path, count)
        evaluator.evaluate_development_events(rows, [], split_start_ms=start, split_end_ms=end,
                                             interval_ms=interval, hold_bars=1)
        if rows[0]["bar_open_ts"] != start or rows[-1]["bar_close_ts"] != end:
            raise RuntimeError("DEVELOPMENT_PREFIX_COVERAGE")
        snapshot_ref = manifest["cost_snapshots"][symbol]
        cost_path = dataset_dir / snapshot_ref["path"]
        if file_sha(cost_path) != snapshot_ref["sha256"]:
            raise RuntimeError("DEVELOPMENT_COST_BYTES_IDENTITY")
        snapshot = json.loads(cost_path.read_text())["snapshot"]
        if snapshot["snapshot_sha256"] != alpha.sha({k: v for k, v in snapshot.items() if k != "snapshot_sha256"}):
            raise RuntimeError("DEVELOPMENT_COST_SNAPSHOT_SEAL")
        cost = dev["cost_by_symbol"][symbol]
        if (cost["snapshot_sha256"] != snapshot["snapshot_sha256"] or cost["spread_bps"] != snapshot["charged_spread_round_trip_bps"]
                or cost["impact_bps"] != snapshot["charged_impact_round_trip_bps"] or cost["funding_p95_per_settlement_bps"] != snapshot["funding_p95_abs_bps"]):
            raise RuntimeError("DEVELOPMENT_COST_BINDING_PARITY")
        rows_by[symbol] = rows
        source_access[symbol] = {"decoded_partition": "development", "decoded_rows": len(rows), "decoded_validation_rows": 0,
                                 "decoded_OOS_rows": 0, "opaque_complete_file_checksum_only": True,
                                 "first_open_ms": start, "last_close_ms": end, "development_rows_sha256": alpha.sha(rows)}
    return rows_by, source_access


@contextmanager
def io_boundary(read_paths, output):
    """Deny network/process access and all non-allowlisted data I/O in the probe."""
    allowed = {str(Path(p).resolve()) for p in read_paths}
    output = Path(output).resolve(); enabled = [True]
    filenames = {"trades.jsonl.gz", "events.jsonl.gz", "feature_exclusions.jsonl.gz", "receipt.json"}
    def guard(event, args):
        if not enabled[0]:
            return
        if event.startswith(("socket.", "subprocess.", "urllib.")) or event in {"os.system", "os.fork", "os.posix_spawn"}:
            raise RuntimeError("DEVELOPMENT_NETWORK_OR_PROCESS_FORBIDDEN")
        if event == "open" and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).resolve()
            flags = args[2] if len(args) > 2 else 0
            writing = flags is not None and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            own_output = path.parent == output and path.name in filenames
            if writing and not own_output:
                raise RuntimeError("DEVELOPMENT_WRITE_FORBIDDEN")
            if not writing and not own_output and str(path) not in allowed and not str(path).startswith("/usr/share/zoneinfo/"):
                raise RuntimeError("DEVELOPMENT_READ_FORBIDDEN:" + str(path))
    sys.addaudithook(guard)
    try:
        yield
    finally:
        enabled[0] = False


def cost_components(entry_ms, exit_ms, binding):
    count = expected_funding_boundaries(entry_ms, exit_ms)
    parts = {"fee_bps": binding["fee_bps"], "spread_bps": binding["spread_bps"], "impact_bps": binding["impact_bps"],
             "slippage_bps": 0.0, "funding_bps": count * binding["funding_p95_per_settlement_bps"]}
    if any(not math.isfinite(float(x)) or x < 0 for x in parts.values()):
        raise RuntimeError("DEVELOPMENT_COST_INVALID")
    total = parent.development_cost(entry_ms, exit_ms, binding)
    if not math.isclose(sum(parts.values()), total, rel_tol=1e-12, abs_tol=1e-12):
        raise RuntimeError("DEVELOPMENT_COST_DOUBLE_CHARGE_OR_OMISSION")
    return {**parts, "cost_bps": total, "funding_settlements_crossed": count,
            "slippage_included_in_impact": True, "cost_scope": "RESEARCH_ONLY_DEVELOPMENT_COST"}


def stamp_year(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).year


def week(ts):
    return (ts - MONDAY_MS) // WEEK_MS


def feature_rows(rows, spec):
    values = [parent.features(rows, i, spec) for i in range(len(rows))]
    for i, value in enumerate(values):
        if value is None and i >= spec["lookback_bars"]:
            # Preserve parent's undefined-volume base, but removing volume must
            # also remove its denominator dependency from diagnostic controls.
            values[i] = {"session_overlap_state": parent.session_overlap(rows[i], spec),
                         "relative_total_volume_activity": None,
                         "pre_entry_breakout_continuation_structure": rows[i]["close"] > max(r["high"] for r in rows[i-spec["lookback_bars"]:i])}
    return values


def scenario_signals(rows, features, policy, spec):
    eligible = [i for i, f in enumerate(features) if f is not None]
    session = {i: features[i]["session_overlap_state"] for i in eligible}
    groups = defaultdict(list)
    for i in eligible:
        ts = rows[i]["bar_open_ts"]
        groups[(stamp_year(ts), ts % DAY_MS)].append(i)
    permuted = dict(session)
    for key, indices in sorted(groups.items()):
        labels = [session[i] for i in indices]
        random.Random(str(policy["controls"]["seed"]) + ":" + str(key)).shuffle(labels)
        permuted.update(zip(indices, labels))
    result = {name: [] for name in policy["scenarios"] if name != "baseline_exposure_matched"}
    for i in eligible:
        f = features[i]
        volume = f["relative_total_volume_activity"]
        a, b, c = session[i], volume is not None and volume > spec["relative_volume_min_exclusive"], f["pre_entry_breakout_continuation_structure"]
        decisions = {"base": a and b and c, "ablation_session": b and c, "ablation_volume": a and c,
                     "ablation_breakout": a and b, "baseline_breakout": c, "regime_permutation": permuted[i] and b and c}
        for name, yes in decisions.items():
            if yes:
                result[name].append(i)
        if decisions["base"]:
            for name in ("direction_flip", "time_shift_placebo", "delayed_entry"):
                result[name].append(i)
    return result


def attach_trade(raw, symbol, scenario, policy, dev, spec, source_rows):
    costs = cost_components(raw["entry_ts"], raw["exit_ts"], dev["cost_by_symbol"][symbol])
    signal = source_rows[raw["signal_index"]]
    entry_bar = {"bar_open_ts": raw["entry_ts"], "bar_close_ts": raw["entry_ts"] + 1}
    value = {**raw, **costs, "symbol": symbol, "scenario": scenario,
             "experiment_id": policy["experiment_id"], "parent_candidate": policy["parent_candidate"],
             "candidate_sha256": policy["parent_candidate_sha256"], "config_sha256": policy["receipt_sha256"],
             "code_sha256": alpha.sha(policy["code_files_sha256"]), "data_sha256": policy["dataset_sha256"],
             "cost_sha256": dev["receipt_sha256"], "split": "development", "fill_kind": "MODELLED_NEXT_BAR_OPEN_AND_TIME_STOP_CLOSE",
             "observation_time_semantics": "SIGNAL_BAR_CLOSE; OPEN_FILL_IS_ZERO_COMPUTE_LATENCY_MODEL; DELAY_CONTROL_SEPARATE",
             "signal_bar_any_session_overlap": parent.session_overlap(signal, spec),
             "modelled_entry_inside_session_overlap": parent.session_overlap(entry_bar, spec),
             "gross_bps": raw["gross_bps"], "net_bps": raw["gross_bps"] - costs["cost_bps"],
             "cost2x_net_bps": raw["gross_bps"] - parent.development_cost(raw["entry_ts"], raw["exit_ts"], dev["cost_by_symbol"][symbol], multiplier=2),
             "risk_model": "ONE_EQUAL_NOTIONAL_SLOT_PER_SYMBOL_MAX_ONE_OPEN; NO_ACCOUNT_RETURN_CLAIM",
             "exclusion_reason": None, **DEV_AUTH}
    value["trade_sha256"] = alpha.sha(value)
    return value


def summarize(trades, *, start_ms, end_ms, symbol_count, cost2x=False):
    ordered = sorted(trades, key=lambda t: (t["exit_ts"], t["symbol"], t["signal_ts"]))
    key = "cost2x_net_bps" if cost2x else "net_bps"
    values = [t[key] for t in ordered]; wins = [x for x in values if x > 0]; losses = [x for x in values if x < 0]
    n = len(values); days = (end_ms - start_ms) / DAY_MS
    exposure = sum(t["hold_ms"] for t in trades) / DAY_MS
    return {"completed_T": n, "N_raw": n, "net_bps": sum(values), "gross_bps": sum(t["gross_bps"] for t in trades),
            "expectancy_bps_per_trade": sum(values) / n if n else None, "PF": evaluator._pf(values),
            "win_rate": len(wins) / n if n else None, "average_win_bps": sum(wins) / len(wins) if wins else None,
            "average_loss_bps": sum(losses) / len(losses) if losses else None, "realized_payoff": evaluator._payoff(values),
            "payoff_basis": "NET_WIN_MEAN_DIVIDED_BY_ABS_NET_LOSS_MEAN", "avgR": None,
            "DD_trade_sum_bps": evaluator._dd(values) if n else None,
            "DD_definition": "PEAK_TO_TROUGH_CUMULATIVE_CLOSED_TRADE_BPS_ORDERED_BY_EXIT; NOT_ACCOUNT_DD",
            "exposure_symbol_days": exposure, "time_in_market_fraction": exposure / (symbol_count * days),
            "net_bps_per_exposure_day": sum(values) / exposure if exposure else None,
            "mean_holding_hours": exposure * 24 / n if n else None, "completed_trade_rate_per_day": n / days,
            "wins": len(wins), "losses": len(losses), "flat": sum(x == 0 for x in values),
            "entry_outside_overlap_T": sum(not t.get("modelled_entry_inside_session_overlap", False) for t in trades)}


def quantile(values, p):
    values = sorted(values)
    if not values:
        return None
    point = (len(values) - 1) * p; low = math.floor(point); high = math.ceil(point)
    return values[low] + (values[high] - values[low]) * (point - low)


def cluster_uncertainty(trades_by, policy):
    start, end = policy["development_interval_ms"]
    weeks = list(range(week(start), week(end - 1) + 1))
    aggregates = {}
    for name, trades in trades_by.items():
        groups = defaultdict(lambda: [0.0, 0])
        for trade in trades:
            group = groups[week(trade["entry_ts"])]; group[0] += trade["net_bps"]; group[1] += 1
        aggregates[name] = groups
    draws = {name: [] for name in trades_by}; deltas = {name: [] for name in trades_by if name != "base"}
    rng = random.Random(policy["uncertainty"]["seed"])
    for _ in range(policy["uncertainty"]["replications"]):
        sample = [rng.choice(weeks) for _ in weeks]; means = {}
        for name, groups in aggregates.items():
            net = sum(groups[w][0] for w in sample); count = sum(groups[w][1] for w in sample)
            means[name] = net / count if count else None
            if count:
                draws[name].append(means[name])
        for name in deltas:
            if means["base"] is not None and means[name] is not None:
                deltas[name].append(means["base"] - means[name])
    return {"method": policy["uncertainty"]["method"], "calendar_week_blocks": len(weeks), "N_effective": None,
            "limitations": "WEEK_CLUSTERS_ARE_A_DEPENDENCE_APPROXIMATION; NOT_PROVEN_INDEPENDENT; DEVELOPMENT_ONLY; NO_MULTIPLE_COMPARISON_FORMAL_CLAIM",
            "intervals": {name: {"expectancy_95pct_interval_bps": [quantile(xs, .025), quantile(xs, .975)],
                                 "nonempty_resamples": len(xs), "nonempty_week_clusters": len({week(t["entry_ts"]) for t in trades_by[name]})}
                          for name, xs in draws.items()},
            "paired_base_minus_control_95pct_interval_bps": {name: [quantile(xs, .025), quantile(xs, .975)] for name, xs in deltas.items()}}


def decide(metrics, uncertainty, policy):
    base = metrics["base"]["base_cost"]; stress = metrics["base"]["cost2x"]
    if base["completed_T"] == 0:
        return "DEV_INCONCLUSIVE", ["MEASURED_NO_EVENTS" if metrics["base"].get("event_count", 0) == 0 else "MEASURED_NO_COMPLETED_TRADES"]
    if base["PF"] is None or base["expectancy_bps_per_trade"] is None:
        return "DEV_INCONCLUSIVE", ["UNDEFINED_PAYOFF_OR_PROFIT_FACTOR"]
    rules = policy["development_kill_rules"]
    failures = []
    if base["expectancy_bps_per_trade"] <= 0:
        failures.append("NONPOSITIVE_DEVELOPMENT_EXPECTANCY")
    if base["PF"] <= rules["profit_factor_must_exceed"]:
        failures.append("DEVELOPMENT_PF_NOT_ABOVE_SSOT")
    if stress["net_bps"] <= 0:
        failures.append("COST2X_DEVELOPMENT_NET_NOT_POSITIVE")
    if failures:
        return "DEV_SCREEN_REJECT", failures
    controls = [name for name in metrics if name != "base"]
    missing = [name for name in controls if metrics[name]["base_cost"]["expectancy_bps_per_trade"] is None or metrics[name].get("comparison_valid") is False]
    if missing:
        return "DEV_INCONCLUSIVE", ["CONTROL_UNDEFINED:" + x for x in missing]
    adverse = [name for name in controls if base["expectancy_bps_per_trade"] <= metrics[name]["base_cost"]["expectancy_bps_per_trade"]]
    if adverse:
        return "DEV_SCREEN_REJECT", ["NO_CONDITIONAL_SUPERIORITY:" + name for name in adverse]
    ci = uncertainty["intervals"]["base"]["expectancy_95pct_interval_bps"]
    if ci[0] is None or ci[0] <= 0 or uncertainty["intervals"]["base"]["nonempty_week_clusters"] < 2:
        return "DEV_INCONCLUSIVE", ["CLUSTER_UNCERTAINTY_INCLUDES_NONPOSITIVE_EXPECTANCY"]
    pairs = uncertainty["paired_base_minus_control_95pct_interval_bps"]
    if any(pairs[name][0] is None or pairs[name][0] <= 0 for name in controls):
        return "DEV_INCONCLUSIVE", ["INCREMENTAL_SUPERIORITY_UNCERTAIN_UNDER_PAIRED_WEEK_RESAMPLING"]
    return "DEV_SCREEN_PROMISING_P0_UNRESOLVED", ["DEVELOPMENT_ONLY_REQUIRES_INDEPENDENT_P0_AND_UNTOUCHED_VALIDATION"]


def compute(rows_by, policy, dev, spec):
    trades_by = {}; events = []; feature_exclusions = []; signal_counts = Counter()
    start, end = policy["development_interval_ms"]
    for symbol, rows in rows_by.items():
        features = feature_rows(rows, spec)
        for i, value in enumerate(features):
            if value is None or value["relative_total_volume_activity"] is None:
                feature_exclusions.append({"symbol": symbol, "bar_close_ts": rows[i]["bar_close_ts"],
                                           "reason": "LOOKBACK_WARMUP" if i < spec["lookback_bars"] else "NONPOSITIVE_PRIOR_VOLUME_BASE_AND_VOLUME_DEPENDENT_ONLY", "split": "development"})
        for name, indices in scenario_signals(rows, features, policy, spec).items():
            delay = policy["controls"].get(name + "_delay_bars", 0)
            side = "short" if name == "direction_flip" else spec["side"]
            raw = evaluator.evaluate_development_events(rows, indices, split_start_ms=start, split_end_ms=end,
                                                        interval_ms=policy["interval_ms"], hold_bars=spec["max_hold_bars"],
                                                        entry_delay_bars=delay, side=side)
            trades = [attach_trade(t, symbol, name, policy, dev, spec, rows) for t in raw["trades"]]
            trades_by.setdefault(name, []).extend(trades); signal_counts[name] += len(indices)
            by_index = {t["signal_index"]: t for t in trades}
            rejected = {x["signal_index"]: x["reason"] for x in raw["exclusions"]}
            for i in indices:
                event = {"experiment_id": policy["experiment_id"], "scenario": name, "symbol": symbol,
                         "signal_ts": rows[i]["bar_close_ts"], "signal_index": i, "split": "development",
                         "features": features[i], "status": "COMPLETED" if i in by_index else "EXCLUDED",
                         "exclusion_reason": rejected.get(i), "trade_sha256": by_index[i]["trade_sha256"] if i in by_index else None,
                         "formal_credit": 0}
                events.append(event)
    # Compare equal completed exposure per symbol/year. Hash ranking uses no return values.
    counts = Counter((t["symbol"], stamp_year(t["entry_ts"])) for t in trades_by["base"])
    pool = defaultdict(list)
    for trade in trades_by["baseline_breakout"]:
        pool[(trade["symbol"], stamp_year(trade["entry_ts"]))].append(trade)
    matched = []; match_deficits = []
    for key, count in sorted(counts.items()):
        selected = sorted(pool[key], key=lambda t: alpha.sha([policy["controls"]["seed"], t["symbol"], t["signal_ts"]]))[:count]
        if len(selected) != count:
            match_deficits.append({"symbol_year": key, "required": count, "available": len(selected)})
        for trade in selected:
            value = {**trade, "scenario": "baseline_exposure_matched"}; value.pop("trade_sha256")
            value["trade_sha256"] = alpha.sha(value); matched.append(value)
    trades_by["baseline_exposure_matched"] = matched
    signal_counts["baseline_exposure_matched"] = sum(len(v) for v in pool.values())
    matched_keys = {(t["symbol"], t["signal_ts"]): t for t in matched}
    for trade in trades_by["baseline_breakout"]:
        value = matched_keys.get((trade["symbol"], trade["signal_ts"]))
        events.append({"experiment_id": policy["experiment_id"], "scenario": "baseline_exposure_matched", "symbol": trade["symbol"],
                       "signal_ts": trade["signal_ts"], "signal_index": trade["signal_index"], "split": "development",
                       "status": "COMPLETED" if value else "EXCLUDED", "exclusion_reason": None if value else "EXPOSURE_MATCH_NOT_SELECTED",
                       "trade_sha256": value["trade_sha256"] if value else None, "formal_credit": 0})
    metrics = {}
    for name, trades in trades_by.items():
        common = {"start_ms": start, "end_ms": end, "symbol_count": len(rows_by)}
        metrics[name] = {"event_count": signal_counts[name], "event_rate_per_day": signal_counts[name] / ((end-start)/DAY_MS),
                         "base_cost": summarize(trades, **common), "cost2x": summarize(trades, cost2x=True, **common),
                         "exclusions": dict(Counter(e["exclusion_reason"] for e in events if e["scenario"] == name and e["status"] == "EXCLUDED")),
                         "by_symbol": {s: summarize([t for t in trades if t["symbol"] == s], **{**common, "symbol_count": 1}) for s in rows_by},
                         "by_year": {str(y): summarize([t for t in trades if stamp_year(t["entry_ts"]) == y],
                                     start_ms=max(start, int(datetime(y, 1, 1, tzinfo=timezone.utc).timestamp()*1000)),
                                     end_ms=min(end, int(datetime(y+1, 1, 1, tzinfo=timezone.utc).timestamp()*1000)), symbol_count=len(rows_by))
                                     for y in range(stamp_year(start), stamp_year(end-1)+1)}}
    uncertainty = cluster_uncertainty(trades_by, policy)
    metrics["baseline_exposure_matched"]["comparison_valid"] = not match_deficits
    state, reasons = decide(metrics, uncertainty, policy)
    if match_deficits and state != "DEV_SCREEN_REJECT":
        state, reasons = "DEV_INCONCLUSIVE", ["EXPOSURE_MATCH_INCOMPLETE"]
    return trades_by, events, feature_exclusions, metrics, uncertainty, state, reasons, match_deficits


def write_immutable(path, payload, *, verify_only=False):
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError("DEVELOPMENT_REPRODUCTION_MISMATCH:" + path.name)
    elif verify_only:
        raise RuntimeError("DEVELOPMENT_RECEIPT_MISSING:" + path.name)
    else:
        path.write_bytes(payload)


def run(dataset_dir, output, *, verify_only=False, root=ROOT):
    policy = read(POLICY, root); terminal = read(TERMINAL, root); stage = read(STAGE, root)
    dev, spec = authorize(policy, terminal, stage, root)
    output = output.resolve()
    if output != (root / OUTPUT).resolve():
        raise RuntimeError("DEVELOPMENT_OUTPUT_AUTHORITY_FORBIDDEN")
    if any(p.is_symlink() for p in [root / OUTPUT, *(root / OUTPUT).parents] if p != root and root in p.parents):
        raise RuntimeError("DEVELOPMENT_OUTPUT_SYMLINK_FORBIDDEN")
    if not verify_only:
        output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((dataset_dir / "development_manifest.json").read_text())
    allowed = [dataset_dir / "development_manifest.json"]
    allowed += [dataset_dir / p for p in manifest["dataset_files"]]
    allowed += [dataset_dir / x["path"] for x in manifest["cost_snapshots"].values()]
    # Time-zone data is read-only. No exchange calls or process execution are permitted.
    ZoneInfo("Europe/London"); ZoneInfo("America/New_York")
    with io_boundary(allowed, output):
        rows_by, access = load_development(dataset_dir, policy, dev)
        trades_by, events, skipped, metrics, uncertainty, state, reasons, deficits = compute(rows_by, policy, dev, spec)
        trades = sorted([t for values in trades_by.values() for t in values], key=lambda t: (t["scenario"], t["symbol"], t["signal_ts"]))
        if len({t["trade_sha256"] for t in trades}) != len(trades):
            raise RuntimeError("DEVELOPMENT_DUPLICATE_TRADE")
        event_counts = Counter(e["scenario"] for e in events if e["status"] == "COMPLETED")
        if any(event_counts[name] != len(values) for name, values in trades_by.items()):
            raise RuntimeError("DEVELOPMENT_EVENT_LEDGER_PARITY")
        artifacts = {}
        for name, values in (("trades", trades), ("events", sorted(events, key=lambda e: (e["scenario"],e["symbol"],e["signal_ts"]))),
                             ("feature_exclusions", skipped)):
            plain = b"".join(canonical(v) for v in values)
            path = output / (name + ".jsonl.gz")
            # Verify canonical uncompressed content across Python/zlib versions;
            # preserve the original immutable compression bytes on reproduction.
            if path.exists():
                compressed = path.read_bytes()
                if gzip.decompress(compressed) != plain:
                    raise RuntimeError("DEVELOPMENT_REPRODUCTION_MISMATCH:" + path.name)
            else:
                compressed = gzip.compress(plain, compresslevel=9, mtime=0)
            artifacts[name] = {"path": str(path.relative_to(root)), "rows": len(values),
                               "uncompressed_sha256": hashlib.sha256(plain).hexdigest(), "file_sha256": hashlib.sha256(compressed).hexdigest()}
            write_immutable(path, compressed, verify_only=verify_only)
        base = trades_by["base"]
        receipt = seal({"schema_version": "zel.g5a.development_evidence_probe.v1", "mode": policy["mode"], "state": state,
                        "state_mapping": STATE_MAP[state], "decision_reasons": reasons,
                        "economic_state": "MEASURED" if base else ("MEASURED_NO_EVENTS" if metrics["base"]["event_count"] == 0 else "MEASURED_NO_COMPLETED_TRADES"),
                        "experiment_id": policy["experiment_id"], "parent_candidate": policy["parent_candidate"],
                        "purpose": "DEVELOPMENT_DIAGNOSTIC_OF_PRE_ECONOMIC_REJECT", "parent_candidate_sha256": policy["parent_candidate_sha256"],
                        "parent_terminal_sha256": policy["parent_terminal_sha256"], "original_terminal_unchanged": True,
                        "P0_evidence_state": "P0_UNRESOLVED", "original_rejection_stage": "P0_PRIMARY_EVIDENCE",
                        "original_economic_state": "NOT_RUN_PRIOR_GATE_REJECT", "official_alpha_proof_state": "HOLD_ALPHA_PROOF",
                        "probe_authorized": True, "config_sha256": policy["receipt_sha256"], "code_sha256": alpha.sha(policy["code_files_sha256"]),
                        "code_files_sha256": policy["code_files_sha256"], "cost_sha256": dev["receipt_sha256"], "data_sha256": policy["dataset_sha256"],
                        "data_ref": policy["data_ref"], "split": "development", "unread_outcome_splits": ["validation", "purged_OOS", "prospective"],
                        "source_access": access, "metrics": metrics, "metric_digest": alpha.sha(metrics), "artifacts": artifacts,
                        "trade_set_sha256": alpha.sha(sorted(t["trade_sha256"] for t in base)), "all_scenario_trade_set_sha256": alpha.sha(sorted(t["trade_sha256"] for t in trades)),
                        "cluster_audit": {"N_raw": len(base), "same_signal_window_clusters": len({t["signal_ts"] for t in base}),
                                          "calendar_week_clusters_with_events": len({week(t["entry_ts"]) for t in base}),
                                          "largest_same_signal_window_cluster": max(Counter(t["signal_ts"] for t in base).values(), default=0), "N_effective": None},
                        "uncertainty": uncertainty, "baseline_exposure_match_deficits": deficits,
                        "integrity": {"duplicate": 0, "gap": 0, "lookahead": 0, "holdout_rows_decoded": 0, "production_ledger_access": False,
                                      "network_access": False, "fill_prices": "MODELLED_NOT_ACTUAL_FILLS", "account_return_claimed": False},
                        "independent_empirical_evidence_units": 1, "distinct_candidates_in_family": 1, "family_candidate_budget_remaining": 2,
                        "distinct_experiments": 1, "experiment_budget_remaining": 0, "reproduction_does_not_increment_budget": True,
                        "paid_AI_calls": 0, "paid_AI_cost_usd": 0, "G5B_fresh_T": 0, "production_credit": 0, **DEV_AUTH})
        write_immutable(output / "receipt.json", canonical(receipt), verify_only=verify_only)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = run(args.data_dir.resolve(), ROOT / OUTPUT, verify_only=args.verify_only)
    print(json.dumps({"state": result["state"], "experiment_id": result["experiment_id"], "metrics": result["metrics"]["base"],
                      "trade_set_sha256": result["trade_set_sha256"], "receipt_sha256": result["receipt_sha256"], "formal_credit": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
