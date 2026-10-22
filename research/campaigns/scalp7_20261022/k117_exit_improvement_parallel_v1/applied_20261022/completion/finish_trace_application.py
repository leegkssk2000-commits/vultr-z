"""Seal completed passive traces only; never calls a price replay or changes strategy."""
from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, importlib.util, sys
S=Path(__file__).resolve().parent
BASE=Path('/home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1')
C=Path('/home/z/z/runtime/k117_passive_exit_observer_c_20261022_v1')
D=Path('/home/z/k117_be_observer_d_once_20261022_v1')
PREFIX='research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/applied_20261022'
def load(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def put(name,raw):
 p=S/name
 if p.exists():
  if p.read_bytes()!=raw:raise ValueError('EXISTING_COMPLETION_FILE_CHANGED:'+name)
 else:
  with p.open('xb') as f:f.write(raw)
def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
findings=load(S/'TRACE_FINDINGS.json')
if not findings['C']['completed'] or not findings['D']['completed'] or not findings['C_D_matched117']:raise ValueError('TRACE_NOT_COMPLETE')
if findings['C']['all117_touch_bound']!=117 or not findings['D']['all117_gross_cost_net_reconciled']:raise ValueError('TRACE_IDENTITY_OR_ACCOUNTING_INCOMPLETE')
files=['TRACE_FINDINGS.json','TRACE_FACTS_ALL117.json','report_traces.py','finish_trace_application.py']
trace_manifest={}
for label,folder,receipt_name,all117 in [('C',C,'PASSIVE_EXIT_OBSERVER_RECEIPT.json','EXIT_TRACE_ALL117.json.gz'),('D',D,'OBSERVER_RECEIPT.json','BE_ALL117.json.gz')]:
 receipt=load(folder/receipt_name)
 if not receipt['raw117_exact'] or receipt['new_policy_comparisons']!=0:raise ValueError('BASELINE_NOT_EXACT')
 for name,pin in receipt['files'].items():
  raw=(folder/name).read_bytes()
  if sha(raw)!=pin['sha256']:raise ValueError('TRACE_DIGEST_CHANGED:'+label+':'+name)
  trace_manifest[label+':'+name]={'remote_path':str(folder/name),'sha256':sha(raw),'bytes':len(raw)}
 for name in [receipt_name,all117]:
  dest=label+'_'+name;put(dest,(folder/name).read_bytes());files.append(dest)
 for n in ['PROCESS_'+label+'.json','EXIT_'+label+'.json']:
  r=load(S/n)
  if n.startswith('EXIT_') and (r['exit_code']!=0 or not r['receipt_exists']):raise ValueError('OBSERVER_EXIT_NOT_SUCCESS')
  files.append(n)
for name in ['QUEUE_INVOKED.json','RESUME_PUBLISHED.json','QUEUE_BINDING.json']:
 if (S/name).exists():files.append(name)
put('TRACE_STORAGE_MANIFEST.json',enc(trace_manifest));files.append('TRACE_STORAGE_MANIFEST.json')
if not (S/'RESULT.md').exists():
 c=findings['C']['groups'];d=findings['D']['groups']
 lines=['# K117 실제 C/D 시세 상태추적 완료','', '분류: ACTUAL_PASSIVE_TRACE_COMPLETE_NOT_NEW_ECONOMIC_IMPROVEMENT.', '', '고정 baseline 8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8, 117거래·미결·경계·원래 신호·기회만료 사건의 정확한 재현을 각 관측기가 검증했다.', '정책 변경·추가 경제비교·실주문·현행 Shadow 변경은 모두 0이다. 계측에 사용한 두 원형 재생은 신규 전략 성과가 아니다.', '', '## 실제 결과', '- C: 전체 117거래의 원래 EMA 접촉과 실제 완료봉 판단·청산 순서를 연결했다.', '- D: 전체 117거래의 본전보호·다음 봉 손절 적용·부분익절·러너·최종 청산을 연결하고 Gross-Cost=Net을 검산했다.', '', 'C 집단별 관측: ```json\n'+json.dumps(c,ensure_ascii=False,indent=2)+'\n```', '', 'D 집단별 관측: ```json\n'+json.dumps(d,ensure_ascii=False,indent=2)+'\n```', '', '## 한계', '불리한 종가 관측만으로 실패 구분이나 조기청산 이익은 증명되지 않는다. 원래 청산 이후 회복 여부 및 대체 정책의 순손익·놓친 승리는 별도 비교가 필요하다. 기존 K117 개발 손익은 변경하지 않았다.', '', '모든 원시 호출 trace는 서버에 보존하고 파일별 해시를 TRACE_STORAGE_MANIFEST.json에 기록했다. GitHub에는 전체 117거래 연결 trace 두 개·실행 영수증·검산 결과를 저장했다.', '완료 기록 생성 UTC: '+datetime.now(timezone.utc).isoformat()]
 put('RESULT.md', ('\n'.join(lines)+'\n').encode())
files.append('RESULT.md')
if (S/'STORAGE_completion.json').exists():
 storage=load(S/'STORAGE_completion.json')
else:
 spec=importlib.util.spec_from_file_location('_existing_trace_persist',BASE/'persist.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
 p.S=S;p.PREFIX=PREFIX;storage=p.save('completion',files)
sys.path.insert(0,str(S));import owner_claim
owner_claim.update('TERMINAL',{'phase_detail':'BOTH_EXACT_K117_NATIVE_OBSERVERS_COMPLETE_AND_PERSISTED','native_observer_runs':2,'new_policy_comparisons':0,'economic_started':False,'current_shadow_changes':0,'orders':0,'result_commit':storage['commit'],'result_path':storage['path']+'/RESULT.md','completed_at_utc':datetime.now(timezone.utc).isoformat(),'C_raw117_exact':True,'D_raw117_exact':True,'trace_accounting_all117_reconciled':True})
print('NATIVE_TRACE_COMPLETE_SAVED_OWNER_RELEASED',storage['commit'],flush=True)
