# PR1211 KR3 실제 G5A 증거 연결과 인증 수선

같은 ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR / task-c28e09b57c612762 / 기존 PR1211. 후보44·KR3 FULL/noSL/noTP/TRADEOFF 및 과거 완료 결과를 보존한다. 구현 결과와 경제 성과·정식 채택은 구분한다.

| Gate | 이전 미연결 | 이번 실제 연결 / 기존 owner 판정 |
|---|---|---|
| P0 | primary evidence missing | 원형 KR3 비교 근거 연결; 독립 기계적 근거 수·구성 부족, HOLD |
| P1 | causal map missing | native 진입 변수3개·완료봉 가용시각·무효화·보유상태 분리, PASS |
| P2 | numeric inventory missing | native/design 숫자14개·7종목 비용값·선택이력 연결; 전체 inventory 및 경험적 prior 근거 부족, HOLD |
| P3 | development receipt missing | 실제 저장379signals/202closed 및 비용·빈도·두 기간 필요 경제조건 연결; forward/MFE/MAE 중앙값과 정식 launch 판정 부족, HOLD |
| P4 | controls missing | regime 라벨은 native replay 뒤 붙는다는 코드 근거로 순열 비적용; 나머지3대조군·3진입특징 ablation 실제 결과 없음, HOLD |
| P5 | provider review missing | 누적 원장0회 확인; 같은 KR3의 실제 provider2곳 검토 없음, HOLD |
| P6 | source reality missing | 기존 source/cost owner metadata 연결; full/SEEN2026 receipt만으로 DEV2025 slice immutability를 인정하지 않음. 정확한 slice·KR3 split·cost proxy 검증 부족, HOLD |

실제 명령 `python -m backend.research.rebuild.step7_kr3_g5a_evidence_v1 --out-dir out/step7-g5a-evidence`의 변경하지 않은 Alpha Proof owner 결과는 HOLD_ALPHA_PROOF. Candidate identity와 P1만 PASS다. 53,813 또는30일×3를 보편적 G5A gate로 추가하지 않았다.

| 9종 보고 | 실제 저장 결과 재사용 | 합성 생산기 / 실제 신규 실행 |
|---|---|---|
| base_replay | 동일 KR3 FULL 두 기간 저장 지표 | 과거 합성 완료 / 신규0 |
| realistic_cost | 선언된 DEV 비용모형 구성요소 | 과거 합성 완료 / 실제 체결비용 검증 미완료 |
| cost2x | 전체 비용2배 저장 결과 | 과거 합성 완료 / 신규0 |
| purged_oos | 없음; 이미 본 DEV를 OOS로 재명명하지 않음 | 합성만 완료 / 실제 미실행 |
| chronological_split | 저장 월별 기술통계 | 합성 완료 / KR3 사전고정 독립 split 미완료 |
| symbol_decomposition | 저장 종목별 결과 | 과거 합성 완료 / 신규0 |
| regime_decomposition | 없음 | 합성만 완료 / 실제 미실행 |
| parameter_neighbor_stability | 없음 | 합성만 완료 / 실제 미실행 |
| negative_controls | 적용성 및 코드 명세만 연결 | 합성만 완료 / 실제 미실행 |

5종 실제 DEV 구성요소를 재사용했으며9종 formal complete는0이다. 새 경제 성과·독립 데이터 접근·새 후보·원천 요청은0. 각 행의 candidate/data/cost/spec/historical producer와 synthetic receipt 구분은 KR3_G5A_EVIDENCE.json에 저장했다.

| 보존 lane | 현재 개발 판정 | 정식 자격 / 다음 처리 |
|---|---|---|
| Keltner KR3 FULL | 양기간 TRADEOFF; 부모 KR1 개선 보존 | G5A 미충족; 정확한 같은 후보 증거만 보완 |
| Break | Q0 별도; V2→BR1→BR2, BR2 2025REJECT/2026FULL TRADEOFF | 원형·부분 개선 보존, 관측/후보 리셋 없음 |
| Supertrend | SR1 2026이득/2025피해 함께 보존 | H12와 연장 피해 분리, 노출 사고 보존, 신규실측 없음 |
| Primary | TPC1 청산 개선, TPQ1 손실감소와 REJECT 보존 | 별도 향후 부모·진입구조 결정; 자동이식 없음 |
| Broad | 역사30건/70%와 현재native/TBR1 별도 | 동일입력 전체 연결 미확정; Primary 이식 없음 |

알려진 인증 P1은 live callback 대신 서명에 결속된 Python 의존 snapshot을 새 -I/-S/-B 프로세스로 실행해 수선했다. 직접 함수교체·json/produce_reports·간접 helper·읽기 중 변경을 검증한다. 추가로 호출자 PATH의 가짜 OpenSSL 우회는 고정 /usr/bin/openssl 소유권과 환경 검사로 차단했다. 외부 Ed25519 신뢰키·독립 validator UID·영속1회예약을 유지하며 실패/timeout 후 권리를 복구하지 않는다. 후보 identity는 유지하되 실행코드 서명은 dependency/worker/runtime identity로 새로 받아야 한다. 신뢰된 독립 OS·stdlib·dispatcher 전제이며 적대적 호스트 sandbox 주장이 아니다.

새 인증12회귀, 관련 기존25회귀, 증거8회귀가 로컬에서 확인됐다. 마지막 native 시험은 합성 서명→예약→읽기→child→거래0인 상수 합성봉9종 출력이며 경제 실측이 아니다. 최종 바이트의45개 관련 CI와 고정 merge 재현은 CI_MERGE_RECEIPT.json/PR completion comment로 결속한다. frontend validate PASS, 운영 배포 불필요. rollback은 코드만 되돌리고 예산·예약·노출 원장은 삭제하지 않는다.

API 실제 Gemini0/OpenAI0, 정산/예약 USD0/0, 합계USD5 유지. 키·gh·dispatch 경로 부재, 원격 secret 미확인, 기존 adapter의 TPQ1 scope로 실제 KR3 호출 불가. 무과금 존재확인 다음 명령과 KR3 dossier/runtime/가격/상한/영속예약 선행조건은 SOURCE_API_STATUS.md에 있다. 실제 호출/활용 완료로 표시하지 않았다.

원천 기존1/1+추가1/1 소비 유지. 이전 추가run34158767327은 종료됐고 새 수집0. Q0/G5B·기존 수집·다른 Work를 조작하지 않았다.

남은 권한·자료 결정을 한 묶음으로 남긴다: 정확한 KR3 P0/P2 근거 및 P3 metric/launch owner, 사전명세가 정해진 적용 가능한 DEV 대조군/ablations·이웃검증의 실행 범위, 독립 OOS 경계·미노출 자료 접근, 검증된 비용 proxy와 정확한 DEV slice receipt, 동일 KR3의 실제2provider 검토 경로. STEP7 11수치·noSL/NetR 정식 예외·G5B 등록·실주문은 이 구현으로 승인되지 않는다. 기존 b6d45358…안의 일괄 활성화나 새 데이터/후보는 자동 실행하지 않는다.

현재 산출물은 필수 CI/병합/고정 merge 재현 대기이며 완료로 표시하지 않는다. 최종 세션 완료와 경제 목표 미완료는 별도로 기록한다.
