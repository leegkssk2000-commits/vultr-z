import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.architecture_factory import g5a_development_data_v1 as data
from backend.research.architecture_factory import g5a_stage_admission_v1 as admission
from backend.research.architecture_factory import g5a_stage_candidate_v1 as candidate
from backend.research.architecture_factory import g5a_source_admission_v1 as source
from backend.research.architecture_factory import a1_common_source_semantic_guard_v1 as semantic
from backend.research.rebuild import g5b_operational_terminal_v1 as operational
from backend.research import p3_prospective_native_feature_collector as native


def bars(n=40, start=1_700_006_400_000):
    return [{"bar_open_ts": start+i*14_400_000,"bar_close_ts": start+(i+1)*14_400_000,
             "open":100.0,"high":101.0,"low":99.0,"close":100.0,"volume":10.0} for i in range(n)]


class HistoryTests(unittest.TestCase):
    def test_history_no_lookahead_duplicate_or_gap(self):
        rows=bars(); cutoff=rows[-1]["bar_close_ts"]
        self.assertEqual(data.validate_history(rows,cutoff)["gap"],0)
        for bad in (rows+rows[-1:], rows[:10]+rows[11:]):
            with self.assertRaises(RuntimeError): data.validate_history(bad,cutoff)
        with self.assertRaisesRegex(RuntimeError,"LOOKAHEAD"):
            data.validate_history(rows,cutoff-1)

    def test_raw_gap_is_audit_only_and_cannot_enter_common_development(self):
        rows=bars(); bad=rows[:3]+rows[4:]
        self.assertEqual(data.validate_history(bad,rows[-1]["bar_close_ts"],archive=True)["missing"],1)
        with self.assertRaisesRegex(RuntimeError,"GAP"):
            data.validate_history(bad,rows[-1]["bar_close_ts"])
        self.assertEqual(data.validate_history(bad[5:],rows[-1]["bar_close_ts"])["gap"],0)

    def test_split_uses_all_symbol_common_calendar_before_outcomes(self):
        c=source.read(data.CONTRACT)
        interval=14_400_000; start=1000*interval
        m={"A":{"first_open_ms":start,"last_close_ms":start+1000*interval},
           "B":{"first_open_ms":start+100*interval,"last_close_ms":start+900*interval}}
        split=data.freeze_split(m,c)
        self.assertEqual(split["development"][0],m["B"]["first_open_ms"])
        self.assertEqual(split["purged_OOS"][1],m["B"]["last_close_ms"])
        self.assertEqual(split["validation"][0]-split["development"][1],26*interval)
        self.assertTrue(split["frozen_before_outcomes"])

    def test_immutable_write_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"data.json";data.write_once(p,{"bars":1});data.write_once(p,{"bars":1})
            with self.assertRaisesRegex(RuntimeError,"IMMUTABLE"):
                data.write_once(p,{"bars":2})


