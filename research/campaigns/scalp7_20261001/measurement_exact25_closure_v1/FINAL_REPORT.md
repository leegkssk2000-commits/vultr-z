# PR #1345 이후 측정·원래25개 구현 증분

이번 실제 수정은 측정 경계, 새 HG/Kell/Gajjala 연구 caller, 거래량·상품 계약과 통합 시험이다. 신규 FULL·역사 전략 probe·파라미터 탐색은 0회다. PR1345의 다섯 완료 identity와 소진5/5, 원래25개 및 미완료19개, 양수 parent와 실패 이력을 보존했다.

## 1. 실제 결손 원인과 회수 결과

2026-02-13 20:32~20:35 UTC, 여섯 BingX USDT-M 심볼의 원 HTTP body와 canonical 분봉에서 실제4분이 빠졌다. 앞20:31과 뒤20:36은 있다. 단순 join/시각 연결 오류가 아니다. 동일상품·동일시각 klines를 각1회(총6회) 무상 조회했지만 HTTP200/code0/data=[]여서24개 심볼·분을 회수하지 못했다. 원본과 별도 회수 receipt를 보존하고 반복 회수를 끝냈다.

그 공백에서 기존16개 보유 소유권(ST1+1, SR6+2, Noise6)이 UNRESOLVED로 남는다. 후속 동일 심볼 진입이 차단되고 모든5개 saved NAV는20:30UTC 표본에서 끝난다. 소유권 삭제·0손익 청산·자동 재실행은 없다. 측정 수선은 누락을 복구했다고 주장하지 않고, 소유권/후속 주문/NAV 경계를 실제 저장 원장에 결속했다.

Noise validation/rolling1의 cohort 불완결과 sampled NAV 자료 완결은 다르다. 새 진단은 필요한 내부 snapshot까지 검수해 두 상태를 분리한다. 기존 보고·손익·curve를 덮어쓰지 않았다. sampled LAST-price NAV가 있어도 실계좌·봉중 DD·funding-inclusive Net은 아니다.

Noise의 저장 NAV 전용 DD를 별도 회수했다. validation은1x26.452093% /2x30.619460%, rolling1은1x12.240693% /2x13.960787%다. 새 체결이나 손익 개선이 아니라 이미 저장된 LAST 표본의 측정값이다. 이후 결손·전체 계좌 DD·funding 불확실성은 남는다.

공통 구간은 수익과 무관하게 여섯 심볼의 모든 연속 구간에 같은90일 context와30m 격자를 적용했다. 각 구간은 별도 flat 연구계좌이며 기존 미확정 부모를 닫지 않는다. 구간 계좌곡선은 연속 전체 NAV로 합산하지 않는다.

| 구간 | 원자료 UTC 범위(끝 제외) | 평가 UTC 범위(끝 제외) |
|---|---|---|
| common_contiguous_1 | 2025-09-15T00:00:00+00:00 → 2026-02-13T20:32:00+00:00 | 2025-12-14T00:00:00+00:00 → 2026-02-13T20:30:00+00:00 |
| common_contiguous_2 | 2026-02-13T20:36:00+00:00 → 2026-09-15T00:00:00+00:00 | 2026-05-14T21:00:00+00:00 → 2026-09-15T00:00:00+00:00 |

## 2. 실제 닫은 구현·역할 공백

| 변경 | 실제 함수·통합 | 시험·한계 |
|---|---|---|
| HG1997 하나 | scalp7_hg_closure_v1.compile_model/create_adapter: 자격→첫눌림→조건부 주문→무효화·재자격→확정 pivot 관리; closure_dispatch.run_fixture 연결 | 원 모드는 수익으로 선택하지 않았다. 원문/동결/기계화 가설 분리; PIT 가격격자·경제 근거는 미확보 |
| Kell/Gajjala | compile_model/management_update/run_fixture: 원 부품 재사용, 상위TF 선정·형성·진입·실패·30% 모델 부분청산·계좌 | Gajjala 두 ID는 동일계보1개. 숫자·crypto 선정은 선언 가설, 원저자 전체법 인증0 |
| 공통 거래량 | volume_contract.adapt_volume_frame/evaluate_volume_component: AVWAP/BBIII/OBV/MFI 기존 수식에 필드·단위·가용시각 차이 adapter | 실제 volume UNKNOWN·quote ABSENT. mark→last 재표기 차단 수선, 없는 근거는 BLOCKED |
| 상품·체결 | product_contracts.bind_price_grid/fvg_receipt_adapter/turtle_daily_filled_units/value_native_spot_ledger | tick은 가격격자다. FVG touch≠fill, DAILY 유지, perp 현물재고 대체금지. Turtle/DGT 전체 caller 완료 주장은 없다 |
| 공통 측정 | measurement_repair continuity/ownership/NAV gates; measurement_compare.segment_inputs/freeze_comparison/run_authorized_comparison | 기존 engine 재사용. 인공 gap→held owner→후속진입→NAV 회귀 및 새 gateway의 승인 전 차단. 실자료 loader·경제실행0; 미승인 관문 거부 시험 |

