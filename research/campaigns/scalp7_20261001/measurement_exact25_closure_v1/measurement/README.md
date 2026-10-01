# 공통 측정 결손 수선: 원본 보존·독립 연속구간

이번 변경의 경제 FULL 실행은 0회다. PR #1345의 5개 실행과 소진된 승인은 그대로 보존한다. 새 전략 손익은 미측정이며 이 작업을 원래 25개 또는 G4 전체 완료로 표시하지 않는다.

## 실제 원인과 회수 한계

BTC/ETH/SOL/XRP/LINK/DOGE-USDT의 보존된 BingX USDT-M 응답에는 2026-02-13 20:32–20:35 UTC의 분봉이 모두 없다. 최초 누락 open timestamp는 1771014720000, 재개는 1771014960000이다. 따라서 canonical loader의 세그먼트 연결만 수정해서 복구할 수 있는 결손이 아니다. 거래소가 당시 봉을 제공하지 않는 근본 이유까지 입증한 것은 아니다.

동일 endpoint와 상품의 좁은 구간을 심볼별 1회, 총 6회 무료 조회했다. HTTP 200/code 0이지만 모두 data=[]였다. 복구 0/24봉, 재시도 0회이며 이 한정 회수는 종료했다. 원본 18개 해시와 canonical 분봉 파일 2,196개 해시가 유지된다. 다른 거래소, 합성, 보간, forward-fill은 사용하지 않았다.

- 원 응답 경로·행·해시: recovery_probe/same_source_gap_20260213_v1/PRESERVED_SOURCE_INSPECTION.json
- 회수 요청·응답·원본 불변: 같은 디렉터리 SUMMARY.json과 심볼별 receipt/body
- 실제 canonical 전체 시각 감사: CONTINUOUS_DATA_CONTRACT.json 및 CANONICAL_MINUTE_HASHES.json
- 기존 실행 영향: SOURCE_AND_OWNERSHIP_AUDIT.json

## 보유·후속 진입·계좌곡선 영향

모든 16개 미확정 owner의 최초 관측은 같은 누락 경계다. ST_CONTROL/ST_TRAIL은 각각 SOL 1개, SR_CONTROL은 6개, SR_RETEST는 BTC/XRP 2개, NOISE는 6개다. 보유 수량·진입·주문 ID·원 ledger를 감사에 복사하고 삭제하지 않았다. 해당 owner 심볼의 결손 이후 fill은 모두 0건이다.

조건부 주문 경로에서 기존 소유권 때문에 막힌 후속 status는 ST 각각 127건, SR_CONTROL 912건, SR_RETEST 131건이다. NOISE는 session 경로이므로 같은 이름의 status를 찍지 않으며 미확정 상태와 종료까지의 미체결을 별도로 보존한다. 새로운 구간의 flat 초기 상태는 과거 보유를 0손익으로 청산하는 행위가 아니다.

모든 원본 계좌곡선의 마지막 신뢰 표본은 2026-02-13 20:30 UTC다. 이후 전체 NAV/DD는 계속 미확정이다. NOISE의 validation/rolling_1은 경계 이월 거래 때문에 closed-entry cohort가 불완전하지만, 그 두 창의 예상 30분 NAV 표본은 모두 존재한다. 따라서 원 보고서의 0/10 완결은 10개 창 모두에 물리적 결손이 있었다는 뜻이 아니다.

새 진단은 cohort completeness와 NAV sample completeness를 분리한다. 원 보고서의 null은 덮어쓰지 않고, 저장 곡선의 명시된 양끝 경계를 포함하는 별도 표본 DD를 제공한다. NOISE validation/rolling_1 DD는 1x 26.452092654%/12.240692897%, 2x 30.619460288%/13.960786774%다. 이 값은 과거 저장 NAV 산술이며 새 전략 실행 결과가 아니다. 펀딩 제외 기준가격 연구 평가이고 실제 계좌·거래소 mark DD나 분봉 내부 DD가 아니다.

## 다음 비교의 공통 데이터 계약

손익을 보지 않고 모든 심볼 공통의 모든 연속 구간을 택한다. 동일한 90일 문맥과 30분 UTC grid를 적용한다. 첫·마지막 불완전 decision bucket은 평가에서 제외한다.

| 구간 | 원자료 범위 UTC (끝 제외) | 평가 범위 UTC (끝 제외) |
|---|---|---|
| common_contiguous_1 | 2025-09-15 00:00 → 2026-02-13 20:32 | 2025-12-14 00:00 → 2026-02-13 20:30 |
| common_contiguous_2 | 2026-02-13 20:36 → 2026-09-15 00:00 | 2026-05-14 21:00 → 2026-09-15 00:00 |

각 구간은 독립 연구 계좌/자본/소유권 namespace다. 구간 사이의 NAV를 이어 붙이거나 합산 전체 계좌 손익으로 부르지 않는다. 90일 문맥 중 진입은 금지된다. 구간 말 미종료 보유도 강제청산하지 않는다. parent의 규칙·비용·진입·SL·청산은 변경하지 않는다.

## 코드·시험·실행 경계

scalp7_measurement_repair_v1.py는 실제 clock coverage, 해시 계약, 연속 detail adapter, owner admission, 표본 완결·DD를 제공한다. 계약 변조, 내부 NAV 표본 누락, 실제 시각보다 앞당긴 가용시각을 허용하지 않는다.

scalp7_measurement_compare_v1.py의 segment_inputs는 주어진 detail을 기존 aggregate_minutes로 연결한다. run_synthetic_comparison은 기존 SR compiler/create_order/exit_update와 runner.run_fixture를 실제 호출하며 최대 2심볼·심볼당 5,000분의 명시된 합성 fixture만 받는다. 표식만으로 외부 가격의 진위를 증명할 수 있다는 주장은 하지 않는다.

freeze_comparison(parent_binding, contract, label)은 SR_CONTROL/SR_RETEST 각각 한 identity 안에 모든 독립 구간을 결속한다. run_authorized_comparison은 기존 승인·정확한 예약·예산을 읽기 전용으로 먼저 확인하고 STARTED 성공 후에만 원 loader와 기존 replay를 호출한다. 승인·예약을 생성하지 않는다. 구간별 체크포인트와 실패의 소진 상태를 보존하며 자동 재시도하지 않는다. 이번 작업에서는 genuine 경로를 실행하지 않았다.

17개 합성 회귀(실제 임시파일의 파일 fsync→부모 디렉터리 fsync 및 기존 체크포인트 덮어쓰기 거부 포함)가 자료 단절→보유→후속 차단→prefix 평가, 연속 자료의 실제 종료→소유권 해제, SR 두 원형의 두 독립 구간 체결·평가, 문맥 진입 금지, NAV 내부 결측, 계약 해시 변조, 지연 시각/mark 가격 재명명, FULL 승인 전 loader 차단을 확인했다. 정상 hooks 및 frontend validate도 통과했다. SYNTHETIC_REGRESSION_RECEIPT.json에 검증과 코드 SHA를 결속한다.

다음 실제 SR 비교의 최소 FULL은 2회(후보별 모든 구간을 묶어 각 1회)다. 데이터·기간·자본 경계가 달라 기존 SR_CONTROL 결과는 동조건 대조군으로 재사용할 수 없다. 새 identity와 승인은 root의 NEXT 배치 문서에서 검토해야 하며 현재 승인량은 0이다. 배포·서비스 변경·실주문·LIVE·승격은 없다.