class StageTests(unittest.TestCase):
    def test_current_clock_cannot_revoke_bound_development_history(self):
        registry=source.read("backend/research/architecture_factory/g5a_source_capability_registry_v1.json")
        self.assertEqual(source.generation_sources(registry,now_ms=registry["as_of_ms"]+86_400_000,stage="G5A_DEVELOPMENT"),["ohlcv","volume"])
        with self.assertRaises(RuntimeError):
            source.generation_sources(registry,now_ms=registry["as_of_ms"]+86_400_000)

    def test_audit_dependency_has_no_self_or_paid_research_trigger(self):
        p=source.ROOT/".github/workflows/g5a-source-g5b-operational-v1.yml"
        text=p.read_text()
        self.assertIn("workflows: ['G5 DATA_STALE Cadence Authority V1']",text)
        self.assertNotIn("workflows: ['G5A Source Terminal",text)
        self.assertIn("github.event_name == 'workflow_run'",text)
        self.assertNotIn('secrets.OPENAI_API_KEY',text)
        paid=(source.ROOT/".github/workflows/a1-gen2-parallel-prep-swarm-v1.yml").read_text()
        self.assertIn("if: github.event_name == 'workflow_dispatch'",paid)
        self.assertNotIn("if: ${{ github.event_name != 'workflow_run'",paid)

    def bundle(self):
        b=alpha._fixture_bundle();r=b["source_implementation_reality"]
        r.update(admission_stage="G5A_DEVELOPMENT",immutable_history_verified=True,split_frozen_before_outcomes=True,
                 development_cost_model_bound=True,development_data_sha="frozen-data",formal_production_credit=0)
        for x in r["sources"]:x.update(fresh=False,historical_immutable=True,semantic_valid=True,source_sha="frozen-data")
        return b

    def test_stale_current_does_not_change_immutable_development(self):
        b=self.bundle();self.assertTrue(alpha.evaluate_p6(b)["passed"])
        b["source_implementation_reality"]["admission_stage"]="G5B_FRESH"
        self.assertFalse(alpha.evaluate_p6(b)["passed"])

    def test_development_missing_data_cost_split_or_parity_rejected(self):
        for key in ("immutable_history_verified","split_frozen_before_outcomes","development_cost_model_bound"):
            b=self.bundle();b["source_implementation_reality"][key]=False
            self.assertFalse(alpha.evaluate_p6(b)["passed"])
        b=self.bundle();b["source_implementation_reality"]["sources"][0]["source_sha"]="different"
        self.assertFalse(alpha.evaluate_p6(b)["passed"])

    def test_fresh_requires_every_symbol_and_exactly_once(self):
        t=1_700_006_400_000
        events=[]
        for symbol in ("A","B"):
            p={**bars(1,start=t-14_400_000)[0],"symbol":symbol}
            events += [{"status":"NEW","payload":p}, {"status":"EVALUATED","state_key":symbol,"payload":{"duplicate":0,"lookahead":0,"closed_bar":True}}]
        stale={"authority_created":True,"authority_value":14_400_000,"authority_unit":"ms"}
        self.assertTrue(admission.fresh_readiness(events,["A","B"],t+1,stale)["G5B_FRESH_READY"])
        self.assertFalse(admission.fresh_readiness(events,["A","B"],t+14_400_000,stale)["G5B_FRESH_READY"])
        self.assertFalse(admission.fresh_readiness(events[:2],["A","B"],t+1,stale)["G5B_FRESH_READY"])
        self.assertFalse(admission.fresh_readiness(events+events[-1:],["A","B"],t+1,stale)["G5B_FRESH_READY"])

    def test_no_cost_binding_blocks_candidate_generation(self):
        dev=source.seal({"G5A_DEVELOPMENT_READY":True,"dataset_sha256":"d","development_cost_model_bound":False})
        with self.assertRaisesRegex(RuntimeError,"COST_AUTHORITY"):
            admission.require_development({"development":dev})

    def test_development_does_not_grant_production_cost_lineage(self):
        self.assertFalse(admission.production_ready({"development_cost_model_bound":True,"duplicate":0,"lookahead":0}))

    def test_development_alpha_pass_cannot_bypass_fresh_boundary_gate(self):
        b=self.bundle()
        self.assertTrue(alpha.evaluate_bundle(b)["p0_p6_passed"])
        with self.assertRaisesRegex(RuntimeError,"FRESH_RECEIPT_REQUIRED"):
            operational.freeze_boundary(b,{}, {},now_ms=1)

    def test_alpha_reject_cannot_create_new_boundary(self):
        with self.assertRaisesRegex(RuntimeError,"ALPHA_PROOF_REQUIRED"):
            operational.freeze_boundary({}, {}, {},now_ms=1)


