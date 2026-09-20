# Exact25 구현 증분 결과

이번 변경은 원래25개의 수치·사건·회계 부품과 실제 호출·체결·평가 연결을 추가한 구현 증분이다. **G4 전체 경제개발 완료가 아니다.**

| 실제 경제 결과 | 이번 증분 |
|---|---|
| 새 FULL / 실제 역사 신호 probe | 0 / 0 |
| 새 T·WR·Gross·Cost·Net·Net/T·PF·DD·연패 | 미측정 |
| 승리 훼손·기회 누락의 실제 경제 변화 | 미측정 |
| 경제적으로 살아난 후보 / 뒤집은 기존 실패 | 0 / 0 |
| 기존 PR1340/1341 결과·등급 | 보존 |
| 동결된 완결 신규 기준본 / 필요한 새 대조군 | 0 / 0 |
| 현재 준비 집합의 최소 FULL | 0 — 준비 집합이 비어 있음; 향후 필요량·상한은 미정 |
| 원형 전체 또는 완결 연구 모델이 남은 항목 | 25 |
| LIVE·주문·승격 | BLOCKED |

PR1341 예산은4/4 COMPLETED이고 이번 scope는 승인 원장에 없다. 관련3개 원장을 읽기 전용으로 회수했고 Issue1334의7개 comment에도 추가 배정이 없다. 승인 부족과 별도로 각 행에 미확정 모드·자료·수량·관리 조건이 남아 있다. 이를 감추고25회/50회 예산이나 완성 전략을 만들지 않았다.

25개별 닫힌 공백·남은 공백·다음 결속은 [COVERAGE.md](COVERAGE.md), 실제 함수/소스/시험 해시는 [EXACT25_IMPLEMENTATION.json](EXACT25_IMPLEMENTATION.json)에 있다.

## 변경한 실행 경로

- `scalp7_exact25_{indicators,reference,session,structure,capital}_v1.py`:25개ID의 actual catalog/evaluate와 규칙 출처·가설 분리. BBIII와 Anti 최종 정정 적용.
- `scalp7_exact25_execution_v1.py`:기존 단일 세부봉 판정 helper를 상태형 주문·부분 체결·만료·취소·갭/순서 불확실 처리에 연결하고 실제 수량/수수료 원장을 snapshot helper로 전달.
- `scalp7_exact25_pipeline_v1.py`:실제 producer dispatch·규칙/config/코드/입력 해시 결속과 명시적 인공 실행 completion. 수량·stop·만료·청산 결손을 기본값으로 숨기지 않음.
- `scalp7_implementation_contract_v1.py`:유한 Decimal이 float 변환에서 무한대가 되는 출력 차단. 원PR1342 receipt는 그 당시 원본의 기록으로 보존.
- 신규 causal/failure/통합 시험, 저장 seal 검사 및 읽기 전용 CI. 기존 execution_v2/metrics_v2/campaign_v2와 동결 전략/경제결과는 변경하지 않음.

독립 검수에서 심볼/방향/identity 결속, callback 타입과 상태 갱신, 겹친 봉, 실제 달력·종목군 결속, 수수료 현금제약 및 평가시각 결손을 수선했다. 각 감사는 `audits/INDEPENDENT_*_REVIEW.json`에 있다.

계좌평가는 사후 event-time snapshot이다. 입력된 MARK_PRICE와 LAST_PRICE를 구별하고, low/high로 mark를 만들지 않는다. 표본시각 DD는 intrabar 최대 DD나 청산 위험의 실측값이 아니다. 인공 fixture의 모델 체결은 관측 체결로 표시하지 않는다.

## 운영 영향

서비스·배포·주문·LIVE 변경 없음. GitHub Actions 배포를 실행할 필요가 없다. 롤백은 이번 신규 모듈/시험/caller와 finite-output 수선만 되돌리는 코드 PR로 처리하며 이전 연구 결과와 운영 checkout은 보존한다. 다음 작업은 `WORK_NEXT.txt`와25개별 next_required_closure에서 이어간다.

## 실제 검증

전체 Scalp7 인공·회귀시험 **1335 PASS**(PR1342의1001개 + 이번334개), 정상 Black/Ruff/isolated Mypy/원자료 보호 hook PASS, canonical frontend validation PASS. 기존 저장검증7개도 모두 PASS이며 경제 재실행은0이다. 실제 명령·로그 해시는 `VALIDATION.json`에 저장했다.

25개 dispatcher가 등록됐고, **BBIII 한 경로**만 원시 인공봉→확인 intent→모델 체결→계좌평가까지 검증했다. Alpha는 가짜 OHLC 없이 component/accounting 호출을 검증했다. 25개 전체의 독립 매매 E2E나 경제성 통과로 확대하지 않았다.
