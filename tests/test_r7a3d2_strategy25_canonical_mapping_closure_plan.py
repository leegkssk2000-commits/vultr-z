from __future__ import annotations
import importlib.util, sys
from pathlib import Path

P=Path(__file__).resolve().parents[1]/'tools/r7a3d2_strategy25_canonical_mapping_closure_plan.py'
s=importlib.util.spec_from_file_location('r7a3d2',P); assert s and s.loader
m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; s.loader.exec_module(m)

def test_direct_module_wins():
    row={'strategy_id':'x','lineage_status':'CONFLICT','evidence_count':2,'runtime_owner_refs':['systemd/x.service'],'test_refs':['tests/test_x.py'],'evidence':[{'kind':'DIRECT_STRATEGY_MODULE','source_path':'backend/strategies/x.py','callable':'evaluate','source_blob_sha':'a'*40},{'kind':'PYTHON_LITERAL_REGISTRY_KEY','source_path':'tools/audit.py','callable':'evaluate','registry_like_path':True,'source_blob_sha':'b'*40}]}
    p=m.plan_one(row,90,20,5)
    assert p['resolution']=='AUTO_NARROWED_PLAN'
    assert p['proposed_canonical_mapping']['implementation_path']=='backend/strategies/x.py'

def test_tool_mentions_do_not_auto_select():
    row={'strategy_id':'x','lineage_status':'CONFLICT','evidence_count':2,'evidence':[{'kind':'PYTHON_LITERAL_REGISTRY_KEY','source_path':'tools/x_audit.py','callable':'evaluate','registry_like_path':True,'source_blob_sha':'a'*40},{'kind':'PYTHON_LITERAL_REGISTRY_KEY','source_path':'tools/x_smoke.py','callable':'evaluate','registry_like_path':True,'source_blob_sha':'b'*40}]}
    p=m.plan_one(row,90,20,5)
    assert p['resolution']=='EXPLICIT_MAPPING_REQUIRED'

def test_git_target_path_is_candidate():
    r={'kind':'PYTHON_LITERAL_REGISTRY_KEY','source_path':'backend/registry.py','target_path':'backend/strategies/x.py','target_path_exists_in_git':True,'callable':'evaluate','source_blob_sha':'a'*40}
    assert m.identity(r)==('backend/strategies/x.py','evaluate','git_path')

def test_noncanonical_evidence_rejected():
    row={'strategy_id':'x','evidence_count':1,'evidence':[{'kind':'JSON_STRATEGY_OBJECT','source_path':'config/x.json','config_keys':['risk']}]}
    p=m.plan_one(row,90,20,5)
    assert p['dedup_candidate_count']==0
    assert p['rejected_noncanonical_evidence_count']==1