class CandidateTests(unittest.TestCase):
    def test_features_only_use_signal_and_previous_closed_bars(self):
        spec=source.read(data.CONTRACT)["candidate_spec"]
        rows=bars();before=candidate.features(rows,22,spec)
        for r in rows[23:]:r["close"]=1e9;r["volume"]=1e9
        self.assertEqual(before,candidate.features(rows,22,spec))

    def test_volume_never_supplies_unobservable_semantics(self):
        for term in ("orderflow","aggressor","CVD","volume delta","bid/ask imbalance"):
            self.assertTrue(semantic._semantic_blockers({"required_sources":["ohlcv","volume"],"mechanism":term}))

    def test_cost2x_multiplies_fees_and_all_crossed_funding(self):
        cost={"fee_bps":10,"spread_bps":1,"impact_bps":2,"funding_p95_per_settlement_bps":2}
        one=candidate.development_cost(0,86_400_000,cost)
        self.assertEqual(one,19)
        self.assertEqual(candidate.development_cost(0,86_400_000,cost,multiplier=2),2*one)

    def test_first_failed_gate_stops_before_cheap_economics(self):
        b=alpha._fixture_bundle();b["primary_evidence"]={"supports":[]}
        with self.assertRaisesRegex(RuntimeError,"P0_PRIMARY_EVIDENCE"):
            candidate.require_before_cheap(b)
        b["source_implementation_reality"]["sources"][0]["fresh"]=False
        with self.assertRaisesRegex(RuntimeError,"P6_SOURCE"):
            candidate.require_before_cheap(b)

    def test_all_negative_controls_and_feature_ablations_required(self):
        for kind in alpha.REQUIRED_CONTROL_KINDS:
            b=alpha._fixture_bundle()
            b["negative_controls_and_ablation"]["controls"]=[x for x in b["negative_controls_and_ablation"]["controls"] if x["kind"]!=kind]
            self.assertFalse(alpha.evaluate_p4(b)["passed"])
        b=alpha._fixture_bundle();b["negative_controls_and_ablation"]["feature_ablations"]=[]
        self.assertFalse(alpha.evaluate_p4(b)["passed"])

    def test_ma001_reject_and_original_sha_remain_immutable(self):
        original=source.read("backend/research/architecture_factory/g5a_alpha_factory_latest.json")["next_experiment_candidate"]
        self.assertEqual(original["candidate_id"],"MA001")
        self.assertEqual(original["candidate_sha256"],source.read("backend/research/architecture_factory/g5a_source_terminal_dispositions_v1.json")["candidates"][0]["source_candidate_sha"])
        self.assertEqual(source.read("backend/research/architecture_factory/g5a_source_terminal_dispositions_v1.json")["original_state"],"G5A_SOURCE_BLOCKED_REJECT")


class NativeTests(unittest.TestCase):
    def row(self,source_ms=101,collected=102):
        raw={"symbol":"BTC-USDT","openInterest":"1","time":source_ms}
        # Construct ms-level fixtures independently of the collector's seconds conversion.
        return {"feature":"open_interest","symbol":"BTC-USDT","source_timestamp_ms":source_ms,"collected_at_ms":collected,
                "source_payload_sha256":native.canonical_sha(raw),"raw_payload":raw,"prospective_only":True}

    def test_clean_epoch_append_is_exactly_once_without_rewriting_old(self):
        epoch={"epoch_id":"test","boundary_ms":100}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);data.append_native_epoch(out,epoch,[self.row()]);p=next(out.glob('*.jsonl'));old=p.read_bytes()
            data.append_native_epoch(out,epoch,[self.row()]);self.assertEqual(old,p.read_bytes())
            data.append_native_epoch(out,epoch,[self.row(103,104)]);self.assertTrue(p.read_bytes().startswith(old))

    def test_native_clock_payload_and_monotonic_fail_closed(self):
        epoch={"epoch_id":"test","boundary_ms":100}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            with self.assertRaisesRegex(RuntimeError,"CLOCK"):data.append_native_epoch(out,epoch,[self.row(104,103)])
            row=self.row();row["raw_payload"]["openInterest"]="changed"
            with self.assertRaisesRegex(RuntimeError,"PAYLOAD"):data.append_native_epoch(out,epoch,[row])
            data.append_native_epoch(out,epoch,[self.row()])
            with self.assertRaisesRegex(RuntimeError,"MONOTONIC"):data.append_native_epoch(out,epoch,[self.row(100,102)])

    def test_bad_old_epoch_cannot_be_credited_to_new(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);p=out/'open_interest__BTCUSDT.jsonl'
            p.write_text(json.dumps({**self.row(),"epoch_id":"old"})+'\n')
            with self.assertRaisesRegex(RuntimeError,"NOT_CLEAN_EPOCH"):
                data.append_native_epoch(out,{"epoch_id":"new","boundary_ms":100},[self.row(103,104)])


if __name__ == "__main__":
    unittest.main()
