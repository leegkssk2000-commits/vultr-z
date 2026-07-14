from __future__ import annotations
import importlib.util, json
from pathlib import Path

P=Path(__file__).resolve().parents[1]/"tools/q4r3_exact25_trade_method_consumer_proof_audit.py"
S=importlib.util.spec_from_file_location("audit",P); assert S and S.loader
audit=importlib.util.module_from_spec(S);S.loader.exec_module(audit)

def ssot():
 return {
  "source_suffixes":[".py",".json",".yaml"],"excluded_path_parts":[".git","__pycache__"],
  "max_source_file_bytes":2000000,"scan_roots":["backend","config"],
  "discovery_tokens":["trade_method","method_hint","scalp_first","intraday","tactical_swing","resolve_trade_method"],
  "known_method_families":["scalp_first","intraday","tactical_swing","blocked"],
  "known_method_subtypes":["revert","continuation","liquidity_reclaim","breakout_probe","rescue"],
  "strategy_key_aliases":["strategy_id","strategy","strategy_name","name","id"],
  "method_key_aliases":["method","trade_method","method_hint","method_family","execution_method"],
  "subtype_key_aliases":["method_subtype","trade_method_subtype","subtype","method_variant"],
  "lineage_field_aliases":{
   "event_id":["event_id"],"position_id":["position_id"],"signal_id":["signal_id"],
   "strategy_id":["strategy_id","strategy"],"symbol":["symbol"],"method":["method","trade_method"],
   "method_subtype":["method_subtype","subtype"],"profile_version":["profile_version"],
   "profile_sha256":["profile_sha256"],"entry_style":["entry_style"],"hold_horizon":["hold_horizon"],
   "risk_mode":["risk_mode"],"target_r":["target_r"],"size_multiplier":["size_multiplier"],
   "execution_overlays":["execution_overlays"],"resolver_trace_id":["resolver_trace_id"],
   "realized_r":["realized_r"]
  }
 }

def test_direct_resolver_call_is_proven(tmp_path:Path):
 root=tmp_path;(root/"backend").mkdir()
 (root/"backend/__init__.py").write_text("")
 resolver=root/"backend/method_resolver.py";resolver.write_text("def resolve_trade_method(x):\n return {'method':'scalp_first'}\n")
 producer=root/"backend/producer.py";producer.write_text("from backend.method_resolver import resolve_trade_method\ndef cycle():\n return resolve_trade_method('alpha')\n")
 paths=audit.sources(root,ssot());inv=audit.inventory(root,paths,ssot());g,e=audit.graph(root,[producer],[],50);p=audit.proof(root,g,e,inv)
 assert p["state"]=="PROVEN_DIRECT_RESOLVER_CALL" and p["direct_call_evidence"]

def test_mapping_reads_python_json_yaml(tmp_path:Path):
 root=tmp_path;(root/"backend").mkdir();(root/"config").mkdir()
 (root/"backend/registry.py").write_text("REG={'alpha':{'method_hint':'scalp_first','subtype':'revert'},'beta':{'trade_method':'intraday'}}")
 (root/"config/m.json").write_text(json.dumps({"strategy_id":"gamma","method":"tactical_swing"}))
 (root/"config/m.yaml").write_text("strategy_id: delta\nmethod: scalp_first\nmethod_subtype: liquidity_reclaim\n")
 maps,notes=audit.mappings(root,audit.sources(root,ssot()),ssot())
 got={(x["strategy_id"],x["declared_method"]) for x in maps}
 assert {("alpha","scalp_first"),("beta","intraday"),("gamma","tactical_swing"),("delta","scalp_first")}<=got
 assert not notes

def test_exact_id_linkage_only():
 s=ssot();rows=[{"event_id":"e1","strategy_id":"a"},{"event_id":"e2","strategy_id":"b"}]
 arts=[{"event_id":"e1","method":"scalp_first","source_path":"r/a.json"},{"strategy_id":"b","method":"intraday","source_path":"r/b.json"}]
 x=audit.linkage(rows,arts,s)
 assert x["exact_identifier_linked_count"]==1 and x["exact_identifier_linked_pct"]==50.0

def test_conflict_not_counted():
 s=ssot();rows=[{"event_id":"e1"}];arts=[{"event_id":"e1","method":"scalp_first"},{"event_id":"e1","method":"intraday"}]
 x=audit.linkage(rows,arts,s)
 assert x["exact_identifier_linked_count"]==0 and len(x["conflicts"])==1