독립검토에서 발견한 source mark-price 재표기, 지연 BAR_CLOSE 지원 누락, 후속 주문 submit 시점의 소유권·자본 인과 오류를 실제 수정하고 회귀시험했다. PR 리뷰의 가격격자 영수증→Kell/Gajjala caller 필드 불일치와 심볼별 VWAP 거래량 기준의 조기 거부도 수선하고 통합시험했다. 해결 내역과 명령·해시는 implementation/ 및 audits/guard/에 있다.

## 3. 남은 항목

COVERAGE.md/COVERAGE.json은 정확25개를 자료 부재·명세 미결정·caller 구현 미완료·경제 미실행으로 나눈다. 새3개 연구 lifecycle은4개 행의 코드 연결 증분이며 미완료19개 전체의 검증 완료가 아니다. Anti/Soup PIT grid, volume/quote 원천, FVG 관측 limit 체결, Turtle unit/portfolio·System1 virtual ledger, native DGT caller/현물자료, host/융합 명세와 fresh 근거는 남는다. HG/Kell/Gajjala는 검증된 독립전략으로 승격하지 않았다.

## 4. 다음 경제배치의 정확 대상과 최소 횟수

필요한 다음 배치는 unchanged SR_CONTROL과 SR_RETEST를 같은 공통2구간에서 비교하는 새 identity2개, 각1회로 **최소 FULL2회**다. 기존 대조군은 자료·계좌 정책이 달라 재사용 불가다. 각1회는 해당 후보의 모든 적격구간을 포함하며 구간별 새 FULL이 아니다. cost2x는 동일 fill/수량 재평가로 추가0회다. 이것은 승인 요청 대상의 구체화이며 신규 FULL 승인0을 바꾸지 않는다.

| 새 후보 ID | identity SHA256 | data / cost / period SHA256 |
|---|---|---|
| SR_CONTROL_CONTINUOUS_SEGMENTS_V1 | 08e02370c96bd0c65ced1bb3f65bcb19099665c1b0a487a4226a3bfc49c53200 | 71f76590d3f8186e8dbbad2e43add97fbcab8058fa119f76febd9f8d5d042f57 / e5a76fe1565b1e700abda2b664dced3b561af53e890644e17ef5c86e54914618 / 80b59193906287537c59c3e81da6f7d93c33558f8052772164e7a3195f328ff0 |
| SR_RETEST_CONTINUOUS_SEGMENTS_V1 | 6ccad0c2e6939d801a2a216661213414edd46db79f31ae3f017125afbd348b70 | 71f76590d3f8186e8dbbad2e43add97fbcab8058fa119f76febd9f8d5d042f57 / e5a76fe1565b1e700abda2b664dced3b561af53e890644e17ef5c86e54914618 / 80b59193906287537c59c3e81da6f7d93c33558f8052772164e7a3195f328ff0 |

정확 code/data/cost/기간 결속은 NEXT_ECONOMIC_BATCH.json과 next_freezes/에 있다. 닫을 판단은 동일 연속 구간에서 SR 돌파/retest의 T·WR·Net·DD·비용 민감도·부모 승리 훼손이다. 물리적4분이나 전체 계좌 소유권이 복구되었다는 판단은 닫지 못한다. 새 수익은 **미측정**이다. 과거 결과는 펀딩 제외 연구 손익이며 funding UNKNOWN은0이 아니다.

## 검증·통합·롤백

VALIDATION.json은 실제 시험·정상 hooks·frontend와 저장 검사 명령/exit/출력을 보존한다. INPUT_SEAL과 saved guard는 PR1345의181파일 및 새 증분을 결속하고, CI는 실제 인공시험과 이전 saved-only 검산을 다시 수행한다. 보존 검사는 고정된 이전181파일과 현재 게시 기준의 기존 backend를 구분하며, 같은 게시 기준을 CI의 최초·최종 검사에 전달해 master의 별도 자동 기록을 보존하고 후보의 기존 코드 변경은 거부한다. 정상 리뷰→CI→PR→병합→고정 병합본 검증의 영수증은 PR에 남긴다. 서비스 변경·배포·유료 지출·실주문·LIVE·공식 승격은 없다. 배포 workflow는 불필요하다.

롤백은 이번 연구 증분 PR만 정상 revert한다. 기존 엔진·원자료·봉인·경제결과·소진된 원장 및 이번 결손 회수 증거는 보존하고 사용 예산을 초기화하지 않는다.
