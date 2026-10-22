#!/usr/bin/env python3
"""Offline, terminal-only validation of the frozen Supertrend117 source gap.

Exit 0 means the diagnostic binding was verified, never candidate/economic PASS.
No source module is imported or executed; no strategy or engine callable exists.
The parent is preserved by exact bytes, not by a claimed economic parity replay.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
STATUS = "NO_SOURCE_EXACT_CAUSAL_CHILD"
SCOPE = "ZEL_C_SUPERTREND_WINNER_RETENTION_AFTER_K117_V1"
CONTRACT_FIELDS = ("author", "license", "activation", "distance", "update", "cadence", "gap_precedence", "causal_availability")
# Immutable originals independently retrieved; these constants are not loaded from
# the editable manifest. Runtime checks compare both manifest and actual bytes.
SOURCE_PINS = {'.github/workflows/a1-a4-exact-parent-repair-batch-v1.yml': ('a976e3c41a8a3195eb832c3ce22c627dc7040ebe',
                                                              'ac1a4bd36966ab19e1e981363a1ef677cffc8e69caf81c9d9aa4c34e29657456',
                                                              'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/contracts/a1_a5_no_idle_research_v1.json': ('6ab9768e0d4bdca36168b426d59ac2fe21706d54',
                                                               '568b900be078f228f2b2e3066eb3b33bb6b640536c203840243d3ea42ae514ea',
                                                               'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/rebuild/a1_a4_exact_parent_repair_batch_v1.py': ('91023eeef62c2e2d77683d0aa7ead248d9c3d31e',
                                                                    '338972f09465157b6eb53e01c18106b8043a7f0663b0129957f8aab1d1900035',
                                                                    'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/rebuild/a1_exact25_generic_evaluator_v1.py': ('5da6ed21eab6d5482602bc1b856537f74f268a15',
                                                                 '074ccb2a0bec3454e7900d86deb365b47c652dc5f024884124692496a4ffcf5d',
                                                                 'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/rebuild/a1_exact25_generic_evaluator_v2.py': ('b8fbf673287270925fb32536449d5f9ada352f10',
                                                                 'e615f2a4300f671bd0af0dd9fc2c6fdefb5a5c8ff0b2f57901c33704bc965a5f',
                                                                 'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/rebuild/a1_exact25_policy_adapter_v1.py': ('8f41a6855be575b458df21df07fa1f22c038bade',
                                                              '0a8b817f1e301b5c79d05840805af42c4b5dfd03ced034e9751b9a70923869b3',
                                                              'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/rebuild/a1_supertrend_native_line_trail_latest.json': ('b824e44b5d0796eaddc1e9a860515018e7edbc2d',
                                                                          '3d57dbad77b6591bf15026faf8f266fb3c01928e12c92d487f76dc845c15aa33',
                                                                          None),
 'backend/research/rebuild/a1_supertrend_native_line_trail_v2.py': ('ccd629825f7ce0bd78799912727058e90ae6236a',
                                                                    '27997cebc0202c9a85cb602bc5aa1e32ea6e4802f534eddfb8db1555b21c20d6',
                                                                    None),
 'backend/research/rebuild/a1_trend_rider_exact_parent_repair_batch_v1.py': ('7e33b17e97dcc68d636bda48e0ad808232973ddb',
                                                                             'b878606b67ed1153cbb95b8a357055b2a1824e64e2652a22e7d830552957d45d',
                                                                             'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/rebuild/evidence_packet_trend_cluster_v1.json': ('6e03a2008c92357caac048eca9765e9d0c499e78',
                                                                    'e34d61d3391bf9f379f3d1adee82f2b41d346508fb1673a45b61270cfc61ed53',
                                                                    'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/rebuild/policy_kernel_v1.py': ('28875a0bfd16b07f3686f128cb2f6943f8364006',
                                                  'e6b21d2d3ae6a4e6af6a3c2039dcf8e8ebf4caa51d29a82a5285e4059c82759e',
                                                  'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/research/rebuild/trend_policy_batch_v1.py': ('5212f92a0b181e523c235dc546b64ea2852045e7',
                                                       'f58792c31d9b358894c6626ea8aa273aef3ba086366d023913003eeb8e576b1e',
                                                       'b73129138e75bdf3fd8ffe58bea87effa2e59f2f'),
 'backend/strategies/supertrend_pullback.py': ('7941bb1cfb380b01b27cbe196746bfb2b382ab6c',
                                               'b5398dfce04260422f04a758736d210763dc8c6097eeca953af82a56eb80fe25',
                                               '1dadb1f6a28662823058a58fdeaa978fcd104b7b'),
 'research/campaigns/scalp7_20260915/broad_v2/supertrend/PARENT_CONTROLS_FREEZE_V2.json': ('7dbb16efd77bc5f8b6dd6414830993e129b934df',
                                                                                           'b656b00954cd0ec06de105b9b6c6467e7f426e7744fd803ae838f907dca614ec',
                                                                                           None),
 'research/campaigns/scalp7_20260915/broad_v2/supertrend/SUPERTREND_ARCHITECTURE_FREEZE_V2.json': ('84edfbab1ae78cd8b98dd3dcccefe4efb4ab5c7a',
                                                                                                   'ff20ffc5bd7bfce0792d499eb10e0d0f4f67a77aebca219b260707b4e64ab328',
                                                                                                   None)}

IDENTITY = {
    "strategy_id": "supertrend_pullback",
    "candidate_id": "supertrend_pullback__exact_parent__volatility_regime_owner_only",
    "candidate_sha256": "25f5ccd009e33d477a59bfe3f249663e73ad2c3f8d1832d58d283ed9c6066e3d",
    "trade_identity_sha256": "e42711d8843107a94f32019e0a7d1c7492319e812ddf5be377bbdbdac1365e01",
    "parent_receipt_sha256": "9edb8d722b985af9e6e5f8e77dc560b5473befbaa365e0c61a94838478cfdc9a",
    "summary_receipt_sha256": "b00e7cc6fcf5439912a5ba3e7eb3ff9c9d2998ad70adb0ac75ec2d6da2faddc1",
    "summary_git_blob": "97a6bc3d50dfb91ea3d9d3815549327d40dfafad",
    "summary_file_sha256": "1c979597753e5f4a1490632df43295f9e2d49991ca46ec6550de0537e050bd89",
    "parent_file_sha256": "5018f26c115a89bf69b3d3cccf0f7ccaac42bb3083bb2d3a6cc4360bb1fa9619",
    "parent_policy_git_blob": "5212f92a0b181e523c235dc546b64ea2852045e7",
    "parent_config_sha256": "ac462a17bf7c607cd0d3e97fa37bd33c5cc0672b7a81ecf37bd9e586d91fd2c4",
    "source_context_commit": "b73129138e75bdf3fd8ffe58bea87effa2e59f2f",
    "timeframe": "1h", "parent_T": 236, "subset_T": 117,
    "parent_net_wins": 64, "subset_net_wins": 32,
    "trade_retention_pct": 49.57627118644068,
    "net_winner_count_retention_pct": 50.0,
    "retention_is_not_winner_retention": True,
}
LEGACY_PATH = "backend/strategies/supertrend_pullback.py"


class BindingError(ValueError):
    """A diagnostic input contradicts the immutable terminal binding."""


def require(condition, code):
    if not condition:
        raise BindingError(code)


def exact(actual, expected, code):
    require(type(actual) is type(expected) and actual == expected, code)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def decode_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "DUPLICATE_JSON_KEY:" + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def load_pinned(path, expected_sha, expected_blob=None):
    raw = Path(path).read_bytes()
    exact(sha256(raw), expected_sha, "FILE_SHA256_MISMATCH:" + str(path))
    if expected_blob is not None:
        exact(git_blob(raw), expected_blob, "GIT_BLOB_MISMATCH:" + str(path))
    return decode_json(raw)


def validate_identity(summary, parent):
    """Bind distinct Supertrend117 to its saved 236-row 1h parent, not K117."""
    exact(summary.get("schema_version"), "zel.a1.a4.exact_parent_repair_batch.v1", "SUMMARY_SCHEMA")
    exact(summary.get("receipt_sha256"), IDENTITY["summary_receipt_sha256"], "SUMMARY_RECEIPT")
    for label, value in (("summary", summary), ("parent", parent)):
        for key, wanted in {"order_authority": "BLOCKED", "live_trade_authority": "BLOCKED",
                            "execution_authority": "NONE", "promotion_authority": False,
                            "selection_authority": False, "protected_mutations": 0}.items():
            exact(value.get(key), wanted, label + ":AUTHORITY:" + key)
    for key, wanted in {"strategy_id": IDENTITY["strategy_id"],
                        "receipt_sha256": IDENTITY["parent_receipt_sha256"],
                        "policy_sha": IDENTITY["parent_policy_git_blob"],
                        "config_sha": IDENTITY["parent_config_sha256"], "completed_trades": 236}.items():
        exact(parent.get(key), wanted, "PARENT_IDENTITY:" + key)
    exact(parent.get("source", {}).get("interval"), "1h", "PARENT_TIMEFRAME")
    rows = parent.get("trades")
    require(isinstance(rows, list) and len(rows) == 236, "PARENT_236_RAW_ROWS_REQUIRED")
    for row in rows:
        exact(row.get("policy_sha"), IDENTITY["parent_policy_git_blob"], "ROW_POLICY_IDENTITY")
        exact(row.get("config_sha"), IDENTITY["parent_config_sha256"], "ROW_CONFIG_IDENTITY")
    strategy = summary.get("strategies", {}).get(IDENTITY["strategy_id"], {})
    for key, wanted in {"parent_receipt_sha256": IDENTITY["parent_receipt_sha256"],
                        "parent_policy_sha": IDENTITY["parent_policy_git_blob"],
                        "parent_config_sha": IDENTITY["parent_config_sha256"]}.items():
        exact(strategy.get(key), wanted, "SUMMARY_PARENT_IDENTITY:" + key)
    candidates = [c for c in strategy.get("candidates", []) if c.get("candidate_id") == IDENTITY["candidate_id"]]
    require(len(candidates) == 1, "EXACT_117_CANDIDATE_REQUIRED")
    candidate = candidates[0]
    wanted = {key: IDENTITY[key] for key in ("strategy_id", "candidate_id", "candidate_sha256",
                                            "trade_identity_sha256", "parent_receipt_sha256")}
    wanted.update(completed_trades=117, changed_axis="VOLATILITY_REGIME_OWNER_ONLY", changed_axis_count=1,
                  development_candidate_ready=False, economic_gate_pass=False,
                  parent_trade_identity_subset=True, new_trade_admission_forbidden=True,
                  parameter_sweep=False, post_outcome_trade_deletion=False,
                  parent_cost_model_changed=False, parent_entry_signal_geometry_changed=False,
                  parent_stop_geometry_changed=False, parent_timeout_changed=False)
    for key, value in wanted.items():
        exact(candidate.get(key), value, "SUBSET_IDENTITY:" + key)
    return candidate


def validate_source_records(records):
    require(isinstance(records, list) and len(records) == len(SOURCE_PINS), "SOURCE_RECORD_COUNT")
    found = set()
    for record in records:
        path = record.get("repo_path")
        require(path in SOURCE_PINS and path not in found, "UNKNOWN_OR_DUPLICATE_SOURCE")
        found.add(path)
        blob, digest, commit = SOURCE_PINS[path]
        for key, value in {"git_blob": blob, "sha256": digest, "snapshot_context_commit": commit,
                           "frozen_path": "source/" + path}.items():
            exact(record.get(key), value, "SOURCE_PIN:" + path + ":" + key)


def validate_execution_features(features):
    # This diagnostic accepts no execution feature set. Outcome-derived labels
    # remain valid saved-report columns, but never become an admission/exit rule.
    if features == []:
        return
    require(isinstance(features, list), "INVALID_EXECUTION_FEATURES")
    labels = json.dumps(features).lower()
    if any(token in labels for token in ("month", "date", "symbol", "winner", "loser", "mfe", "mae",
                                        "net", "pnl", "profit", "outcome", "trade_key", "exit_reason")):
        raise BindingError("OUTCOME_DERIVED_EXECUTION_FEATURE")
    raise BindingError("NO_EXECUTION_FEATURES_WITHOUT_CHILD")


def validate_packet(packet):
    exact(packet.get("schema_version"), "zel.work_c.supertrend.source_exact_falsification.v1", "PACKET_SCHEMA")
    exact(packet.get("scope_key"), SCOPE, "PACKET_SCOPE")
    exact(packet.get("status"), STATUS, "TERMINAL_STATUS_REQUIRED")
    exact(packet.get("first_blocker"), "SOURCE_EXACT_EXIT_RULE_UNBOUND", "SOURCE_BLOCKER_REQUIRED")
    for key, value in IDENTITY.items():
        exact(packet.get("frozen_identity", {}).get(key), value, "PACKET_IDENTITY:" + key)
    validate_source_records(packet.get("source_objects"))
    contract = packet.get("source_contract", {})
    require(set(contract) == set(CONTRACT_FIELDS), "SOURCE_CONTRACT_FIELDS_REQUIRED")
    known_provenance = {path + "@" + pin[0] for path, pin in SOURCE_PINS.items()}
    for field in CONTRACT_FIELDS:
        item = contract[field]
        require(isinstance(item, dict), "MALFORMED_SOURCE_FIELD:" + field)
        exact(item.get("complete"), False, "UNSUPPORTED_SOURCE_COMPLETION_CLAIM:" + field)
        require(isinstance(item.get("evidence"), str) and item["evidence"].strip(), "MISSING_GAP_EVIDENCE:" + field)
        refs = item.get("provenance")
        require(isinstance(refs, list) and refs and all(ref in known_provenance for ref in refs),
                "UNBOUND_GAP_PROVENANCE:" + field)
    for key in ("new_child_count", "economic_runs", "market_api_calls", "actions_runs_started", "orders_submitted"):
        exact(packet.get(key), 0, "NONZERO_WORK_ACTION:" + key)
    handoff = packet.get("owner_handoff", {})
    for key, value in {"owner": "CLOUD_WORK_COORDINATOR_ISSUE1358_V1",
                       "requested_action": "MECHANISM_REPLACEMENT_DECISION_ONLY",
                       "same_parent_new_exit_candidate_ready": False,
                       "new_rule_freeze_created": False, "economic_command": None}.items():
        exact(handoff.get(key), value, "TERMINAL_HANDOFF:" + key)
    observed = packet.get("observed_parent_execution", {})
    exact(observed.get("data_interval"), "1h", "EXECUTION_TIMEFRAME")
    exact(observed.get("trailing_executed"), False, "INVENTED_PARENT_TRAIL")
    gaps = packet.get("raw_data_gaps", {})
    for key, value in {"saved_parent_ledger_available": True, "saved_parent_trade_count": 236,
                       "saved_subset_trade_identity_hash_available": True,
                       "saved_117_trade_id_list_in_recovered_packet": False,
                       "raw_contiguous_1h_bars_in_recovered_packet": False,
                       "intrade_ohlc_stage_trace_in_recovered_packet": False,
                       "separate_from_source_rule_gap": True}.items():
        exact(gaps.get(key), value, "RAW_DATA_SCOPE:" + key)
    validate_execution_features(packet.get("execution_features", []))


def legacy_source_facts(raw):
    """Static falsification of the immutable HIST_R7 exit interpretation.

    This deliberately parses syntax, never imports the historical module (whose
    dependency imports could otherwise initialize an engine). The hash prevents
    treating this limited static inspection as proof about any other program.
    """
    exact(sha256(raw), SOURCE_PINS[LEGACY_PATH][1], "LEGACY_SOURCE_SHA256")
    tree = ast.parse(raw)
    strategy = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "strategy")
    calls = [node for node in ast.walk(strategy) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "_build_result"]
    actions = []
    for call in calls:
        action = next((kw.value for kw in call.keywords if kw.arg == "action"), None)
        require(isinstance(action, ast.Constant) and isinstance(action.value, str), "LEGACY_DYNAMIC_ACTION")
        actions.append(action.value)
    exact(sorted(set(actions)), ["add", "enter", "hold"], "LEGACY_ACTIONS_CHANGED")
    position = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_infer_position_state")
    returned = next(node.value for node in ast.walk(position) if isinstance(node, ast.Return))
    position_keys = sorted(key.value for key in returned.keys)
    exact(position_keys, ["add_count", "avg_entry", "last_add_price", "position_qty", "position_side"], "LEGACY_POSITION_FIELDS_CHANGED")
    geometry = {}
    for node in ast.walk(strategy):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("long_sl", "short_sl"):
                geometry[node.targets[0].id] = ast.unparse(node.value)
    exact(geometry.get("long_sl"), "min(st_now - atr_now * cfg.stop_atr_buffer, trend_ma - atr_now * cfg.trail_atr_mult, low)", "LEGACY_LONG_GEOMETRY_CHANGED")
    exact(geometry.get("short_sl"), "max(st_now + atr_now * cfg.stop_atr_buffer, trend_ma + atr_now * cfg.trail_atr_mult, high)", "LEGACY_SHORT_GEOMETRY_CHANGED")
    decide = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "decide")
    intents = sorted({kw.value.attr for node in ast.walk(decide) if isinstance(node, ast.Call)
                      for kw in node.keywords if kw.arg == "intent" and isinstance(kw.value, ast.Attribute)})
    exact(intents, ["ENTER_LONG", "HOLD"], "LEGACY_DECISION_INTENTS_CHANGED")
    return {"inspection": "AST_ONLY_NO_EXECUTION", "git_blob": SOURCE_PINS[LEGACY_PATH][0],
            "strategy_actions": sorted(set(actions)), "decide_intents": intents,
            "position_state_keys": position_keys, "proposed_initial_geometry": geometry,
            "exit_or_trail_update_action_present": False,
            "interpretation": "trail_atr_mult is used in entry/add proposed geometry; the pinned source supplies no position-stop recurrence or causal exit clock. An enum EXIT_LONG declaration is not an executed decision."}


def audit(base=HERE, *, summary_path=None, parent_path=None, packet_path=None, source_root=None):
    base = Path(base)
    summary_path = Path(summary_path) if summary_path else base / "inputs/a4_summary.json"
    parent_path = Path(parent_path) if parent_path else base / "inputs/parent236.json"
    packet_path = Path(packet_path) if packet_path else base / "SOURCE_EXACT_FALSIFICATION.json"
    source_root = Path(source_root) if source_root else base / "inputs/source"
    summary = load_pinned(summary_path, IDENTITY["summary_file_sha256"], IDENTITY["summary_git_blob"])
    parent = load_pinned(parent_path, IDENTITY["parent_file_sha256"])
    validate_identity(summary, parent)
    packet_raw = packet_path.read_bytes()
    packet = decode_json(packet_raw)
    validate_packet(packet)
    manifest_raw = (base / "inputs/SOURCE_OBJECTS.json").read_bytes()
    manifest = decode_json(manifest_raw)
    validate_source_records(manifest.get("records"))
    sources = {}
    for path, (blob, digest, _) in SOURCE_PINS.items():
        raw = (source_root / path).read_bytes()
        exact(sha256(raw), digest, "SOURCE_SHA256:" + path)
        exact(git_blob(raw), blob, "SOURCE_GIT_BLOB:" + path)
        sources[path] = raw
    facts = legacy_source_facts(sources[LEGACY_PATH])
    # Check file preservation after all reads/AST inspection. No parent or source
    # is opened for writing. These checks make no economic parity claim.
    exact(sha256(parent_path.read_bytes()), IDENTITY["parent_file_sha256"], "PARENT_CHANGED_DURING_AUDIT")
    exact(sha256(summary_path.read_bytes()), IDENTITY["summary_file_sha256"], "SUMMARY_CHANGED_DURING_AUDIT")
    exact(packet_path.read_bytes(), packet_raw, "PACKET_CHANGED_DURING_AUDIT")
    exact((base / "inputs/SOURCE_OBJECTS.json").read_bytes(), manifest_raw, "MANIFEST_CHANGED_DURING_AUDIT")
    for path, raw in sources.items():
        exact((source_root / path).read_bytes(), raw, "SOURCE_CHANGED_DURING_AUDIT:" + path)
    return {"schema_version": "zel.work_c.supertrend.source_binding_diagnostic.v1",
            "scope_key": SCOPE, "binding_valid": True, "status": STATUS,
            "diagnostic_completed": True, "candidate_ready": False,
            "first_blocker": "SOURCE_EXACT_EXIT_RULE_UNBOUND", "missing_source_fields": list(CONTRACT_FIELDS),
            "frozen_identity": dict(IDENTITY), "source_objects_verified": len(sources),
            "source_packet_sha256": sha256(packet_raw), "legacy_source_facts": facts,
            "parent_preservation": "EXACT_BYTES_UNCHANGED_NOT_ECONOMIC_REPLAY_PARITY",
            "raw_117_membership_recovered": False, "economic_command": None,
            "economic_runs": 0, "market_api_calls": 0, "actions_runs_started": 0,
            "orders_submitted": 0, "new_child_count": 0,
            "next_owner_action": "MECHANISM_REPLACEMENT_DECISION_ONLY",
            "exit_zero_meaning": "Diagnostic binding valid; terminal no-child, never candidate/economic PASS."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=HERE, help="frozen diagnostic package directory")
    parser.add_argument("--output", type=Path, help="optional new diagnostic JSON; refuses an existing file")
    args = parser.parse_args(argv)
    try:
        result = audit(args.base)
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            # Exclusive create prevents replacement of the parent, source, prior
            # diagnostic, or any other existing file; no directory creation.
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        print(rendered, end="")
        return 0
    except (BindingError, OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        print(json.dumps({"binding_valid": False, "candidate_ready": False,
                          "status": "INVALID_DIAGNOSTIC_BINDING", "error": str(error),
                          "economic_command": None}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
