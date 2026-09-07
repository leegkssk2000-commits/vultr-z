# G5A 실제 gate 경계 — 기존 규칙 유지, 미승인 우회 없음

조회 기준: 6426e226b3883de22f6fc9c3e3bfea4a50701d29. 같은 STEP7 캠페인과 44건/사용 예산을 승계한다. 이 문서는 실제 소스의 요구사항을 구분하며 후보 G5A PASS나 새 통계/자료 승인이 아니다.

## 1. P4: 정당한 비적용 경로가 이미 있다

owner: backend/research/alpha_proof/a1_alpha_proof_gate_v1.py:evaluate_p4

기존 코드는 네 control 종류를 모두 표에 남기되, applicable=false와 비어 있지 않은 not_applicable_reason을 명시하는 경우를 허용한다. 해당 control의 passed=true를 위조하거나 행 자체를 삭제할 필요가 없다. KR3에 regime 진입 feature가 없어 라벨회전이 퇴화한다는 PR1210 진단은 이 적용성 검토의 근거가 된다. 다만 문자열을 넣는 것 자체는 과학적 정당성 검증이 아니다. 정확한 candidate/causal-map과 기존 결과를 근거로 비적용 사유를 검토·결속해야 하며, 다른 적용 가능한 control·feature ablation의 실제 우월성 검증은 계속 필요하다. 현재 gate는 P4에 holdout_outcomes_used=false를 요구한다. 전방봉인 검증 보고와 개발 P4를 구분한다.

## 2. P5: 실제 서로 다른 provider 두 곳

owner: 같은 파일:evaluate_p5

controller_review_sha 외에, 서로 다른 provider 최소2곳의 successful PASS/PASS_TO_REPLAY/PASS_TO_PREREGISTER와 model/input_sha/prompt_sha/response_sha가 필요하다. 동일 provider의 하위 agent 이름을 바꿔 두 곳으로 계산할 수 없다. 이 캠페인의 Gemini/OpenAI 호출0은 이 formal route의 완료 근거가 아니다. 기존 진짜 검토를 재사용하려면 정확한 KR3 명세·입력과 일치해야 한다. 없으면 승인된 shared USD5 안의 실제 입력/응답 연결 또는 정확한 런타임 권한 장애가 필요하다. 가짜 provider 결과를 fixture에서 옮기지 않는다.

## 3. P6: G5A_DEVELOPMENT와 fresh source는 별도

owner: 같은 파일:evaluate_p6

G5A_DEVELOPMENT는 immutable history, 결과 전 고정 split, 검증된 development cost model, historical/semantic/source SHA 일치 및 formal_production_credit=0를 요구한다. 이 경로에 실시간 tick의 fresh=true를 새로 필수화하지 않는다. Proxy는 declared AND validated이어야 한다. 이미 본 자료를 OOS로 바꾸거나 결과 후 split을 고정한 것처럼 쓰는 권한은 아니다. g5b_operational_terminal_v1.freeze_boundary는 해당 경로의 새 G5B 등록 때 적격 fresh_receipt를 별도로 요구한다.

## 4. G5A 경제 완료와 미승인 전방 설계

G5A 등록경로는 P0–P6, 실제9종 경제보고/identity/hash, purged_oos_pass, negative_controls_superior, no_leakage/no_cherry_pick, duplicate0, netE>0/PF>1/cost2net>0를 요구한다. 53,813이나 30day×3는 이 기존 함수의 보편적인 숫자 gate가 아니다. STEP7의 미승인 전방프로토콜과 G5B terminal NetR/retention 정의는 별도 결손으로 남긴다. 미사용 적격 OOS 또는 정확한 자료승인 없이 G5A PASS를 만들지는 않는다.

## 5. 다음 실제 작업의 순서

1. 같은 KR3 candidate에 P0/P1/P2/P3/P4/P5/P6별 기존 증거를 매핑한다. 이미 끝낸 기존 성적/산술시험은 재실행하지 않는다.
2. P4 비적용의 근거·owner 검토를 먼저 끝내고, 적용 가능한 control/ablation의 기사용 DEV 시험 명세를 동결한다. 후보 최적화·새 전략/threshold 탐색은 하지 않는다. 신규 경제실행 권한과 자료 범위는 결과 전에 확인한다.
3. P5는 정확한 KR3 입력의 실제 provider 검토를 확보한다. 호출코드 존재나 하위agent 완료를 대체 증거로 쓰지 않는다.
4. P6 historical-development 자료와 검증용 OOS를 구분하고, 미노출 이력 및 접근승인을 검증한다. 이미 본 2025/2026 자료를 새 독립 OOS로 재분류하지 않는다.
5. 전체9종 실제 결과와 proof가 충족된 때만 기존 G5A owner로 판정한다. 결측/실패는 그대로 둔다. G5B 경계와 원천 가동은 그 뒤의 별도 조건이다.

이번 신규 시험은 기존 gate에 대한 TEST FIXTURE 회귀일 뿐이다. 규칙 파일·실제 candidate proof·승격 권한·source/경제 예산은 변경하지 않는다. no-SL/NetR 정식 적용성도 자동 승인하지 않는다.
